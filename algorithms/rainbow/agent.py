"""
Adapted from https://github.com/Kaixhin/Rainbow

Wrapper class including setup, training and evaluation functions for Rainbow DQN model
"""
import os
import numpy as np
import torch
from torch import optim

from algorithms.rainbow.model import RainbowDQN


class Agent:
    """
    Wraps control between both online and target network for setup, training and evaluation
    """
    def __init__(self, args, env):
        """
        Q(s,a) is the expected reward. Z is the full distribution from which Q is generated.
        Support represents the support of Z distribution (non-zero part of pdf)
        Z is represented with a fixed number of "atoms", which are pairs of values (x_i, p_i)
        composed by the discrete positions (x_i) equidistant along its support defined between
        Vmin-Vmax and the probability mass or "weight" (p_i) for that particular position.

        As an example, for a given (s,a) pair, we can represent Z(s,a) with 8 atoms as follows:

                   .        .     .
                .  |     .  |  .  |
                |  |  .  |  |  |  |  .
                |  |  |  |  |  |  |  |
           Vmin ----------------------- Vmax
        """
        self.action_space = env.action_space
        self.atoms = args.num_atoms
        self.Vmin = args.V_min
        self.Vmax = args.V_max
        self.support = torch.linspace(args.V_min, args.V_max, self.atoms).to(device=args.device)
        self.delta_z = (args.V_max - args.V_min) / (self.atoms - 1)
        self.batch_size = args.batch_size
        self.n = args.multi_step
        self.discount = args.discount

        self.online_net = RainbowDQN(args, self.action_space).to(device=args.device)
        if args.model and os.path.isfile(args.model):
            """
            When you call torch.load() on a file which contains GPU tensors, those tensors will be 
            loaded to GPU by default. You can call torch.load(.., map_location=’cpu’) and then 
            load_state_dict() to avoid GPU RAM surge when loading a model checkpoint.
            Source: https://pytorch.org/docs/stable/torch.html#torch.load
            """
            self.online_net.load_state_dict(torch.load(args.model, map_location='cpu'))
        self.online_net.train()

        self.target_net = RainbowDQN(args, self.action_space).to(device=args.device)
        self.update_target_net()
        self.target_net.train()
        for param in self.target_net.parameters():
            param.requires_grad = False

        self.optimiser = optim.Adam(self.online_net.parameters(), lr=args.lr, eps=args.adam_eps)

    def reset_noise(self):
        """ Resets noisy weights in all linear layers (of online net only) """
        self.online_net.reset_noise()

    def act(self, state):
        """ Acts based on single state (no batch) """
        with torch.no_grad():
            return (self.online_net(state.unsqueeze(0)) * self.support).sum(2).argmax(1).item()

    def act_e_greedy(self, state, epsilon=0.001):
        """
        Acts with an ε-greedy policy (used for evaluation only)
        High ε can reduce evaluation scores drastically
        """
        return np.random.randint(0, self.action_space.n) if np.random.random() < epsilon \
            else self.act(state)

    def learn(self, mem):
        """
        Executes 1 gradient descent step sampling batch_size transitions from the memory
        """
        # Sample transitions
        idxs, states, actions, returns, next_states, nonterminals, weights = \
          mem.sample(self.batch_size)

        """ Calculate current state probabilities (online network noise already sampled)
        The log provides more stability for the gradients propagation during training and it is 
        not needed for evaluation """
        log_ps = self.online_net(states, log=True)  # Log probabilities log p(s_t, ·; θonline)
        log_ps_a = log_ps[range(self.batch_size), actions]  # log p(s_t, a_t; θonline)

        with torch.no_grad():
            """
            -------------------
            Policy Evaluation
            -------------------
            Calculate nth next state action probabilities with the online policy for N-step Learning
            Probabilities: p(s_t+n, ·; θonline), i.e. for all actions
            """
            pns = self.online_net(next_states)
            # We compute the expected Q from the N-step distribution
            # d_t+n = (z, p(s_t+n, ·; θonline)) = Q(s_t+n, ·) = sum_i(z_i·p_i(s_t+n, ·)) ALL actions

            dns = self.support.expand_as(pns) * pns
            # Choose optimal action a* from online network
            # argmax_a[(z, p(s_t+n, a; θonline))]
            argmax_indices_ns = dns.sum(2).argmax(1)
            # Sample new target net noise, i.e. fix new random weights for noisy layers to
            # encourage exploration
            self.target_net.reset_noise()
            # Calculate nth next state action probabilities with the target policy for N-step
            # Learning. Probabilities p(s_t+n, ·; θtarget), i.e. for all actions
            pns = self.target_net(next_states)
            """ Calculate target probabilities for Double DQN. For that we compare the expected Q 
            from online greedy selection with the expected Q from the target network for the same 
            action. Probabilities p(s_t+n, argmax_a[(z, p(s_t+n, a; θonline))]; θtarget) """
            pns_a = pns[range(self.batch_size), argmax_indices_ns]
            """ Apply distributional N-step Bellman operator Tz (Bellman operator T applied to z)
            Tz = R^n + (γ^n)z (accounting for terminal states)
            Look at in _get_sample_from_segment() from memory.py for more details """
            Tz = returns.unsqueeze(1) + nonterminals * (self.discount ** self.n) \
                 * self.support.unsqueeze(0)
            # Clamp values so they fall within the support of Z values
            Tz = Tz.clamp(min=self.Vmin, max=self.Vmax)
            """ Compute L2 projection of Tz onto fixed support Z.
            1. Find which values of the discrete fix distribution are the closest lower (l) and 
            upper value (u) to the values from Tz (b).
            b = (Tz - Vmin) / Δz """
            b = (Tz - self.Vmin) / self.delta_z
            l, u = b.floor().to(torch.int64), b.ceil().to(torch.int64)
            # Fix disappearing probability mass when l = b = u (b is int)
            l[(u > 0) * (l == u)] -= 1
            u[(l < (self.atoms - 1)) * (l == u)] += 1
            """
            2. Distribute probability of Tz. Since b is most likely not having the exact value of 
            one of our predefined atoms, we split its mass between the closest atoms (l, u) in 
            proportion to their distance to b.
                                 u
                     l    b      .     
                     ._d__.__2d__|    
                ...  |    :      |  ...    mass_l += mass_b * 1 / 3
                     |    :      |         mass_r += mass_b * 2 / 3
           Vmin ----------------------- Vmax
            
            """
            m = states.new_zeros(self.batch_size, self.atoms)
            offset = torch.linspace(0, ((self.batch_size - 1) * self.atoms),
                                    self.batch_size).unsqueeze(1).expand(self.batch_size,
                                                                         self.atoms).to(actions)
            # m_l = m_l + p(s_t+n, a*)(u - b)
            m.view(-1).index_add_(0, (l + offset).view(-1), (pns_a * (u.float() - b)).view(-1))
            # m_u = m_u + p(s_t+n, a*)(b - l)
            m.view(-1).index_add_(0, (u + offset).view(-1), (pns_a * (b - l.float())).view(-1))

        # Cross-entropy loss (minimises KL-distance between Z and m: DKL(m||p(s_t, a_t)))
        loss = -torch.sum(m * log_ps_a, 1)
        self.online_net.zero_grad()
        # Backpropagate importance-weighted (Prioritized Experience Replay) minibatch loss
        (weights * loss).mean().backward()
        self.optimiser.step()
        # Update priorities of sampled transitions
        mem.update_priorities(idxs, loss.detach().cpu().numpy())

    def update_target_net(self):
        """ Updates target network as explained in Double DQN """
        self.target_net.load_state_dict(self.online_net.state_dict())

    def save(self, path):
        """ Save model parameters on current device (don't move model between devices) """
        torch.save(self.online_net.state_dict(), os.path.join(path, 'model.pth'))

    def evaluate_q(self, state):
        """ Evaluates Q-value based on single state (no batch) """
        with torch.no_grad():
            return (self.online_net(state.unsqueeze(0)) * self.support).sum(2).max(1)[0].item()

    def train(self):
        self.online_net.train()

    def eval(self):
        self.online_net.eval()