from random import choice
from axi.abstract_cpu import AbstractCPU

class RandomCPU(AbstractCPU):
    def __init__(self, match):
        super().__init__(match)
        self.name = "Random CPU"

    def compute(self, options):
        return choice(options)

