"""Tests for ClaudeCPU — prompt building, response parsing, and SDK integration.

All tests mock the Claude Agent SDK so no API calls are made.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from copy import copy

from axi.claude_cpu import (
    ClaudeCPU,
    PHASE_COMBAT,
    PHASE_EFFECTS,
    EMOJI_REFRESH,
    EMOJI_SHIELD,
    EMOJI_CYCLONE,
    EMOJI_NO_ENTRY,
    EMOJI_SKIP,
    SYSTEM_PROMPT,
)

# Emoji constants for spells
RED_CIRCLE = "\N{LARGE RED CIRCLE}"
RED_SQUARE = "\N{LARGE RED SQUARE}"
RED_HEART = "\N{HEAVY BLACK HEART}"
GREEN_CIRCLE = "\N{LARGE GREEN CIRCLE}"
GREEN_SQUARE = "\N{LARGE GREEN SQUARE}"
GREEN_HEART = "\N{GREEN HEART}"
BLUE_CIRCLE = "\N{LARGE BLUE CIRCLE}"
BLUE_SQUARE = "\N{LARGE BLUE SQUARE}"
BLUE_HEART = "\N{BLUE HEART}"


class FakeSpell:
    def __init__(self, name, color, shape, dmg=5):
        self.name = name
        self.color = color
        self.shape = shape
        self.dmg = dmg
        self._emoji = {
            ("red", "circle"): RED_CIRCLE,
            ("red", "square"): RED_SQUARE,
            ("red", "heart"): RED_HEART,
            ("green", "circle"): GREEN_CIRCLE,
            ("green", "square"): GREEN_SQUARE,
            ("green", "heart"): GREEN_HEART,
            ("blue", "circle"): BLUE_CIRCLE,
            ("blue", "square"): BLUE_SQUARE,
            ("blue", "heart"): BLUE_HEART,
        }[(color, shape)]

    def emoji(self):
        return self._emoji

    def description(self):
        return f"Deals {self.dmg} damage. "

    def __repr__(self):
        return f"*{self.name}*"


class FakeWand:
    def __init__(self, spells):
        self.spells = {s.emoji(): s for s in spells}
        self.active = {e: False for e in self.spells}
        self.frozen = {e: False for e in self.spells}
        self.frozen[EMOJI_REFRESH] = False
        self.frozen[EMOJI_SHIELD] = False
        self.hexes = []

    def info(self, limit):
        return "> Spell Pool: ...\n"

    def opp_info(self, limit):
        return "> Opponent Pool: ...\n"


class FakeUser:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return isinstance(other, FakeUser) and self.name == other.name


def make_default_spells():
    return [
        FakeSpell("Ignite", "red", "circle"),
        FakeSpell("Wildfire", "red", "square", 8),
        FakeSpell("Burn", "red", "heart", 3),
        FakeSpell("Overgrowth", "green", "circle"),
        FakeSpell("Earthquake", "green", "square", 8),
        FakeSpell("Poison", "green", "heart", 3),
        FakeSpell("Reflecting Pool", "blue", "circle"),
        FakeSpell("Tidal Wave", "blue", "square", 8),
        FakeSpell("Freeze", "blue", "heart", 3),
    ]


class FakeMatch:
    """Minimal match stub with enough state for ClaudeCPU methods."""

    def __init__(self):
        self.human = FakeUser("Player1")
        self.cpu = None  # Set after ClaudeCPU is created
        self.players = [self.human]
        self.round = 3
        self.phase = PHASE_COMBAT
        self.scores = {}
        self.wands = {}
        self.combat_options = {}
        self.casters = []
        self.blockers = []
        self.chargers = []
        self.scouters = []
        self.effects = {}
        self.expected_num_decisions = {self.human: 1}
        self.emojis_to_moves = {
            RED_CIRCLE: ("red", "circle"),
            RED_SQUARE: ("red", "square"),
            RED_HEART: ("red", "heart"),
            GREEN_CIRCLE: ("green", "circle"),
            GREEN_SQUARE: ("green", "square"),
            GREEN_HEART: ("green", "heart"),
            BLUE_CIRCLE: ("blue", "circle"),
            BLUE_SQUARE: ("blue", "square"),
            BLUE_HEART: ("blue", "heart"),
        }

    def setup_cpu(self, cpu):
        self.cpu = cpu
        self.players.append(cpu)
        self.scores = {self.human: 40, cpu: 40}
        spells = make_default_spells()
        self.wands = {
            self.human: FakeWand(spells),
            cpu: FakeWand(spells),
        }
        self.combat_options = {self.human: None, cpu: None}
        self.effects = {self.human: {}, cpu: {}}
        self.expected_num_decisions[cpu] = 1

    def match_state(self, p):
        opp = self.human if p == self.cpu else self.cpu
        return (
            f"> {p} 40-40 {opp}\n"
            f"> {p}\n> Effects: None\n"
            f"{self.wands[p].info(5)}"
            f"> {opp}\n> Effects: None\n"
            f"{self.wands[opp].opp_info(5)}"
        )

    def opponent(self, p):
        if p == self.players[0]:
            return self.players[1]
        return self.players[0]

    def charge_limit_fx(self, p):
        return 5


@pytest.fixture
def match_and_cpu():
    """Create a FakeMatch and ClaudeCPU wired together."""
    match = FakeMatch()
    # Patch CLAUDE_SDK_AVAILABLE to allow instantiation without the real SDK
    with patch("axi.claude_cpu.CLAUDE_SDK_AVAILABLE", True):
        cpu = ClaudeCPU(match)
    match.setup_cpu(cpu)
    return match, cpu


# === Response Parsing ===

class TestParseResponse:
    def test_single_emoji_found(self, match_and_cpu):
        _, cpu = match_and_cpu
        options = [EMOJI_REFRESH, EMOJI_SHIELD, RED_CIRCLE]
        result = cpu._parse_response(RED_CIRCLE, options, 1)
        assert result == RED_CIRCLE

    def test_single_emoji_with_surrounding_text(self, match_and_cpu):
        _, cpu = match_and_cpu
        options = [EMOJI_REFRESH, EMOJI_SHIELD, RED_CIRCLE]
        result = cpu._parse_response(f"I'll cast {RED_CIRCLE} for fire damage", options, 1)
        assert result == RED_CIRCLE

    def test_multiple_emojis(self, match_and_cpu):
        _, cpu = match_and_cpu
        options = [RED_CIRCLE, RED_SQUARE, GREEN_CIRCLE, GREEN_SQUARE, BLUE_CIRCLE]
        result = cpu._parse_response(
            f"{RED_CIRCLE} {GREEN_SQUARE} {BLUE_CIRCLE}", options, 3
        )
        assert result == [RED_CIRCLE, GREEN_SQUARE, BLUE_CIRCLE]

    def test_fallback_on_empty_response(self, match_and_cpu):
        _, cpu = match_and_cpu
        options = [EMOJI_REFRESH, EMOJI_SHIELD, RED_CIRCLE]
        result = cpu._parse_response("", options, 1)
        assert result == EMOJI_REFRESH  # First option

    def test_fallback_on_gibberish(self, match_and_cpu):
        _, cpu = match_and_cpu
        options = [EMOJI_REFRESH, EMOJI_SHIELD]
        result = cpu._parse_response("I don't know what to do", options, 1)
        assert result == EMOJI_REFRESH

    def test_multi_fallback_returns_list(self, match_and_cpu):
        _, cpu = match_and_cpu
        options = [RED_CIRCLE, RED_SQUARE, GREEN_CIRCLE]
        result = cpu._parse_response("no emojis here", options, 2)
        assert result == [RED_CIRCLE, RED_SQUARE]

    def test_no_duplicates(self, match_and_cpu):
        _, cpu = match_and_cpu
        options = [RED_CIRCLE, RED_SQUARE, GREEN_CIRCLE]
        # Response repeats RED_CIRCLE but should only count once
        result = cpu._parse_response(
            f"{RED_CIRCLE} {RED_CIRCLE} {GREEN_CIRCLE}", options, 2
        )
        assert result == [RED_CIRCLE, GREEN_CIRCLE]

    def test_stops_at_num_decisions(self, match_and_cpu):
        _, cpu = match_and_cpu
        options = [RED_CIRCLE, RED_SQUARE, GREEN_CIRCLE, GREEN_SQUARE]
        result = cpu._parse_response(
            f"{RED_CIRCLE} {RED_SQUARE} {GREEN_CIRCLE} {GREEN_SQUARE}", options, 2
        )
        assert result == [RED_CIRCLE, RED_SQUARE]

    def test_whitespace_stripped(self, match_and_cpu):
        _, cpu = match_and_cpu
        options = [EMOJI_SHIELD, RED_CIRCLE]
        result = cpu._parse_response(f"\n  {EMOJI_SHIELD}  \n", options, 1)
        assert result == EMOJI_SHIELD


# === Option Descriptions ===

class TestDescribeOption:
    def test_refresh(self, match_and_cpu):
        _, cpu = match_and_cpu
        desc = cpu._describe_option(EMOJI_REFRESH)
        assert "Refresh" in desc
        assert "hexes" in desc

    def test_shield(self, match_and_cpu):
        _, cpu = match_and_cpu
        desc = cpu._describe_option(EMOJI_SHIELD)
        assert "Block" in desc

    def test_cyclone(self, match_and_cpu):
        _, cpu = match_and_cpu
        desc = cpu._describe_option(EMOJI_CYCLONE)
        assert "Bounce" in desc

    def test_no_entry(self, match_and_cpu):
        _, cpu = match_and_cpu
        desc = cpu._describe_option(EMOJI_NO_ENTRY)
        assert "Cancel" in desc
        assert "4 HP" in desc

    def test_skip(self, match_and_cpu):
        _, cpu = match_and_cpu
        desc = cpu._describe_option(EMOJI_SKIP)
        assert "Skip" in desc

    def test_own_spell_shows_name_and_description(self, match_and_cpu):
        _, cpu = match_and_cpu
        desc = cpu._describe_option(RED_CIRCLE)
        assert "Cast Ignite" in desc
        assert "red" in desc
        assert "circle" in desc
        assert "damage" in desc

    def test_unknown_emoji(self, match_and_cpu):
        _, cpu = match_and_cpu
        desc = cpu._describe_option("\N{SNOWMAN}")
        assert "Unknown" in desc


# === Phase Context ===

class TestPhaseContext:
    def test_combat_phase(self, match_and_cpu):
        match, cpu = match_and_cpu
        match.phase = PHASE_COMBAT
        ctx = cpu._phase_context()
        assert "cast a spell" in ctx
        assert "block" in ctx
        assert "refresh" in ctx

    def test_caster_phase(self, match_and_cpu):
        match, cpu = match_and_cpu
        match.phase = PHASE_EFFECTS
        match.casters = [cpu]
        match.combat_options[cpu] = RED_CIRCLE
        ctx = cpu._phase_context()
        assert "Ignite" in ctx
        assert "won combat" in ctx

    def test_blocker_phase(self, match_and_cpu):
        match, cpu = match_and_cpu
        match.phase = PHASE_EFFECTS
        match.blockers = [cpu]
        match.combat_options[match.human] = RED_SQUARE
        ctx = cpu._phase_context()
        assert "blocked" in ctx
        assert "Wildfire" in ctx
        assert "Bounce" in ctx or "Cancel" in ctx

    def test_charger_phase(self, match_and_cpu):
        match, cpu = match_and_cpu
        match.phase = PHASE_EFFECTS
        match.chargers = [cpu]
        ctx = cpu._phase_context()
        assert "refreshing" in ctx

    def test_scouter_phase(self, match_and_cpu):
        match, cpu = match_and_cpu
        match.phase = PHASE_EFFECTS
        match.scouters = [cpu]
        ctx = cpu._phase_context()
        assert "divine" in ctx

    def test_no_role_returns_empty(self, match_and_cpu):
        match, cpu = match_and_cpu
        match.phase = PHASE_EFFECTS
        match.casters = []
        match.blockers = []
        match.chargers = []
        match.scouters = []
        ctx = cpu._phase_context()
        assert ctx == ""


# === Prompt Building ===

class TestBuildPrompt:
    def test_includes_round_number(self, match_and_cpu):
        match, cpu = match_and_cpu
        match.round = 7
        prompt = cpu._build_prompt([EMOJI_REFRESH, EMOJI_SHIELD], 1)
        assert "Round 7" in prompt

    def test_combat_phase_label(self, match_and_cpu):
        match, cpu = match_and_cpu
        match.phase = PHASE_COMBAT
        prompt = cpu._build_prompt([EMOJI_REFRESH], 1)
        assert "Combat Phase" in prompt

    def test_effects_phase_label(self, match_and_cpu):
        match, cpu = match_and_cpu
        match.phase = PHASE_EFFECTS
        match.chargers = [cpu]
        prompt = cpu._build_prompt([RED_CIRCLE], 1)
        assert "Effects Phase" in prompt

    def test_includes_game_state(self, match_and_cpu):
        match, cpu = match_and_cpu
        prompt = cpu._build_prompt([EMOJI_REFRESH], 1)
        assert "40-40" in prompt

    def test_includes_option_descriptions(self, match_and_cpu):
        match, cpu = match_and_cpu
        prompt = cpu._build_prompt([EMOJI_REFRESH, RED_CIRCLE], 1)
        assert "Refresh" in prompt
        assert "Ignite" in prompt

    def test_includes_num_decisions(self, match_and_cpu):
        match, cpu = match_and_cpu
        prompt = cpu._build_prompt([RED_CIRCLE, GREEN_CIRCLE], 3)
        assert "choose 3" in prompt
        assert "3 emoji(s)" in prompt


# === Compute (mocked SDK) ===

class TestCompute:
    def test_compute_calls_sdk_and_parses(self, match_and_cpu):
        match, cpu = match_and_cpu
        match.phase = PHASE_COMBAT
        options = [EMOJI_REFRESH, EMOJI_SHIELD, RED_CIRCLE]

        # Mock _async_compute to return a response with the shield emoji
        async def mock_async(prompt):
            return EMOJI_SHIELD

        with patch.object(cpu, "_async_compute", side_effect=mock_async):
            result = cpu.compute(copy(options))

        assert result == EMOJI_SHIELD

    def test_compute_multi_decision(self, match_and_cpu):
        match, cpu = match_and_cpu
        match.phase = PHASE_EFFECTS
        match.chargers = [cpu]
        match.expected_num_decisions[cpu] = 3
        options = [RED_CIRCLE, RED_SQUARE, GREEN_CIRCLE, GREEN_SQUARE, BLUE_CIRCLE]

        async def mock_async(prompt):
            return f"{RED_CIRCLE} {GREEN_CIRCLE} {BLUE_CIRCLE}"

        with patch.object(cpu, "_async_compute", side_effect=mock_async):
            result = cpu.compute(copy(options))

        assert result == [RED_CIRCLE, GREEN_CIRCLE, BLUE_CIRCLE]

    def test_compute_fallback_on_bad_response(self, match_and_cpu):
        match, cpu = match_and_cpu
        match.phase = PHASE_COMBAT
        options = [EMOJI_REFRESH, EMOJI_SHIELD, RED_CIRCLE]

        async def mock_async(prompt):
            return "I'm confused and don't know what to pick"

        with patch.object(cpu, "_async_compute", side_effect=mock_async):
            result = cpu.compute(copy(options))

        # Should fallback to first option
        assert result == EMOJI_REFRESH


# === Initialization ===

class TestInit:
    def test_name(self, match_and_cpu):
        _, cpu = match_and_cpu
        assert cpu.name == "Claude CPU"
        assert "Claude" in repr(cpu)

    def test_raises_without_sdk(self):
        match = FakeMatch()
        with patch("axi.claude_cpu.CLAUDE_SDK_AVAILABLE", False):
            with pytest.raises(ImportError, match="claude-agent-sdk"):
                ClaudeCPU(match)
