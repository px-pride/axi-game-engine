from abc import ABC, abstractmethod

from axi.abstract_dm_game import AbstractDmGame

'''
Sometimes, it is easier to implement separate modes of a game as separate games.
This class lets you combine those modes under one umbrella.
The key is to set self.true_game when defining initialize_match_state().
'''


class AbstractModeSelector(AbstractDmGame, ABC):
    def __init__(self, players, mode="versus"):
        super().__init__(players, mode=mode)
        self.true_game = None

    @abstractmethod
    def validate_mode(self):
        pass

    @abstractmethod
    def initialize_match_state(self):
        pass

    def get_options(self, p):
        return self.true_game.get_options(p)

    def match_step(self):
        self.true_game.match_step()

    def winner(self):
        return self.true_game.winner()

    def receive_command(self, p, c):
        return self.true_game.receive_command(p, c)

    def match_init_msg(self, p):
        return self.true_game.match_init_msg(p)

    def match_over_msg(self, p):
        return self.true_game.match_over_msg(p)

    def initialize_message_queue(self):
        self.true_game.initialize_message_queue()

    def refresh_decisions(self):
        self.true_game.refresh_decisions()

    def flush_message_queue(self, p):
        return self.true_game.flush_message_queue(p)

    def agents(self):
        return self.true_game.agents()

    def add_spectator(self, user):
        self.true_game.add_spectator(user)

    def validate_decision(self, user, decision):
        return self.true_game.validate_decision(user, decision)

    def validate_emoji_decision(self, user, decision):
        return self.true_game.validate_emoji_decision(user, decision)

    def check_all_decisions_in(self):
        return self.true_game.check_all_decisions_in()

    def check_match_over(self):
        self.match_over = self.true_game.check_match_over()
        return self.match_over