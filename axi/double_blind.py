from axi.abstract_dm_game import AbstractDmGame

class DoubleBlind(AbstractDmGame):

    def validate_mode(self):
        return self.mode == "versus"

    def initialize_match_state(self):
        self.done = False
        self.selections = {p: "NO SELECTION MADE" for p in self.players}

    def get_options(self, p):
        return ["\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE}"]

    def match_step(self):
        msg = ''
        for p in self.players:
            msg += f"{p} selected: {self.selections[p]}.\n"
        for p in self.message_queue:
            self.message_queue[p].append((msg, None))
        self.done = True

    def winner(self):
        if self.done:
            return self.players[0]
        return None

    def receive_command(self, p, c):
        self.selections[p] = c

    def match_init_msg(self, p):
        msg = ''
        msg += 'Double-blind character selection has begun!\n'
        msg += 'Type and send the name of your character, then react with \N{BLACK RIGHT-POINTING DOUBLE TRIANGLE}.\n'
        return msg, None

    def match_over_msg(self, p):
        return "Double-blind character selection has finished.\n", None


DoubleBlind.__name__ = "doubleblind"
