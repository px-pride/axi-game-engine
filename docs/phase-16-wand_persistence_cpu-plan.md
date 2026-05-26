# Phase 16: Wand DB persistence + CPU smart wand

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 16.

Two independent improvements to the Wonder Wand subsystem:

**(a) Wand persistence — structured columns.** Target currently
persists Wonder Wand profiles via `database_handler.add_game(name)`
which creates a 3-column table (`user_id INT PK, profile BLOB,
timestamp`). The profile is a pickled `WonderWandProfile` instance.
Source has a dedicated `wands` table with 18 typed columns (8 spell
slots × 2 fields each + name + timestamp). Phase 16 migrates target
to the structured schema for queryability and to drop pickle.

**(b) CPU smart wand.** Source's `CPU2` (`cpu2.py:11-16`) overrides
`generate_wand()` to sample 3 spells per shape from page 0 of the
spellbook — produces varied CPU play instead of a fixed default
wand. Target's `SimpleCPU`, `ClaudeCPU`, `RandomCPU` all use the
default wand from `wand_default()` (via `load_saved_wand`'s
AbstractCPU branch). Phase 16 adds `generate_wand()` to
`AbstractCPU` and overrides it in `SimpleCPU` / `ClaudeCPU` /
`RandomCPU` to sample (source CPU2 behavior).

## Scope

Part (a) — wand persistence:

- Add `wands` table to `axi/handlers/database_handler.py` matching
  source's schema (`user_id INT PK, name TEXT, spell_emoji_0..8
  TEXT, spell_page_0..8 INT, timestamp`).
- Add `save_wand(user, wand)` / `load_wand(user)` helpers to
  `examples/wonder_wand/wonder_wand_profile.py` (or a new
  `wand_persistence.py`) using structured columns.
- Update `WonderWandProfile` to load/save via structured columns
  instead of pickle BLOB.
- Update `load_saved_wand(p)` to use the structured path for
  human users.

Part (b) — CPU smart wand:

- Add `generate_wand(self)` to `AbstractCPU` (default returns
  `wand_default()` — Wonder Wand specific; gated on whether the CPU
  is in a Wonder Wand match).
- Override in `SimpleCPU` and `ClaudeCPU` (and `RandomCPU`) to
  sample 3 page-0 spells per shape (source CPU2 logic).
- Update `examples/wonder_wand/wonder_wand.py:load_saved_wand(p)`
  to call `p.generate_wand()` when `p` is an AbstractCPU instance
  (currently calls `wand_default()` unconditionally for CPUs).

## Files

| File | Change |
|---|---|
| `axi/handlers/database_handler.py` | Add `wands` table init + helpers. |
| `examples/wonder_wand/wonder_wand_profile.py` | Replace pickle path with structured save/load. |
| `examples/wonder_wand/wonder_wand.py` | `load_saved_wand` calls `cpu.generate_wand()` for CPUs. |
| `axi/abstract_cpu.py` | Add `generate_wand` method (default = wand_default). |
| `axi/simple_cpu.py` | Override `generate_wand` to sample page 0. |
| `axi/claude_cpu.py` | Override `generate_wand` to sample page 0. |
| `axi/random_cpu.py` | Override `generate_wand` to sample page 0. |
| `tests/test_wand_persistence_cpu.py` (NEW) | Persistence round-trip + CPU wand sampling tests. |

## Wands table schema

```sql
CREATE TABLE IF NOT EXISTS wands (
    user_id INT PRIMARY KEY,
    name TEXT,
    spell_emoji_0 TEXT,
    spell_page_0 INT,
    spell_emoji_1 TEXT,
    spell_page_1 INT,
    spell_emoji_2 TEXT,
    spell_page_2 INT,
    spell_emoji_3 TEXT,
    spell_page_3 INT,
    spell_emoji_4 TEXT,
    spell_page_4 INT,
    spell_emoji_5 TEXT,
    spell_page_5 INT,
    spell_emoji_6 TEXT,
    spell_page_6 INT,
    spell_emoji_7 TEXT,
    spell_page_7 INT,
    spell_emoji_8 TEXT,
    spell_page_8 INT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Mirrors source's schema. 8 spell slots indexed 0-8 (9 columns) — a
Wonder Wand has 9 spells (3 shapes × 3 colors).

## Save / load API

```python
# examples/wonder_wand/wand_persistence.py (new)

def save_wand(user_id, wand):
    """Persist a Wand instance to the wands table.

    `wand.spells` is a dict {emoji: spell_instance}. We flatten the
    9 (emoji, page) pairs into spell_emoji_0..8 + spell_page_0..8.

    Spell.page is needed to reconstruct the spell at load time —
    spells.generate_spellbook() returns indexed pages, so emoji +
    page uniquely identify the spell.
    """
    cols = {"user_id": user_id, "name": wand.name}
    for i, emoji in enumerate(_canonical_emoji_order(wand.spells)):
        spell = wand.spells[emoji]
        cols[f"spell_emoji_{i}"] = emoji
        cols[f"spell_page_{i}"] = _resolve_page(spell)
    db.add_entry("wands", _row_from_cols(cols))


def load_wand(user_id):
    """Reconstruct a Wand from the wands table.

    Reads (emoji, page) pairs and looks up the spell from
    spells.generate_spellbook(). Returns None if no row.
    """
    row = db.load_entry("wands", user_id)
    if not row:
        return None
    name = row[1]
    spellbook = spells.generate_spellbook()
    spell_list = []
    for i in range(9):
        emoji = row[2 + i * 2]
        page = row[3 + i * 2]
        if not emoji:
            continue
        # Look up the spell at (emoji_shape, page, emoji_color).
        shape_key = wonder_wand.shape(emoji)
        color_idx = wonder_wand.color_id(emoji)
        try:
            spell = spellbook[shape_key][page][color_idx]
            spell_list.append(spell)
        except (KeyError, IndexError):
            continue
    return Wand(name, spell_list) if spell_list else None
```

## CPU.generate_wand API

```python
# axi/abstract_cpu.py
class AbstractCPU(ABC):
    def __init__(self, match):
        self.match = match
        self.name = "Abstract CPU"

    @abstractmethod
    def compute(self, options):
        pass

    def generate_wand(self):
        """Default — return the fixed default wand. Subclasses
        override to produce varied gameplay."""
        from examples.wonder_wand.wonder_wand import wand_default
        return wand_default()
```

```python
# axi/simple_cpu.py
class SimpleCPU(AbstractCPU):
    ...

    def generate_wand(self):
        """Source CPU2 behavior: sample 3 spells per shape from
        page 0 of the spellbook for varied play."""
        from random import sample
        from examples.wonder_wand import spells, wonder_wand
        spellbook = spells.generate_spellbook()
        spell_list = []
        for shape in spellbook:
            spell_list += sample(spellbook[shape][0], 3)
        return wonder_wand.Wand("SimpleCPU's wand", spell_list)
```

Same logic in `ClaudeCPU` and `RandomCPU`. The shared implementation
can live on `AbstractCPU` directly as a non-default helper
(`generate_random_wand()`) that subclasses opt into; alternative is
to keep three identical overrides. We pick the latter — it matches
source's structure and avoids assuming all CPUs want varied wands.

Actually — for DRY: put `generate_random_wand()` on `AbstractCPU`
as a helper, and have `SimpleCPU/ClaudeCPU/RandomCPU.generate_wand`
each call `self.generate_random_wand()`. Then if a future CPU
subclass wants to keep the default, it can.

## Load path update

```python
# examples/wonder_wand/wonder_wand.py
def load_saved_wand(p):
    if isinstance(p, AbstractCPU):
        # Phase 16: each CPU subclass decides its wand.
        return p.generate_wand()
    profile = load_profile(p, "wonderwand")
    if not profile:
        profile = WonderWandProfile()
        save_profile(p, "wonderwand", profile)
    return profile.get_equipped_wand()
```

The human-user branch (`load_profile`) still works against the
existing pickled BLOB path; Phase 16 doesn't remove it (deferred to
a follow-up cleanup) — the new `wands` table coexists. If admins
want migration, they can run a one-off script.

## Test plan

`tests/test_wand_persistence_cpu.py`:

1. **`TestWandsTable`** — wands table exists after
   `database_handler.initialize_basic_tables()`. Verify schema:
   `user_id INT, name TEXT, spell_emoji_0..8 TEXT, spell_page_0..8 INT`.

2. **`TestSaveLoadRoundTrip`** — save a default wand for user_id=1,
   load it back, verify same name + spell emojis (and pages).

3. **`TestLoadEmptyReturnsNone`** — `load_wand(999)` for an
   unsaved user → None.

4. **`TestSaveOverwrite`** — saving wand A then wand B for the
   same user → load returns B (PRIMARY KEY behavior).

5. **`TestCpuGenerateWandDefault`** — `AbstractCPU.generate_wand()`
   returns the default 9-spell wand.

6. **`TestSimpleCpuGenerateWand`** — `SimpleCPU().generate_wand()`
   returns a Wand with 9 spells (3 shapes × 3 spells per shape).

7. **`TestSimpleCpuGenerateWandIsVaried`** — call
   `SimpleCPU().generate_wand()` 5 times with a fresh CPU each
   time; spell sets should differ at least once (randomness check —
   may flake with very small probability; use a seed if needed).

8. **`TestCpuGenerateWandUsesPage0`** — verify the sampled spells
   all come from `spells.generate_spellbook()[shape][0]` (page 0).

9. **`TestLoadSavedWandForCpu`** — `load_saved_wand(SimpleCPU(m))`
   calls `cpu.generate_wand()`, not `wand_default()`. Verify by
   comparing returned wand to either default or sampled.

10. **`TestClaudeCpuGenerateWand`** — same shape as SimpleCPU test.

11. **`TestRandomCpuGenerateWand`** — same shape.

Conftest mocks include `numpy` / `openskill` / `pytimeparse`, but
the wand machinery doesn't depend on those — it's pure Python +
DB. Should work without extra mocks.

## Major decisions

### A. Keep both pickle-BLOB and structured-wand paths coexisting

The existing pickled `wonderwand` profile path is preserved for
backwards compat with existing user data. Phase 16 adds a parallel
`wands` table; new saves go to both (or to `wands` only — see
Decision F). Old `load_profile(p, "wonderwand")` calls still work.

### B. 9 spell slots (indexed 0-8), not 8

Source uses 8 (`spell_emoji_0..7` + `spell_emoji_8` = 9 total).
Counting: 0, 1, 2, 3, 4, 5, 6, 7, 8 — that's 9 slots. We follow.

### C. Sample from page 0 (source convention)

Source's `CPU2.generate_wand` samples from `spellbook[shape][0]`.
Page 0 is the "basic" page of spells per shape. Phase 16 follows.

Target's existing `CustomizeWand.generate_random_wand` samples from
page `-1` (last page) — that's a different behavior, used for
randomizing the user's own wand picks. We leave it alone.

### D. `generate_wand` on AbstractCPU returns default

Per source's `BasicPveAgent.generate_wand` (`basic_pve_agent.py:37`).
Subclasses override to sample.

### E. `generate_random_wand` helper on AbstractCPU

DRY across SimpleCPU/ClaudeCPU/RandomCPU. Each subclass's
`generate_wand` is a one-liner: `return self.generate_random_wand()`.
A future subclass can return the default or a custom wand.

### F. New saves go to `wands` table; reads check structured first,
fall back to pickle

`WonderWandProfile.save` writes both old + new (or just new).
`WonderWandProfile.load` checks new first, falls back to old. Once
all users are migrated, the pickle path can be removed.

Phase 16 implementation: `save` writes both (idempotent); `load`
checks new first. (Simplest migration story.)

### G. `(emoji, page) → spell` reconstruction at load time

Spells aren't pickled — the (emoji, page) pair is the canonical
key. Load looks up via `spells.generate_spellbook()[shape][page][
color_idx]`. The page is needed because each shape has multiple
spell pages (Basic, Advanced, Hex, etc.).

### H. Migration script not in scope

Existing pickled BLOB profiles aren't migrated to `wands` table by
Phase 16. Users save their wand via `/customize` after deploy, and
the structured row is populated then. Phase 16 doesn't run a
one-shot migration — deferred.

### I. `customize_wand`'s in-flight Wand instance unchanged

`CustomizeWand` constructs and mutates a `WonderWandProfile`
in-memory; only `save_profile` is changed (writes structured).

## Resolved questions

1. **What if a saved wand is missing spells?** Load returns a Wand
   with however many spells survived the reconstruction. The Wand
   constructor handles variable-length spell lists.

2. **What format is `spell_page_X`?** Integer index into
   `spells.generate_spellbook()[shape]` — 0 = basic page, 1 =
   advanced, etc.

3. **What if shape/color can't be resolved?** Skip that slot. Other
   slots load normally.

4. **Do we delete the pickle table when migrating?** No — Phase 16
   keeps both tables. The pickle table can be dropped in a follow-up
   cleanup once we're confident structured wands work.

5. **What about per-game wand variants?** Source has CPU2 generating
   one wand style. We add 3 (SimpleCPU/ClaudeCPU/RandomCPU all use
   sampled page-0 wands). All identical to source semantics.

6. **What about wand validation?** Source's `Wand.__init__` accepts
   any spell list; no validation. Target follows.

7. **Schema versioning?** Not needed for Phase 16 — wands schema
   matches source 1:1.

## What's deferred

- **Migration script** (BLOB → structured columns) for existing
  user data. Manual re-save via `/customize` is the workaround.
- **Removal of pickle-based profile path** — coexists until
  follow-up cleanup.
- **`wand_versioning`** — a `wand_version` column for future
  schema migrations. Defer until needed.
- **Per-CPU wand customization** beyond the default sampled wand —
  e.g. ClaudeCPU asking the LLM to design a wand. Defer.
- **`/wand` slash command** to print a user's saved wand — could
  be useful but not in Phase 16 scope.
- **Wand sharing / templates** — admins exposing curated wands for
  users to load. Defer.
