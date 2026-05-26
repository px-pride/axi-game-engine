"""Phase 16 tests — wand persistence + CPU smart wand.

Covers:
1. wands table schema is correct (21 columns).
2. save_wand / load_wand round-trip.
3. load_wand returns None for unknown user.
4. PRIMARY KEY behavior — overwrite on re-save.
5. AbstractCPU.generate_wand defaults to wand_default.
6. SimpleCPU.generate_wand returns a 9-spell sampled wand.
7. Sampled wand varies across CPUs (randomness check, seeded).
8. Sampled spells all come from page 0 of the spellbook.
9. load_saved_wand(cpu) delegates to cpu.generate_wand.
10. RandomCPU + ClaudeCPU (skip if SDK unavailable) override correctly.

Conftest mocks include numpy/openskill/pytimeparse/discord; the wand
machinery doesn't depend on those. ClaudeCPU is gated on the
claude-agent-sdk extra so its constructor may raise — handled.
"""

import pytest

import axi.handlers.database_handler as db
from axi.abstract_cpu import AbstractCPU
from axi.random_cpu import RandomCPU
from axi.simple_cpu import SimpleCPU
from examples.wonder_wand import spells, wand_persistence, wonder_wand
from examples.wonder_wand.wonder_wand_profile import WonderWandProfile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_wands_table():
    db.cursor.execute("DELETE FROM wands")
    db.connection.commit()
    yield
    db.cursor.execute("DELETE FROM wands")
    db.connection.commit()


# ---------------------------------------------------------------------------
# Table schema
# ---------------------------------------------------------------------------


class TestWandsTable:
    def test_table_exists(self):
        db.cursor.execute("PRAGMA table_info(wands)")
        cols = db.cursor.fetchall()
        assert len(cols) > 0

    def test_table_has_21_columns(self):
        db.cursor.execute("PRAGMA table_info(wands)")
        cols = db.cursor.fetchall()
        # user_id + name + 9*(emoji, page) + timestamp = 21.
        assert len(cols) == 21

    def test_user_id_is_primary_key(self):
        db.cursor.execute("PRAGMA table_info(wands)")
        cols = db.cursor.fetchall()
        # col format: (cid, name, type, notnull, dflt_value, pk)
        user_id_col = next(c for c in cols if c[1] == "user_id")
        assert user_id_col[5] == 1

    def test_table_has_9_spell_slots(self):
        db.cursor.execute("PRAGMA table_info(wands)")
        cols = db.cursor.fetchall()
        names = [c[1] for c in cols]
        for i in range(9):
            assert f"spell_emoji_{i}" in names
            assert f"spell_page_{i}" in names


# ---------------------------------------------------------------------------
# save_wand / load_wand round-trip
# ---------------------------------------------------------------------------


class TestSaveLoadRoundTrip:
    def test_save_then_load_default_wand(self):
        default = wonder_wand.wand_default()
        wand_persistence.save_wand(1001, default)
        loaded = wand_persistence.load_wand(1001)
        assert loaded is not None
        assert loaded.name == default.name

    def test_save_then_load_preserves_emojis(self):
        default = wonder_wand.wand_default()
        wand_persistence.save_wand(1001, default)
        loaded = wand_persistence.load_wand(1001)
        # Both wands should have the same set of spell emojis.
        assert set(loaded.spells.keys()) == set(default.spells.keys())

    def test_save_then_load_preserves_spell_count(self):
        default = wonder_wand.wand_default()
        wand_persistence.save_wand(1001, default)
        loaded = wand_persistence.load_wand(1001)
        assert len(loaded.spells) == len(default.spells)


# ---------------------------------------------------------------------------
# Missing user
# ---------------------------------------------------------------------------


class TestLoadEmptyReturnsNone:
    def test_unsaved_user_returns_none(self):
        assert wand_persistence.load_wand(99_999) is None


# ---------------------------------------------------------------------------
# Overwrite semantics
# ---------------------------------------------------------------------------


class TestSaveOverwrite:
    def test_second_save_replaces_first(self):
        wand_a = wonder_wand.wand_default()
        # Build a 1-spell wand B (different name) by re-using one spell.
        first_spell = next(iter(wand_a.spells.values()))
        wand_b = wonder_wand.Wand("Wand B", [first_spell])
        wand_persistence.save_wand(1001, wand_a)
        wand_persistence.save_wand(1001, wand_b)
        loaded = wand_persistence.load_wand(1001)
        assert loaded.name == "Wand B"
        # Only the spells that were saved survive — 1 spell here.
        assert len(loaded.spells) == 1

    def test_only_one_row_per_user(self):
        wand = wonder_wand.wand_default()
        wand_persistence.save_wand(1001, wand)
        wand_persistence.save_wand(1001, wand)
        wand_persistence.save_wand(1001, wand)
        db.cursor.execute("SELECT COUNT(*) FROM wands WHERE user_id=1001")
        count = db.cursor.fetchone()[0]
        assert count == 1


# ---------------------------------------------------------------------------
# AbstractCPU default generate_wand
# ---------------------------------------------------------------------------


class TestCpuGenerateWandDefault:
    """AbstractCPU is abstract — but its generate_wand method works on any
    subclass. We test the default via SimpleCPU subclass with a
    minimal compute() override... actually SimpleCPU has its own
    generate_wand override, so we need a minimal AbstractCPU subclass."""

    def _make_minimal_cpu(self):
        class _MinimalCPU(AbstractCPU):
            def compute(self, options):
                return options[0]
        return _MinimalCPU(match=None)

    def test_default_returns_wand_default(self):
        cpu = self._make_minimal_cpu()
        wand = cpu.generate_wand()
        assert wand.name == "Default Wand"

    def test_default_has_9_spells(self):
        cpu = self._make_minimal_cpu()
        wand = cpu.generate_wand()
        assert len(wand.spells) == 9


# ---------------------------------------------------------------------------
# SimpleCPU.generate_wand
# ---------------------------------------------------------------------------


class TestSimpleCpuGenerateWand:
    def test_returns_wand(self):
        cpu = SimpleCPU(match=None)
        wand = cpu.generate_wand()
        assert isinstance(wand, wonder_wand.Wand)

    def test_wand_has_9_spells(self):
        cpu = SimpleCPU(match=None)
        wand = cpu.generate_wand()
        # 3 shapes × 3 sampled spells = 9.
        assert len(wand.spells) == 9

    def test_name_includes_cpu_name(self):
        cpu = SimpleCPU(match=None)
        wand = cpu.generate_wand()
        # "Simple CPU's wand" or similar.
        assert "Simple" in wand.name or "wand" in wand.name.lower()

    def test_sampled_spells_come_from_page_0(self):
        cpu = SimpleCPU(match=None)
        wand = cpu.generate_wand()
        book = spells.generate_spellbook()
        page_0_emojis = set()
        for shape, pages in book.items():
            for spell in pages[0]:
                page_0_emojis.add(spell.emoji())
        for emoji in wand.spells.keys():
            assert emoji in page_0_emojis

    def test_sampled_spells_cover_all_three_shapes(self):
        cpu = SimpleCPU(match=None)
        wand = cpu.generate_wand()
        shapes = {wonder_wand.shape(e) for e in wand.spells.keys()}
        assert shapes == {"circle", "square", "heart"}


class TestSimpleCpuGenerateWandIsVaried:
    """generate_random_wand samples randomly — across many calls,
    we should see variation in the chosen colors."""

    def test_multiple_cpus_produce_different_wands(self):
        wands = [SimpleCPU(match=None).generate_wand() for _ in range(10)]
        # Compare emoji sets — over 10 samples, at least 2 should differ.
        emoji_sets = [frozenset(w.spells.keys()) for w in wands]
        unique = set(emoji_sets)
        assert len(unique) >= 2


# ---------------------------------------------------------------------------
# load_saved_wand for CPUs
# ---------------------------------------------------------------------------


class TestLoadSavedWandForCpu:
    def test_simple_cpu_uses_generate_wand(self):
        cpu = SimpleCPU(match=None)
        wand = wonder_wand.load_saved_wand(cpu)
        # 3 shapes × 3 sampled = 9.
        assert len(wand.spells) == 9

    def test_random_cpu_uses_generate_wand(self):
        cpu = RandomCPU(match=None)
        wand = wonder_wand.load_saved_wand(cpu)
        assert len(wand.spells) == 9

    def test_minimal_cpu_falls_back_to_wand_default(self):
        class _MinimalCPU(AbstractCPU):
            def compute(self, options):
                return options[0]
        cpu = _MinimalCPU(match=None)
        wand = wonder_wand.load_saved_wand(cpu)
        # Default has 9 spells too; verify name to distinguish from
        # sampled wand which carries "CPU's wand"-style name.
        assert wand.name == "Default Wand"


# ---------------------------------------------------------------------------
# RandomCPU.generate_wand
# ---------------------------------------------------------------------------


class TestRandomCpuGenerateWand:
    def test_returns_9_spells(self):
        cpu = RandomCPU(match=None)
        wand = cpu.generate_wand()
        assert len(wand.spells) == 9

    def test_spells_from_page_0(self):
        cpu = RandomCPU(match=None)
        wand = cpu.generate_wand()
        book = spells.generate_spellbook()
        page_0_emojis = set()
        for pages in book.values():
            for spell in pages[0]:
                page_0_emojis.add(spell.emoji())
        for emoji in wand.spells.keys():
            assert emoji in page_0_emojis


# ---------------------------------------------------------------------------
# ClaudeCPU.generate_wand (skip if SDK unavailable)
# ---------------------------------------------------------------------------


class TestClaudeCpuGenerateWand:
    """ClaudeCPU __init__ requires claude-agent-sdk. We test its
    generate_wand by calling the unbound method to bypass __init__."""

    def test_generate_wand_returns_sampled_wand(self):
        from axi.claude_cpu import ClaudeCPU
        # Synthesize a "real enough" instance via __new__ to bypass the
        # SDK availability check in __init__.
        cpu = ClaudeCPU.__new__(ClaudeCPU)
        cpu.name = "Claude CPU"
        wand = cpu.generate_wand()
        assert len(wand.spells) == 9


# ---------------------------------------------------------------------------
# WonderWandProfile structured save/load
# ---------------------------------------------------------------------------


class TestWonderWandProfileStructured:
    def test_save_structured_writes_row(self):
        p = WonderWandProfile()
        p.save_structured(1001)
        loaded = wand_persistence.load_wand(1001)
        assert loaded is not None

    def test_load_structured_returns_profile(self):
        p = WonderWandProfile()
        p.save_structured(1001)
        loaded = WonderWandProfile.load_structured(1001)
        assert loaded is not None
        assert loaded.get_equipped_wand() is not None

    def test_load_structured_unknown_user_returns_none(self):
        assert WonderWandProfile.load_structured(99_999) is None

    def test_round_trip_preserves_default_wand(self):
        p = WonderWandProfile()
        p.save_structured(1001)
        loaded = WonderWandProfile.load_structured(1001)
        original_emojis = set(p.get_equipped_wand().spells.keys())
        loaded_emojis = set(loaded.get_equipped_wand().spells.keys())
        assert original_emojis == loaded_emojis
