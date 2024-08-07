import examples.wonder_wand.wonder_wand as wonder_wand

colors = [
    "red",
    "orange",
    "yellow",
    "green",
    "blue",
    "purple",
]
shapes = ["circle", "square", "heart"]
emojis_to_moves = {
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
moves_to_emojis = {emojis_to_moves[k]: k for k in emojis_to_moves}


class Spell:
    def __init__(self, name, page_num, color, shape, dmg):
        self.name = name
        self.page_num = page_num
        self.color = color
        self.shape = shape
        self.dmg = dmg
        self.emoji_table = {
            "red": {
                "circle": "\N{LARGE RED CIRCLE}",
                "square": "\N{LARGE RED SQUARE}",
                "heart": "\N{HEAVY BLACK HEART}",
            },
            "orange": {
                "circle": "\N{LARGE ORANGE CIRCLE}",
                "square": "\N{LARGE ORANGE SQUARE}",
                "heart": "\N{ORANGE HEART}",
            },
            "yellow": {
                "circle": "\N{LARGE YELLOW CIRCLE}",
                "square": "\N{LARGE YELLOW SQUARE}",
                "heart": "\N{YELLOW HEART}",
            },
            "green": {
                "circle": "\N{LARGE GREEN CIRCLE}",
                "square": "\N{LARGE GREEN SQUARE}",
                "heart": "\N{GREEN HEART}",
            },
            "blue": {
                "circle": "\N{LARGE BLUE CIRCLE}",
                "square": "\N{LARGE BLUE SQUARE}",
                "heart": "\N{BLUE HEART}",
            },
            "purple": {
                "circle": "\N{LARGE PURPLE CIRCLE}",
                "square": "\N{LARGE PURPLE SQUARE}",
                "heart": "\N{PURPLE HEART}",
            },
        }

    def __repr__(self):
        return f"*{self.name}*"

    def deal_damage(self, game, player, opponent):
        msg = ''
        game.scores[opponent] -= self.dmg
        #game.scores[opponent] = max(game.scores[opponent], 0)
        msg += f"*Damage:* {player}'s {self.emoji()} {self.name} deals {self.dmg} damage to {opponent}!\n"
        return msg

    def activate(self, game, player, opponent, choice):
        msg = ''
        if self.shape == "heart":
            if self not in game.wands[opponent].hexes:
                game.wands[opponent].hexes.append(self)
                msg += f"{opponent} is Hexed!\n"
                if self not in game.effects[player]:
                    game.effects[player][self] = -1
        return msg

    def description(self):
        return f"Deals {self.dmg} damage. "

    def emoji(self):
        return self.emoji_table[self.color][self.shape]

    def get_choice_msg(self):
        msg = f"This spell doesn't require any choices. React to continue.\n"
        return msg

    def get_choices(self, game, player, opponent):
        return "\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE}"

    def get_num_choices(self):
        return 1

class RedCounterA(Spell):
    def __init__(self):
        super().__init__("Ignite", 0, "red", "circle", 5)
        self.bonus = 5
        self.chosen_color = None

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        self.chosen_color = wonder_wand.color(choice)
        if choice == "\N{LARGE RED CIRCLE}":
            msg += f"{player}'s fire spells deal +{self.bonus} damage next round.\n"
        elif choice == "\N{LARGE ORANGE CIRCLE}":
            msg += f"{player}'s earth spells deal +{self.bonus} damage next round.\n"
        elif choice == "\N{LARGE YELLOW CIRCLE}":
            msg += f"{player}'s lightning spells deal +{self.bonus} damage next round.\n"
        elif choice == "\N{LARGE GREEN CIRCLE}":
            msg += f"{player}'s nature spells deal +{self.bonus} damage next round.\n"
        elif choice == "\N{LARGE BLUE CIRCLE}":
            msg += f"{player}'s water spells deal +{self.bonus} damage next round.\n"
        elif choice == "\N{LARGE PURPLE CIRCLE}":
            msg += f"{player}'s air spells deal +{self.bonus} damage next round.\n"
        if self not in game.effects[player]:
            game.effects[player][self] = 1
        return msg

    def description(self):
        msg = super().description()
        msg += f"Choose an element. Your spells of that element deal +{self.bonus} damage next round. "
        return msg

    def get_choice_msg(self):
        return f"Choose an element. Your spells of that element deal +{self.bonus} damage next round.\n"

    def get_choices(self, game, player, opponent):
        return ["\N{LARGE RED CIRCLE}", "\N{LARGE ORANGE CIRCLE}", "\N{LARGE YELLOW CIRCLE}", "\N{LARGE GREEN CIRCLE}", "\N{LARGE BLUE CIRCLE}", "\N{LARGE PURPLE CIRCLE}", ]

class RedCounterB(Spell):
    def __init__(self):
        super().__init__("Red Counter A", 1, "red", "circle", 4)
        self.bonus = 4
        self.chosen_shape = None

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        self.chosen_shape = wonder_wand.shape(choice)
        if choice == "\N{PURPLE HEART}":
            msg += f"{player}'s Hexes deal +{self.bonus} damage next round.\n"
        elif choice == "\N{LARGE PURPLE SQUARE}":
            msg += f"{player}'s Strikes deal +{self.bonus} damage next round.\n"
        elif choice == "\N{LARGE PURPLE CIRCLE}":
            msg += f"{player}'s Counters deal +{self.bonus} damage next round.\n"
        if self not in game.effects[player]:
            game.effects[player][self] = 1
        return msg

    def description(self):
        msg = super().description()
        msg += f"Choose a spell class. You get a +{self.bonus} damage bonus on that spell class next round. "
        return msg

    def get_choice_msg(self):
        return f"Choose a spell class. Your spells of that spell class deal +{self.bonus} damage next round.\n"

    def get_choices(self, game, player, opponent):
        return ["\N{ORANGE HEART}", "\N{LARGE ORANGE SQUARE}", "\N{LARGE ORANGE CIRCLE}"]

class OrangeCounterA(Spell):
    def __init__(self):
        super().__init__("Stone Wall", 0, "orange", "circle", 7)
        self.bonus = 4
        self.chosen_shape = None

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        self.chosen_shape = wonder_wand.shape(choice)
        if choice == "\N{PURPLE HEART}":
            msg += f"{player} won't take damage from {opponent}'s Hexes next round.\n"
        elif choice == "\N{LARGE PURPLE SQUARE}":
            msg += f"{player}'s won't take damage from {opponent}'s Strikes next round.\n"
        elif choice == "\N{LARGE PURPLE CIRCLE}":
            msg += f"{player}'s won't take damage from {opponent}'s Counters next round.\n"
        if self not in game.effects[player]:
            game.effects[player][self] = 1
        return msg

    def description(self):
        msg = super().description()
        msg += f"Choose a spell class. You won't take damage from that spell class next round. "
        return msg

    def get_choice_msg(self):
        return f"Choose a spell class. You won't take damage from that spell class next round.\n"

    def get_choices(self, game, player, opponent):
        return ["\N{ORANGE HEART}", "\N{LARGE ORANGE SQUARE}", "\N{LARGE ORANGE CIRCLE}"]

class YellowCounterA(Spell):
    def __init__(self):
        super().__init__("Overclock", 0, "yellow", "circle", 4)
        self.penalty = 2

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        game.wands[player].active[choice] = True
        game.wands[player].known[choice] = True
        msg += f"{player} prepares {choice}.\n"
        game.scores[player] -= self.penalty
        msg += f"{player} pays {self.penalty} HP.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Choose a spell. Put it in your spell pool. Costs {self.penalty} HP. "
        return msg

    def get_choice_msg(self):
        return f"Choose a spell. Put it in your spell pool. Costs {self.penalty} HP.\n"

    def get_choices(self, game, player, opponent):
        choices = []
        for e in sorted(game.wands[player].spells, key=lambda x: list(emojis_to_moves.keys()).index(x)):
            if e == self.emoji():
                continue
            if not game.wands[player].active[e]:
                choices.append(e)
        return choices

class YellowCounterB(Spell):
    def __init__(self):
        super().__init__("Faraday Cage", 0, "yellow", "circle", 4)

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        if self not in game.effects[player]:
            game.effects[player][self] = 1
        msg += f"{player} is protected from divination this round.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"You are protected from divination this round. "
        return msg

class GreenCounterA(Spell):
    def __init__(self):
        super().__init__("Regenerate", 0, "green", "circle", 3)

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        game.scores[player] += 1
        msg += f"{player} gains 1 HP.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Gain 1 HP. "
        return msg

class GreenCounterB(Spell):
    def __init__(self):
        super().__init__("Green Counter B", 1, "green", "circle", 3)

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        game.wands[player].active[choice] = True
        msg += f"{player} loads {choice}.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Choose a spell. Put it in your spell pool. "
        return msg

    def get_choice_msg(self):
        return f"Choose a spell. Put it in your spell pool.\n"

    def get_choices(self, game, player, opponent):
        choices = []
        for e in game.wands[player].spells:
            if e == self.emoji():
                continue
            if not game.wands[player].active[e]:
                choices.append(e)
        return choices

class BlueCounterA(Spell):
    def __init__(self):
        super().__init__("Reflecting Pool", 0, "blue", "circle", 4)
        self.chosen_shape = None

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        self.chosen_shape = wonder_wand.shape(choice)
        countered = game.decisions[opponent]
        same_shape = []
        for clr in colors:
            same_shape.append(moves_to_emojis[(clr, self.chosen_shape)])
        msg += f"{player} is now divining"
        for e in same_shape:
            msg += f" {e}"
        msg += ".\n"
        for e in same_shape:
            if e in game.wands[opponent].active and game.wands[opponent].active[e]:
                game.wands[opponent].known[e] = True
                game.wands[opponent].equip_know(e)
            else:
                game.wands[opponent].antiknown[e] = True
                game.wands[opponent].equip_know(e)
        game.wands[opponent].check_completeness()
        return msg

    def description(self):
        msg = super().description()
        msg += "Choose a spell class. Divine all spells of that spell class. "
        return msg

    def get_choice_msg(self):
        return f"Choose a spell class. Divine all spells of that spell class.\n"

    def get_choices(self, game, player, opponent):
        return ["\N{LARGE BLUE CIRCLE}", "\N{LARGE BLUE SQUARE}", "\N{BLUE HEART}"]

class BlueCounterB(Spell):
    def __init__(self):
        super().__init__("Blue Counter B", 1, "blue", "circle", 5)
        self.chosen_color = None

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        self.chosen_color = wonder_wand.color(choice)
        countered = game.decisions[opponent]
        same_shape = []
        if self.chosen_color == "red":
            same_shape = ["\N{ORANGE HEART}", "\N{LARGE ORANGE SQUARE}", "\N{LARGE ORANGE CIRCLE}"]
        elif self.chosen_color == "green":
            same_shape = ["\N{GREEN HEART}", "\N{LARGE GREEN SQUARE}", "\N{LARGE GREEN SQUARE}"]
        elif self.chosen_color == "blue":
            same_shape = ["\N{PURPLE HEART}", "\N{LARGE PURPLE SQUARE}", "\N{LARGE PURPLE SQUARE}"]
        msg += f"{player} is now divining"
        for e in same_shape:
            msg += f" {e}"
        msg += ".\n"
        for e in same_shape:
            if e in game.wands[opponent].active and game.wands[opponent].active[e]:
                game.wands[opponent].known[e] = True
                game.wands[opponent].equip_know(e)
            else:
                game.wands[opponent].antiknown[e] = True
                game.wands[opponent].equip_know(e)
        msg += ".\n"
        game.wands[opponent].check_completeness()
        return msg

    def description(self):
        msg = super().description()
        msg += "Choose an element. Divine all spells of that element. "
        return msg

    def get_choice_msg(self):
        return f"Choose an element. Divine all spells of that element.\n"

    def get_choices(self, game, player, opponent):
        return ["\N{LARGE ORANGE CIRCLE}", "\N{LARGE GREEN CIRCLE}", "\N{LARGE PURPLE CIRCLE}"]

class PurpleCounterA(Spell):
    def __init__(self):
        super().__init__("Ventilate", 0, "purple", "circle", 3)

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        hexes = []
        for s in game.effects[opponent]:
            if s.shape == "heart":
                hexes.append(s)
        if hexes:
            for s in hexes:
                del game.effects[opponent][s]
                msg += f"Shedding Hex: {s.emoji()} {s.name}.\n"
            game.scores[opponent] -= 2*len(hexes)
            msg += f"{player} deals {2*len(hexes)} extra damage to {opponent}!\n"
        else:
            msg += f"No Hexes to shed.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += "Shed all Hexes. Deals 2 extra damage for each Hex shedded. "
        return msg

class RedStrikeA(Spell):
    def __init__(self):
        super().__init__("Wildfire", 0, "red", "square", 8)
        self.cost = 4
        self.choice = None

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        if choice == "\N{THUMBS UP SIGN}":
            game.scores[player] -= self.cost
            game.wands[player].active[self.emoji()] = True
            game.wands[player].known[self.emoji()] = True
            game.wands[player].antiknown[self.emoji()] = False
            msg += f"{player} paid {self.cost} HP to save {self.emoji()} {self.name}.\n"
        else:
            msg += f"{player} did not choose to save {self.emoji()} {self.name}.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Choose whether to pay {self.cost} HP to return this spell to your spell pool. "
        return msg

    def get_choice_msg(self):
        return f"Choose whether to pay {self.cost} HP to return this spell to your spell pool.\n"

    def get_choices(self, game, player, opponent):
        return ["\N{CROSS MARK}", "\N{THUMBS UP SIGN}"]

class RedStrikeB(Spell):
    def __init__(self):
        super().__init__("Red Strike B", 1, "red", "square", 9)
        self.chosen_color = None

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        self.chosen_color = wonder_wand.color(choice)
        if self not in game.effects[player]:
            game.effects[player][self] = 1
            if self.chosen_color == "red":
                game.wands[opponent].frozen["\N{ORANGE HEART}"] = True
                game.wands[opponent].frozen["\N{LARGE ORANGE SQUARE}"] = True
                game.wands[opponent].frozen["\N{LARGE ORANGE CIRCLE}"] = True
                msg += f"{opponent} can't cast \N{LARGE ORANGE CIRCLE} \N{LARGE ORANGE SQUARE} \N{ORANGE HEART} next round.\n"
            elif self.chosen_color == "green":
                game.wands[opponent].frozen["\N{GREEN HEART}"] = True
                game.wands[opponent].frozen["\N{LARGE GREEN SQUARE}"] = True
                game.wands[opponent].frozen["\N{LARGE GREEN CIRCLE}"] = True
                msg += f"{opponent} can't cast \N{LARGE GREEN CIRCLE} \N{LARGE GREEN SQUARE} \N{GREEN HEART} next round.\n"
            elif self.chosen_color == "blue":
                game.wands[opponent].frozen["\N{PURPLE HEART}"] = True
                game.wands[opponent].frozen["\N{LARGE PURPLE SQUARE}"] = True
                game.wands[opponent].frozen["\N{LARGE PURPLE CIRCLE}"] = True
                msg += f"{opponent} can't cast \N{LARGE PURPLE CIRCLE} \N{LARGE PURPLE SQUARE} \N{PURPLE HEART} next round.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Choose an element. Your opponent can't cast that element next round. "
        return msg

    def get_choice_msg(self):
        return f"Choose an element. Your opponent can't cast that element next round.\n"

    def get_choices(self, game, player, opponent):
        return ["\N{LARGE ORANGE SQUARE}", "\N{LARGE GREEN SQUARE}", "\N{LARGE PURPLE SQUARE}"]

class OrangeStrikeA(Spell):
    def __init__(self):
        super().__init__("Shatter", 0, "orange", "square", 9)
        self.chosen_color = None

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        if not isinstance(choice, list):
            choice = [choice]
        for c in choice:
            if c in game.wands[opponent].active:
                game.wands[opponent].active[c] = False
                game.wands[opponent].known[c] = False
                game.wands[opponent].antiknown[c] = True
                msg += f"Unpreparing {choice} from {opponent}'s wand.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Choose two spells you know your opponent has prepared. Unprepare them. "
        return msg

    def get_choice_msg(self):
        return f"Choose two spells you know your opponent has prepared. Unprepare them.\n"

    def get_choices(self, game, player, opponent):
        choices = []
        for e in game.wands[opponent].spells:
            if game.wands[opponent].active[e] and game.wands[opponent].known[e]:
                choices.append(e)
        return choices

    def get_num_choices(self):
        return 2

class YellowStrikeA(Spell):
    def __init__(self):
        super().__init__("Lightning Bolt", 0, "yellow", "square", 7)
        self.chosen_shape = None

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        self.chosen_shape = wonder_wand.shape(choice)
        if self not in game.effects[player]:
            game.effects[player][self] = 1
            if self.chosen_shape == "circle":
                game.wands[opponent].frozen["\N{LARGE RED CIRCLE}"] = True
                game.wands[opponent].frozen["\N{LARGE ORANGE CIRCLE}"] = True
                game.wands[opponent].frozen["\N{LARGE YELLOW CIRCLE}"] = True
                game.wands[opponent].frozen["\N{LARGE GREEN CIRCLE}"] = True
                game.wands[opponent].frozen["\N{LARGE BLUE CIRCLE}"] = True
                game.wands[opponent].frozen["\N{LARGE PURPLE CIRCLE}"] = True
                msg += f"{opponent} can't cast \N{LARGE RED CIRCLE} \N{LARGE ORANGE CIRCLE} \N{LARGE YELLOW CIRCLE} \N{LARGE GREEN CIRCLE} \N{LARGE BLUE CIRCLE} \N{LARGE PURPLE CIRCLE} next round.\n"
            elif self.chosen_shape == "square":
                game.wands[opponent].frozen["\N{LARGE RED SQUARE}"] = True
                game.wands[opponent].frozen["\N{LARGE ORANGE SQUARE}"] = True
                game.wands[opponent].frozen["\N{LARGE YELLOW SQUARE}"] = True
                game.wands[opponent].frozen["\N{LARGE GREEN SQUARE}"] = True
                game.wands[opponent].frozen["\N{LARGE BLUE SQUARE}"] = True
                game.wands[opponent].frozen["\N{LARGE PURPLE SQUARE}"] = True
                msg += f"{opponent} can't cast \N{LARGE RED SQUARE} \N{LARGE ORANGE SQUARE} \N{LARGE YELLOW SQUARE} \N{LARGE GREEN SQUARE} \N{LARGE BLUE SQUARE} \N{LARGE PURPLE SQUARE} next round.\n"
            elif self.chosen_shape == "heart":
                game.wands[opponent].frozen["\N{HEAVY BLACK HEART}"] = True
                game.wands[opponent].frozen["\N{ORANGE HEART}"] = True
                game.wands[opponent].frozen["\N{YELLOW HEART}"] = True
                game.wands[opponent].frozen["\N{GREEN HEART}"] = True
                game.wands[opponent].frozen["\N{BLUE HEART}"] = True
                game.wands[opponent].frozen["\N{PURPLE HEART}"] = True
                msg += f"{opponent} can't cast \N{HEAVY BLACK HEART} \N{ORANGE HEART} \N{YELLOW HEART} \N{GREEN HEART} \N{BLUE HEART} \N{PURPLE HEART} next round.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Choose a spell class. Your opponent can't cast that spell class next round. "
        return msg

    def get_choice_msg(self):
        return f"Choose a spell class. Your opponent can't cast that spell class next round.\n"

    def get_choices(self, game, player, opponent):
        return ["\N{LARGE YELLOW CIRCLE}", "\N{LARGE YELLOW SQUARE}", "\N{YELLOW HEART}"]

class GreenStrikeA(Spell):
    def __init__(self):
        super().__init__("Evolutionary Response", 0, "green", "square", 7)
        self.bonus = 4
        self.bonus_activated = False

    def deal_damage(self, game, player, opponent):
        msg = super().deal_damage(game, player, opponent)
        self.bonus_activated = (game.combat_options[opponent] in game.wands[opponent].known and game.wands[opponent].known[game.combat_options[opponent]])
        return msg

    def activate(self, game, player, opponent, choice):
        msg = ''
        if self.bonus_activated:
            game.scores[opponent] -= self.bonus
            msg += f"{player} knew {opponent} had {game.combat_options[opponent]} loaded! +{self.bonus} damage.\n"
        elif game.combat_options[opponent] in game.wands[opponent].known:
            msg += f"{player} did not know {opponent} had {game.combat_options[opponent]} loaded. No bonus damage.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Gets a +{self.bonus} damage bonus vs spells you know your opponent has loaded. "
        return msg

class GreenStrikeB(Spell):
    def __init__(self):
        super().__init__("Green Strike B", 1, "green", "square", 11)

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        if self not in game.effects[player]:
            game.effects[player][self] = 0
        msg += f"{player} returned {opponent}'s spell to their wand.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Return your opponent's spell to their wand. "
        return msg

class BlueStrikeA(Spell):
    def __init__(self):
        super().__init__("Ice Beam", 0, "blue", "square", 7)
        self.chosen_color = None

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        self.chosen_color = wonder_wand.color(choice)
        if self not in game.effects[player]:
            game.effects[player][self] = 1
            if self.chosen_color == "red":
                game.wands[opponent].frozen["\N{HEAVY BLACK HEART}"] = True
                game.wands[opponent].frozen["\N{LARGE RED SQUARE}"] = True
                game.wands[opponent].frozen["\N{LARGE RED CIRCLE}"] = True
                msg += f"{opponent} can't cast \N{LARGE RED CIRCLE} \N{LARGE RED SQUARE} \N{HEAVY BLACK HEART} next round.\n"
            elif self.chosen_color == "orange":
                game.wands[opponent].frozen["\N{ORANGE HEART}"] = True
                game.wands[opponent].frozen["\N{LARGE ORANGE SQUARE}"] = True
                game.wands[opponent].frozen["\N{LARGE ORANGE CIRCLE}"] = True
                msg += f"{opponent} can't cast \N{LARGE ORANGE CIRCLE} \N{LARGE ORANGE SQUARE} \N{ORANGE HEART} next round.\n"
            elif self.chosen_color == "yellow":
                game.wands[opponent].frozen["\N{YELLOW HEART}"] = True
                game.wands[opponent].frozen["\N{LARGE YELLOW SQUARE}"] = True
                game.wands[opponent].frozen["\N{LARGE YELLOW CIRCLE}"] = True
                msg += f"{opponent} can't cast \N{LARGE YELLOW CIRCLE} \N{LARGE YELLOW SQUARE} \N{YELLOW HEART} next round.\n"
            elif self.chosen_color == "green":
                game.wands[opponent].frozen["\N{GREEN HEART}"] = True
                game.wands[opponent].frozen["\N{LARGE GREEN SQUARE}"] = True
                game.wands[opponent].frozen["\N{LARGE GREEN CIRCLE}"] = True
                msg += f"{opponent} can't cast \N{LARGE GREEN CIRCLE} \N{LARGE GREEN SQUARE} \N{GREEN HEART} next round.\n"
            elif self.chosen_color == "blue":
                game.wands[opponent].frozen["\N{BLUE HEART}"] = True
                game.wands[opponent].frozen["\N{LARGE BLUE SQUARE}"] = True
                game.wands[opponent].frozen["\N{LARGE BLUE CIRCLE}"] = True
                msg += f"{opponent} can't cast \N{LARGE BLUE CIRCLE} \N{LARGE BLUE SQUARE} \N{BLUE HEART} next round.\n"
            elif self.chosen_color == "purple":
                game.wands[opponent].frozen["\N{PURPLE HEART}"] = True
                game.wands[opponent].frozen["\N{LARGE PURPLE SQUARE}"] = True
                game.wands[opponent].frozen["\N{LARGE PURPLE CIRCLE}"] = True
                msg += f"{opponent} can't cast \N{LARGE PURPLE CIRCLE} \N{LARGE PURPLE SQUARE} \N{PURPLE HEART} next round.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Choose an element. Your opponent can't cast that element next round. "
        return msg

    def get_choice_msg(self):
        return f"Choose an element. Your opponent can't cast that element next round.\n"

    def get_choices(self, game, player, opponent):
        return ["\N{LARGE RED SQUARE}", "\N{LARGE ORANGE SQUARE}", "\N{LARGE YELLOW SQUARE}", "\N{LARGE GREEN SQUARE}", "\N{LARGE BLUE SQUARE}", "\N{LARGE PURPLE SQUARE}"]

class BlueStrikeB(Spell):
    def __init__(self):
        super().__init__("Blue Strike B", 1, "blue", "square", 8)
        self.bonus = 4

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        if game.decisions[opponent] in game.wands[opponent].known and game.wands[opponent].known[game.decisions[opponent]]:
            game.scores[opponent] -= self.bonus
            msg += f"{player} knew {opponent} had {game.decisions[opponent]} loaded! +{self.bonus} damage.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Gets a +{self.bonus} damage bonus vs spells you know your opponent has loaded. "
        return msg

class PurpleStrikeA(Spell):
    def __init__(self):
        super().__init__("Gust of Wind", 0, "purple", "square", 4)
        self.bonus = 8

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        if choice == "\N{THUMBS UP SIGN}":
            if self not in game.effects[player]:
                game.effects[player][self] = 0
            if game.combat_options[opponent] in game.wands[opponent].spells:
                game.wands[opponent].active[game.combat_options[opponent]] = True
                game.wands[opponent].burned[game.combat_options[opponent]] = False
                game.wands[opponent].known[game.combat_options[opponent]] = True
                game.wands[opponent].antiknown[game.combat_options[opponent]] = False
                game.wands[opponent].equip_know(game.combat_options[opponent])
                msg += f"{player} returned {opponent}'s spell to their wand.\n"
            game.scores[opponent] -= self.bonus
            msg += f"{player} dealt an additional {self.bonus} damage to {opponent}!\n"
        else:
            msg += f"{player} did not use {self.emoji()}'s ability.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Choose whether to return your opponent's spell to their wand and deal an additional {self.bonus} damage. "
        return msg

    def get_choice_msg(self):
        return f"Choose whether to return your opponent's spell to their wand and deal an additional {self.bonus} damage.\n"

    def get_choices(self, game, player, opponent):
        return ["\N{CROSS MARK}", "\N{THUMBS UP SIGN}"]

class RedHexA(Spell):
    def __init__(self):
        super().__init__("Burn", 0, "red", "heart", 5)
        self.penalty = 3

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        msg += f"Hex: Deal {self.penalty} damage to your opponent at the end of each round.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Hex: Deal {self.penalty} damage to your opponent at the end of each round. "
        return msg

    def effect_msg(self, game, player, opponent):
        msg = ""
        msg += f"Hex: Deal {self.penalty} damage to {opponent} at the end of each round.\n"
        return msg

class RedHexB(Spell):
    def __init__(self):
        super().__init__("Red Hex B", 1, "red", "heart", 6)
        self.chosen_shape = None

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        self.chosen_shape = wonder_wand.shape(choice)
        if self.chosen_shape == "circle":
            msg += f"Hex: It costs 2 HP for your opponent to cast \N{LARGE ORANGE CIRCLE} \N{LARGE GREEN CIRCLE} \N{LARGE PURPLE CIRCLE}.\n"
        elif self.chosen_shape == "square":
            msg += f"Hex: It costs 2 HP for your opponent to cast \N{LARGE ORANGE SQUARE} \N{LARGE GREEN SQUARE} \N{LARGE PURPLE SQUARE}.\n"
        elif self.chosen_shape == "heart":
            msg += f"Hex: It costs 2 HP for your opponent to cast \N{ORANGE HEART} \N{GREEN HEART} \N{PURPLE HEART}.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Choose a spell class. Hex: It costs 2 HP for your opponent to cast that spell class. "
        return msg

    def get_choice_msg(self):
        return f"Choose a spell class. Hex: It costs 2 HP for your opponent to cast that spell class. "

    def get_choices(self, game, player, opponent):
        return ["\N{ORANGE HEART}", "\N{LARGE ORANGE SQUARE}", "\N{LARGE ORANGE CIRCLE}"]

    def effect_msg(self, game, player, opponent):
        msg = ""
        if self.chosen_shape == "circle":
            msg += f"Hex: It costs 2 HP for your opponent to cast \N{LARGE ORANGE CIRCLE} \N{LARGE GREEN CIRCLE} \N{LARGE PURPLE CIRCLE}.\n"
        elif self.chosen_shape == "square":
            msg += f"Hex: It costs 2 HP for your opponent to cast \N{LARGE ORANGE SQUARE} \N{LARGE GREEN SQUARE} \N{LARGE PURPLE SQUARE}.\n"
        elif self.chosen_shape == "heart":
            msg += f"Hex: It costs 2 HP for your opponent to cast \N{ORANGE HEART} \N{GREEN HEART} \N{PURPLE HEART}.\n"
        return msg

class OrangeHexA(Spell):
    def __init__(self):
        super().__init__("Crumble to Dust", 0, "orange", "heart", 4)

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        msg += f"Hex: When your opponent loses in combat, instead of performing divination, they unprepare a spell.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Hex: When your opponent loses in combat, instead of performing divination, they unprepare a spell. "
        return msg

    def effect_msg(self, game, player, opponent):
        msg = ""
        msg += f"Hex: When {opponent} loses in combat, instead of performing divination, they unprepare a spell.\n"
        return msg

class YellowHexA(Spell):
    def __init__(self):
        super().__init__("Plug In", 0, "yellow", "heart", 5)

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        msg += f"Hex: The next time your opponent refreshes, you refresh too.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Hex: The next time your opponent refreshes, you refresh too. "
        return msg

    def effect_msg(self, game, player, opponent):
        msg = ""
        msg += f"Hex: The next time {opponent} refreshes, {player} refreshes too.\n"
        return msg

class GreenHexA(Spell):
    def __init__(self):
        super().__init__("Parasite", 0, "green", "heart", 4)

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        msg += f"Hex: Whenever you win combat, gain 1 HP.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Hex: Whenever you win combat, gain 1 HP. "
        return msg

    def effect_msg(self, game, player, opponent):
        msg = ""
        msg += f"Hex: Whenever {player} wins combat, they gain 1 HP.\n"
        return msg

class GreenHexB(Spell):
    def __init__(self):
        super().__init__("Green Hex B", 1, "green", "heart", 5)

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        msg += f"Hex: The next time your opponent refreshes, you refresh too. "
        return msg

    def description(self):
        msg = super().description()
        msg += f"Hex: The next time your opponent refreshes, you refresh too. "
        return msg

    def effect_msg(self, game, player, opponent):
        msg = ""
        msg += f"Hex: The next time your opponent refreshes, you refresh too.\n"
        return msg

class BlueHexA(Spell):
    def __init__(self):
        super().__init__("Freezing Temperatures", 0, "blue", "heart", 4)
        self.chosen_shape = None
        self.penalty = 2

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        self.chosen_shape = wonder_wand.shape(choice)
        if self.chosen_shape == "circle":
            msg += f"Hex: It costs {self.penalty} HP for your opponent to cast \N{LARGE RED CIRCLE} \N{LARGE ORANGE CIRCLE} \N{LARGE YELLOW CIRCLE} \N{LARGE GREEN CIRCLE} \N{LARGE BLUE CIRCLE} \N{LARGE PURPLE CIRCLE}.\n"
        elif self.chosen_shape == "square":
            msg += f"Hex: It costs {self.penalty} HP for your opponent to cast \N{LARGE RED SQUARE} \N{LARGE ORANGE SQUARE} \N{LARGE YELLOW SQUARE} \N{LARGE GREEN SQUARE} \N{LARGE BLUE SQUARE} \N{LARGE PURPLE SQUARE}.\n"
        elif self.chosen_shape == "heart":
            msg += f"Hex: It costs {self.penalty} HP for your opponent to cast \N{HEAVY BLACK HEART} \N{ORANGE HEART} \N{YELLOW HEART} \N{GREEN HEART} \N{BLUE HEART} \N{PURPLE HEART}.\n"
        return msg

    def description(self):
        msg = super().description()
        msg += f"Choose a spell class. Hex: It costs {self.penalty} HP for your opponent to cast that spell class. "
        return msg

    def get_choice_msg(self):
        return f"Choose a spell class. Hex: It costs {self.penalty} HP for your opponent to cast that spell class.\n"

    def get_choices(self, game, player, opponent):
        return ["\N{BLUE HEART}", "\N{LARGE BLUE SQUARE}", "\N{LARGE BLUE CIRCLE}"]

    def effect_msg(self, game, player, opponent):
        msg = ""
        if self.chosen_shape == "circle":
            msg += f"Hex: It costs {self.penalty} HP for {opponent} to cast \N{LARGE RED CIRCLE} \N{LARGE ORANGE CIRCLE} \N{LARGE YELLOW CIRCLE} \N{LARGE GREEN CIRCLE} \N{LARGE BLUE CIRCLE} \N{LARGE PURPLE CIRCLE}.\n"
        elif self.chosen_shape == "square":
            msg += f"Hex: It costs {self.penalty} HP for {opponent} to cast \N{LARGE RED SQUARE} \N{LARGE ORANGE SQUARE} \N{LARGE YELLOW SQUARE} \N{LARGE GREEN SQUARE} \N{LARGE BLUE SQUARE} \N{LARGE PURPLE SQUARE}.\n"
        elif self.chosen_shape == "heart":
            msg += f"Hex: It costs {self.penalty} HP for {opponent} to cast \N{HEAVY BLACK HEART} \N{ORANGE HEART} \N{YELLOW HEART} \N{GREEN HEART} \N{BLUE HEART} \N{PURPLE HEART}.\n"
        return msg

class BlueHexB(Spell):
    def __init__(self):
        super().__init__("Blue Hex B", 1, "blue", "heart", 7)

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        msg += f"Hex: Your opponent takes 1 damage whenever you block a spell. "
        return msg

    def description(self):
        msg = super().description()
        msg += f"Hex: Your opponent takes 1 damage whenever you block a spell. "
        return msg

    def effect_msg(self, game, player, opponent):
        msg = ""
        msg += f"Hex: Your opponent takes 1 damage whenever you block a spell.\n"
        return msg

class PurpleHexA(Spell):
    def __init__(self):
        super().__init__("Featherweight", 0, "purple", "heart", 5)

    def activate(self, game, player, opponent, choice):
        msg = super().activate(game, player, opponent, choice)
        msg += f"Hex: Your opponent takes 2 damage whenever they block a spell. "
        return msg

    def description(self):
        msg = super().description()
        msg += f"Hex: Your opponent takes 2 damage whenever they block a spell. "
        return msg

    def effect_msg(self, game, player, opponent):
        msg = ""
        msg += f"Hex: {opponent} takes 2 damage whenever they blocks a spell.\n"
        return msg

def generate_spellbook():
    book = {
        "circle": [],
        "square": [],
        "heart": [],
    }
    book["circle"].append([
        RedCounterA(),
        OrangeCounterA(),
        YellowCounterA(),
        GreenCounterA(),
        BlueCounterA(),
        PurpleCounterA(),
    ])
    book["square"].append([
        RedStrikeA(),
        OrangeStrikeA(),
        YellowStrikeA(),
        GreenStrikeA(),
        BlueStrikeA(),
        PurpleStrikeA(),
    ])
    book["heart"].append([
        RedHexA(),
        OrangeHexA(),
        YellowHexA(),
        GreenHexA(),
        BlueHexA(),
        PurpleHexA(),
    ])
    return book
