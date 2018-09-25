import random

import cv2
import numpy as np
import skimage.color, skimage.transform
import ai2thor.controller

class ThorWrapperEnv():
    def __init__(self, scene_id='FloorPlan28', task=0):
        self.scene_id = 'FloorPlan28'
        self.controller = ai2thor.controller.Controller()
        self.controller.start()

        self.controller.reset(self.scene_id)
        self.event = self.controller.step(dict(action='Initialize', gridSize=0.25))

        self.episode_cut_off = 1000
        self.t = 0
        self.task = task


        # action space stuff for ai2thor
        self.ACTION_SPACE = {0: dict(action='MoveAhead'),
                            1: dict(action='MoveBack'),
                            2: dict(action='MoveRight'),
                            3: dict(action='MoveLeft'),
                            4: dict(action='LookUp'),
                            5: dict(action='LookDown'),
                            6: dict(action='RotateRight'),
                            7: dict(action='RotateLeft'),
                            # 1: dict(action='OpenObject'), # needs object id
                            # 1: dict(action='CloseObject'), # needs object id
                            8: dict(action='PickupObject'),  # needs object id???
                            9: dict(action='PutObject')  # needs object id
                            }

        # also Teleport and TeleportFull but obviously only used for initialisation
        self.NUM_ACTIONS = len(self.ACTION_SPACE.keys())
        self.action_space = self.NUM_ACTIONS
        self.resolution = (64, 64)
        self.observation_space = np.array((1, ) + self.resolution)

        self.mugs_ids_collected_and_placed = set()
        self.last_amount_of_mugs = len(self.mugs_ids_collected_and_placed)

    def step(self, action_int):
        if action_int == 8:
            if len(self.event.metadata['inventoryObjects']) == 0:
                for o in self.event.metadata['objects']:
                    if o['visible'] and (o['objectType'] == 'Mug'):
                        mug_id = o['objectId']
                        self.event = self.controller.step(
                            dict(action='PickupObject', objectId=mug_id), raise_for_failure=True)
                        self.mugs_ids_collected_and_placed.add(mug_id)
                        # reward = self.calculate_reward(mug_id)
                        break
        elif action_int == 9:
            # action = dict(action='PutObject', )
            if len(self.event.metadata['inventoryObjects']) > 0:

                for o in self.event.metadata['objects']:
                    if o['visible'] and o['receptacle'] and (o['objectType'] == 'CounterTop' or
                                                             o['objectType'] == 'TableTop' or
                                                             o['objectType'] == 'Sink' or
                                                             o['objectType'] == 'CoffeeMachine' or
                                                             o['objectType'] == 'Box'):
                        # import pdb;pdb.set_trace()
                        mug_id = self.event.metadata['inventoryObjects'][0]['objectId']
                        try:
                            self.event = self.controller.step(dict(action='PutObject', objectId=mug_id, receptacleObjectId=o['objectId']),
                                                    raise_for_failure=True)
                            self.mugs_ids_collected_and_placed.remove(mug_id)
                        except Exception as e:
                            # sometimes crashes here for placing mug onto table top which should be fine except distance?
                            # import pdb;pdb.set_trace()
                            print(e)
                            test = 5
                        # reward = self.calculate_reward(mug_id)
                        break
        else:
            action = self.ACTION_SPACE[action_int]
            self.event = self.controller.step(action)

        self.t += 1
        return self.preprocess(self.event.frame), self.calculate_reward(), self.is_episode_finished()

    def reset(self):
        self.t = 0
        self.controller.reset(self.scene_id)
        # todo it seems this doesn't reset inventory?
        self.event = self.controller.step(dict(action='Initialize', gridSize=0.25))
        print('Just resetted. Current self.event.metadata["inventory"]: {}'.format(self.event.metadata['inventoryObjects']))
        return self.preprocess(self.event.frame)

    def preprocess(self, img):
        img = skimage.transform.resize(img, self.resolution)
        img = img.astype(np.float32)
        gray = self.rgb2gray(img)
        return gray

    def rgb2gray(self, rgb):
        return np.dot(rgb[..., :3], [0.299, 0.587, 0.114])

    def calculate_reward(self):
        # todo also just try endless reward and see if it spams picking up the cup.
        # todo interface shouldn't have a mug? should just check
        if self.task == 0:
            if self.last_amount_of_mugs != len(self.mugs_ids_collected_and_placed):
                if self.last_amount_of_mugs < len(self.mugs_ids_collected_and_placed):
                    self.last_amount_of_mugs = len(self.mugs_ids_collected_and_placed)
                    # has correctly picked up cup if we are here
                    print('Reward collected!!!!!! {}'.format(self.mugs_ids_collected_and_placed))
                    return 1
            self.last_amount_of_mugs = len(self.mugs_ids_collected_and_placed)
            return 0
        elif self.task == 1:
            pass
            # if mug_id in mugs_ids_collected_and_placed:
            #     # already collected
            #     return 0
            # else:
            #     mugs_ids_collected_and_placed.add(mug_id)
            #     print('Reward collected!!!!!! {}'.format(mugs_ids_collected_and_placed))
            #     return 1.0


    def get_total_reward(self):
        return len(self.mugs_ids_collected_and_placed)

    def is_episode_finished(self):
        if self.t > self.episode_cut_off:
            return True
        if len(self.mugs_ids_collected_and_placed) == 3:
            # todo this is called before the total reward
            self.mugs_ids_collected_and_placed = set()
            return True
        else:
            return False

    def seed(self, seed):
        return #todo

if __name__ == '__main__':
    # Random agent example with wrapper
    env = ThorWrapperEnv()
    for episode in range(5):
        for t in range(1000):
            a = random.randint(0, len(env.ACTION_SPACE) - 1)
            s, r, terminal = env.step(a)