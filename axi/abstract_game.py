from abc import ABC, abstractmethod

class AbstractGame(ABC):
    def __init__(self, players, mode="versus", ladder=None, best_of=1, checkin_timer=None, label="UNRANKED"):
        self.players = players
        self.mode = mode
        self.ladder = ladder
        self.best_of = best_of
        self.checkin_timer = checkin_timer
        self.label = label
        self.checkins = set()
        self.checkin_deadline = None
        self.streamed = False
        self.match_over = False

    def agents(self):
        return self.players

    def check_match_over(self):
        if not self.match_over:
            self.match_over = self.winner() is not None
        return self.match_over

    def opponent(self, player):
        if len(self.players) != 2 or player not in self.players:
            return None
        return self.players[0] if self.players[1] == player else self.players[1]

    @abstractmethod
    # Return type: AxiUser or None
    # Description: Returns None if the game is ongoing, or the winning player if the game has completed.
    def winner(self):
        pass

    def loser(self):
        return self.opponent(self.winner())

    def first_to(self):
        return (self.best_of + 1) // 2

    def description(self, pov=None, checkintimer=False):
        msg = ''
        msg += f"{self.label}: "
        if self.best_of:
            if self.best_of < 9:
                msg += f"*Bo{self.best_of}.* "
            else:
                msg += f"*Ft{self.first_to()}.* "
        if len(self.players) == 2:
            msg += "**"
            if self.label in ["DOUBLE DANGER", "LOSERS FINALS", "GRAND FINALS"]:
                msg += ":rotating_light: "
            msg += f"{self.players[0].parse(self.players[0] not in self.checkins)} vs "
            if self.label in ["DOUBLE DANGER", "LOSERS FINALS", "GRAND FINALS", "DANGER MATCH"]:
                msg += ":rotating_light: "
            msg += f"{self.players[1].parse(self.players[1] not in self.checkins)}.** "
        else:
            if self.players:
                msg += "**"
                for p in self.players:
                    msg += f" {p.parse(p not in self.checkins)} |"
                msg += "**"
            msg += " "
        if self.check_match_over():
            if not pov:
                msg += f"{self.winner()} wins."
            else:
                winning = "wins" if pov == self.winner() else "loses"
                msg += f"{pov} {winning}."
        if self.checkin_deadline:
            if checkintimer:
                msg += "\n"
            time_left = self.checkin_deadline - time.time()
            if time_left > 60:
                mins_left = round(time_left / 60)
                if checkintimer:
                    msg += f"Just say something to automatically check in! ~{mins_left} minute{'s' if mins_left != 1 else ''} left.\n"
                    if mins_left > 6:
                        msg += f"*(Increased timer because a player was on break.)*\n"
            else:
                secs_left = round(time_left)
                if checkintimer:
                    msg += f"Just say something to automatically check in! ~{secs_left} second{'s' if secs_left != 1 else ''} left.\n"
        return msg