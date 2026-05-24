"""Phase 11 tests — DB-backed scheduler persistence.

Tests verify the callback registry, schedule_event_persistent +
DB row insertion + auto-cleanup on fire, startup_replay's drop-expired
behavior, and persistence across simulated restarts.

Uses asyncio.run for async paths (no pytest-asyncio dependency).
"""

import asyncio
import json
import time

import pytest

import axi.handlers.database_handler as db
import axi.handlers.schedule_handler as sh


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_scheduler_tables():
    db.cursor.execute("DELETE FROM scheduled_callbacks")
    db.cursor.execute("DELETE FROM startup_callbacks")
    db.connection.commit()


def _clean_inmemory():
    sh.scheduled_events.clear()
    sh.scheduled_times.clear()
    sh.scheduled_keys.clear()
    sh.scheduled_tasks.clear()


@pytest.fixture(autouse=True)
def _clean_state():
    _clean_scheduler_tables()
    _clean_inmemory()
    yield
    _clean_scheduler_tables()
    _clean_inmemory()


# ---------------------------------------------------------------------------
# Schema tables
# ---------------------------------------------------------------------------


class TestSchemaTables:
    def test_scheduled_callbacks_table_exists(self):
        cols = db.get_column_names("scheduled_callbacks")
        assert "fire_at" in cols
        assert "callback_name" in cols
        assert "kwargs_json" in cols
        assert "keys_json" in cols
        assert "suffix" in cols

    def test_startup_callbacks_table_exists(self):
        cols = db.get_column_names("startup_callbacks")
        assert "callback_name" in cols
        assert "kwargs_json" in cols
        assert "guild_id" in cols


# ---------------------------------------------------------------------------
# Callback registry
# ---------------------------------------------------------------------------


class TestCallbackRegistry:
    def test_register_and_get(self):
        async def my_cb(x):
            return x * 2
        sh.register_callback("test_get", my_cb)
        assert sh.get_callback("test_get") is my_cb

    def test_get_unknown_returns_none(self):
        assert sh.get_callback("nonexistent_xyz") is None

    def test_re_register_overrides(self):
        async def cb1():
            return 1
        async def cb2():
            return 2
        sh.register_callback("test_override", cb1)
        sh.register_callback("test_override", cb2)
        assert sh.get_callback("test_override") is cb2


# ---------------------------------------------------------------------------
# schedule_event_persistent inserts a row
# ---------------------------------------------------------------------------


class TestSchedulePersistent:
    def test_inserts_db_row(self):
        async def cb(x=None):
            return x
        sh.register_callback("persist_insert", cb)

        async def run():
            return await sh.schedule_event_persistent(
                time.time() + 60,  # 60s in the future
                "persist_insert",
                kwargs={"x": 42},
            )
        rowid = asyncio.run(run())
        assert rowid is not None
        row = db.load_entry("scheduled_callbacks", rowid)
        assert row is not None
        assert row[1] == "persist_insert"  # callback_name
        assert json.loads(row[2]) == {"x": 42}

    def test_persists_keys(self):
        async def cb():
            return None
        sh.register_callback("persist_keys", cb)

        async def run():
            return await sh.schedule_event_persistent(
                time.time() + 60, "persist_keys",
                keys=["key1", "key2"],
            )
        rowid = asyncio.run(run())
        row = db.load_entry("scheduled_callbacks", rowid)
        assert json.loads(row[3]) == ["key1", "key2"]  # keys_json column

    def test_persists_suffix(self):
        async def cb():
            return None
        sh.register_callback("persist_suffix", cb)

        async def run():
            return await sh.schedule_event_persistent(
                time.time() + 60, "persist_suffix",
                keys=["a"], suffix="checkin",
            )
        rowid = asyncio.run(run())
        row = db.load_entry("scheduled_callbacks", rowid)
        assert row[4] == "checkin"  # suffix column


# ---------------------------------------------------------------------------
# startup_replay
# ---------------------------------------------------------------------------


class TestStartupReplay:
    def test_expired_dropped(self):
        # Write a row with fire_at in the past.
        db.add_entry("scheduled_callbacks", (
            time.time() - 100,  # 100s ago
            "expired_test",
            json.dumps({}),
            None,
            None,
        ))
        # Register the callback so name resolution succeeds (won't fire).
        invoked = []
        async def cb():
            invoked.append(True)
        sh.register_callback("expired_test", cb)

        asyncio.run(sh.startup_replay())
        # Expired row dropped — no remaining rows.
        rows = db.cursor.execute(
            "SELECT * FROM scheduled_callbacks WHERE callback_name=?",
            ("expired_test",)
        ).fetchall()
        assert rows == []
        # Callback was NOT invoked.
        assert invoked == []

    def test_future_rescheduled(self):
        # Write a row with fire_at slightly in the future.
        db.add_entry("scheduled_callbacks", (
            time.time() + 60,  # 60s ahead
            "future_test",
            json.dumps({}),
            None,
            None,
        ))
        invoked = []
        async def cb():
            invoked.append(True)
        sh.register_callback("future_test", cb)

        asyncio.run(sh.startup_replay())
        # Row still in DB (will fire later — we don't wait for it).
        rows = db.cursor.execute(
            "SELECT * FROM scheduled_callbacks WHERE callback_name=?",
            ("future_test",)
        ).fetchall()
        assert len(rows) == 1

    def test_unregistered_callback_dropped(self):
        # Write a row referencing a callback name nobody registered.
        db.add_entry("scheduled_callbacks", (
            time.time() + 100,
            "totally_unregistered_xyz",
            json.dumps({}),
            None,
            None,
        ))
        asyncio.run(sh.startup_replay())
        # Row dropped because callback name isn't registered.
        rows = db.cursor.execute(
            "SELECT * FROM scheduled_callbacks WHERE callback_name=?",
            ("totally_unregistered_xyz",)
        ).fetchall()
        assert rows == []

    def test_startup_callback_invoked(self):
        invoked = []
        async def cb(key=None):
            invoked.append(key)
        sh.register_callback("startup_test", cb)
        # Add a startup callback row.
        sh.register_startup_callback("startup_test", kwargs={"key": "val"})

        asyncio.run(sh.startup_replay())
        assert invoked == ["val"]
        # Row deleted.
        rows = db.cursor.execute(
            "SELECT * FROM startup_callbacks WHERE callback_name=?",
            ("startup_test",)
        ).fetchall()
        assert rows == []

    def test_startup_callback_unregistered_dropped(self):
        sh.register_startup_callback("totally_unregistered_xyz",
                                     kwargs={})
        asyncio.run(sh.startup_replay())
        # Even unregistered startup callbacks get their rows cleaned up.
        rows = db.cursor.execute(
            "SELECT * FROM startup_callbacks WHERE callback_name=?",
            ("totally_unregistered_xyz",)
        ).fetchall()
        assert rows == []

    def test_startup_callback_with_guild_id_merged_into_args(self):
        captured = {}
        async def cb(guild_id=None, **kwargs):
            captured["guild_id"] = guild_id
            captured["kwargs"] = kwargs
        sh.register_callback("guild_test", cb)
        sh.register_startup_callback(
            "guild_test", kwargs={"x": 1}, guild_id=999)
        asyncio.run(sh.startup_replay())
        assert captured["guild_id"] == 999
        assert captured["kwargs"] == {"x": 1}


# ---------------------------------------------------------------------------
# unschedule_persistent
# ---------------------------------------------------------------------------


class TestUnschedulePersistent:
    def test_deletes_db_row(self):
        async def cb():
            return None
        sh.register_callback("unschedule_test", cb)

        async def run_full():
            await sh.schedule_event_persistent(
                time.time() + 60, "unschedule_test",
                keys=["unsched-key"],
            )
            await sh.unschedule_persistent(
                "unschedule_test", keys=["unsched-key"])

        asyncio.run(run_full())
        rows = db.cursor.execute(
            "SELECT * FROM scheduled_callbacks WHERE callback_name=?",
            ("unschedule_test",)
        ).fetchall()
        assert rows == []

    def test_unschedule_without_keys_deletes_all(self):
        async def cb():
            return None
        sh.register_callback("unschedule_all", cb)

        async def run_full():
            await sh.schedule_event_persistent(
                time.time() + 60, "unschedule_all")
            await sh.schedule_event_persistent(
                time.time() + 120, "unschedule_all")
            await sh.unschedule_persistent("unschedule_all")

        asyncio.run(run_full())
        rows = db.cursor.execute(
            "SELECT * FROM scheduled_callbacks WHERE callback_name=?",
            ("unschedule_all",)
        ).fetchall()
        assert rows == []


# ---------------------------------------------------------------------------
# Persistence simulating restart
# ---------------------------------------------------------------------------


class TestRestartSimulation:
    def test_persists_across_simulated_restart(self):
        invoked = []
        async def cb(key=None):
            invoked.append(key)
        sh.register_callback("restart_test", cb)

        async def schedule_phase():
            await sh.schedule_event_persistent(
                time.time() + 60, "restart_test",
                kwargs={"key": "alpha"},
            )

        asyncio.run(schedule_phase())
        # Simulate restart: clear in-memory state (DB row persists).
        _clean_inmemory()
        # Verify DB row still there.
        rows = db.cursor.execute(
            "SELECT * FROM scheduled_callbacks WHERE callback_name=?",
            ("restart_test",)
        ).fetchall()
        assert len(rows) == 1
        # Call startup_replay; row should be re-scheduled (not invoked yet).
        asyncio.run(sh.startup_replay())
        # Row still in DB until it fires.
        rows = db.cursor.execute(
            "SELECT * FROM scheduled_callbacks WHERE callback_name=?",
            ("restart_test",)
        ).fetchall()
        assert len(rows) == 1
        assert invoked == []

    def test_100_scheduled_callbacks_survive_restart(self):
        invoked = []
        async def cb(n=None):
            invoked.append(n)
        sh.register_callback("stress_test", cb)

        async def schedule_many():
            for i in range(100):
                await sh.schedule_event_persistent(
                    time.time() + 60 + i,
                    "stress_test",
                    kwargs={"n": i},
                )

        asyncio.run(schedule_many())
        # Restart simulation.
        _clean_inmemory()
        # Verify all 100 rows persist.
        rows = db.cursor.execute(
            "SELECT * FROM scheduled_callbacks WHERE callback_name=?",
            ("stress_test",)
        ).fetchall()
        assert len(rows) == 100
        # Replay re-schedules all 100 in-memory.
        asyncio.run(sh.startup_replay())
        # All 100 rows still in DB (none fired yet).
        rows = db.cursor.execute(
            "SELECT * FROM scheduled_callbacks WHERE callback_name=?",
            ("stress_test",)
        ).fetchall()
        assert len(rows) == 100

    def test_expired_event_not_re_fired_on_restart(self):
        invoked = []
        async def cb():
            invoked.append(True)
        sh.register_callback("expired_no_refire", cb)

        # Manually insert an already-expired row.
        db.add_entry("scheduled_callbacks", (
            time.time() - 1000,  # 1000s ago
            "expired_no_refire",
            json.dumps({}),
            None,
            None,
        ))
        # Restart simulation: clear in-memory, call replay.
        _clean_inmemory()
        asyncio.run(sh.startup_replay())
        # Callback not invoked, row dropped.
        assert invoked == []
        rows = db.cursor.execute(
            "SELECT * FROM scheduled_callbacks WHERE callback_name=?",
            ("expired_no_refire",)
        ).fetchall()
        assert rows == []


# ---------------------------------------------------------------------------
# ScheduleCallback.persist field
# ---------------------------------------------------------------------------


class TestScheduleCallbackEffect:
    def test_default_persist_false(self):
        from axi.effects import ScheduleCallback
        e = ScheduleCallback(delay_seconds=1, callback_name="cb")
        assert e.persist is False

    def test_persist_kwarg_settable(self):
        from axi.effects import ScheduleCallback
        e = ScheduleCallback(delay_seconds=1, callback_name="cb", persist=True)
        assert e.persist is True
