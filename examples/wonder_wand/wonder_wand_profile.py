#from axi.abstract_profile import AbstractProfile
import examples.wonder_wand.wonder_wand as wonder_wand

class WonderWandProfile:
    def __init__(self):
        self.equipped = wonder_wand.wand_default()

    def get_equipped_wand(self):
        return self.equipped

