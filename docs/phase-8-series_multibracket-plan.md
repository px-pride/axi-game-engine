# Phase 8: Series + multibracket data model

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 8.

Phase 8 introduces the **Series** (recurring tournament lineage across
episodes) and **Multibracket** (single event with parallel brackets
across games) data model. Both are pure data classes + DB tables;
neither carries Discord state. Tournaments gain `series` and
`multibracket` references so they can be grouped, queried, and
visualized as part of a larger event structure.

## Scope

- New `axi/series.py` containing `Series` and `Multibracket` pure-data
  classes.
- New DB tables in `axi/handlers/database_handler.py`: `series`,
  `multibrackets`, `tourneys`. Schemas mirror source
  (`database_manager.py:71–97`).
- New `axi/handlers/series_handler.py` for the scope→series mapping,
  `set_series` / `create_series` / `create_multibracket` /
  `get_series_ctr` operations. Mirrors `axi_backend.py` series-related
  methods.
- `axi/tournament.py` gains optional `series_id` and `multibracket_id`
  fields (default `None`). Phase 1 `Tournament.__init__` already
  takes a `series=` kwarg; expand to `series_id` for DB-persistence.
- DB persistence: when a `Tournament` is registered with a series and
  multibracket, a row in the `tourneys` table is inserted via
  `series_handler.register_tournament`.
- Tests cover Series/Multibracket construction, DB-row roundtrip,
  scope→series mapping, `get_series_ctr` counter advancing.

## Data model

```
Series
  guild_id  : int        (Discord guild scoping)
  name      : str        (e.g. "PXL", "Daily")
  season    : int        (e.g. 7)
  game      : str        ("rps" | "smash" | … | comma-joined for multi)
  pinned_channel : str   (channel name for series announcements)
  timestamp : datetime   (auto)

Multibracket
  name      : str        (e.g. "Quarterfinals weekend")
  timestamp : datetime   (auto)

Tourney  (the join row that links a Tournament to its parent series + multibracket)
  multibracket_id : int  (FK → multibrackets.rowid; nullable for solo
                          tournaments)
  series_id       : int  (FK → series.rowid)
  series_ctr      : int  (which episode in the series; auto-incremented
                          per series_id at insert time)
  timestamp       : datetime
```

Note: source uses sqlite ROWID as the implicit primary key — no
explicit `id INTEGER PRIMARY KEY` column. We follow the same
convention for direct table-compatibility.

## Files

| File | Change |
|---|---|
| `axi/series.py` (NEW) | `Series` + `Multibracket` dataclasses with `get_db_entry()` methods. |
| `axi/handlers/database_handler.py` | Add 3 `CREATE TABLE` statements (idempotent, mirror source). |
| `axi/handlers/series_handler.py` (NEW) | `state: SeriesState` (scope→Series map), `create_series`, `create_multibracket`, `set_series_for_scope`, `get_series_ctr`, `register_tournament`. |
| `axi/tournament.py` | Add `series_id: int | None = None`, `multibracket_id: int | None = None` constructor kwargs + attributes. Existing `series=` kwarg becomes `series=` (Series instance) | `series_id=` (int) — accept both, prefer instance. |
| `tests/test_series.py` (NEW) | Series/Multibracket construct + DB-entry shape. |
| `tests/test_series_handler.py` (NEW) | Scope→series map, create/set/get_series_ctr, register_tournament adds tourneys row. |

## `axi/series.py` shape

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Series:
    """Recurring tournament lineage across episodes."""
    guild_id: int
    name: str
    season: int
    game: str           # comma-joined when multi-game
    pinned_channel: str
    rowid: Optional[int] = None

    def get_db_entry(self):
        # Mirrors source's column order for series table.
        return (
            self.guild_id,
            self.name,
            self.season,
            self.game,
            self.pinned_channel,
        )


@dataclass
class Multibracket:
    """Named event with multiple parallel brackets per episode."""
    name: str
    rowid: Optional[int] = None

    def get_db_entry(self):
        return (self.name,)
```

## `axi/handlers/series_handler.py` shape

```python
from collections import defaultdict

import axi.handlers.database_handler as db
from axi.series import Series, Multibracket


class SeriesState:
    def __init__(self):
        # (guild_id, scope) → Series instance
        self.scope_to_series = defaultdict(lambda: None)
        # series rowid → Series
        self.series_by_id = {}
        # multibracket rowid → Multibracket
        self.multibrackets_by_id = {}

    def reset(self):
        self.scope_to_series.clear()
        self.series_by_id.clear()
        self.multibrackets_by_id.clear()


state = SeriesState()


def create_series(guild_id, name, season, game, pinned_channel):
    s = Series(guild_id=guild_id, name=name, season=season,
               game=game if isinstance(game, str) else ", ".join(game),
               pinned_channel=pinned_channel)
    s.rowid = db.add_entry("series", s.get_db_entry())
    state.series_by_id[s.rowid] = s
    return s


def create_multibracket(name):
    m = Multibracket(name=name)
    m.rowid = db.add_entry("multibrackets", m.get_db_entry())
    state.multibrackets_by_id[m.rowid] = m
    return m


def set_series_for_scope(guild_id, scope, series):
    state.scope_to_series[(guild_id, scope)] = series


def get_series_for_scope(guild_id, scope):
    return state.scope_to_series.get((guild_id, scope))


def get_series_ctr(series_id):
    """Return next episode index for this series (count + 1)."""
    rows = db.load_entries_where("tourneys", "series_id", series_id)
    return len(rows) + 1


def register_tournament(tournament, multibracket_id=None):
    """Insert a tourneys row linking the Tournament to its series +
    multibracket. Sets tournament.series_id, multibracket_id, series_ctr."""
    series_id = tournament.series_id
    if series_id is None:
        return
    series_ctr = get_series_ctr(series_id)
    db.add_entry("tourneys", (multibracket_id, series_id, series_ctr))
    tournament.series_ctr = series_ctr
    tournament.multibracket_id = multibracket_id
```

## DB schema additions (`axi/handlers/database_handler.py`)

Add three `CREATE TABLE IF NOT EXISTS` statements (mirror source exactly):

```python
self.cursor.execute("""
    CREATE TABLE IF NOT EXISTS series(
       guild_id INT,
       name TEXT,
       season INT,
       game TEXT,
       pinned_channel TEXT,
       timestamp DATETIME DEFAULT CURRENT_TIMESTAMP);
""")
self.cursor.execute("""
    CREATE TABLE IF NOT EXISTS multibrackets(
       name TEXT,
       timestamp DATETIME DEFAULT CURRENT_TIMESTAMP);
""")
self.cursor.execute("""
    CREATE TABLE IF NOT EXISTS tourneys(
       multibracket_id INT,
       series_id INT,
       series_ctr INT,
       timestamp DATETIME DEFAULT CURRENT_TIMESTAMP);
""")
self.connection.commit()
```

## `axi/tournament.py` minimal additions

```python
class Tournament:
    def __init__(self, title, scope, series=None, seed=None,
                 series_id=None, multibracket_id=None):
        ...
        # If `series` is a Series instance, derive series_id from it.
        if hasattr(series, "rowid"):
            self.series_id = series.rowid
            self.series = series  # keep instance ref for handler access
        else:
            self.series_id = series_id
            self.series = None
        self.multibracket_id = multibracket_id
        self.series_ctr = None  # set by series_handler.register_tournament
```

Backward compat: existing `series=` kwarg (which was unused in tests)
keeps working; new kwargs default to None.

## Test plan

`tests/test_series.py`:
- `Series` constructs with all 5 fields + None rowid.
- `Series.get_db_entry()` returns the 5-tuple in source's column order.
- `Multibracket` constructs with name + None rowid.
- `Multibracket.get_db_entry()` returns `(name,)`.
- Multi-game `Series(game=["rps", "smash"])` → comma-joined in
  `get_db_entry()`.

`tests/test_series_handler.py`:
- `create_series(...)` returns a Series with `rowid` set, registered
  in `state.series_by_id`.
- `create_multibracket(...)` returns a Multibracket with `rowid` set,
  registered in `state.multibrackets_by_id`.
- `set_series_for_scope` + `get_series_for_scope` round-trip.
- `get_series_ctr` returns `len(tourneys with series_id) + 1`.
- `register_tournament` inserts a tourneys row, sets `series_ctr` on
  the Tournament, sets `multibracket_id`.
- Reset clears all state without DB writes.

Existing `Tournament` tests should not break.

## Major decisions

### A. Pure data classes, no Discord refs

`Series` stores `guild_id` (int), not a `Guild` object. `pinned_channel`
is a string, not a channel object. Keeps the layer pure.

### B. Scope→series mapping in `series_handler` state, not on
`tournament_state`

`tournament_state` is for active tournaments. `series_handler.state` is
for the long-lived series registry. They're separate concerns.

### C. `series_ctr` auto-counted from `tourneys` table

`get_series_ctr(series_id)` returns `count(tourneys.series_id == sid) + 1`.
This matches source. No explicit counter column needed; the count
of past tourneys IS the next index.

### D. `Tournament` doesn't auto-register

Calling `register_tournament(tournament, multibracket_id)` is
explicit — happens when Phase 14's `/create` command (or Phase 13's
PXL `createfromconfig`) wires the new tournament into a series.
This keeps Phase 8 a pure data layer; orchestration is later phases.

### E. `multibracket_id` nullable

A solo tournament (not part of a multi-game event) has
`multibracket_id = None`. Source treats this as 0 or NULL; we use
Python `None` and store `NULL` in DB. Compatible with source's
implicit nullability since the column has no NOT NULL constraint.

### F. Backward-compat for existing `Tournament(series=None)` kwarg

Existing tests/callers pass `series=None`. New code that needs DB
linkage passes a Series instance (preferred) or `series_id=int`.
Both paths converge to setting `self.series_id`.

## What's deferred

- **Phase 13 PXL config** wires `createfromconfig` to call
  `create_series` + `create_multibracket` + `Tournament(...)` +
  `register_tournament(...)`.
- **Phase 14 Discord commands** (`/createseries`, `/createmultibracket`,
  `/setseries`) wrap the handler API.
- **Series → Tournament listing UI** (Phase 15 visualization). Phase 8
  exposes `state.scope_to_series` + the DB tables; rendering is
  Phase 15.
- **Cross-episode standings aggregation** (e.g. "all-time series
  rankings"). Out of scope.
- **Editing / deleting Series + Multibracket** post-creation. Phase 8
  is insert-only; updates land in a later cleanup pass if needed.

## Resolved questions

1. **What's "scope" in `scope_to_series`?** Discord channel name (str),
   matching the convention used elsewhere (`tournament.scope`,
   `Ladder.queue_channel`).

2. **Can one scope have multiple series simultaneously?** No. The map
   is 1:1. `set_series_for_scope` overwrites.

3. **Are Series and Multibracket DB-persistent?** Yes — both create
   rows on construction via the handler. Pure data classes are fine
   without DB IDs; the handler is the persistence layer.

4. **`game` field on Series — string or list?** Stored as comma-joined
   string. Constructor accepts either (mirrors source's
   `Series.__init__`).

5. **What's `pinned_channel` for?** Where series-wide messages (final
   standings, season summaries) post. Stored as channel name string.
   No Discord coupling at this layer.

6. **DB tables created when?** On `database_handler` init (alongside
   existing tables). Idempotent `IF NOT EXISTS`.

7. **Are the existing `tourney_checkpoints` / `tourney_player_states`
   tables related?** Phase 10 (checkpoint/undo) handles those. Phase 8
   is just series + multibracket + tourneys.
