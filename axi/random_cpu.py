from random import choice
from axi.abstract_cpu import AbstractCPU

class RandomCPU(AbstractCPU):
    def __init__(self, match):
        super().__init__(match)
        self.name = "Random CPU"

    def compute(self, options):
        return choice(options)

    def generate_wand(self):
        """Phase 16: sample 3 page-0 spells per shape (varied CPU play)."""
        return self.generate_random_wand()

