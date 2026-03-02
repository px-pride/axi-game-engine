# Plan: Consolidate Global Mutable State into Service Objects

## Current State

21 module-level mutable variables spread across 7 modules. The effects refactor already
separated I/O from logic, but state ownership is still implicit — each module "owns" its
global dicts, and cleanup happens via external knowledge of what to clear.

## Assessment

**Already good enough:**
- `registry.py` (dm_games, thread_games) — simple registries, rarely mutated
- `database_handler.py` (connection, cursor) — single DB connection, fine as module globals
- `discord_handler.py` adapter state — only used by the adapter, never touched by pure code
- `user_handler.py` cache — simple key-value cache

**Worth consolidating:**
- `match_handler.py` — 3 tightly coupled dicts that must be kept in sync (users_to_dm_matches,
  users_to_thread_matches, matches_by_id). All match lifecycle functions operate on this state.
- `ladder_handler.py` — 7+ variables that track active ladders and streaming. The `death_row`
  dict appears unused. `event_name` is set but barely used.

## Plan

### 1. MatchState dataclass (match_handler.py)

Group the 3 match tracking dicts into a single object:

```python
class MatchState:
    def __init__(self):
        self.users_to_dm_matches = dict()
        self.users_to_thread_matches = dict()
        self.matches_by_id = dict()

state = MatchState()
```

All functions in match_handler access `state.users_to_dm_matches` instead of the bare global.
External code (discord_handler, tests) accesses `match_handler.state.users_to_dm_matches`.

Benefits:
- Single `state = MatchState()` to reset in tests instead of clearing 3 dicts
- Makes state ownership explicit
- Enables future dependency injection if needed

### 2. LadderState dataclass (ladder_handler.py)

Group ladder tracking state:

```python
class LadderState:
    def __init__(self):
        self.ladders = dict()           # (guild, scope) → Ladder
        self.ladders_by_id = dict()     # id(ladder) → Ladder
        self.streamers = dict()         # Ladder → user
        self.stream_pairs = dict()      # Ladder → current pair
        self.stream_history = dict()    # Ladder → history list
        self.downtime_minimum = 20

state = LadderState()
```

Also: remove `death_row` (unused) and `event_name` (barely used, only in `get_db_entry()`).

### 3. Update tests

The conftest `_clean_match_state` fixture becomes:
```python
match_handler.state = MatchState()
```

### Files changed

| File | Change |
|---|---|
| `axi/handlers/match_handler.py` | Add MatchState class. Replace bare globals with `state.xxx`. |
| `axi/handlers/ladder_handler.py` | Add LadderState class. Replace bare globals with `state.xxx`. Remove `death_row` and `event_name`. |
| `axi/handlers/discord_handler.py` | Update references: `match_handler.users_to_dm_matches` → `match_handler.state.users_to_dm_matches`, etc. Same for ladder_handler references. |
| `tests/conftest.py` | Simplify cleanup fixture. |
| `tests/test_match_handler.py` | Update references if any directly access the dicts. |

### NOT changed

- `registry.py`, `database_handler.py`, `user_handler.py`, `schedule_handler.py` — state is
  already well-scoped or trivial. Consolidating these adds complexity without meaningful benefit.
- `discord_handler.py` adapter state — stays as module globals (only the adapter touches it).

### Risk

Low. The change is mechanical (wrap globals in a class, update references). Zero behavioral change.
