# Phase 11: DB-backed scheduler persistence

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 11.

Makes the in-memory scheduler durable: a bot restart at 7:50pm must
not drop the 8pm check-in reminder. Phase 11 improves on source's
brittle command-string parsing — events are stored as
**structured `(callback_name, kwargs_json)` pairs** with a callback
registry that resolves names at replay time.

## Scope

- 2 new DB tables in `axi/handlers/database_handler.py`:
  - `scheduled_callbacks (fire_at REAL, callback_name TEXT,
    callback_args TEXT, keys_str TEXT, suffix TEXT, timestamp)` — one
    row per pending timer event.
  - `startup_callbacks (callback_name TEXT, callback_args TEXT,
    timestamp)` — replay-on-restart events.
- `axi/handlers/schedule_handler.py` extensions:
  - **Callback registry**: `register_callback(name, fn)` + dict
    `_registered_callbacks`. Modules register their callbacks at
    import time.
  - `schedule_event_persistent(fire_at, callback_name, callback_args,
    keys=None, suffix=None)` — saves to DB AND schedules in-memory.
    On fire: invoke callback, delete the DB row.
  - `register_startup_callback(callback_name, callback_args)` — saves
    to startup_callbacks table.
  - `startup_replay()` — reads scheduled_callbacks (drops expired,
    re-schedules future), reads startup_callbacks (invokes each).
    Called by bot startup.
- `axi/effects.py`: `ScheduleCallback` already exists from Phase 9.
  Extend its dispatch in `discord_handler.execute_effects` to call
  `schedule_event_persistent` instead of in-memory `schedule_event`
  when the effect has a flag `persist=True` (default False for
  backward compat).
- Wire existing scheduled callbacks (Phase 9 `resolve_checkins`,
  Phase 14 future) through the registry.

## Files

| File | Change |
|---|---|
| `axi/handlers/database_handler.py` | 2 new CREATE TABLE statements. |
| `axi/handlers/schedule_handler.py` | Callback registry + `schedule_event_persistent` + `register_startup_callback` + `startup_replay`. |
| `axi/effects.py` | Add `persist: bool = False` field to `ScheduleCallback`. |
| `axi/handlers/discord_handler.py` | Pre-register existing callbacks (e.g. `resolve_checkins`); when `effect.persist` is True, route through `schedule_event_persistent`. Call `startup_replay()` on bot ready event. |
| `tests/test_db_scheduler.py` (NEW) | persistence + restart simulation + callback registry tests. |

## Source ↔ target diff

Source (`axi_backend.py:56–76` + `database_manager.py:143–159`):
- 2 tables (`startup_commands`, `timer_commands`) with `command_str
  TEXT` columns.
- Replay parses the string back into a command via
  `parse_and_run_command(cmd, caller, guild, channel)`.

Target improvement:
- Replace string parsing with structured callbacks:
  `(callback_name TEXT, callback_args TEXT JSON)`. On replay, look up
  the function in `_registered_callbacks[callback_name]`, parse args
  as JSON, invoke. No grammar/parser layer.
- Why: command-string parsing breaks when command syntax changes
  (e.g. new args, renamed flags). Structured callbacks survive any
  grammar evolution since each is independently registered.

## Schema

```sql
CREATE TABLE IF NOT EXISTS scheduled_callbacks(
   fire_at REAL,
   callback_name TEXT,
   callback_args TEXT,        -- JSON-encoded kwargs dict
   keys_str TEXT,             -- JSON-encoded list of keys (optional)
   suffix TEXT,               -- optional dedup suffix
   timestamp DATETIME DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS startup_callbacks(
   callback_name TEXT,
   callback_args TEXT,        -- JSON-encoded kwargs dict
   timestamp DATETIME DEFAULT CURRENT_TIMESTAMP);
```

## Callback registry

```python
# In axi/handlers/schedule_handler.py

_registered_callbacks = {}  # name → async callable

def register_callback(name, fn):
    """Modules register their persistable callbacks at import time.

    `fn` must accept **kwargs matching the JSON args dict. It is
    typically async.

    Example (from discord_handler):
        from axi.handlers import schedule_handler, match_handler

        async def resolve_checkins_cb(match_id):
            match = match_handler.state.matches_by_id.get(match_id)
            if match:
                return match_handler.resolve_checkins(match)
            return []

        schedule_handler.register_callback(
            "resolve_checkins", resolve_checkins_cb)
    """
    _registered_callbacks[name] = fn

def get_callback(name):
    return _registered_callbacks.get(name)
```

## `schedule_event_persistent`

```python
async def schedule_event_persistent(
        fire_at, callback_name, callback_args=None,
        keys=None, suffix=None):
    """Persist + schedule a single-fire event.

    Inserts a row in scheduled_callbacks, then schedules in-memory.
    On fire, invokes the callback and deletes the row.
    """
    import json
    import axi.handlers.database_handler as db
    callback_args = callback_args or {}
    rowid = db.add_entry("scheduled_callbacks", (
        fire_at,
        callback_name,
        json.dumps(callback_args),
        json.dumps(list(keys)) if keys else None,
        suffix,
    ))
    async def _on_fire():
        cb = get_callback(callback_name)
        if cb is None:
            return
        try:
            await cb(**callback_args)
        finally:
            # Delete the row whether the callback succeeded or not.
            db.cursor.execute(
                "DELETE FROM scheduled_callbacks WHERE rowid=?",
                (rowid,))
            db.connection.commit()
    await schedule_event(fire_at, _on_fire, keys=keys, suffix=suffix)
    return rowid
```

## `startup_replay`

```python
async def startup_replay():
    """Read scheduled_callbacks + startup_callbacks, replay each.

    Called by the bot's on_ready event. Expired scheduled_callbacks
    (fire_at < now()) are dropped from DB; future ones are
    re-scheduled in-memory.
    """
    import json
    import time
    import axi.handlers.database_handler as db
    now = time.time()
    # Re-schedule pending events.
    rows = db.cursor.execute(
        "SELECT rowid, fire_at, callback_name, callback_args, "
        "keys_str, suffix FROM scheduled_callbacks"
    ).fetchall()
    for row in rows:
        rowid, fire_at, name, args_str, keys_str, suffix = row
        args = json.loads(args_str) if args_str else {}
        keys = json.loads(keys_str) if keys_str else None
        if fire_at < now:
            # Expired — drop the row, don't replay.
            db.cursor.execute(
                "DELETE FROM scheduled_callbacks WHERE rowid=?", (rowid,))
            db.connection.commit()
            continue
        cb = get_callback(name)
        if cb is None:
            continue  # Callback not registered; skip (warn?).
        # Re-schedule with the same wrapper as schedule_event_persistent.
        async def _on_fire(rid=rowid, n=name, a=args):
            cb = get_callback(n)
            if cb:
                try:
                    await cb(**a)
                finally:
                    db.cursor.execute(
                        "DELETE FROM scheduled_callbacks WHERE rowid=?",
                        (rid,))
                    db.connection.commit()
        await schedule_event(fire_at, _on_fire, keys=keys, suffix=suffix)
    # Invoke startup callbacks (no future scheduling).
    rows = db.cursor.execute(
        "SELECT rowid, callback_name, callback_args FROM startup_callbacks"
    ).fetchall()
    for rowid, name, args_str in rows:
        args = json.loads(args_str) if args_str else {}
        cb = get_callback(name)
        if cb is not None:
            try:
                await cb(**args)
            finally:
                db.cursor.execute(
                    "DELETE FROM startup_callbacks WHERE rowid=?", (rowid,))
                db.connection.commit()
```

## ScheduleCallback effect extension

```python
@dataclass
class ScheduleCallback:
    delay_seconds: float
    callback_name: str
    callback_args: dict = field(default_factory=dict)
    keys: list = None
    suffix: str = None
    persist: bool = False    # Phase 11: True → persist to DB
```

`discord_handler.execute_effects` dispatch:

```python
elif isinstance(effect, ScheduleCallback):
    ...
    if effect.persist:
        await schedule_handler.schedule_event_persistent(
            time() + effect.delay_seconds,
            effect.callback_name,
            effect.callback_args,
            keys=effect.keys,
            suffix=effect.suffix,
        )
    else:
        # existing in-memory schedule_event path
        ...
```

## Bot startup wiring

In `discord_handler` on the bot's `on_ready` (existing event):

```python
@bot.event
async def on_ready():
    ...existing...
    # Phase 11: replay persisted scheduler state.
    await schedule_handler.startup_replay()
```

Plus all callbacks need to be registered at import time:

```python
# axi/handlers/discord_handler.py — module init
schedule_handler.register_callback(
    "resolve_checkins", _resolve_checkins_cb)
schedule_handler.register_callback(
    "checkin_reminder", _checkin_reminder_cb)
# ...
```

## Test plan

`tests/test_db_scheduler.py`:

1. **`TestSchemaTables`** — both tables exist with expected columns.

2. **`TestCallbackRegistry`** — `register_callback(name, fn)` stores;
   `get_callback(name)` retrieves; unknown name returns None;
   re-register overrides.

3. **`TestSchedulePersistent`** — `schedule_event_persistent` inserts
   a row with correct fire_at/name/args; in-memory schedule_event
   also fired. (Use `asyncio.run` + a near-future fire_at.)

4. **`TestExpiredDropOnReplay`** — write a row with `fire_at` in the
   past; call `startup_replay`; verify the row was deleted from DB
   and the callback was NOT invoked.

5. **`TestFutureReplayInvokes`** — write a row with `fire_at` 0.1s
   ahead; call `startup_replay`; wait 0.2s; verify the callback was
   invoked and the row deleted.

6. **`TestStartupCallbackReplay`** — register a startup callback;
   call `startup_replay`; verify the callback was invoked and the
   row deleted.

7. **`TestMissingCallbackName`** — write a row referencing an
   unregistered callback name; call `startup_replay`; verify the
   row stays (or is dropped — pick one, document) and no crash.

8. **`TestScheduleCallbackEffectPersist`** — `ScheduleCallback(...
   persist=True)` triggers the persistent path; `persist=False`
   uses the existing in-memory path.

## Major decisions

### A. Structured callbacks + registry (vs source's command strings)

Already locked by the card: "IMPROVE on source: store STRUCTURED
event specs (callback_name + kwargs_json), NOT raw command strings."

### B. JSON for callback_args (vs pickle / repr / source's brittle TEXT)

JSON is the obvious choice — survives Python version changes, easy
to debug. Limit: only JSON-serializable types in callback_args.
Discord objects (Guild, Channel, User) must be passed as IDs and
re-resolved inside the callback.

### C. Auto-cleanup on fire

When a callback fires, its row is deleted (whether success or
failure). Avoids unbounded DB growth from expired events.

### D. Expired-on-replay = drop, don't invoke

If a scheduled event is past `fire_at` at restart time (e.g. bot was
down across the fire time), Phase 11 DROPS the event rather than
firing late. Why: late firing can cause double-execution if other
mechanisms already triggered, and most scheduler-fired events are
time-sensitive (check-in reminders that are already irrelevant).

Phase 14 may add a `late_fire_grace_seconds` flag if specific
callbacks need to handle late firing (e.g. tournament begin).

### E. Missing callback on replay → skip, drop row

If a row references an unregistered callback name (e.g. extension
unloaded), drop the row and continue. Logging recommended but
defer to Phase 11+ if a logger lands.

### F. Single writer assumption

The DB writes assume one bot process. Multi-process scheduling would
need row-level locking — out of scope.

### G. `ScheduleCallback.persist` defaults to False

Backward compat with Phase 9 / earlier callsites. Phase 11 callsites
opt in to persistence per-event.

## Test environment caveat

Most scheduler tests need async event loops. The existing pytest
suite doesn't use `pytest-asyncio` for prior phases (effects are
tested via direct emission, not by awaiting `schedule_event`).
Phase 11 tests use `asyncio.run` directly inside test methods for
async paths, avoiding a new fixture dependency. Pass `keys=None` and
`suffix=None` for tests that don't exercise dedup.

## Resolved questions

1. **What format is `fire_at`?** Unix timestamp (float seconds since
   epoch). Matches `time.time()`.

2. **What's `keys_str`?** JSON-encoded list of dedup keys, same
   semantics as `schedule_event`'s `keys` param. Optional.

3. **What happens if the same `fire_at` is scheduled twice with the
   same keys?** Source/target both already dedup via
   `scheduled_keys`. Phase 11 adds DB persistence — the second
   `schedule_event_persistent` call still writes a new row (dedup
   is in-memory only). On replay, both rows would re-schedule;
   the in-memory dedup catches the second one and skips.
   Acceptable for Phase 11; cleanup pass later if needed.

4. **Should `startup_replay` be sync or async?** Async — it `await`s
   `schedule_event` (which is async). Called from the bot's
   `on_ready` event handler (also async).

5. **What about callbacks that need a guild/channel reference?**
   Pass `guild_id` / `channel_name` in callback_args; the callback
   re-resolves them via `bot.get_guild(...)` / `discord.utils.get`.

## What's deferred

- **Late-fire grace** — per-callback flag for "fire even if late by
  N seconds." Phase 14 if needed.
- **Logging / observability** — when callbacks fail or names are
  unknown.
- **Multi-process locking** — not in scope.
- **Bulk schedule for high-frequency callbacks** — not needed for
  tournament cadence.
- **Cleanup of orphaned rows** (e.g. a bug leaves rows un-deleted) —
  manual SQL for now; Phase 14 admin command later.
