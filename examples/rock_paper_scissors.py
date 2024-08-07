from axi.abstract_dm_game import AbstractDmGame
from axi.simple_cpu import SimpleCPU

class RockPaperScissors(AbstractDmGame):

    def initialize_match_state(self):
        if self.mode == "cpu":
            cpu = SimpleCPU(self)
            self.players.append(cpu)
            self.expected_num_decisions[cpu] = 1
        self.scores = {p: 0 for p in self.players}
        self.first_to = 5
        self.max_rounds = 20
        self.options = ["\N{ROCK}", "\N{SCROLL}", "\N{BLACK SCISSORS}"]
        self.round_num = 1

    def vs_msg(self):
        msg = ''
        header = True
        msg += '**'
        for p in self.players:
            if not header:
                msg += ' vs. '
            msg += f'{p}'
            header = False
        msg += '.**\n'
        return msg

    def score_msg(self):
        msg = ""
        header = True
        msg += f"{self.players[0]} "
        for p in self.players:
            if not header:
                msg += '-'
            msg += f'{self.scores[p]}'
            header = False
        msg += f" {self.players[-1]}"
        msg += "\n"
        return msg

    def decisions_msg(self):
        msg = ""
        header = True
        msg += f"{self.players[0]} "
        for p in self.players:
            if not header:
                msg += '-'
            msg += f'{self.decisions[p]}'
            header = False
        msg += f" {self.players[-1]}"
        msg += "\n"
        return msg

    def options_str(self):
        msg = ""
        for i in range(len(self.options)):
            if i == len(self.options) - 1:
                msg += "or "
            msg += self.options[i]
            if i < len(self.options) - 1:
                msg += ', '
        return msg

    def validate_mode(self):
        return self.mode in ["versus", "cpu"]

    def get_options(self, p):
        return self.options

    def match_step(self):
        msg = self.decisions_msg()
        p_ls = []
        for p in self.players:
            p_ls.append((p, self.decisions[p].upper()))
        if p_ls[0][1] == p_ls[1][1]:
            msg += f"It's a tie!  Go again.\n"
        elif (p_ls[0][1] == self.options[0] and p_ls[1][1] == self.options[1]) or (
                    p_ls[0][1] == self.options[1] and p_ls[1][1] == self.options[2]) or (
                    p_ls[0][1] == self.options[2] and p_ls[1][1] == self.options[0]):
                self.scores[p_ls[1][0]] += 1
                msg += f"{p_ls[1][0]} wins the round.\n"
        else:
            self.scores[p_ls[0][0]] += 1
            msg += f"{p_ls[0][0]} wins the round.\n"
        msg += self.score_msg()
        if max(self.scores.values()) < self.first_to:
            if self.round_num + 5 >= self.max_rounds:
                msg += f"First to {self.first_to} points. Maximum {self.max_rounds} rounds.\n"
            else:
                msg += f"First to {self.first_to} points.\n"
            msg += f"Round {self.round_num}. React with {self.options_str()}.\n"
        self.round_num += 1
        for p in self.message_queue:
            self.message_queue[p].append((msg, None))

    def winner(self):
        if len(self.resigned) == 2:
            return self.resigned[-1]
        if len(self.resigned) == 1:
            for p in self.players:
                if p not in self.resigned:
                    return p
        max_p = None
        max_score = 0
        won = self.round_num >= self.max_rounds
        for p in self.scores:
            if self.scores[p] >= max_score:
                max_score = self.scores[p]
                max_p = p
                if max_score >= self.first_to:
                    won = True
        if won:
            return max_p
        return None

    def receive_command(self, p, c):
        return False

    def match_init_msg(self, p):
        msg = ''
        msg += f"RPS, standard rules. First to {self.first_to}. Maximum {self.max_rounds} rounds.\n"
        msg += f"{self.vs_msg()}"
        msg += f"{self.score_msg()}"
        msg += f"Round {self.round_num}. React with {self.options_str()}.\n"
        return (msg, None)

    def match_over_msg(self, p):
        msg = f"The winner is {self.winner()}!\n"
        return (msg, None)


RockPaperScissors.__name__ = "rps"
