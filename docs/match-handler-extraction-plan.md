# Plan: match_handler Extraction from Discord I/O

## Problem

`match_handler.py` is now functionally pure (all functions sync, return `list[Effect]`),
but it cannot be imported without Discord installed because of this chain:

```
match_handler (line 9) → axi.axi (line 3) → discord_handler → discord
```

match_handler only uses two things from `axi.axi`:
- `axi.dm_games` — dict mapping game names to DM game classes (lines 20, 21, 44)
- `axi.thread_games` — dict mapping game names to thread game config dicts (lines 31, 32)

## Solution: Create `axi/registry.py`

Extract the game registries into a new module with zero Discord dependency.

### New file: `axi/registry.py`

```python
dm_games = dict()
thread_games = dict()
```

That's it. Two dicts, no imports.

### Changes

| File | Change |
|---|---|
| `axi/registry.py` | **New.** Contains `dm_games` and `thread_games` dicts. |
| `axi/handlers/match_handler.py` | Line 9: `import axi.axi as axi` → `import axi.registry as registry`. Update 5 references: `axi.dm_games` → `registry.dm_games`, `axi.thread_games` → `registry.thread_games`. |
| `axi/axi.py` | Import from `axi.registry` instead of defining dicts locally. `add_dm_game` and `add_thread_game` stay here (they call `database_handler.add_game` and are only used by the entry point). Replace `dm_games = dict()` / `thread_games = dict()` with imports from registry. |
| `axi/handlers/discord_handler.py` | Line 17: `import axi.axi as axi` → `import axi.registry as registry`. Update ~10 references from `axi.dm_games`/`axi.thread_games` to `registry.dm_games`/`registry.thread_games`. |
| `tests/conftest.py` | Line 53: `import axi.axi as axi` → `import axi.registry as registry`. Fixture writes to `registry.dm_games`/`registry.thread_games`. |
| `tests/test_match_handler.py` | Line 7: same change. |

### Files NOT changed

- `example_main.py` — Still imports `add_dm_game`, `add_thread_game`, `run` from `axi.axi`. This is the entry point; Discord dependency is expected.
- `examples/wonder_wand/` — Imports `load_profile`/`save_profile` from `axi.axi`. Separate concern (profile functions), not in scope for this card.
- `axi/handlers/ladder_handler.py` — Already clean; does not import `axi.axi`.

### Verification

After the change, this import should work without Discord:
```python
import axi.handlers.match_handler as match_handler
```

The existing 52 tests should continue to pass unchanged (just with cleaner imports).

### Risk

Minimal. The only semantic change is where the dicts live in memory.
`axi.axi` will re-export them (or import and use them), so `example_main.py` and
wonder_wand code that accesses `axi.axi.dm_games` still works.
