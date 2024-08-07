import examples.wonder_wand.spells as spells
import examples.wonder_wand.customize_wand as customize_wand
from examples.wonder_wand.wonder_wand_profile import WonderWandProfile
from axi.abstract_dm_game import AbstractDmGame
from axi.abstract_mode_selector import AbstractModeSelector
from axi.abstract_cpu import AbstractCPU
from axi.simple_cpu import SimpleCPU
from axi.axi import load_profile, save_profile


class Wand:
    def __init__(self, name, choices):
        self.emojis_to_moves = {
            "\N{LARGE RED CIRCLE}": ("red", "circle"),
            "\N{LARGE RED SQUARE}": ("red", "square"),
            "\N{HEAVY BLACK HEART}": ("red", "heart"),
            "\N{LARGE ORANGE CIRCLE}": ("orange", "circle"),
            "\N{LARGE ORANGE SQUARE}": ("orange", "square"),
            "\N{ORANGE HEART}": ("orange", "heart"),
            "\N{LARGE YELLOW CIRCLE}": ("yellow", "circle"),
            "\N{LARGE YELLOW SQUARE}": ("yellow", "square"),
            "\N{YELLOW HEART}": ("yellow", "heart"),
            "\N{LARGE GREEN CIRCLE}": ("green", "circle"),
            "\N{LARGE GREEN SQUARE}": ("green", "square"),
            "\N{GREEN HEART}": ("green", "heart"),
            "\N{LARGE BLUE CIRCLE}": ("blue", "circle"),
            "\N{LARGE BLUE SQUARE}": ("blue", "square"),
            "\N{BLUE HEART}": ("blue", "heart"),
            "\N{LARGE PURPLE CIRCLE}": ("purple", "circle"),
            "\N{LARGE PURPLE SQUARE}": ("purple", "square"),
            "\N{PURPLE HEART}": ("purple", "heart"),
        }
        self.name = name
        self.spells = {s.emoji(): s for s in choices}
        self.equipped = sorted(
            list(set(self.spells.keys())),
            key=lambda x: list(self.emojis_to_moves.keys()).index(x))
        self.unequipped = sorted(
            list(set(self.emojis_to_moves.keys()) - set(self.equipped)),
            key=lambda x: list(self.emojis_to_moves.keys()).index(x))
        self.active = {e: False for e in self.spells}
        self.burned = {e: False for e in self.spells}
        self.frozen = dict()
        self.frozen["\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}"] = False
        self.frozen["\N{SHIELD}"] = False
        for e in self.emojis_to_moves:
            self.frozen[e] = False
        self.known = {e: False for e in self.spells}
        self.antiknown = {e: False for e in self.spells}
        self.superknown = {e: False for e in self.spells}
        self.equipped_known = {e: True for e in self.emojis_to_moves.keys()}
        self.equipped_fully_known = True
        self.hexes = []
        self.bounced = None
        self.fresh_charge = False

    def equip_know(self, e):
        self.superknown[e] = True
        self.equipped_known[e] = True
        complete = True
        for e_ in self.equipped:
            if not self.equipped_known[e_]:
                complete = False
                break
        if not complete:
            complete = True
            for e_ in self.unequipped:
                if not self.equipped_known[e_]:
                    complete = False
                    break
        if complete and not self.equipped_fully_known:
            self.equipped_fully_known = True
            for e_ in self.equipped_known:
                self.equipped_known[e_] = True

    def info(self, limit):
        self.check_completeness()
        msg = ""
        msg += f"> Locked Out: "
        locked = ""
        for e in sorted(self.active.keys(), key=lambda x: list(self.emojis_to_moves.keys()).index(x)):
            if self.frozen[e]:
                locked += f"{e} "
        if locked:
            msg += f"{locked}\r\n"
        else:
            msg += f"None\r\n"
        msg += f"> Spell Pool: "
        pool = ""
        for e in sorted(self.active.keys(), key=lambda x: list(self.emojis_to_moves.keys()).index(x)):
            if self.active[e]:
                pool += f"{e} "
        if pool:
            msg += f"{pool}\r\n"
        else:
            msg += f"None\r\n"
        msg += f"> Unprepared: "
        for e in sorted(self.active.keys(), key=lambda x: list(self.emojis_to_moves.keys()).index(x)):
            if not self.active[e]:
                msg += f"{e} "
        msg += "\r\n"
        return msg

    def opp_info(self, limit):
        if self.fresh_charge:
            msg = ""
            msg += "> Locked Out: None\r\n"
            msg += f"> Spell Pool: "
            for i in range(limit):
                msg += f"\N{BLACK QUESTION MARK ORNAMENT}"
            msg += "\r\n"
            msg += f"> Unprepared: "
            for i in range(len(self.spells) - limit):
                msg += f"\N{BLACK QUESTION MARK ORNAMENT}"
            msg += "\r\n"
            msg += f"> Equipped: "
            nonqmarks = ""
            qmarks = ""
            for e in self.equipped:
                if self.equipped_known[e]:
                    nonqmarks += f"{e} "
                else:
                    qmarks += f"\N{BLACK QUESTION MARK ORNAMENT}"
            if nonqmarks or qmarks:
                msg += f"{nonqmarks}{qmarks}\r\n"
            else:
                msg += f"None\r\n"
            '''
            msg += f"> Unequipped: "
            nonqmarks = ""
            qmarks = ""
            for e in self.unequipped:
                if self.equipped_known[e]:
                    nonqmarks += f"{e} "
                else:
                    qmarks += f"\N{BLACK QUESTION MARK ORNAMENT}"
            if nonqmarks or qmarks:
                msg += f"{nonqmarks}{qmarks}\r\n"
            else:
                msg += f"None\r\n"
            '''
            return msg
        self.check_completeness()
        msg = ""
        msg += f"> Locked Out: "
        locked = ""
        for e in sorted(self.spells.keys(), key=lambda x: list(self.emojis_to_moves.keys()).index(x)):
            if self.frozen[e]:
                locked += f"{e} "
        if locked:
            msg += f"{locked}\r\n"
        else:
            msg += f"None\r\n"
        msg += f"> Spell Pool: "
        nonqmarks = ""
        qmarks = ""
        for e in sorted(self.active.keys(), key=lambda x: list(self.emojis_to_moves.keys()).index(x)):
            if self.active[e]:
                if self.known[e]:
                    nonqmarks += f"{e} "
                else:
                    qmarks += f"\N{BLACK QUESTION MARK ORNAMENT}"
        if nonqmarks or qmarks:
            msg += f"{nonqmarks}{qmarks}\r\n"
        else:
            msg += f"None\r\n"
        msg += f"> Unprepared: "
        nonqmarks = ""
        qmarks = ""
        for e in sorted(self.active.keys(), key=lambda x: list(self.emojis_to_moves.keys()).index(x)):
            if not self.active[e]:
                if self.antiknown[e]:
                    nonqmarks += f"{e} "
                else:
                    qmarks += f"\N{BLACK QUESTION MARK ORNAMENT}"
        if nonqmarks or qmarks:
            msg += f"{nonqmarks}{qmarks}\r\n"
        else:
            msg += f"None\r\n"
        msg += f"> Equipped: "
        nonqmarks = ""
        qmarks = ""
        for e in self.equipped:
            if self.equipped_known[e]:
                nonqmarks += f"{e} "
            else:
                qmarks += f"\N{BLACK QUESTION MARK ORNAMENT}"
        if nonqmarks or qmarks:
            msg += f"{nonqmarks}{qmarks}\r\n"
        else:
            msg += f"None\r\n"
        '''
        msg += f"> Unequipped: "
        nonqmarks = ""
        qmarks = ""
        for e in self.unequipped:
            if self.equipped_known[e]:
                nonqmarks += f"{e} "
            else:
                qmarks += f"\N{BLACK QUESTION MARK ORNAMENT}"
        if nonqmarks or qmarks:
            msg += f"{nonqmarks}{qmarks}\r\n"
        else:
            msg += f"None\r\n"
        '''
        return msg

    def check_completeness(self):
        if self.fresh_charge:
            return False
        known_count = 0
        antiknown_count = 0
        for e in self.spells:
            if self.known[e]:
                known_count += 1
            if self.antiknown[e]:
                antiknown_count += 1
        if known_count == self.count() and self.equipped_fully_known:
            for e in self.spells:
                if not self.known[e]:
                    self.antiknown[e] = True
                    self.equip_know(e)
            return True
        if antiknown_count == len(self.spells) - self.count() and self.equipped_fully_known:
            for e in self.spells:
                if not self.antiknown[e]:
                    self.known[e] = True
                    self.equip_know(e)
            return True
        return False

    def load(self, emoji):
        self.active[emoji] = True

    def unload(self, emoji):
        self.active[emoji] = False

    def count(self):
        c = 0
        for e in self.active:
            if self.active[e]:
                c += 1
        return c

    def refresh(self):
        self.active = {e: False for e in self.spells}
        self.burned = {e: False for e in self.spells}
        self.frozen = dict()
        self.frozen["\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}"] = False
        self.frozen["\N{SHIELD}"] = False
        for e in self.emojis_to_moves:
            self.frozen[e] = False
        self.known = {e: False for e in self.spells}
        self.antiknown = {e: False for e in self.spells}
        self.hexes = []

    def recharge(self, emojis):
        self.refresh()
        for e in emojis:
            if e in self.spells:
                self.active[e] = True
        self.fresh_charge = False

def color(e):
    if e in ["\N{PURPLE HEART}", "\N{LARGE PURPLE SQUARE}", "\N{LARGE PURPLE CIRCLE}"]:
        return "purple"
    if e in ["\N{BLUE HEART}", "\N{LARGE BLUE SQUARE}", "\N{LARGE BLUE CIRCLE}"]:
        return "blue"
    if e in ["\N{GREEN HEART}", "\N{LARGE GREEN SQUARE}", "\N{LARGE GREEN CIRCLE}"]:
        return "green"
    if e in ["\N{YELLOW HEART}", "\N{LARGE YELLOW SQUARE}", "\N{LARGE YELLOW CIRCLE}"]:
        return "yellow"
    if e in ["\N{ORANGE HEART}", "\N{LARGE ORANGE SQUARE}", "\N{LARGE ORANGE CIRCLE}"]:
        return "orange"
    if e in ["\N{HEAVY BLACK HEART}", "\N{LARGE RED SQUARE}", "\N{LARGE RED CIRCLE}"]:
        return "red"
    return None

def color_id(e):
    c = color(e)
    if c == "red":
        return 0
    if c == "orange":
        return 1
    if c == "yellow":
        return 2
    if c == "green":
        return 3
    if c == "blue":
        return 4
    if c == "purple":
        return 5
    return None

def element(e):
    c = color(e)
    if c == "red":
        return "Fire"
    if c == "orange":
        return "Earth"
    if c == "yellow":
        return "Lightning"
    if c == "green":
        return "Nature"
    if c == "blue":
        return "Water"
    if c == "purple":
        return "Air"
    return None

def shape(e):
    if e in ["\N{BROWN HEART}", "\N{PURPLE HEART}", "\N{BLUE HEART}", "\N{GREEN HEART}", "\N{YELLOW HEART}", "\N{ORANGE HEART}", "\N{HEAVY BLACK HEART}"]:
        return "heart"
    if e in ["\N{LARGE BROWN SQUARE}", "\N{LARGE PURPLE SQUARE}", "\N{LARGE BLUE SQUARE}", "\N{LARGE GREEN SQUARE}", "\N{LARGE YELLOW SQUARE}", "\N{LARGE ORANGE SQUARE}", "\N{LARGE RED SQUARE}"]:
        return "square"
    if e in ["\N{LARGE BROWN CIRCLE}", "\N{LARGE PURPLE CIRCLE}", "\N{LARGE BLUE CIRCLE}", "\N{LARGE GREEN CIRCLE}", "\N{LARGE YELLOW CIRCLE}", "\N{LARGE ORANGE CIRCLE}", "\N{LARGE RED CIRCLE}"]:
        return "circle"
    return None

def spellclass(e):
    s = shape(e)
    if s == "heart":
        return "Hex"
    if s == "square":
        return "Strike"
    if s == "circle":
        return "Counter"

def wand_default():
    return Wand("Default Wand", [
                     spells.RedCounterA(), #
                     spells.RedStrikeA(), #
                     spells.RedHexA(), ##
                     spells.GreenCounterA(), #
                     spells.GreenStrikeA(), #
                     spells.GreenHexA(), ##
                     spells.BlueCounterA(), #
                     spells.BlueStrikeA(), #
                     spells.BlueHexA(), ##
                 ])

def load_saved_wand(p):
    if isinstance(p, AbstractCPU):
        return wand_default()
    profile = load_profile(p, "wonderwand")
    if not profile:
        profile = WonderWandProfile()
        save_profile(p, "wonderwand", profile)
    return profile.get_equipped_wand()

PHASE_COMBAT = 0
PHASE_EFFECTS = 1
PHASE_EOT = 2

class WonderWandVersus(AbstractDmGame):

    def validate_mode(self):
        return self.mode in ["versus", "cpu"]

    def initialize_match_state(self):
        if self.mode == "cpu":
            cpu = SimpleCPU(self)
            self.players.append(cpu)
            self.expected_num_decisions[cpu] = 1
        self.initial_hp = 40
        self.scores = {p: self.initial_hp for p in self.players}
        self.options = []
        self.colors = [
            "red",
            "orange",
            "yellow",
            "green",
            "blue",
            "purple",
        ]
        self.shapes = ["circle", "square", "heart"]
        self.color_advantage_chart = {
            "red": {
                "red": 0,
                "orange": -1,
                "yellow": 0,
                "green": 1,
                "blue": -1,
                "purple": 0,
            },
            "orange": {
                "red": 1,
                "orange": 0,
                "yellow": 1,
                "green": -1,
                "blue": -1,
                "purple": -1.
            },
            "yellow": {
                "red": 0,
                "orange": -1,
                "yellow": 0,
                "green": -1,
                "blue": 1,
                "purple": 1,
            },
            "green": {
                "red": -1,
                "orange": 1,
                "yellow": 1,
                "green": 0,
                "blue": 1,
                "purple": -1,
            },
            "blue": {
                "red": 1,
                "orange": 1,
                "yellow": -1,
                "green": -1,
                "blue": 0,
                "purple": 0,
            },
            "purple": {
                "red": 0,
                "orange": 1,
                "yellow": -1,
                "green": 1,
                "blue": 0,
                "purple": 0,
            },
        }
        self.emojis_to_moves = {
            "\N{LARGE RED CIRCLE}": ("red", "circle"),
            "\N{LARGE RED SQUARE}": ("red", "square"),
            "\N{HEAVY BLACK HEART}": ("red", "heart"),
            "\N{LARGE ORANGE CIRCLE}": ("orange", "circle"),
            "\N{LARGE ORANGE SQUARE}": ("orange", "square"),
            "\N{ORANGE HEART}": ("orange", "heart"),
            "\N{LARGE YELLOW CIRCLE}": ("yellow", "circle"),
            "\N{LARGE YELLOW SQUARE}": ("yellow", "square"),
            "\N{YELLOW HEART}": ("yellow", "heart"),
            "\N{LARGE GREEN CIRCLE}": ("green", "circle"),
            "\N{LARGE GREEN SQUARE}": ("green", "square"),
            "\N{GREEN HEART}": ("green", "heart"),
            "\N{LARGE BLUE CIRCLE}": ("blue", "circle"),
            "\N{LARGE BLUE SQUARE}": ("blue", "square"),
            "\N{BLUE HEART}": ("blue", "heart"),
            "\N{LARGE PURPLE CIRCLE}": ("purple", "circle"),
            "\N{LARGE PURPLE SQUARE}": ("purple", "square"),
            "\N{PURPLE HEART}": ("purple", "heart"),
        }
        self.moves_to_emojis = {self.emojis_to_moves[k]: k for k in self.emojis_to_moves}
        self.wands = dict()
        for p in self.players:
            self.wands[p] = load_saved_wand(p)
        self.round = 0
        self.winning_ids = []
        self.combat_options = {p: None for p in self.players}
        self.casters = []
        self.blockers = []
        self.chargers = [p for p in self.players]
        self.scouters = []
        self.max_rounds = self.initial_hp * 2 // 4
        self.charge_limit = 5
        self.effects = {p: dict() for p in self.players}
        self.divinations = {p: [] for p in self.players}
        self.phase = PHASE_EFFECTS
        self.set_num_decisions()

    def vs_msg(self, p=None):
        msg = ''
        header = True
        if p not in self.players:
            msg += '*'
            for p in self.players:
                if not header:
                    msg += ' vs. '
                msg += f'{p}'
                header = False
            msg += '.*\n'
        else:
            opp = self.players[0]
            if opp == p:
                opp = self.players[1]
            msg += f'*{p} vs. {opp}.*\n'
        return msg

    def score_msg(self, p=None):
        msg = ""
        header = True
        if p not in self.players:
            msg += f"{self.players[0]} "
            for p in self.players:
                if not header:
                    msg += '-'
                msg += f'{max(self.scores[p], 0)}'
                header = False
            msg += f" {self.players[-1]}"
            msg += "\n"
        else:
            opp = self.players[0]
            if opp == p:
                opp = self.players[1]
            msg += f'*{p}* {max(self.scores[p], 0)}-{max(self.scores[opp], 0)} *{opp}*\n'
        if self.scores[self.players[0]] <= -5 or self.scores[self.players[1]] <= -5:
            msg += "\n> ***Overkill.***\n"
        return msg

    def decisions_msg(self, p=None):
        msg = ""
        header = True
        if p not in self.players:
            msg += f"{self.players[0]} "
            for p in self.players:
                if not header:
                    msg += '-'
                msg += f'{self.decisions[p]}'
                header = False
            msg += f" {self.players[-1]}"
            msg += "\n"
        else:
            opp = self.players[0]
            if opp == p:
                opp = self.players[1]
            msg += f'{p} {self.decisions[p]}-{self.decisions[opp]} {opp}\n'
        return msg

    def charge_limit_fx(self, p):
        #for s in self.effects[p]:
        #    if isinstance(s, spells.GreenCounterB):
        #        return 7
        return self.charge_limit

    def info(self, p=None, active=False):
        msg = ''
        if p is not None and p in self.players:
            msg += f"*{p}'s Wand*\r\n"
            w = self.wands[p]
            for se in sorted(w.spells.keys(), key=lambda x: list(self.emojis_to_moves.keys()).index(x)):
                if not active or w.active[se]:
                    s = w.spells[se]
                    msg += f'{se} {s}. {s.description()}\r\n'
            msg += f'\n'
            opp = self.players[0]
            if opp == p:
                opp = self.players[1]
            msg += f"*{opp}'s Wand*\r\n"
            w = self.wands[opp]
            qmarks = ""
            for se in sorted(w.spells.keys(), key=lambda x: list(self.emojis_to_moves.keys()).index(x)):
                if not active or w.active[se]:
                    if w.superknown[se]:
                        s = w.spells[se]
                        msg += f'{se} {s}. {s.description()}\r\n'
                    else:
                        msg += f'{se} Spell not revealed yet.\r\n'
            #msg += qmarks
            msg += f'\n'
        else:
            for q in self.players:
                msg += f"*{q}'s Wand*\r\n"
                w = self.wands[q]
                for se in sorted(w.spells.keys(), key=lambda x: list(self.emojis_to_moves.keys()).index(x)):
                    if not active or w.active[se]:
                        s = w.spells[se]
                        msg += f'{se} {s}. {s.description()}\r\n'
                msg += f'\r\n'
        return msg

    def match_state(self, p):
        if p not in self.players:
            p = self.players[0]
            opp = self.players[1]
        else:
            opp = self.players[1]
            if p == opp:
                opp = self.players[0]
        if opp == p:
            opp = self.players[0]
        msg = ''
        msg += f"> {self.score_msg(p)}"
        msg += f'> \n'
        msg += f"> *{p}*\n"
        msg += f"> Effects In Play: "
        if self.effects[p]:
            for s in self.effects[p]:
                msg += f"{s.emoji()} "
            msg += "\n"
        else:
            msg += "None\n"
        msg += f"{self.wands[p].info(self.charge_limit_fx(p))}"
        msg += f"> \n"
        msg += f"> *{opp}*\n"
        msg += f"> Effects In Play: "
        if self.effects[opp]:
            for s in self.effects[opp]:
                msg += f"{s.emoji()} "
            msg += "\r\n"
        else:
            msg += "None\r\n"
        msg += f"{self.wands[opp].opp_info(self.charge_limit_fx(opp))}"
        return msg

    def get_rules(self):
        msg = ''
        msg += f"*Wands.*\n"
        msg += f"You have a wand with 9 spells.\n"
        msg += f"These spells deal damage and other effects when they win combat interactions.\n"
        msg += f"Your goal is to use your spells to defeat your opponent.\n"
        msg += f"\n"
        msg += f"*Combat.*\n"
        msg += f"Every round, you engage in combat.\n"
        msg += f"You get to choose ONE of the following actions.\n"
        msg += "\N{LARGE BROWN CIRCLE} Cast one of your loaded spells.\n"
        msg += "\N{SHIELD} Block your opponent's spell.\n"
        msg += "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS} Refresh your wand.\n"
        msg += "You and your opponent choose actions simultaneously.\n"
        msg += "\n"
        msg += f"*Spell Elements.*\n"
        msg += f"Spells come in one of six elements: \N{LARGE RED CIRCLE} Fire, \N{LARGE ORANGE CIRCLE} Earth, \N{LARGE YELLOW CIRCLE} Lightning, \N{LARGE GREEN CIRCLE} Nature, \N{LARGE BLUE CIRCLE} Water, \N{LARGE PURPLE CIRCLE} Air.\n"
        msg += f"Some elements beat out others, and some elements tie with each other.\n"
        msg += ':heavy_multiplication_x: :red_circle: :orange_circle: :yellow_circle: :green_circle: :blue_circle: :purple_circle:\n'
        msg += ':red_circle: :handshake: :x: :handshake: :white_check_mark: :x: :handshake:\n'
        msg += ':orange_circle: :white_check_mark: :handshake: :white_check_mark: :x: :x: :x:\n'
        msg += ':yellow_circle: :handshake: :x: :handshake: :x: :white_check_mark: :white_check_mark:\n'
        msg += ':green_circle: :x: :white_check_mark: :white_check_mark: :handshake: :white_check_mark: :x:\n'
        msg += ':blue_circle: :white_check_mark: :white_check_mark: :x: :x: :handshake: :handshake:\n'
        msg += ':purple_circle: :handshake: :white_check_mark: :x: :white_check_mark: :handshake: :handshake:\n'
        msg += "\n"
        msg += f"*Spell Classes.*\n"
        msg += f"Spells come in one of three classes \N{LARGE BROWN CIRCLE} \N{LARGE BROWN SQUARE} \N{BROWN HEART}.\n"
        msg += f"When elements tie, classes can affect which spells win out.\n"
        msg += "\n"
        msg += "*Spell Class - Counters.*\n"
        msg += f"\N{LARGE BROWN CIRCLE} Counters (Circles) have defensive effects or other utilities.\n"
        msg += f"Counters return to your wand when they win in combat.\n"
        msg += "Counters beat out other spells during elemental ties, but do nothing if your opponent doesn't cast a spell.\n"
        msg += "\n"
        msg += "*Spell Class - Strikes.*\n"
        msg += f"\N{LARGE BROWN SQUARE} Strikes (Squares) deal high damage and aggressive effects.\n"
        msg += f"Strikes beat out Hexes during elemental ties, and also beat out refreshes.\n"
        msg += "\n"
        msg += "*Spell Class - Hexes.*\n"
        msg += f"\N{BROWN HEART} Hexes (Hearts) place lingering effects on your opponent until they refresh.\n"
        msg += f"Hexes are unblockable and beat out refreshes.\n"
        msg += "\n"
        msg += f"*Block.*\n"
        msg += "Blocking your opponent's \N{LARGE BROWN CIRCLE} \N{LARGE BROWN SQUARE} Counter or Strike protects you from it.\n"
        msg += "When you block a spell, make one of the following choices.\n"
        msg += "\N{CYCLONE} Bounce the spell, returning it to your opponent's spell pool and locking it out for a round.\n"
        msg += "\N{NO ENTRY SIGN} Cancel the spell, removing it from your opponent's spell pool. Costs 4 HP.\n"
        msg += "*(Hexes are unblockable.)*\n"
        msg += "\n"
        msg += f"*Refresh.*\n"
        msg += f"Refreshing lets you prepare more spells and removes your opponent's hexes.\n"
        msg += f"When you refresh your wand, unprepare your current spells, then choose {self.charge_limit} of your 9 spells and prepare them.\n"
        msg += f"Getting hit by a \N{LARGE BROWN SQUARE} \N{BROWN HEART} Strike or Hex will beat out your refresh.\n"
        msg += f"\n"
        msg += "*Divination.*\n"
        msg += f"Whenever you lose combat, you get to perform divination.\n"
        msg += f"React with \N{YELLOW HEART} \N{LARGE PURPLE CIRCLE} with two spells to identify them and check if your opponent them prepared.\n"
        msg += f"Your opponent won't know which spells you chose.\n"
        msg += f"\n"
        msg += f"*Game Start.* Before the first round, both players refresh their wands.\n"
        msg += f"*Round Structure.*\n"
        msg += f"1. Combat Phase: either cast a spell, block, or refresh.\n"
        msg += f"2. Effect Phase.\n"
        msg += f"2A. If you win in combat, make any choices required for your winning option.\n"
        msg += f"2B. If you lose in combat, perform divination.\n"
        msg += f"*{self.initial_hp} HP. Maximum {self.max_rounds} rounds.*\n"
        msg += "\n"
        return msg

    def win_loss(self, p, opp, a, b, flag=0):
        outcome_msg = '*Outcome:* '
        if a == b:
            if a == "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}":
                outcome_msg += "Both players successfully refresh!\n"
                return [0,1], outcome_msg
            outcome_msg += "It's a draw!\n"
            return [], outcome_msg
        if a == "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}" and b == "\N{SHIELD}":
            outcome_msg += f"{p} successfully \N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS} refreshes, and {opp} blocks nothing!\n"
            return [flag], outcome_msg
        if a == "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}" and shape(b) == "circle":
            outcome_msg += f"{p} successfully \N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS} refreshes, and {opp}'s {b} {self.wands[opp].spells[b].name} does nothing!\n"
            outcome_msg += "*(Counters only activate against other spells.)*\n"
            return [flag], outcome_msg
        if a == "\N{SHIELD}" and shape(b) in ["circle", "square"]:
            outcome_msg += f"{p}'s \N{SHIELD} blocked {opp}'s {b} {self.wands[opp].spells[b].name}!\n"
            return [flag], outcome_msg
        if shape(a) == "square" and b == "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}":
            outcome_msg += f"{p}'s {a} {self.wands[p].spells[a].name} hits, preventing {opp}'s \N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}!\n"
            outcome_msg += "*(Strikes beat out refreshes.)*\n"
            return [flag], outcome_msg
        if shape(a) == "heart" and b == "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}":
            outcome_msg += f"{p}'s {a} {self.wands[p].spells[a].name} hits, preventing {opp}'s \N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}!\n"
            outcome_msg += "*(Hexes beat out refreshes.)*\n"
            return [flag], outcome_msg
        if shape(a) == "heart" and b == "\N{SHIELD}":
            outcome_msg += f"{p}'s {a} {self.wands[p].spells[a].name} bypasses {opp}'s \N{SHIELD}!\n"
            outcome_msg += "*(Hexes are unblockable.)*\n"
            return [flag], outcome_msg
        if shape(a) and shape(b):
            if self.color_advantage_chart[color(a)][color(b)] > 0:
                outcome_msg += f"{p}'s {a} {self.wands[p].spells[a].name} defeats {opp}'s {b} {self.wands[opp].spells[b].name} by elemental advantage!\n"
                outcome_msg += f"*({element(a)} spells defeat {element(b)} spells.)*\n"
                return [flag], outcome_msg
            if self.color_advantage_chart[color(a)][color(b)] == 0:
                if shape(a) == shape(b):
                    outcome_msg += "It's a draw!\n"
                    if color(a) != color(b):
                        outcome_msg += f"*({element(a)} spells tie with {element(b)} spells.)*"
                    return [], outcome_msg
                if shape(a) == "circle" and shape(b) != "circle":
                    outcome_msg += f"{p}'s {a} {self.wands[p].spells[a].name} defeats {opp}'s {b} {self.wands[opp].spells[b].name} by spell class advantage!\n"
                    if color(a) != color(b):
                        outcome_msg += f"*({element(a)} spells tie with {element(b)} spells.)*\n"
                    outcome_msg += f"*({spellclass(a)}s defeat {spellclass(b)}s during elemental ties.)*\n"
                    return [flag], outcome_msg
                if shape(a) == "square" and shape(b) == "heart":
                    outcome_msg += f"{p}'s {a} {self.wands[p].spells[a].name} defeats {opp}'s {b} {self.wands[opp].spells[b].name} by spell class advantage!\n"
                    outcome_msg += f"*({spellclass(a)}s defeat {spellclass(b)}s during elemental ties.)*\n"
                    if color(a) != color(b):
                        outcome_msg += f"*({element(a)} spells tie with {element(b)} spells.)*\n"
                    return [flag], outcome_msg
        return self.win_loss(opp, p, b, a, 1)

    def opponent(self, p):
        if p == self.players[0]:
            return self.players[1]
        return self.players[0]

    def get_options(self, p):
        options = []
        if self.phase == PHASE_COMBAT:
            if p in self.players:
                options.append("\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}")
                options.append("\N{SHIELD}")
                for e in sorted(self.wands[p].spells.keys(), key=lambda x: list(self.emojis_to_moves.keys()).index(x)):
                    if not self.wands[p].frozen[e] and (e not in self.wands[p].active or self.wands[p].active[e]):
                        options.append(e)
        elif self.phase == PHASE_EFFECTS:
            if p in self.casters:
                opp = self.players[0]
                if opp == p:
                    opp = self.players[1]
                options = self.wands[p].spells[self.combat_options[p]].get_choices(self, p, opp)
            elif p in self.blockers:
                options.append("\N{CYCLONE}")
                options.append("\N{NO ENTRY SIGN}")
            elif p in self.chargers:
                for e in sorted(self.wands[p].spells.keys(), key=lambda x: list(self.emojis_to_moves.keys()).index(x)):
                    options.append(e)
            elif p in self.scouters:
                opp = self.players[0]
                if opp == p:
                    opp = self.players[1]
                keep_going = True
                for s in list(self.effects[opp].keys()):
                    if isinstance(s, spells.YellowCounterB):
                        keep_going = False
                        break
                if keep_going:
                    for s in list(self.effects[opp].keys()):
                        if isinstance(s, spells.OrangeHexA):
                            keep_going = False
                            break
                    if not keep_going:
                        for e in self.wands[p].active:
                            if self.wands[p].active[e]:
                                options.append(e)
                    else:
                        for e in sorted(self.wands[opp].spells.keys(), key=lambda x: list(self.emojis_to_moves.keys()).index(x)):
                            if not (self.wands[opp].known[e] or self.wands[opp].antiknown[e]):
                                options.append(e)
        if not options:
            options.append("\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE}")
        return options

    def match_step(self):
        p_ls = []
        for p in self.players:
            p_ls.append(
                (p, self.decisions[p].upper() if isinstance(self.decisions[p], str)
                else [d.upper() for d in self.decisions[p]]))
        if self.phase == PHASE_COMBAT:
            self.match_step_combat(p_ls)
        elif self.phase == PHASE_EFFECTS:
            self.match_step_effects(p_ls)
        self.set_num_decisions()

    def set_num_decisions(self):
        for p in self.players:
            if self.phase == PHASE_COMBAT:
                self.expected_num_decisions[p] = 1
            elif self.phase == PHASE_EFFECTS:
                x = len(self.get_options(p))
                if p in self.casters:
                    x = min(x, self.wands[p].spells[self.combat_options[p]].get_num_choices())
                elif p in self.blockers:
                    x = min(x, 1)
                elif p in self.chargers:
                    x = min(x, self.charge_limit_fx(p))
                elif p in self.scouters:
                    x = min(x, 2)
                    opp = self.players[0]
                    if opp == p:
                        opp = self.players[1]
                    for sp in list(self.effects[opp].keys()):
                        if isinstance(sp, spells.OrangeHexA) and self.effects[opp][sp] < -1:
                            x = min(x, 1)
                            break
                self.expected_num_decisions[p] = x

    def match_step_combat(self, p_ls):
        # Initialize messages.
        msgs = {p: [''] for p in self.agents()}

        # Decision messages.
        for a in self.agents():
            if a in self.players:
                p = a
                opp = self.opponent(p)
            else:
                p = self.players[0]
                opp = self.players[1]
            msgs[a][-1] += self.decisions_msg(p)
            if self.decisions[p] == "\N{SHIELD}":
                msgs[a][-1] += f"{p} raises their {self.decisions[p]} shield!\n"
            elif self.decisions[p] == "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}":
                msgs[a][-1] += f"{p} is attempting to {self.decisions[p]} refresh!\n"
            else:
                msgs[a][-1] += f"{p} casts {self.decisions[p]} {self.wands[p].spells[self.decisions[p]].name}!\n"
            if self.decisions[opp] == "\N{SHIELD}":
                msgs[a][-1] += f"{opp} raises their {self.decisions[opp]} shield!\n"
            elif self.decisions[opp] == "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}":
                msgs[a][-1] += f"{opp} is attempting to {self.decisions[opp]} refresh!\n"
            else:
                msgs[a][-1] += f"{opp} casts {self.decisions[opp]} {self.wands[opp].spells[self.decisions[opp]].name}!\n"
            msgs[a][-1] += "\n"

        # Outcome message.
        self.combat_options = {
            p_ls[0][0]: p_ls[0][1],
            p_ls[1][0]: p_ls[1][1],
        }
        self.winning_ids, _ = self.win_loss(p_ls[0][0], p_ls[1][0], p_ls[0][1], p_ls[1][1])
        for a in msgs:
            p = self.players[0]
            opp = self.opponent(p)
            msgs[a][-1] += self.win_loss(p, opp, self.combat_options[p], self.combat_options[opp])[1] + "\n"

        if 0 in self.winning_ids and shape(p_ls[0][1]):
            self.casters.append(p_ls[0][0])
        if 1 in self.winning_ids and shape(p_ls[1][1]):
            self.casters.append(p_ls[1][0])
        if 0 in self.winning_ids and p_ls[0][1] == "\N{SHIELD}":
            self.blockers.append(p_ls[0][0])
        if 1 in self.winning_ids and p_ls[1][1] == "\N{SHIELD}":
            self.blockers.append(p_ls[1][0])
        if 0 in self.winning_ids and p_ls[0][1] == "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}":
            self.chargers.append(p_ls[0][0])
            self.wands[p_ls[0][0]].fresh_charge = True
        if 1 in self.winning_ids and p_ls[1][1] == "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}":
            self.chargers.append(p_ls[1][0])
            self.wands[p_ls[1][0]].fresh_charge = True
        for a in self.players:
            for s in list(self.effects[a].keys()):
                if isinstance(s, spells.BlueHexA):
                    opp = self.players[0]
                    if opp == a:
                        opp = self.players[1]
                    if shape(self.combat_options[opp]) == s.chosen_shape:
                        self.scores[opp] -= s.penalty
                        for p in msgs:
                            msgs[p][-1] += s.effect_msg(self, a, opp)
        self.scouters = [p for p in self.players]
        for a in (self.casters + self.blockers + self.chargers):
            if a in self.scouters:
                self.scouters.remove(a)
        for a in self.casters:
            opp = self.players[0]
            if opp == a:
                opp = self.players[1]
            protected = False
            for s in list(self.effects[opp].keys()):
                if isinstance(s, spells.OrangeCounterA):
                    if self.effects[opp][s] == 0 and shape(self.combat_options[a]) == s.chosen_shape:
                        for p in msgs:
                            msgs[p][-1] += f"{opp}'s {s.emoji()} protected them from damage!"
                        protected = True
            if not protected:
                dmg_msg = self.wands[a].spells[self.combat_options[a]].deal_damage(self, a, opp)
                for p in msgs:
                    msgs[p][-1] += dmg_msg
                for s in list(self.effects[a].keys()):
                    if isinstance(s, spells.RedCounterA):
                        if self.effects[a][s] == 0 and color(self.combat_options[a]) == s.chosen_color:
                            self.scores[opp] -= s.bonus
                            for p in msgs:
                                msgs[p][-1] += f"{a}'s dealt +{s.bonus} damage!"
            for s in list(self.effects[a].keys()):
                if isinstance(s, spells.GreenHexA):
                    self.scores[a] += 1
                    for p in msgs:
                        msgs[p][-1] += s.effect_msg(self, a, opp)
        for a in self.blockers:
            opp = self.players[0]
            if opp == a:
                opp = self.players[1]
            for s in list(self.effects[opp].keys()):
                if isinstance(s, spells.PurpleHexA):
                    for p in msgs:
                        msgs[p][-1] += s.effect_msg(self, opp, a)
                    self.scores[a] -= 2
        if len(self.chargers) == 1:
            a = self.chargers[0]
            opp = self.players[0]
            if opp == a:
                opp = self.players[1]
            for s in list(self.effects[opp].keys()):
                if isinstance(s, spells.YellowHexA):
                    for p in msgs:
                        msgs[p][-1] += s.effect_msg(self, opp, a)
                    self.chargers.append(opp)
        for c in self.casters:
            opp = self.players[0]
            if opp == c:
                opp = self.players[1]
            w_c = self.wands[c]
            w_o = self.wands[opp]
            s_c = w_c.spells[self.combat_options[c]]
            s_o = w_o.spells[self.combat_options[opp]] if self.combat_options[opp] in w_o.spells else None
            if s_c.shape != "circle":
                w_c.active[self.combat_options[c]] = False
                w_c.burned[self.combat_options[c]] = True
                w_c.known[self.combat_options[c]] = False
                w_c.antiknown[self.combat_options[c]] = True
                w_c.equip_know(self.combat_options[c])
            else:
                w_c.active[self.combat_options[c]] = True
                w_c.burned[self.combat_options[c]] = False
                w_c.known[self.combat_options[c]] = True
                w_c.antiknown[self.combat_options[c]] = False
                w_c.equip_know(self.combat_options[c])
        for s in self.scouters:
            opp = self.players[0]
            if opp == s:
                opp = self.players[1]
            w_c = self.wands[s]
            w_o = self.wands[opp]
            s_c = w_c.spells[self.combat_options[s]] if self.combat_options[s] in w_c.spells else None
            s_o = w_o.spells[self.combat_options[opp]] if self.combat_options[opp] in w_o.spells else None
            if s_c:
                if True:#not (s_o and isinstance(s_o, spells.PurpleStrikeA) and opp not in self.scouters):
                    w_c.active[self.combat_options[s]] = False
                    w_c.burned[self.combat_options[s]] = True
                    w_c.known[self.combat_options[s]] = False
                    w_c.antiknown[self.combat_options[s]] = True
                    w_c.equip_know(self.combat_options[s])
                '''
                else:
                    w_c.active[self.combat_options[s]] = True
                    w_c.burned[self.combat_options[s]] = False
                    w_c.known[self.combat_options[s]] = True
                    w_c.antiknown[self.combat_options[s]] = False
                    w_c.equip_know(self.combat_options[s])
                '''
        # Effects header messages.
        for p in msgs:
            msgs[p].append('')
            for a in self.casters:
                msgs[p][-1] += f"{a} is making any needed choices for {self.combat_options[a]} {self.wands[a].spells[self.combat_options[a]]}'s effect.\n"
            for a in self.blockers:
                msgs[p][-1] += f"{a} is making a \N{SHIELD} blocking decision.\n"
            for a in self.chargers:
                msgs[p][-1] += f"{a} is choosing {self.charge_limit_fx(a)} spells to \N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS} refresh with.\n"
            for a in self.scouters:
                msgs[p][-1] += f"{a} is performing divination.\n"

        for a in self.casters:
            opp = self.players[0]
            if opp == a:
                opp = self.players[1]
            spell_msg = "*Cast:* " + self.wands[a].spells[self.combat_options[a]].get_choice_msg()
            self.message_queue[a].append((msgs[a][-2], None))
            self.message_queue[a].append((self.match_state(a), None))
            if not self.check_match_over():
                self.message_queue[a].append(('', "examples/wonder_wand/assets/ww_header_effects.png"))
                self.message_queue[a].append((msgs[a][-1], None))
                self.message_queue[a].append((spell_msg, None))
        for a in self.blockers:
            opp = self.players[0]
            if opp == a:
                opp = self.players[1]
            block_msg = f"*Block:* Choose whether to \N{CYCLONE} *bounce* or \N{NO ENTRY SIGN} *cancel* {opp}'s spell.\n"
            self.message_queue[a].append((msgs[a][-2], None))
            self.message_queue[a].append((self.match_state(a), None))
            if not self.check_match_over():
                self.message_queue[a].append(('', "examples/wonder_wand/assets/ww_header_effects.png"))
                self.message_queue[a].append((msgs[a][-1], None))
                self.message_queue[a].append((block_msg, None))
        for a in self.chargers:
            opp = self.players[0]
            if opp == a:
                opp = self.players[1]
            refresh_msg = f"*Refresh:* React {self.charge_limit_fx(a)} times to load your wand.\n"
            self.message_queue[a].append((msgs[a][-2], None))
            self.message_queue[a].append((self.match_state(a), None))
            if not self.check_match_over():
                self.message_queue[a].append(('', "examples/wonder_wand/assets/ww_header_effects.png"))
                self.message_queue[a].append((msgs[a][-1], None))
                self.message_queue[a].append((refresh_msg, None))
            if a in self.scouters:
                self.scouters.remove(a)
        for a in self.chargers:
            self.wands[a].refresh()
            opp = self.players[0]
            if opp == a:
                opp = self.players[1]
            old_hexes = []
            for s in list(self.effects[opp].keys()):
                if s.shape == "heart":
                    old_hexes.append(s)
            for s in old_hexes:
                del self.effects[opp][s]
        for a in self.scouters:
            opp = self.players[0]
            if opp == a:
                opp = self.players[1]
            divine_msg = ''
            if self.wands[opp].check_completeness():
                divine_msg += "*Divination:* [Secret] You already know your opponent's entire spell pool. React to continue.\n"
            else:
                keep_going = True
                ohex = None
                for s in list(self.effects[opp].keys()):
                    if isinstance(s, spells.YellowCounterB):
                        keep_going = False
                        break
                if not keep_going:
                    divine_msg += f"*Divination:* Your opponent is protected from divination this round. React to continue.\n"
                else:
                    for s in list(self.effects[opp].keys()):
                        if isinstance(s, spells.OrangeHexA):
                            keep_going = False
                            ohex = s
                            break
                    if not keep_going:
                        divine_msg += ohex.effect_msg(self, opp, a)
                        divine_msg += f"{ohex}: Choose a spell to unprepare.\n"
                    else:
                        divine_msg += f"*Divination:* React to two spells to identify them and see if your opponent prepared them.\n"
            self.message_queue[a].append((msgs[a][-2], None))
            self.message_queue[a].append((self.match_state(a), None))
            if not self.check_match_over():
                self.message_queue[a].append(('', "examples/wonder_wand/assets/ww_header_effects.png"))
                self.message_queue[a].append((msgs[a][-1], None))
                self.message_queue[a].append((divine_msg, None))
        for a in self.spectators:
            self.message_queue[a].append((msgs[a][-2], None))
            self.message_queue[a].append((self.match_state(a), None))
            if not self.check_match_over():
                self.message_queue[a].append(('', "examples/wonder_wand/assets/ww_header_effects.png"))
                self.message_queue[a].append((msgs[a][-1], None))
        self.phase = PHASE_EFFECTS

    def match_step_effects(self, p_ls):
        # Initialize messages.
        msgs = {p: [''] for p in self.agents()}

        for p in self.wands:
            for e in self.wands[p].frozen:
                self.wands[p].frozen[e] = False
        for c in self.casters:
            w_c = self.wands[c]
            s_c = w_c.spells[self.combat_options[c]]
            if c == p_ls[0][0]:
                opp = p_ls[1][0]
                choice = p_ls[0][1]
            else:
                opp = p_ls[0][0]
                choice = p_ls[1][1]
            activate_msg = s_c.activate(self, c, opp, choice)
            for p in msgs:
                msgs[p][-1] += activate_msg
        for c in self.blockers:
            if c == p_ls[0][0]:
                opp = p_ls[1][0]
                choice = p_ls[0][1]
            else:
                opp = p_ls[0][0]
                choice = p_ls[1][1]
            w_c = self.wands[c]
            w_o = self.wands[opp]
            s_o = w_o.spells[self.combat_options[opp]]
            if choice == "\N{CYCLONE}":
                penalty = 0
                for p in msgs:
                    msgs[p][-1] += f"{c} bounced {self.combat_options[opp]}.\n"
                    msgs[p][-1] += f"{opp} can't cast {self.combat_options[opp]} next round.\n"
                self.scores[c] -= penalty
                w_o.active[self.combat_options[opp]] = True
                w_o.burned[self.combat_options[opp]] = False
                w_o.known[self.combat_options[opp]] = True
                w_o.antiknown[self.combat_options[opp]] = False
                w_o.frozen[self.combat_options[opp]] = True
                w_o.equip_know(self.combat_options[c])
            elif choice == "\N{NO ENTRY SIGN}":
                penalty = 4
                for p in msgs:
                    msgs[p][-1] += f"{c} paid {penalty} HP to cancel {self.combat_options[opp]}.\n"
                    msgs[p][-1] += f"{self.combat_options[opp]} has been removed from {opp}'s spell pool.\n"
                self.scores[c] -= penalty
                w_o.active[self.combat_options[opp]] = False
                w_o.burned[self.combat_options[opp]] = True
                w_o.known[self.combat_options[opp]] = False
                w_o.antiknown[self.combat_options[opp]] = True
                w_o.frozen[self.combat_options[opp]] = False
                w_o.equip_know(self.combat_options[c])
        for c in self.chargers:
            self.wands[c].recharge(self.decisions[c])
            for p in msgs:
                msgs[p][-1] += f"{c} has finished refreshing.\n"
                if p == c:
                    msgs[p][-1] += f"[Secret] {c} put"
                    for e in self.decisions[c]:
                        msgs[p][-1] += f" {e}"
                    msgs[p][-1] += " into their spell pool.\n"
            opp = self.players[0]
            if opp == c:
                opp = self.players[1]
            self.divinations[opp] = []
        for s in self.scouters:
            for p in msgs:
                opp = self.opponent(s)
                keep_going = True
                for sp in list(self.effects[opp].keys()):
                    if isinstance(sp, spells.OrangeHexA) and self.effects[opp][sp] < -1:
                        keep_going = False
                        break
                if keep_going:
                    msgs[p][-1] += f"{s} has finished divination.\n"
                    if p == s:
                        if self.decisions[s] == "\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE}":
                            continue
                        if not isinstance(self.decisions[s], list):
                            self.decisions[s] = [self.decisions[s]]
                        for e in self.decisions[s]:
                            msgs[p][-1] += f"[Secret] {opp}'s {e} identified as {self.wands[opp].spells[e]}. Use *x!spells* for more info.\n"
                            if e in self.wands[opp].spells and self.wands[opp].active[e]:
                                msgs[p][-1] += f"[Secret] {opp} has {e} in their spell pool.\n"
                                self.wands[opp].known[e] = True
                                self.wands[opp].equip_know(e)
                            elif e in self.wands[opp].equipped:
                                msgs[p][-1] += f"[Secret] {opp} has {e} unprepared.\n"
                                self.wands[opp].antiknown[e] = True
                                self.wands[opp].equip_know(e)
                else:
                    msgs[p][-1] += f"{self.opponent(s)}'s \N{ORANGE HEART} forced {s} to unprepare a spell instead of peforming divination.\n"
                    if p == s and self.decisions[s] in self.wands[s].spells:
                        self.wands[s].active[self.decisions[s]] = False
                        self.wands[s].known[self.decisions[s]] = False
                        self.wands[s].antiknown[self.decisions[s]] = True
                        msgs[p][-1] += f"[Secret] {s} unprepared {self.decisions[s]}."
        for c in self.agents():
            self.message_queue[c].append((msgs[c][-1] + "\n", None))
        self.casters = []
        self.blockers = []
        self.chargers = []
        for p in self.players:
            opp = self.players[0]
            if opp == p:
                opp = self.players[1]
            for s in list(self.effects[p].keys()):
                if self.effects[p][s] == 0:
                    if isinstance(s, spells.YellowStrikeA):
                        for clr in self.colors:
                            self.wands[opp].frozen[self.moves_to_emojis[(clr, s.chosen_shape)]] = False
                if self.effects[p][s] == 0:
                    del self.effects[p][s]
                else:
                    self.effects[p][s] -= 1
        for a in self.players:
            for s in list(self.effects[a].keys()):
                if isinstance(s, spells.RedHexA):
                    opp = self.players[0]
                    if opp == a:
                        opp = self.players[1]
                    self.scores[opp] -= s.penalty
                    for p in self.message_queue:
                        msgs[p][-1] += s.effect_msg(self, a, opp)
        self.winning_ids = []
        self.combat_options = {p: None for p in self.combat_options}
        self.round += 1
        for a in self.agents():
            round_warning_msg = ""
            if self.round + 5 > self.max_rounds:
                round_warning_msg += f"Maximum {self.max_rounds} rounds.\n"
            combat_msg = f"Both players must select a combat option!\n"
            combat_msg += f"Refresh, block, or cast a spell.\n"
            self.message_queue[a].append((self.match_state(a), None))
            if not self.check_match_over():
                self.message_queue[a].append(('', "examples/wonder_wand/assets/ww_header_round_start.png"))
                self.message_queue[a].append((f"*Round {self.round}.*\n", None))
                self.message_queue[a].append((round_warning_msg, None))
                self.message_queue[a].append(('', "examples/wonder_wand/assets/ww_header_combat.png"))
                self.message_queue[a].append((combat_msg, None))
        self.scouters = []
        self.phase = PHASE_COMBAT

    def winner(self):
        if len(self.resigned) == 2:
            return self.resigned[-1]
        if len(self.resigned) == 1:
            for p in self.players:
                if p not in self.resigned:
                    return p
        max_p = None
        max_score = 0
        won = self.round > self.max_rounds
        for p in self.scores:
            if p not in self.resigned and self.scores[p] >= max_score:
                max_score = self.scores[p]
                max_p = p
            if self.scores[p] <= 0:
                won = True
        if won:
            return max_p
        return None

    def receive_command(self, p, c):
        if c == "x!rules":
            msg = self.get_rules()
            self.message_queue[p].append((msg, None))
            return True
        if c == "x!elements":
            msg = ''
            msg += ':heavy_multiplication_x: :red_circle: :orange_circle: :yellow_circle: :green_circle: :blue_circle: :purple_circle:\n'
            msg += ':red_circle: :handshake: :x: :handshake: :white_check_mark: :x: :handshake:\n'
            msg += ':orange_circle: :white_check_mark: :handshake: :white_check_mark: :x: :x: :x:\n'
            msg += ':yellow_circle: :handshake: :x: :handshake: :x: :white_check_mark: :white_check_mark:\n'
            msg += ':green_circle: :x: :white_check_mark: :white_check_mark: :handshake: :white_check_mark: :x:\n'
            msg += ':blue_circle: :white_check_mark: :white_check_mark: :x: :x: :handshake: :handshake:\n'
            msg += ':purple_circle: :handshake: :white_check_mark: :x: :white_check_mark: :handshake: :handshake:\n'
            self.message_queue[p].append((msg, None))
            return True
        if c == "x!spells":
            msg = self.info(p)
            self.message_queue[p].append((msg, None))
            return True
        return False

    def match_init_msg(self, p):
        commands_msg = ''
        commands_msg += f"For rules, use *x!rules.*\n"
        commands_msg += f"To view element matchups, use *x!elements.*\n"
        commands_msg += f"To see your spells, use *x!spells.*\n"
        commands_msg += f"To customize your wand, */abort* this game and use */solo wonderwand customize*.\n"
        refresh_msg = f"Refresh your wand by reacting to {self.charge_limit} options.\n"
        return [
            ('', 'examples/wonder_wand/assets/ww_header_game_start.png'),
            (self.vs_msg(p), None),
            (commands_msg, None),
            (self.match_state(p), None),
            (refresh_msg, None),
        ]

    def match_over_msg(self, p):
        msg = f"The winner is {self.winner()}!\n"
        return [
            ('', 'examples/wonder_wand/assets/ww_header_game_over.png'),
            (msg, None)]


class WonderWand(AbstractModeSelector):
    def validate_mode(self):
        return self.mode in ["versus", "cpu", "customize"]

    def initialize_match_state(self):
        if self.mode == "versus" or self.mode == "cpu":
            self.true_game = WonderWandVersus(self.players, mode=self.mode)
        elif self.mode == "customize":
            self.true_game = customize_wand.CustomizeWand(self.players, mode=self.mode)
        self.true_game.initialize_match_state()
        self.expected_num_decisions = self.true_game.expected_num_decisions
        self.resigned = self.true_game.resigned


WonderWand.__name__ = "wonderwand"
