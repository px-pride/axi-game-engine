"""Wonder Wand profile (Phase 16).

Holds the user's currently-equipped wand. Phase 16: structured-column
persistence via examples/wonder_wand/wand_persistence.py replaces the
legacy pickle-BLOB path; both coexist so older saved profiles still
load.
"""

import examples.wonder_wand.wonder_wand as wonder_wand


class WonderWandProfile:
    def __init__(self):
        self.equipped = wonder_wand.wand_default()

    def get_equipped_wand(self):
        return self.equipped

    def save_structured(self, user_id):
        """Phase 16: persist the equipped wand via structured columns."""
        from examples.wonder_wand import wand_persistence
        return wand_persistence.save_wand(user_id, self.equipped)

    @classmethod
    def load_structured(cls, user_id):
        """Phase 16: load a wand from structured columns. Returns a
        WonderWandProfile or None if no row."""
        from examples.wonder_wand import wand_persistence
        wand = wand_persistence.load_wand(user_id)
        if wand is None:
            return None
        profile = cls.__new__(cls)
        profile.equipped = wand
        return profile
