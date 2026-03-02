# Plan: ladder_handler Extraction from Discord I/O

## Current State

`ladder_handler.py` is already *mostly* pure:
- Core matchmaking (`matchmaking`, `generate_pairing_hypothesis`, `score_hypothesis`) — pure computation
- `update_ladders()`, `call_matches()`, `push_ladder_updates()` — return effects
- Database operations (`add_to_db`, `update_ratings_db`, `load_from_ratings_db`) — SQLite only, not Discord

**Remaining Discord coupling**: `user_handler` import (7 functions call `user_handler.get_user(guild, caller)` to resolve raw Discord users to AxiUser objects).

## Strategy: Push User Resolution to discord_handler

The pattern: discord_handler resolves all user references *before* calling ladder_handler. Then ladder_handler receives AxiUser objects directly and drops the user_handler import.

### Functions to change

| Function | Current params | New params | discord_handler resolves |
|---|---|---|---|
| `queue` | `(caller, guild, channel)` | `(user, guild, channel)` | `caller` → `user` |
| `dequeue` | `(caller, guild, channel)` | `(user, guild, channel)` | `caller` → `user` |
| `autoqueue` | `(caller, guild, channel, mode)` | `(user, guild, channel, mode)` | `caller` → `user` |
| `status` | `(caller, guild, channel)` | `(user, guild, channel)` | `caller` → `user` |
| `history` | `(caller, guild, channel)` | `(user, guild, channel)` | `caller` → `user` |
| `set_streamer` | `(guild, channel, username)` | `(guild, channel, user)` | `username` → `user` |
| `challenge` | `(caller, guild, channel, opponent)` | `(user, guild, channel, opponent)` | `caller` → `user`, `opponent` → `opp` |

Note: `challenge` internally calls `user_handler.get_user(guild, opponent)` to resolve the opponent string, AND also calls `queue(caller, guild, channel)` recursively. After the change, it will call `queue(user, guild, channel)` — but it also calls `queue(opponent, guild, channel)` where `opponent` is the *raw* string. So discord_handler must resolve both users and pass them in. The recursive `queue()` call inside `challenge()` will use the already-resolved user objects.

### Additional cleanup

1. **Remove dead import**: `from axi.thread_game import ThreadGame` in ladder_handler.py (unused)
2. **Remove dead import**: `sleep` from `from time import time, sleep` in ladder_handler.py (unused)
3. **Remove dead import**: `import axi.handlers.discord_handler as discord_handler` in ladder.py (imported but never used)

### Files changed

| File | Change |
|---|---|
| `axi/handlers/ladder_handler.py` | Remove `user_handler` import. Remove dead `ThreadGame` and `sleep` imports. Change 7 function signatures to accept resolved AxiUser instead of raw Discord caller. |
| `axi/handlers/discord_handler.py` | Add `user_handler.get_user()` calls before each ladder_handler call. ~7 call sites. |
| `axi/ladder.py` | Remove dead `discord_handler` import. |

### Out of scope

- **Circular `ladder.py ↔ ladder_handler.py` dependency**: ladder.py calls `ladder_handler.update_ratings_db()` and `ladder_handler.load_from_ratings_db()`. This works via Python late binding but is architecturally messy. Separate concern from Discord extraction.
- **Database I/O in ladder_handler**: `add_to_db`, `update_ratings_db`, `load_from_ratings_db` are SQLite operations. Not Discord-related, so acceptable for this card.

### Verification

After the change:
- `ladder_handler.py` should have zero Discord-related imports
- All existing tests pass
- ladder_handler functions receive AxiUser objects (same type as before, just resolved earlier)
