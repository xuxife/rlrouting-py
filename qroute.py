import numpy as np

from base_policy import Policy


class Qroute(Policy):
    """ Qroute use Q routing as policy.

    Attributes:
        Qtable : Stores the Q scores of all nodes.
    """
    attrs = Policy.attrs | set(['Qtable'])

    def __init__(self, network, initQ=0):
        super().__init__(network)
        self.Qtable = {source:
                       np.random.normal(
                           initQ, 1, (len(self.links), len(neighbors)))
                       for source, neighbors in self.links.items()}
        for source, table in self.Qtable.items():
            # Q_x(z, x) = 0, forall z in x.neighbors (not useful)
            table[source] = 0
            # Q_x(z, y) = -1 if z == y else 0
            table[self.links[source]] = -np.eye(table.shape[1])

    def choose(self, source, dest, score=False):
        scores = self.Qtable[source][dest]
        score_max = scores.max()
        choice = np.random.choice(np.argwhere(scores == score_max).flatten())
        if score:
            return self.links[source][choice], score_max
        else:
            return self.links[source][choice]

    def get_reward(self, source, action, packet):
        return {'max_Q_y': self.Qtable[action][packet.dest].max()}

    def learn(self, rewards, lr={'q': 0.1}):
        for reward in filter(lambda r: r.action != r.dest, rewards):
            source, dest, action = reward.source, reward.dest, reward.action
            action_max = reward.agent_info['max_Q_y']
            action_idx = self.action_idx[source][action]
            old_score = self.Qtable[source][dest][action_idx]
            self.Qtable[source][dest][action_idx] += lr['q'] * \
                (-reward.agent_info['q_y'] + action_max - old_score)


class CDRQ(Qroute):
    attrs = Qroute.attrs | set(['confidence'])

    def __init__(self, network, decay=0.9, initQ=0):
        super().__init__(network, initQ)
        network.dual = True  # enable DUAL mode
        self.decay = decay
        self.confidence = {source:
                           np.zeros((len(self.links), len(neighbors)))
                           for source, neighbors in self.links.items()}
        self.updated_conf = {source:
                             np.zeros(
                                 (len(self.links), len(neighbors)), dtype=bool)
                             for source, neighbors in self.links.items()}
        for source in self.links.keys():
            # C_x(z, y) = 1 if z == y else 0
            self.confidence[source][self.links[source]] = np.eye(
                len(self.links[source]))
            self.updated_conf[source][self.links[source]] = np.eye(
                len(self.links[source], dtype=bool))

    def get_reward(self, source, action, packet):
        z_x, max_Q_x = self.choose(source, packet.source, score=True)
        z_y, max_Q_y = self.choose(action, packet.dest, score=True)
        return {
            'max_Q_x': max_Q_x,
            'max_Q_y': max_Q_y,
            'C_x': self.confidence[source][packet.source][z_x],
            'C_y': self.confidence[action][packet.dest][z_y],
        }

    def learn(self, rewards, lr={'f': 0.85, 'b': 0.95}):
        for reward in filter(lambda r: r.action != r.dest, rewards):
            x, y = reward.source, reward.action
            source, dest = reward.packet.source, reward.packet.dest
            info = reward.agent_info
            x_idx, y_idx = self.action_idx[y][x], self.action_idx[x][y]
            " forward "
            if y != dest:
                old_Q_x = self.Qtable[x][dest][y_idx]
                eta_forward = max(
                    info['C_y'], 1-self.confidence[x][dest][y_idx])
                self.Qtable[x][dest][y_idx] += lr['f'] * eta_forward * \
                    (info['max_Q_y'] - info['q_y'] - old_Q_x)
                self.confidence[x][dest][y_idx] += eta_forward * \
                    (info['C_y']-self.confidence[x][dest][y_idx])
                self.updated_conf[x][dest][y_idx] = True
            " backward "
            if x != source:
                old_Q_y = self.Qtable[y][source][x_idx]
                eta_backward = max(
                    info['C_x'], 1-self.confidence[y][source][x_idx])
                self.Qtable[y][source][x_idx] += lr['b'] * eta_backward * \
                    (info['max_Q_x'] - info['q_x'] - old_Q_y)
                self.confidence[y][source][x_idx] += eta_backward * \
                    (info['C_x']-self.confidence[y][source][x_idx])
                self.updated_conf[y][source][x_idx] = True

        for source, table in self.updated_conf.items():
            self.confidence[source][~table] *= self.decay
            table.fill(False)
            table[self.links[source]] = np.eye(table.shape[1], dtype=bool)
