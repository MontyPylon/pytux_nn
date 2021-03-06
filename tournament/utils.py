import pystk
import numpy as np
import pathlib
import PIL.Image
from PIL import Image, ImageDraw, ImageFont
from torch.utils.data import Dataset, DataLoader
import os
import matplotlib.pyplot as plt
import torch
import random
from torchvision.transforms import functional as F

import os,sys,inspect
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0,parentdir) 

from agent.player import HockeyPlayer

HACK_DICT = dict()

class Player:
    def __init__(self, player, team=0):
        self.player = player
        self.team = team

    @property
    def config(self):
        return pystk.PlayerConfig(controller=pystk.PlayerConfig.Controller.PLAYER_CONTROL, kart=self.player.kart, team=self.team)
    
    def __call__(self, image, player_info):
        return self.player.act(image, player_info)

class DummyPlayer:
    def __init__(self, team=0):
        self.team = team

    @property
    def config(self):
        return pystk.PlayerConfig(
            controller=pystk.PlayerConfig.Controller.AI_CONTROL,
            team=self.team)
    
    def __call__(self, image, player_info):
        return dict()

class DontMove:
    def __init__(self, player_id = 0):
        self.kart = 'wilber'
        
    def act(self, image, player_info):
        action = {
            'steer': 0,
            'acceleration': 0,
            'brake': False,
            'drift': False,
            'nitro': False, 
            'rescue': False
        }
        return action

FIRST = True
IM = None
BACKUP = False

class OraclePlayer:
    kart = ""
    
    def __init__(self, player_id = 0):
        #all_players = ['adiumy', 'amanda', 'beastie', 'emule', 'gavroche', 'gnu', 'hexley', 'kiki', 'konqi', 'nolok', 'pidgin', 'puffy', 'sara_the_racer', 'sara_the_wizard', 'suzanne', 'tux', 'wilber', 'xue']
        self.player_id = player_id

        # players with the largest max_steer_angle
        if player_id == 0:
            self.kart = 'wilber'
        if player_id == 1:
            self.kart = 'hexley'
        if player_id == 2:
            self.kart = 'konqi'
        if player_id == 3:
            self.kart = 'xue'
        
        self.team = player_id % 2
        
    def act(self, image, player_info):
        """
        :param image: numpy array of shape (300, 400, 3)
        :param player_info: pystk.Player object for the current kart.
        return: Dict describing the action
        """
        global FIRST, IM, BACKUP

        front = np.array(HACK_DICT['kart'].front)[[0, 2]]
        kart = np.array(HACK_DICT['kart'].location)[[0, 2]]
        puck = np.array(HACK_DICT['state'].soccer.ball.location)[[0, 2]]

        u = front - kart
        u = u / np.linalg.norm(u)

        v = puck - kart
        v = v / np.linalg.norm(v)

        theta = np.arccos(np.dot(u, v))
        signed_theta = -np.sign(np.cross(u, v)) * theta

        steer = 20 * signed_theta
        accel = 0.5
        brake = False
        drift = False

        if np.degrees(theta) > 60 and np.degrees(theta) < 90:
            drift = True

        if np.degrees(theta) > 90 and not BACKUP:
            BACKUP = True

        if BACKUP:
            if np.degrees(theta) > 30:
                accel = 0
                brake = True
                steer = -steer
            else:
                BACKUP = False
        
        # visualize the controller in real time
        # if player_info.kart.id == 0:
        #     ax1 = plt.subplot(111)
        #     if FIRST:
        #         IM = ax1.imshow(image)
        #         FIRST = False
        #     else:
        #         IM.set_data(image)
        #     print('angle: ', "{:.2f}".format(np.degrees(signed_theta)))
        #     print('loc: ' + str(kart))
        #     plt.pause(0.001)
        

        action = {
            'steer': steer,
            'acceleration': accel,
            'brake': brake,
            'drift': drift,
            'nitro': False, 
            'rescue': False}

        return action

GOAL_0 = np.array([0, 64.5])
GOAL_1 = np.array([0, -64.5])

def load_detector():
    from model.puck_detector import PuckDetector
    from torch import load
    from os import path
    r = PuckDetector()
    r.load_state_dict(load(path.join(path.dirname(path.abspath(__file__)), '../model/puck_det.th'), map_location='cpu'))
    return r

class ScorePlayer:
    kart = ""
    
    def __init__(self, player_id = 0):
        #all_players = ['adiumy', 'amanda', 'beastie', 'emule', 'gavroche', 'gnu', 'hexley', 'kiki', 'konqi', 'nolok', 'pidgin', 'puffy', 'sara_the_racer', 'sara_the_wizard', 'suzanne', 'tux', 'wilber', 'xue']
        self.player_id = player_id

        # players with the largest max_steer_angle
        if player_id == 0:
            self.kart = 'wilber'
        if player_id == 1:
            self.kart = 'hexley'
        if player_id == 2:
            self.kart = 'konqi'
        if player_id == 3:
            self.kart = 'xue'
        
        self.team = player_id % 2

        self.puck_detector = load_detector()
        self.puck_detector.eval()
        import torchvision
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

    def extract_peak(self, nz):
        xs = []
        ys = []
        for i in enumerate(nz):
            xs.append(i[1][1].item())
            ys.append(i[1][2].item())
        
        avg_x = sum(xs) / len(xs)
        avg_y = sum(ys) / len(ys)
        return [avg_y, avg_x]
        
    def act(self, image, player_info):
        """
        :param image: numpy array of shape (300, 400, 3)
        :param player_info: pystk.Player object for the current kart.
        return: Dict describing the action
        """
        global FIRST, IM, BACKUP

        score_goal = None
        if self.team == 0:
            score_goal = GOAL_0
        else:
            score_goal = GOAL_1

        front = np.array(HACK_DICT['kart'].front)[[0, 2]]
        kart = np.array(HACK_DICT['kart'].location)[[0, 2]]
        puck = np.array(HACK_DICT['state'].soccer.ball.location)[[0, 2]]

        # player vector
        u = front - kart
        u = u / np.linalg.norm(u)

        # player to puck
        v = puck - kart
        v = v / np.linalg.norm(v)

        # goal to puck
        w = puck - score_goal
        w = w / np.linalg.norm(w)

        # adjust for scoring
        v2 = v + (w / 2)
        v2 = v2 / np.linalg.norm(v2)

        theta = np.arccos(np.dot(u, v2))
        signed_theta = -np.sign(np.cross(u, v2)) * theta

        steer = 5*signed_theta
        accel = random.uniform(0.4, 0.8)
        brake = False
        drift = False

        if np.degrees(theta) > 20 and np.degrees(theta) < 90:
            drift = True

        if np.degrees(theta) > 90 and not BACKUP:
            BACKUP = True

        if BACKUP:
            if np.degrees(theta) > 30:
                accel = 0
                brake = True
                steer = -steer
            else:
                BACKUP = False


        p_info = []
        mask = (HACK_DICT['race'].render_data[self.player_id].instance == 134217729)
        mask = F.to_tensor(mask)
        nz = torch.nonzero(mask)

        if nz.numel() == 0:
            HACK_DICT['player_bool_%d' % self.player_id] = False
        else:
            HACK_DICT['player_bool_%d' % self.player_id] = True

            p_info.extend(kart)
            p_info.extend(u)
            peak = self.extract_peak(nz)
            p_info.extend(peak)
            
        #test = self.get_puck_coords(image)
        #p_info.extend(self.get_puck_coords(image))

        HACK_DICT['player_info_%d' % self.player_id] = p_info
        HACK_DICT['puck_vec_%d' % self.player_id] = (puck - kart)
        
        # visualize the controller in real time
        # if player_info.kart.id == 0:
        #     ax1 = plt.subplot(111)
        #     if FIRST:
        #         IM = ax1.imshow(image)
        #         FIRST = False
        #     else:
        #         IM.set_data(image)
            
        #     # print('p_to_fron: ', u)
        #     # print('WORLD p_to_puck: ', (puck - kart))
        #     # puck_xy = self.get_puck_coords(image)
        #     # screen_p_to_puck = np.array([200, 180]) - puck_xy
        #     # screen_p_to_puck[0] = -screen_p_to_puck[0]
        #     # print('SCREEN p_to_puck: ', screen_p_to_puck)
        #     # print('puck_to_g: ', w)
        #     # print('aim_vec__: ', v2)
        #     # print('signed theta: ', signed_theta)
        #     # print('steer: ', steer)
        #     # print('loc: ' + str(kart))
        #     # print('-----------------------')
        #     plt.pause(0.001)
        

        action = {
            'steer': steer,
            'acceleration': accel,
            'brake': brake,
            'drift': drift,
            'nitro': False, 
            'rescue': False}

        return action

SAVE_COUNT = 0
SAVE_AT = 10

class Tournament:
    _singleton = None

    def __init__(self, players, screen_width=400, screen_height=300, track='icy_soccer_field'):
        assert Tournament._singleton is None, "Cannot create more than one Tournament object"
        Tournament._singleton = self

        HACK_DICT.clear()

        self.graphics_config = pystk.GraphicsConfig.hd()
        self.graphics_config.screen_width = screen_width
        self.graphics_config.screen_height = screen_height
        pystk.init(self.graphics_config)

        self.race_config = pystk.RaceConfig(num_kart=len(players), track=track, mode=pystk.RaceConfig.RaceMode.SOCCER)
        self.race_config.players.pop()
        
        self.active_players = []
        for p in players:
            if p is not None:
                self.race_config.players.append(p.config)
                self.active_players.append(p)
        
        self.k = pystk.Race(self.race_config)

        self.k.start()
        self.k.step()

    def play(self, save=None, max_frames=50, save_callback=None):
        global SAVE_COUNT, SAVE_AT
        state = pystk.WorldState()
        
        if save is not None:
            import PIL.Image
            if not os.path.exists(save):
                os.makedirs(save)

        # turn on interactive mode for controller visualization
        plt.ion()

        for t in range(max_frames):
            print('\rframe %d' % t, end='\r')

            state.update()
            list_actions = []

            for i, p in enumerate(self.active_players):
                HACK_DICT['race'] = self.k
                HACK_DICT['render_data'] = self.k.render_data[i]
                HACK_DICT['kart'] = state.karts[i]
                HACK_DICT['state'] = state
                
                #print('kart: ', state.karts[i].name, '\t\t max_steer: ', "{:.4f}".format(state.karts[i].max_steer_angle))

                player = state.players[i]
                image = np.array(self.k.render_data[i].image)
                
                action = pystk.Action()
                player_action = p(image, player)
                for a in player_action:
                    setattr(action, a, player_action[a])
                
                list_actions.append(action)

                if save is not None:
                    im = PIL.Image.fromarray(image)
                    #draw = ImageDraw.Draw(im)
                    #draw.text((0, 0),"Sample Text",(255,255,255))
                    im.save(os.path.join(save, 'player%02d_%05d.png' % (i, t)))

            for i, action in enumerate(list_actions):
                HACK_DICT['player_%d' % i] = {
                    'steer': action.steer,
                    'acceleration': action.acceleration
                    }

            if save_callback is not None:
                save_callback(self.k, state, t, HACK_DICT)
            
            SAVE_COUNT += 1

            s = self.k.step(list_actions)
            if not s:  # Game over
                break

        if save is not None:
            import subprocess
            for i, p in enumerate(self.active_players):
                dest = os.path.join(save, 'player%02d' % i)
                output = 'videos/_player%02d.mp4' % i
                subprocess.call(['ffmpeg', '-y', '-framerate', '10', '-i', dest + '_%05d.png', output])
                
        if hasattr(state, 'soccer'):
            return state.soccer.score
        return state.soccer_score

    def close(self):
        self.k.stop()
        del self.k

FINAL_INPUT = []
FINAL_LABEL = []

class DataCollector(object):
    def __init__(self, destination):
        self.images = list()
        self.destination = pathlib.Path(destination)
        self.destination.mkdir(exist_ok=True)

        self.image = os.path.join(destination, 'images')
        if not os.path.exists(self.image):
            os.mkdir(self.image)

        # self.image_p = os.path.join(self.image, 'has_puck')
        # if not os.path.exists(self.image_p): 
        #     os.mkdir(self.image_p)

        # self.image_np = os.path.join(self.image, 'no_puck')
        # if not os.path.exists(self.image_np): 
        #     os.mkdir(self.image_np)

        self.puck = os.path.join(destination, 'puck')
        if not os.path.exists(self.puck):
            os.mkdir(self.puck)

        # self.action = os.path.join(destination, 'actions')
        # if not os.path.exists(self.action): 
        #     os.mkdir(self.action)

    def save_puck_loc(self, race, state, t, hack_dict):
        global FINAL_INPUT, FINAL_LABEL

        for i in range(4):
            if not HACK_DICT['player_bool_%d' % i]:
                continue

            # player info
            pli = torch.Tensor(hack_dict['player_info_%d' % i])
            # puck info
            puu = torch.Tensor(hack_dict['puck_vec_%d' % i])

            FINAL_INPUT.append(pli)
            FINAL_LABEL.append(puu)

    def save_frame(self, race, state, t, hack_dict):
        # player
        for i in range(4):
            mask = (race.render_data[i].instance == 134217729)
            output_path = '%s/%d_%06d.png' % (self.puck, i, t)
            Image.fromarray(mask).save(output_path)
            
            image = race.render_data[i].image       # np uint8 (h, w, 3) [0, 255]
            output_path = '%s/%d_%06d.png' % (self.image, i, t)
            Image.fromarray(image).save(output_path)

            # has_puck = False
            # for row in mask:
            #     for b in row:
            #         if b:
            #             has_puck = True
            #             break

            # if has_puck:
            #     output_path = '%s/%d_%06d.png' % (self.puck, i, t)
            #     Image.fromarray(mask).save(output_path)

            # image = race.render_data[i].image       # np uint8 (h, w, 3) [0, 255]
            # if not has_puck:
            #     output_path = '%s/%d_%06d.png' % (self.image_np, i, t)
            #     Image.fromarray(image).save(output_path)
            # else:
            #     output_path = '%s/%d_%06d.png' % (self.image_p, i, t)
            #     Image.fromarray(image).save(output_path)

            # action = hack_dict['player_%d' % i]
            # output_path = '%s/%d_%06d.txt' % (self.action, i, t)
            # pathlib.Path(output_path).write_text('%.3f %.3f' % (action['steer'], action['acceleration']))

def collect_data(agents, dest, num_frames):
    players = []

    for i, player in enumerate(agents):
        if player == 'AI':
            players.append(DummyPlayer(i % 2))
        else:
            players.append(Player(player(i), i % 2))

    data_collector = DataCollector(dest)
    tournament = Tournament(players)
    score = tournament.play(max_frames=num_frames, save_callback=data_collector.save_frame)
    print('Final score', score)

def collect_puck_loc(agents, dest, num_frames):
    import pickle
    global FINAL_INPUT, FINAL_LABEL
    players = []
    for i, player in enumerate(agents):
        if player == 'AI':
            players.append(DummyPlayer(i % 2))
        else:
            players.append(Player(player(i), i % 2))

    data_collector = DataCollector(dest)
    tournament = Tournament(players)
    score = tournament.play(max_frames=num_frames, save_callback=data_collector.save_puck_loc)
    print('Final score', score)
    print("length of data: ", len(FINAL_LABEL))
    pickle.dump(FINAL_INPUT, open("data/puck_info.p", "wb"))
    pickle.dump(FINAL_LABEL, open("data/puck_vec.p", "wb"))

def test(agents, dest=None):
    players = []
    for i, player in enumerate(agents):
        if player == 'AI':
            players.append(DummyPlayer(i % 2))
        else:
            players.append(Player(player(i), i % 2))
        
    tournament = Tournament(players)
    #score = tournament.play(save=dest, max_frames=200)
    score = tournament.play(max_frames=1000)
    print('Final score', score)

if __name__ == '__main__':
    # Collect an episode.
    # collect_data([ScorePlayer, ScorePlayer, ScorePlayer, 'AI'], 'data', 12500)
    # collect_puck_loc([ScorePlayer, ScorePlayer, ScorePlayer, ScorePlayer], 'data', 10000)
    # test([ScorePlayer, 'AI', ScorePlayer, 'AI'])
    # test([OraclePlayer, OraclePlayer, OraclePlayer, OraclePlayer], 'test')
    test([HockeyPlayer, DontMove, HockeyPlayer, 'AI'])