from axi.abstract_cpu import AbstractCPU

class SimpleCPU(AbstractCPU):
    def __init__(self, match):
        super().__init__(match)
        self.name = "Simple CPU"
        self.state = 0

    def compute(self, options):
        num_decisions = self.match.expected_num_decisions[self]
        decision = None
        for i in range(num_decisions):
            self.state += 1
            choice = options[self.state % len(options)]
            options.remove(choice)
            if not decision:
                decision = choice
            elif isinstance(decision, list):
                decision.append(choice)
            else:
                decision = [decision, choice]
        return decision

