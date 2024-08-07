from axi.abstract_dm_game import AbstractDmGame
from axi.axi import load_profile, save_profile
from examples.wonder_wand.wonder_wand_profile import WonderWandProfile
import examples.wonder_wand.spells as spells
import examples.wonder_wand.wonder_wand as wonder_wand
import random

PHASE_CHOOSE_SHAPE = 0
PHASE_CHOOSE_SPELL = 1
PHASE_CHOOSE_DISCARD = 2

class CustomizeWand(AbstractDmGame):

    def get_options(self, p):
        options = []
        if self.phase == PHASE_CHOOSE_SHAPE:
            options.append("\N{CROSS MARK}")
            if not self.saved:
                options.append("\N{FLOPPY DISK}")
            options.append("\N{GAME DIE}")
            options.append("\N{LARGE BROWN CIRCLE}")
            options.append("\N{LARGE BROWN SQUARE}")
            options.append("\N{BROWN HEART}")
        elif self.phase == PHASE_CHOOSE_SPELL:
            spellbook = spells.generate_spellbook()
            shapebook = spellbook[self.chosen_shape]
            shapepage = shapebook[self.page_num]
            options.append("\N{CROSS MARK}")
            if not self.saved:
                options.append("\N{FLOPPY DISK}")
            if self.page_num > 0:
                options.append("\N{BLACK LEFT-POINTING DOUBLE TRIANGLE}")
            elif self.page_num < len(shapebook) - 1:
                options.append("\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE}")
            for spell in shapepage:
                options.append(spell.emoji())
        elif self.phase == PHASE_CHOOSE_DISCARD:
            options.append("\N{CROSS MARK}")
            if self.chosen_spell.emoji() in self.profile.equipped.spells:
                options.append("\N{THUMBS UP SIGN}")
            else:
                for e in sorted(self.profile.equipped.spells.keys(), key=lambda x: list(self.emojis_to_moves.keys()).index(x)):
                    if wonder_wand.shape(e) == self.chosen_shape:
                        options.append(e)
        return options

    def generate_random_wand(self):
        spell_list = []
        spellbook = spells.generate_spellbook()
        for sh in spellbook:
            spell_list += random.sample(spellbook[sh][-1], 3)
        return wonder_wand.Wand(self.profile.equipped.name, spell_list)

    def info(self):
        msg = '\r\n**CURRENT WAND**\r\n'
        w = self.profile.equipped
        for se in sorted(w.spells.keys(), key=lambda x: list(self.emojis_to_moves.keys()).index(x)):
            s = w.spells[se]
            msg += f'{se} *{s.name}:* {s.description()}\r\n'
        if not self.saved:
            msg += f'*You have unsaved changes.*\r\n'
        msg += f'\r\n'
        return msg

    def print_spell_page(self, spells_):
        msg = '\r\n**SPELLBOOK**\r\n'
        w = self.profile.equipped
        for s in spells_:
            se = s.emoji()
            msg += f'{se} *{s.name}:* {s.description()}\r\n'
        msg += f'\r\n'
        return msg

    def win_loss(self, a, b, flag=0):
        if a == b:
            if a == "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}":
                return [0,1]
            return []
        if a == "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}" and b == "\N{SHIELD}":
            return [flag]
        if a == "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}" and wonder_wand.shape(b) == "circle":
            return [flag]
        if a == "\N{SHIELD}" and wonder_wand.shape(b) in ["circle", "square"]:
            return [flag]
        if wonder_wand.shape(a) == "square" and b == "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}":
            return [flag]
        if wonder_wand.shape(a) == "heart" and not wonder_wand.shape(b):
            return [flag]
        if wonder_wand.shape(a) and wonder_wand.shape(b):
            if self.color_advantage_chart[wonder_wand.color(a)][wonder_wand.color(b)] > 0:
                return [flag]
            if wonder_wand.color(a) == wonder_wand.color(b):
                if wonder_wand.shape(a) == "circle":
                    return [flag]
                if wonder_wand.shape(a) == "square" and wonder_wand.shape(b) == "heart":
                    return [flag]
        return self.win_loss(b, a, 1)

    def match_step(self):
        p_ls = []
        actors = self.players
        for p in actors:
            p_ls.append((p, self.decisions[p].upper() if isinstance(self.decisions[p], str) else [d.upper() for d in self.decisions[p]]))
        msg = ''
        if self.phase == PHASE_CHOOSE_SHAPE:
            if p_ls[0][1] == "\N{CROSS MARK}":
                self.customize_over = True
                msg += "Customization over. Go play!\n"
            elif p_ls[0][1] == "\N{FLOPPY DISK}":
                save_profile(self.players[0], "wonderwand", self.profile)
                self.saved = True
                msg += self.info()
                msg += "Wand saved.\n"
                msg += f"React with a spell class to start equipping spells.\n"
            elif p_ls[0][1] == "\N{GAME DIE}":
                self.profile.equipped = self.generate_random_wand()
                self.saved = False
                msg += self.info()
                msg += "Wand randomized.\n"
                if not self.saved:
                    msg += f"React with \N{FLOPPY DISK} to save your wand.\n"
                msg += f"React with a spell class to start equipping spells.\n"
            else:
                self.chosen_shape = wonder_wand.shape(p_ls[0][1])
                self.page_num = 0
                self.chosen_spell = None
                self.phase = PHASE_CHOOSE_SPELL
                msg += self.info()
                if not self.saved:
                    msg += f"React with \N{FLOPPY DISK} to save your wand.\n"
                msg += "Pick a spell to equip.\n"
                spellbook = spells.generate_spellbook()
                if len(spellbook[self.chosen_shape]) > 1:
                    msg += "Use \N{BLACK LEFT-POINTING DOUBLE TRIANGLE} and \N{BLACK RIGHT-POINTING DOUBLE TRIANGLE} to see more pages of spells.\n"
                msg += self.print_spell_page(spellbook[self.chosen_shape][self.page_num])
        elif self.phase == PHASE_CHOOSE_SPELL:
            if p_ls[0][1] == "\N{CROSS MARK}":
                self.chosen_shape = None
                self.page_num = None
                self.chosen_spell = None
                self.phase = PHASE_CHOOSE_SHAPE
                msg += self.info()
                if not self.saved:
                    msg += f"React with \N{FLOPPY DISK} to save your wand.\n"
                msg += f"React with \N{GAME DIE} to randomize your wand.\n"
                msg += f"React with a spell class to start equipping spells.\n"
            elif p_ls[0][1] == "\N{FLOPPY DISK}":
                save_profile(self.players[0], "wonderwand", self.profile)
                self.saved = True
                spellbook = spells.generate_spellbook()
                msg += self.info()
                msg += "Wand saved.\n"
                msg += self.info()
                msg += f"Page {self.page_num+1}.\n"
                msg += self.print_spell_page(spellbook[self.chosen_shape][self.page_num])
            elif p_ls[0][1] == "\N{BLACK LEFT-POINTING DOUBLE TRIANGLE}":
                self.page_num -= 1
                msg += self.info()
                if not self.saved:
                    msg += f"React with \N{FLOPPY DISK} to save your wand.\n"
                msg += f"Page {self.page_num+1}.\n"
                spellbook = spells.generate_spellbook()
                msg += self.print_spell_page(spellbook[self.chosen_shape][self.page_num])
            elif p_ls[0][1] == "\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE}":
                self.page_num += 1
                msg += self.info()
                if not self.saved:
                    msg += f"React with \N{FLOPPY DISK} to save your wand.\n"
                msg += f"Page {self.page_num+1}.\n"
                spellbook = spells.generate_spellbook()
                msg += self.print_spell_page(spellbook[self.chosen_shape][self.page_num])
            else:
                spellbook = spells.generate_spellbook()
                self.chosen_spell = spellbook[self.chosen_shape][self.page_num][wonder_wand.color_id(p_ls[0][1])]
                self.phase = PHASE_CHOOSE_DISCARD
                if self.chosen_spell.emoji() in self.profile.equipped.spells:
                    msg += self.info()
                    msg += f"You already have a spell of type {self.chosen_spell.emoji()} equipped.\n"
                    msg += "Replace it?\n"
                else:
                    msg += self.info()
                    msg += f"Pick which spell to replace.\n"
        elif self.phase == PHASE_CHOOSE_DISCARD:
            if p_ls[0][1] == "\N{CROSS MARK}":
                pass
            elif p_ls[0][1] == "\N{THUMBS UP SIGN}":
                self.profile.equipped.spells[self.chosen_spell.emoji()] = self.chosen_spell
                self.profile.equipped.refresh()
                self.saved = False
                msg += f"You've replaced {self.chosen_spell.emoji()}.\n"
            else:
                del self.profile.equipped.spells[p_ls[0][1]]
                self.profile.equipped.spells[self.chosen_spell.emoji()] = self.chosen_spell
                self.profile.equipped.refresh()
                self.saved = False
                msg += f"You've replaced {self.chosen_spell.emoji()}.\n"
            self.chosen_spell = None
            self.phase = PHASE_CHOOSE_SPELL
            msg += self.info()
            msg += "Pick a spell to equip.\n"
            spellbook = spells.generate_spellbook()
            if not self.saved:
                msg += f"React with \N{FLOPPY DISK} to save your wand.\n"
            if len(spellbook[self.chosen_shape]) > 1:
                msg += f"Page {self.page_num+1}.\n"
            msg += self.print_spell_page(spellbook[self.chosen_shape][self.page_num])
        self.message_queue[self.players[0]].append((msg, None))

    def validate_mode(self):
        return self.mode in ["customize"]

    def initialize_match_state(self):
        self.colors = [
            "red",
            "orange",
            "yellow",
            "green",
            "blue",
            "purple",
        ]
        self.color_advantage_chart = {
            "red": {
                "red": 0,
                "orange": -1,
                "yellow": 1,
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
                "purple": 1,
            },
            "purple": {
                "red": 0,
                "orange": 1,
                "yellow": -1,
                "green": 1,
                "blue": -1,
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
        self.profile = load_profile(self.players[0], "wonderwand")
        if not self.profile:
            self.profile = WonderWandProfile()
            save_profile(self.players[0], "wonderwand", self.profile)
        self.init = False
        self.round = 0
        self.phase = PHASE_CHOOSE_SHAPE
        self.chosen_shape = None
        self.chosen_spell = None
        self.page_num = None
        self.saved = True
        self.customize_over = False

    def winner(self):
        if self.customize_over:
            return self.players[0]
        return None

    def receive_command(self, p, c):
        return False

    def match_init_msg(self, p):
        msg = ''
        msg += f"**CUSTOMIZE YOUR WAND**\n"
        msg += f"For each spell class \N{LARGE BROWN CIRCLE} \N{LARGE BROWN SQUARE} \N{BROWN HEART}, pick three spells of different elements.\n"
        msg += f"Those nine spells form your wand.\n"
        msg += f"\n"
        msg += self.info()
        msg += f"React with \N{FLOPPY DISK} to save your wand.\n"
        msg += f"React with \N{GAME DIE} to randomize your wand.\n"
        msg += f"React with a spell class to start equipping spells.\n"
        return (msg, None)

    def match_over_msg(self, p):
        return ('', None)


