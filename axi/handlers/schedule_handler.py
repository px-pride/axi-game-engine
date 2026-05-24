import asyncio
import json
from bisect import insort
import random
import time
import copy

scheduled_events = []
scheduled_times = dict()
scheduled_keys = dict()
scheduled_tasks = dict()

# Phase 11: callback registry for persistent scheduling.
# Modules register their callbacks at import time via register_callback().
_registered_callbacks = {}


def register_callback(name, fn):
    """Register a callable under `name` so schedule_event_persistent can
    resolve it by string at fire time. Modules call this at import-time.

    `fn` must be an async callable accepting **kwargs matching the
    callback_args dict that gets persisted.
    """
    _registered_callbacks[name] = fn


def get_callback(name):
    return _registered_callbacks.get(name)


def _list_registered_callbacks():
    """Test helper — returns list of registered callback names."""
    return list(_registered_callbacks.keys())

async def schedule_event(timer, event, keys=None, suffix=None):
    already_scheduled = True
    if keys:
        for k_ in keys:
            k = (k_, suffix) if suffix else k_
            if k not in scheduled_keys:
                scheduled_keys[k] = (timer, event)
                already_scheduled = False
    if not (keys and already_scheduled):
        while timer in scheduled_times:
            timer += 0.01 * random.random()
        pair = (timer, event)
        scheduled_times[timer] = event
        insort(scheduled_events, pair)
        duration = timer - time.time()
        if duration < 0:
            return
        async def event_as_task():
            await asyncio.sleep(duration)
            await event()
            scheduled_events.remove(pair)
            del scheduled_times[timer]
        task = asyncio.create_task(event_as_task())
        if keys:
            for k_ in keys:
                k = (k_, suffix) if suffix else k_
                scheduled_tasks[k] = task

async def schedule_event_sequence(timers, events):
    async def e(x, timers, events, j):
        y = await events[j](x)
        if j + 1 < len(timers):
            await schedule_event(
                timers[j+1], lambda: e(y, timers, events, j+1))
        return y
    await schedule_event(
        timers[0], lambda: e(None, timers, events, 0))

async def unschedule(k):
    for k_ in copy.copy(list(scheduled_keys.keys())):
        if k_ == k or (isinstance(k_, tuple) and k_[0] == k):
            del scheduled_keys[k_]


# ---------------------------------------------------------------------------
# Phase 11: DB-backed scheduler persistence
# ---------------------------------------------------------------------------


async def schedule_event_persistent(fire_at, callback_name, kwargs=None,
                                    keys=None, suffix=None):
    """Persist a timer event to DB and schedule it in-memory.

    On fire: invokes the registered callback by name with the saved
    kwargs, then deletes the DB row (whether the callback succeeded
    or not).

    Returns the rowid of the inserted scheduled_callbacks row.
    """
    import axi.handlers.database_handler as db

    kwargs = kwargs or {}
    rowid = db.add_entry("scheduled_callbacks", (
        fire_at,
        callback_name,
        json.dumps(kwargs),
        json.dumps(list(keys)) if keys else None,
        suffix,
    ))

    async def _on_fire(rid=rowid, name=callback_name, args=kwargs):
        cb = get_callback(name)
        try:
            if cb is not None:
                result = cb(**args)
                if asyncio.iscoroutine(result):
                    await result
        finally:
            try:
                db.cursor.execute(
                    "DELETE FROM scheduled_callbacks WHERE rowid=?", (rid,))
                db.connection.commit()
            except Exception:
                pass

    await schedule_event(fire_at, _on_fire, keys=keys, suffix=suffix)
    return rowid


def register_startup_callback(callback_name, kwargs=None, guild_id=None):
    """Persist a startup-replay event. Invoked once when
    startup_replay() runs (typically on bot ready)."""
    import axi.handlers.database_handler as db
    kwargs = kwargs or {}
    return db.add_entry("startup_callbacks", (
        callback_name,
        json.dumps(kwargs),
        guild_id,
    ))


async def startup_replay():
    """Replay persisted scheduler state. Called on bot startup.

    1. Reads scheduled_callbacks: drops expired (fire_at < now), re-
       schedules future events in-memory.
    2. Reads startup_callbacks: invokes each callback by name, then
       deletes the row.
    """
    import axi.handlers.database_handler as db

    now = time.time()
    # Re-schedule pending events.
    rows = db.cursor.execute(
        "SELECT rowid, fire_at, callback_name, kwargs_json, keys_json, suffix "
        "FROM scheduled_callbacks"
    ).fetchall()
    for row in rows:
        rowid, fire_at, name, args_str, keys_str, suffix = row
        args = json.loads(args_str) if args_str else {}
        keys = json.loads(keys_str) if keys_str else None

        if fire_at < now:
            # Expired — drop row, don't replay.
            db.cursor.execute(
                "DELETE FROM scheduled_callbacks WHERE rowid=?", (rowid,))
            db.connection.commit()
            continue

        cb = get_callback(name)
        if cb is None:
            # Unregistered callback — drop row to avoid stale entries.
            db.cursor.execute(
                "DELETE FROM scheduled_callbacks WHERE rowid=?", (rowid,))
            db.connection.commit()
            continue

        async def _on_fire(rid=rowid, n=name, a=args):
            cb_inner = get_callback(n)
            try:
                if cb_inner is not None:
                    result = cb_inner(**a)
                    if asyncio.iscoroutine(result):
                        await result
            finally:
                try:
                    db.cursor.execute(
                        "DELETE FROM scheduled_callbacks WHERE rowid=?",
                        (rid,))
                    db.connection.commit()
                except Exception:
                    pass

        await schedule_event(fire_at, _on_fire, keys=keys, suffix=suffix)

    # Invoke startup callbacks (no scheduling).
    rows = db.cursor.execute(
        "SELECT rowid, callback_name, kwargs_json, guild_id FROM startup_callbacks"
    ).fetchall()
    for rowid, name, args_str, guild_id in rows:
        args = json.loads(args_str) if args_str else {}
        if guild_id is not None and "guild_id" not in args:
            args["guild_id"] = guild_id
        cb = get_callback(name)
        try:
            if cb is not None:
                result = cb(**args)
                if asyncio.iscoroutine(result):
                    await result
        finally:
            try:
                db.cursor.execute(
                    "DELETE FROM startup_callbacks WHERE rowid=?", (rowid,))
                db.connection.commit()
            except Exception:
                pass


async def unschedule_persistent(callback_name, keys=None):
    """Remove a persisted event from DB and cancel its in-memory task.

    Matches by callback_name and (if supplied) any of the given keys.
    """
    import axi.handlers.database_handler as db

    if keys:
        for k in keys:
            await unschedule(k)
    # Delete matching DB rows.
    if keys:
        keys_str = json.dumps(list(keys))
        db.cursor.execute(
            "DELETE FROM scheduled_callbacks WHERE callback_name=? AND keys_json=?",
            (callback_name, keys_str))
    else:
        db.cursor.execute(
            "DELETE FROM scheduled_callbacks WHERE callback_name=?",
            (callback_name,))
    db.connection.commit()

