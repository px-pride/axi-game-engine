from abc import ABC, abstractmethod


class AbstractCPU(ABC):
    def __init__(self, match):
        self.match = match
        self.name = "Abstract CPU"

    def __repr__(self):
        return self.name

    @abstractmethod
    def compute(self, options):
        pass

    # ------------------------------------------------------------------
    # Phase 16: Wonder Wand customization
    # ------------------------------------------------------------------

    def generate_wand(self):
        """Return the wand this CPU plays with in Wonder Wand matches.

        Default: return the canonical 9-spell `wand_default()`. Subclasses
        override (typically via `generate_random_wand()`) for varied play.
        """
        from examples.wonder_wand.wonder_wand import wand_default
        return wand_default()

    def generate_random_wand(self):
        """Helper: sample 3 spells per shape from page 0 of the
        spellbook, mirroring source CPU2.generate_wand (cpu2.py:11-16).
        Subclasses opt in by calling this from generate_wand()."""
        from random import sample
        from examples.wonder_wand import spells, wonder_wand
        spellbook = spells.generate_spellbook()
        spell_list = []
        for shape in spellbook:
            spell_list += sample(spellbook[shape][0], 3)
        return wonder_wand.Wand(f"{self.name}'s wand", spell_list)
