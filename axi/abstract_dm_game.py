from abc import ABC, abstractmethod

'''
Your custom game will extend AbstractDmGame.
It must implement the abstract methods described at the bottom of the class definition.
'''

class AbstractDmGame(ABC):
    def __init__(self, players, mode="versus"):
        self.players = players
        self.mode = mode
        self.resigned = []
        self.spectators = []
        self.match_over = False
        self.expected_num_decisions = {p: 1 for p in self.players}

    def initialize_message_queue(self):
        self.message_queue = {p: [] for p in self.agents()}
        for p in self.message_queue:
            messages = self.match_init_msg(p)
            if isinstance(messages, list):
                self.message_queue[p] += messages
            else:
                self.message_queue[p].append(messages)

    def refresh_decisions(self):
        self.decisions = {p: None for p in self.players}

    def flush_message_queue(self, p):
        flushed = self.message_queue[p]
        self.message_queue[p] = []
        return flushed

    def agents(self):
        return list(set(self.players).union(set(self.spectators)))

    def add_spectator(self, user):
        self.message_queue[user] = []
        self.spectators.append(user)

    def validate_decision(self, user, decision):
        if decision == "abort":
            self.decisions[user] = decision
            self.resigned.append(user)
            return True
        valid = self.validate_emoji_decision(user, decision)
        if valid:
            if not self.decisions[user]:
                self.decisions[user] = decision
            else:
                if not isinstance(self.decisions[user], list):
                    self.decisions[user] = [self.decisions[user]]
                if not isinstance(decision, list):
                    decision = [decision]
                self.decisions[user] += decision
            return True
        return False

    def validate_emoji_decision(self, user, decision):
        options = self.get_options(user)
        if (self.expected_num_decisions[user] == 1 and self.decisions[user]) or (
                isinstance(self.decisions[user], list) and len(self.decisions[user]) >= self.expected_num_decisions[user]):
            self.message_queue[user].append(("You've already committed!\n", None))
            return False
        if isinstance(decision, list):
            for d in decision:
                if d not in options:
                    self.message_queue[user].append(("Illegal option!\n", None))
                    return False
            return True
        if decision not in options:
            self.message_queue[user].append(("Illegal option! React to choose an option.\n", None))
            return False
        msg = ''
        if self.expected_num_decisions[user] == 1:
            msg += f"[Secret] You chose {decision}.\n"
        elif not self.decisions[user]:
            msg += f"[Secret] You chose {decision}. React {self.expected_num_decisions[user] - 1} more time{'s' if self.expected_num_decisions[user] - 1 > 1 else ''}.\n"
        elif not isinstance(self.decisions[user], list):
            msg += f"[Secret] You chose {decision}. React {self.expected_num_decisions[user] - 2} more time{'s' if self.expected_num_decisions[user] - 2 > 1 else ''}.\n"
        elif len(self.decisions[user]) < self.expected_num_decisions[user] - 1:
            msg += f"[Secret] You chose {decision}. React {self.expected_num_decisions[user] - len(self.decisions[user]) - 1} more time{'s' if self.expected_num_decisions[user] - len(self.decisions[user]) - 1 > 1 else ''}.\n"
        else:
            msg += f"[Secret] You chose {decision}.\n"
        self.message_queue[user].append((msg, None))
        return True

    def check_all_decisions_in(self):
        for p in self.expected_num_decisions:
            if self.expected_num_decisions[p] == 0:
                continue
            if self.decisions[p] == "abort":
                continue
            if not self.decisions[p]:
                return False
            if self.expected_num_decisions[p] > 1:
                if not isinstance(self.decisions[p], list):
                    return False
                if len(self.decisions[p]) < self.expected_num_decisions[p]:
                    return False
        return True

    def check_match_over(self):
        if not self.match_over:
            self.match_over = self.winner() is not None
            if self.match_over:
                for a in self.agents():
                    messages = self.match_over_msg(a)
                    if isinstance(messages, list):
                        self.message_queue[a] += messages
                    else:
                        self.message_queue[a].append(messages)
        return self.match_over

    @abstractmethod
    # Return type: boolean
    # Description: Confirm if mode is supported.
    # Typically, you would set up a list of legal modes and just check self.mode against it.
    def validate_mode(self):
        pass

    @abstractmethod
    # Return type: None
    # Description: Create in initial state.
    # More internal variables will be defined here.
    def initialize_match_state(self):
        pass

    @abstractmethod
    # Return type: list of emojis
    # Description: Determine what the players' allowed choices are.
    # Decisions are made through emoji reactions on Discord.
    def get_options(self, p):
        pass

    @abstractmethod
    # Return type: none
    # Description: After all players have made their decisions, move the game forward one step/turn/round.
    # Most of the logic of your game will be in this function.
    def match_step(self):
        pass

    @abstractmethod
    # Return type: AxiUser or None
    # Description: Returns None if the game is ongoing, or the winning player if the game has completed.
    def winner(self):
        pass

    # Return type: boolean
    # Description: Allows you to control your game with text commands, independent from emoji decisions.
    # Typical use cases are commands to show rules, stats, etc.
    # Returns True if your game recognizes the command and False otherwise.
    @abstractmethod
    def receive_command(self, p, c):
        pass

    # Return type: (string, image_filename) or list of (string, image_filename)s
    # Description: These messages get sent to each agent at the start of the game.
    @abstractmethod
    def match_init_msg(self, p):
        pass

    # Return type: (string, filename) or list of (string, filename)s
    # Description: These messages get sent to each agent at the end of the game.
    @abstractmethod
    def match_over_msg(self, p):
        pass


