import math
from typing import Callable

class GlickoTimeless:
    def __init__(self, match_ratings):
        self.match_ratings = match_ratings
        self.c2 = 0
        self.q = math.log(10) / 400.0

    def calculate_deltas(self, time_decay=0):
        def G(rdi):
            q_prime = 3 * self.q * self.q / (math.pi * math.pi)
            return 1.0 / math.sqrt(1 + q_prime * rdi * rdi)
        def E(r0, ri, rdi):
            return 1.0 / (1 + math.pow(10, G(rdi) * (r0-ri) / (-400)))
        def d2_inv(r0, ri, rdi):
            d2_inverse = G(rdi) * G(rdi) * E(r0, ri, rdi) * (1 - E(r0, ri, rdi))
            d2_inverse *= self.q * self.q
            return d2_inverse

        mu = []
        rdt = []
        for i in range(2):
            mu.append(self.match_ratings[i].mu)
            rdt.append(self.match_ratings[i].sigma)
            if time_decay and self.c2:
                rdt[i] = min(
                    350.0, math.sqrt(rdt[i]*rdt[i] + self.c2*time_decay))
        delta_mu = []
        delta_log_sigma = []
        for i in range(2):
            dm = 0.0
            dm += G(rdt[1-i]) * ((1-i) - E(mu[i], mu[1-i], rdt[1-i]))
            rdp2 = 1.0 / (1/(rdt[i]*rdt[i]) + d2_inv(mu[i], mu[1-i], rdt[1-i]))
            dm *= self.q * rdp2
            rdp = math.sqrt(rdp2)
            dls = math.log(rdp/rdt[i])
            delta_mu.append(dm)
            delta_log_sigma.append(dls)
        result = [[delta_mu[0], delta_log_sigma[0]], [delta_mu[1], delta_log_sigma[1]]]
        return result
