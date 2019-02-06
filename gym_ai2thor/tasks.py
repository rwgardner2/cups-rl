"""
Different task implementations that can be defined inside an ai2thor environment
"""
from collections import Counter
import random

from gym_ai2thor.utils import InvalidTaskParams
from gym_ai2thor.task_utils import get_word_to_idx, check_if_focus_and_close_enough_to_object_type

class TaskFactory:
    """
    Factory for tasks to be defined for a specific environment
    """
    @staticmethod
    def create_task(config):
        """
        Task factory method
        :param config: parsed config file
        :return: Task instance initialized
        """
        task_name = config['task']['task_name']
        if task_name == 'PickUp':
            if config['task']['target_object'] in config['pickup_objects']:
                return PickupTask(**config['task'])
            else:
                raise InvalidTaskParams('Error initializing PickUpTask. {} is not '
                                        'pickupable!'.format(config['task']['target_object']))
        elif task_name == 'NaturalLanguageLookAtObjectTask':
            return NaturalLanguageLookAtObjectTask(**config['task'])
        elif task_name == 'NaturalLanguageNavigateToObjectTask':
            return NaturalLanguageNavigateToObjectTask(**config['task'])
        elif task_name == 'NaturalLanguagePickUpObjectTask':
            return NaturalLanguagePickUpObjectTask(**config['task'])
        else:
            raise NotImplementedError('{} is not yet implemented!'.format(task_name))


class BaseTask:
    """
    Base class and factory for tasks to be defined for a specific environment
    """
    def __init__(self, config):
        self.task_config = config
        self.task_has_language_instructions = False
        self.max_episode_length = config['max_episode_length'] \
            if 'max_episode_length' in config else 1000
        self.movement_reward = config['movement_reward'] if 'movement_reward' in config else 0
        self.step_num = 0

    def transition_reward(self, state):
        """
        Returns the reward given the corresponding information (state, dictionary with objects
        collected, distance to goal, etc.) depending on the task.
        :return: (args, kwargs) First elemnt represents the reward obtained at the step
                                Second element represents if episode finished at this step
        """
        raise NotImplementedError

    def get_extra_state(self):
        return None

    def reset(self):
        """

        :param args, kwargs: Configuration for task initialization
        :return:
        """
        raise NotImplementedError


class PickupTask(BaseTask):
    """
    This task consists of picking up an target object. Rewards are only collected if the right
    object was added to the inventory with the action PickUp (See gym_ai2thor.envs.ai2thor_env for
    details).
    """
    def __init__(self, target_objects=('Mug',), goal=None, **kwargs):
        super().__init__(kwargs)
        self.target_objects = target_objects
        self.goal = Counter(goal if goal else {obj: float('inf') for obj in self.target_objects})
        self.pickedup_objects = Counter()
        self.object_rewards = Counter(self.target_objects)  # all target objects give reward 1
        self.prev_inventory = []

        self.reset()

    def transition_reward(self, event):
        reward, done = self.movement_reward, False
        curr_inventory = event.metadata['inventoryObjects']
        object_picked_up = not self.prev_inventory and curr_inventory and \
                           curr_inventory[0]['objectType'] in self.target_objects

        if object_picked_up:
            # One of the Target objects has been picked up
            self.pickedup_objects[curr_inventory[0]['objectType']] += 1
            # Add reward from the specific object
            reward += self.object_rewards[curr_inventory[0]['objectType']]
            print('{} reward collected!'.format(reward))

        if self.max_episode_length and self.step_num >= self.max_episode_length:
            print('Reached maximum episode length: {}'.format(self.step_num))
            done = True
        if self.goal == self.pickedup_objects:
            print('Reached goal at step {}'.format(self.step_num))
            done = True

        self.prev_inventory = event.metadata['inventoryObjects']
        return reward, done

    def reset(self):
        self.pickedup_objects = Counter()
        self.prev_inventory = []
        self.step_num = 0


class NaturalLanguageBaseTask(BaseTask):
    def __init__(self, list_of_instructions=None, **kwargs):
        super().__init__(kwargs)
        # super().__init__(kwargs)
        self.task_has_language_instructions = True
        # natural language instructions state settings
        # todo make sure object boxes is turned on in env
        self.train_instructions = ('Bowl', 'Mug') if not list_of_instructions else list_of_instructions
        # todo pass as parameter and have default?
        self.word_to_idx = get_word_to_idx(self.train_instructions)

        # get current instruction and object type
        self.curr_instruction_idx = random.randint(0, len(self.train_instructions) - 1)
        self.curr_instruction = self.train_instructions[self.curr_instruction_idx]
        # always last word of the sentence. Needs to be spelled exactly for it to work
        self.curr_object_type = self.curr_instruction.split(' ')[-1]
        print('Current instruction: {}. object type (last word in sentence): {}'.format(
            self.curr_instruction, self.curr_object_type))

        self.default_reward = 1

    def get_extra_state(self):
        return self.curr_instruction

    def reset(self):
        self.curr_instruction_idx = random.randint(0, len(self.train_instructions) - 1)
        self.curr_instruction = self.train_instructions[self.curr_instruction_idx]

        # always last word of the sentence. Has to be spelled exactly
        self.curr_object_type = self.curr_instruction.split(' ')[-1]
        print('Current instruction: {}. object type (last word in sentence): {} '.format(
            self.curr_instruction, self.curr_object_type))

        return self.curr_instruction


class NaturalLanguageLookAtObjectTask(NaturalLanguageBaseTask):
    """
    This task consists of requiring the agent to get close to the object type and look at it
    """

    def __init__(self, list_of_instructions=('Bowl', 'Mug'), **kwargs):
        super().__init__(list_of_instructions)

    def transition_reward(self, event):
        reward, done = self.movement_reward, False
        # check if current target object is in middle of screen and close
        target_objs = check_if_focus_and_close_enough_to_object_type(event, self.curr_object_type,
                                                                     distance_threshold_3d=1.0)
        if target_objs > 0:
            print('Stared at object and is close enough. Num objects in view and '
                  'close: {}'.format(target_objs))
            reward += self.default_reward
            done = True

        return reward, done

    def reset(self):
        return super(NaturalLanguageLookAtObjectTask, self).reset()


class NaturalLanguageNavigateToObjectTask(NaturalLanguageBaseTask):
    """
    This task consists of requiring the agent to get close to the object type and look at it
    The closeness is set by distance_threshold=0.84
    """

    def __init__(self, **kwargs):
        super().__init__(kwargs)

    def transition_reward(self, event):
        reward, done = self.movement_reward, False
        # check if current target object is in middle of screen and close
        target_objs = check_if_focus_and_close_enough_to_object_type(event,
                                                                event.metadata['curr_object_type'],
                                                              distance_threshold_3d=0.84)  # closer
        if target_objs > 0:
            print('Stared at object and is close enough. Num objects in view and '
                  'close: {}'.format(target_objs))
            reward += self.default_reward
            done = True

        return reward, done

    def reset(self):
        return super(NaturalLanguageNavigateToObjectTask, self).reset()


class NaturalLanguagePickUpObjectTask(NaturalLanguageBaseTask):
    # todo unfinished. Loose pickings from Pickup and other language tasks
    """
    This task consists of requiring the agent to get close to the object type and look at it
    """
    """
    This task consists of picking up an target object. Rewards are only collected if the right
    object was added to the inventory with the action PickUp (See gym_ai2thor.envs.ai2thor_env for
    details).
    
    """

    def __init__(self, target_objects=('Mug',), goal=None, **kwargs):
        super().__init__(kwargs)
        self.target_objects = target_objects
        self.goal = Counter(goal if goal else {obj: float('inf') for obj in self.target_objects})
        self.pickedup_objects = Counter()
        self.object_rewards = Counter(self.target_objects)  # all target objects give reward 1
        self.prev_inventory = []

    def transition_reward(self, event):
        reward, done = self.movement_reward, False
        curr_inventory = event.metadata['inventoryObjects']
        object_picked_up = not self.prev_inventory and curr_inventory and \
                           curr_inventory[0]['objectType'] in self.target_objects

        if object_picked_up:
            # One of the Target objects has been picked up
            self.pickedup_objects[curr_inventory[0]['objectType']] += 1
            # Add reward from the specific object
            reward += self.object_rewards[curr_inventory[0]['objectType']]
            print('{} reward collected!'.format(reward))

        if self.max_episode_length and self.step_num >= self.max_episode_length:
            print('Reached maximum episode length: {}'.format(self.step_num))
            done = True
        if self.goal == self.pickedup_objects:
            print('Reached goal at step {}'.format(self.step_num))
            done = True

        self.prev_inventory = event.metadata['inventoryObjects']
        return reward, done

    def reset(self):
        self.pickedup_objects = Counter()
        self.prev_inventory = []
        self.step_num = 0

    # def transition_reward(self, event):
    #     reward, done = self.movement_reward, False
    #     # check if current target object is in middle of screen and close
    #     target_objs = check_if_focus_and_close_enough_to_object_type(event, self.curr_object_type)
    #     if target_objs > 0:
    #         print('Stared at object and is close enough. Num objects in view and '
    #               'close: {}'.format(target_objs))
    #         reward += 10
    #         done = True
    #
    #     return reward, done
    #
    # def reset(self):
    #     return super(NaturalLanguagePickUpObjectTask, self).reset()
