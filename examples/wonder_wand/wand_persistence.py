"""Structured wand persistence (Phase 16).

Replaces the opaque-BLOB profile path (`load_profile` /
`save_profile` in `axi/axi.py`) for Wonder Wand with a structured
`wands` table — 9 (emoji, page) slot pairs. At load time, the
(emoji, page) pair is reconstructed back into a Spell via
`spells.generate_spellbook()[shape][page][color_idx]`.

Coexists with the legacy BLOB path; callers can read structured
first and fall back if absent.
"""

import axi.handlers.database_handler as db
from examples.wonder_wand import spells, wonder_wand


WAND_SPELL_SLOTS = 9


def _resolve_page(spell, shape_key):
    """Find which page of the spellbook a given spell instance lives
    on. Returns 0 if the spell isn't found (sensible default since
    page 0 is canonical)."""
    spellbook = spells.generate_spellbook()
    pages = spellbook.get(shape_key, [])
    target_emoji = spell.emoji() if hasattr(spell, "emoji") else None
    for page_idx, page in enumerate(pages):
        for candidate in page:
            cand_emoji = candidate.emoji() if hasattr(
                candidate, "emoji") else None
            if cand_emoji == target_emoji:
                return page_idx
    return 0


def save_wand(user_id, wand):
    """Persist a Wand to the `wands` table.

    Flattens up to 9 (emoji, page) pairs into spell_emoji_0..8 +
    spell_page_0..8. Excess spells (rare) are truncated.

    Returns the rowid of the inserted row.
    """
    if wand is None:
        return None
    name = getattr(wand, "name", "Custom Wand")
    # Get the canonical emoji order from the wand's spells dict.
    emojis_in_order = list(wand.spells.keys())
    # Build the column tuple: (user_id, name, emoji_0, page_0, ...).
    cols = [user_id, name]
    for i in range(WAND_SPELL_SLOTS):
        if i < len(emojis_in_order):
            emoji = emojis_in_order[i]
            spell = wand.spells[emoji]
            shape_key = wonder_wand.shape(emoji)
            page = _resolve_page(spell, shape_key)
            cols.append(emoji)
            cols.append(page)
        else:
            cols.append(None)
            cols.append(None)
    return db.add_entry("wands", cols)


def load_wand(user_id):
    """Reconstruct a Wand from the `wands` table.

    Returns None if no row for `user_id`. Skips slots whose spell
    can't be resolved (e.g. stale emoji/page).
    """
    row = db.load_entry_where("wands", "user_id", user_id)
    if not row:
        return None
    name = row[1] or "Saved Wand"
    spellbook = spells.generate_spellbook()
    spell_list = []
    for i in range(WAND_SPELL_SLOTS):
        emoji = row[2 + i * 2]
        page = row[3 + i * 2]
        if not emoji or page is None:
            continue
        shape_key = wonder_wand.shape(emoji)
        color_idx = wonder_wand.color_id(emoji)
        if shape_key is None or color_idx is None:
            continue
        try:
            spell = spellbook[shape_key][page][color_idx]
            spell_list.append(spell)
        except (KeyError, IndexError):
            continue
    if not spell_list:
        return None
    return wonder_wand.Wand(name, spell_list)
