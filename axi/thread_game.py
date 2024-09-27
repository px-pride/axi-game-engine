from copy import deepcopy
from axi.util import rng
from axi.abstract_game import AbstractGame
import axi.handlers.match_handler as match_handler

class ThreadGame(AbstractGame):
    def __init__(self, game_info, players, mode="versus", ladder=None, best_of=1, checkin_timer=None, label="UNRANKED"):
        super().__init__(
            players, mode=mode, ladder=ladder, best_of=best_of, checkin_timer=checkin_timer, label=label)
        self.info = game_info
        self.discord_thread = None
        self.streamed = False
        self.checkins = set()
        self.reports = dict()
        self.abort_requests = set()
        self.first_ban = rng.randrange(2)

    def description(self, pov=None, checkintimer=False, first_ban=False):
        msg = super().description(pov=pov, checkintimer=checkintimer)
        if first_ban:
            msg += f"{self.players[self.first_ban]} bans first.\n"
        if self.streamed:
            msg = ':tv: ' + msg
        return msg

    def checkin_user(self, user):
        if user not in self.checkins:
            self.checkins.add(user)
            return True
        return False

    def check_match_over(self):
        return super().check_match_over() or self.check_match_aborted()

    def match_init_msg(self):
        init_msg = deepcopy(self.info["init"])
        init_msg.append([self.description(first_ban=True), ""])
        return init_msg

    def match_over_msg(self):
        return [("Score reported and confirmed.\n", None)]

    def report_winner(self, caller, winner, admin_override=False):
        if admin_override:
            self.reports["admin"] = winner
        else:
            self.reports[caller] = winner

    def report_abort(self, caller):
        self.abort_requests.add(caller)

    def check_match_aborted(self):
        if "admin" in self.abort_requests:
            return True
        for p in self.players:
            if p not in self.abort_requests:
                return False
        return True

    def winner(self):
        if "admin" in self.reports:
            return self.reports["admin"]
        reported_winner = None
        for p in self.players:
            if p not in self.reports:
                return None
            if reported_winner:
                if self.reports[p] != reported_winner:
                    return None
            else:
                reported_winner = self.reports[p]
        return reported_winner
