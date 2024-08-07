from abc import ABC, abstractmethod

class AbstractCPU(ABC):
    def __init__(self, match):
        self.match = match
        self.name = "Abstract CPU"

    def __repr__(self):
        return self.name

    @abstractmethod
    def compute(self, options):
        pass
