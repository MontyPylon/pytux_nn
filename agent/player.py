import numpy as np
import pystk
import matplotlib.pyplot as plt
import torch
from torchvision.transforms import functional as F
import torchvision
from PIL import Image
from os import path

GOAL_0 = np.array([0, 64.5])
GOAL_1 = np.array([0, -64.5])
PLAYER_LOC = np.array([200, 180])

FIRST = True
IM = None
BACKUP = False
PREV_DRAW = None
PREV_DRAW2 = None
LAST_STEER = None

# num frames before we consider puck to be gone
GONE_COUNTER = 0
GONE = 5

# num frames before we consider puck to be back
IS_BACK = 4
IS_BACK_COUNTER = 0

# last 3 frames of which side puck was on (used for backing up in right direction)
PUCK_SIDE_LEN = 3
PUCK_SIDE = []

def load_detector():
    from model.puck_detector import PuckDetector
    from torch import load
    from os import path
    r = PuckDetector()
    r.load_state_dict(load(path.join(path.dirname(path.abspath(__file__)), '../model/puck_det.th'), map_location='cpu'))
    return r

def load_vec():
    from model.vec_detector import VecDetector
    from torch import load
    from os import path
    r = VecDetector()
    r.load_state_dict(load(path.join(path.dirname(path.abspath(__file__)), '../model/puck_vec.th'), map_location='cpu'))
    return r

    # calculate the player to puck vector
    # p_info = []
    # p_info.extend(kart_xy)
    # p_info.extend(kart_to_front)
    # p_info.extend(screen_puck_xy)
    # p_ten = torch.Tensor(p_info)
    # kart_to_puck = self.vec_detector(p_ten).detach().numpy()
    # # puck in world coordinates
    # puck_xy = kart_xy + kart_to_puck
    # goal_to_puck = self.normalize(puck_xy - score_goal_xy)
    # # adjust for scoring
    # aim_vec = self.normalize(kart_to_puck + (goal_to_puck / 2))
    # theta = np.arccos(np.dot(kart_to_front, aim_vec))
    # signed_theta = -np.sign(np.cross(kart_to_front, aim_vec)) * theta
    # steer = 5*signed_theta

class HockeyPlayer:
    def __init__(self, player_id = 0):
        self.player_id = player_id
        self.kart = 'wilber'
        self.team = player_id % 2
        self.puck_detector = load_detector()
        self.puck_detector.eval()
        self.vec_detector = load_vec()
        self.vec_detector.eval()
        self.resize = torchvision.transforms.Resize([150, 200])

    def get_puck_coords(self, image):
        device = torch.device('cpu')
        I = Image.fromarray(image)
        I = self.resize(I)
        I = F.to_tensor(I)
        I = I[None, :]
        I = I.to(device)
        puck_data = self.puck_detector(I)
        puck_data = puck_data.detach().numpy()[0]
        return puck_data

    def puck_off_screen(self, screen_puck_xy):
        screen_puck_x = screen_puck_xy[0]
        screen_puck_y = screen_puck_xy[1]
        if (screen_puck_y > 225 and screen_puck_x > 150 and screen_puck_x < 250):
            return True
        else:
            return False

    def normalize(self, vec):
        return vec / np.linalg.norm(vec)

    def clamp(self, value):
        if value > 0:
            return min(1, value)
        else:
            return max(-1, value)
      
    def act(self, image, player_info):
        global FIRST, IM, BACKUP, PREV_DRAW, PREV_DRAW2, LAST_STEER, \
            GONE_COUNTER, GONE, IS_BACK_COUNTER, IS_BACK, PUCK_SIDE, PUCK_SIDE_LEN

        score_goal_xy = None
        if self.team == 0:
            score_goal_xy = GOAL_0
        else:
            score_goal_xy = GOAL_1

        front_xy = np.array(player_info.kart.front)[[0,2]]
        kart_xy = np.array(player_info.kart.location)[[0,2]]

        # location of puck on screen
        screen_puck_xy = self.get_puck_coords(image)

        kart_to_puck = screen_puck_xy - PLAYER_LOC
        kart_to_puck[1] = -kart_to_puck[1]
        dist_to_puck = np.linalg.norm(kart_to_puck)

        # player orientation vector
        kart_to_front = self.normalize(front_xy - kart_xy)
        kart_to_goal = self.normalize(score_goal_xy - kart_xy)
        turn_dir = np.sign(np.cross(kart_to_front, kart_to_goal))

        new_puck_xy = screen_puck_xy.copy()
        offset = 10
        if dist_to_puck < 60:
            if turn_dir > 0:
                new_puck_xy[0] = new_puck_xy[0] + offset
            else:
                new_puck_xy[0] = new_puck_xy[0] - offset

        # set the player actions
        steer = self.clamp((new_puck_xy[0] - 200) / 20)
        # print("steer: ", steer)
        accel = 0.5
        brake = False
        drift = False

        if not BACKUP:
            # running tally of how many frames puck is off screen
            if self.puck_off_screen(screen_puck_xy):
                GONE_COUNTER += 1
            else:
                # side is -1 if on left, and +1 if on right
                side = 2 * ((screen_puck_xy[0] < 200) - 0.5)
                if len(PUCK_SIDE) == PUCK_SIDE_LEN:
                    PUCK_SIDE.pop(0)
                PUCK_SIDE.append(side)

                if GONE_COUNTER > 0:
                    GONE_COUNTER -= 1

            # print('GONE_COUNTER: ', GONE_COUNTER)
            # print('PUCK_SIDE: ', PUCK_SIDE)

            # puck has been gone for too long, turn on backup mode
            if GONE_COUNTER == GONE:
                BACKUP = True
                IS_BACK_COUNTER = 0
        else:
            accel = 0
            brake = True

            if len(PUCK_SIDE) == 0:
                steer = -0.75
            elif np.mean(PUCK_SIDE) < 0:
                steer = -0.75
            else:
                steer = 0.75

            # print('IS_BACK_COUNTER: ', IS_BACK_COUNTER)
            # print('STEER: ', steer)

            if not self.puck_off_screen(screen_puck_xy):
                IS_BACK_COUNTER += 1
            elif IS_BACK_COUNTER > 0:
                IS_BACK_COUNTER -= 1

            if IS_BACK_COUNTER == IS_BACK:
                BACKUP = False
                GONE_COUNTER = 0

        # visualize the controller in real time
        if player_info.kart.id == 0:
            ax1 = plt.subplot(111)
            if FIRST:
                IM = ax1.imshow(image)
                FIRST = False
            else:
                IM.set_data(image)

            if PREV_DRAW is not None:
                PREV_DRAW.remove()
                PREV_DRAW2.remove()

            #test = plt.Circle(PLAYER_LOC, 10, ec='b', fill=False, lw=1.5)
            #ax1.add_artist(test)

            PREV_DRAW = plt.Circle(screen_puck_xy, 10, ec='g', fill=False, lw=1.5)
            PREV_DRAW2 = plt.Circle(new_puck_xy, 10, ec='r', fill=False, lw=1.5)
            ax1.add_artist(PREV_DRAW)
            ax1.add_artist(PREV_DRAW2)

            plt.pause(0.001)

        action = {
            'steer': steer,
            'acceleration': accel,
            'brake': brake,
            'drift': drift,
            'nitro': False, 
            'rescue': False}

        return action