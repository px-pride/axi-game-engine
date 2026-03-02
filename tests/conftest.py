"""Test configuration — mocks Discord modules so axi pure-layer code can import
without a bot connection or Discord library installed."""

import sys
import os
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# 1. Mock Discord and external deps BEFORE any axi imports.
#    This must happen at module level so it runs before test collection.
# ---------------------------------------------------------------------------

_discord = MagicMock()
sys.modules['discord'] = _discord
sys.modules['discord.abc'] = _discord.abc
sys.modules['discord.app_commands'] = _discord.app_commands
sys.modules['discord.app_commands.checks'] = _discord.app_commands.checks
sys.modules['discord.enums'] = _discord.enums
sys.modules['discord.ext'] = _discord.ext
sys.modules['discord.ext.commands'] = _discord.ext.commands
sys.modules['discord.utils'] = _discord.utils

sys.modules['dotenv'] = MagicMock()
sys.modules['pytimeparse'] = MagicMock()
sys.modules['pytimeparse.timeparse'] = MagicMock()
sys.modules['numpy'] = MagicMock()

_openskill = MagicMock()
sys.modules['openskill'] = _openskill
sys.modules['openskill.constants'] = _openskill.constants
sys.modules['openskill.util'] = _openskill.util
sys.modules['openskill.models'] = _openskill.models
sys.modules['openskill.models.plackett_luce'] = _openskill.models.plackett_luce
sys.modules['openskill.rate'] = _openskill.rate

# ---------------------------------------------------------------------------
# 2. Ensure project root and examples dir are importable.
# ---------------------------------------------------------------------------

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

_examples_dir = os.path.join(_project_root, 'examples')
if _examples_dir not in sys.path:
    sys.path.insert(0, _examples_dir)

# ---------------------------------------------------------------------------
# 3. Now safe to import axi modules.  Register the RPS game for tests.
# ---------------------------------------------------------------------------

import pytest
import axi.registry as registry
import axi.handlers.match_handler as match_handler
from rock_paper_scissors import RockPaperScissors


# ---------------------------------------------------------------------------
# 4. FakeUser — test substitute for AxiUser (no Discord dependency).
# ---------------------------------------------------------------------------

class FakeUid:
    """Mimics a Discord User object with an .id attribute."""
    def __init__(self, user_id):
        self.id = user_id


class FakeUser:
    """Test substitute for AxiUser. Has the interface the pure layer needs:
    .uid.id, str(), repr(), hashable, parse()."""
    def __init__(self, name, user_id):
        self.uid = FakeUid(user_id)
        self._name = name

    def parse(self, mention=False):
        return self._name

    def __str__(self):
        return self._name

    def __repr__(self):
        return self._name


class FakeLadder:
    """Minimal ladder stand-in for thread game tests that need match.ladder."""
    def __init__(self, guild_id=99, results_channel="results"):
        self.guild = type('FakeGuild', (), {'id': guild_id})()
        self.results_channel = results_channel

    def advance(self, match):
        pass

    def abort(self, match):
        pass


# ---------------------------------------------------------------------------
# 5. Fixtures
# ---------------------------------------------------------------------------

THREAD_GAME_INFO = {
    "name": "test_thread_game",
    "init": [["Welcome to the match!", ""]],
}


@pytest.fixture(autouse=True)
def _register_games():
    """Register test games in axi registries, then clean up."""
    registry.dm_games["rps"] = RockPaperScissors
    registry.thread_games["test_thread_game"] = THREAD_GAME_INFO
    yield
    registry.dm_games.pop("rps", None)
    registry.thread_games.pop("test_thread_game", None)


@pytest.fixture(autouse=True)
def _clean_match_state():
    """Reset match_handler global state between tests."""
    from axi.handlers.match_handler import MatchState
    match_handler.state = MatchState()
    yield
    match_handler.state = MatchState()


@pytest.fixture
def p1():
    return FakeUser("Alice", 1001)


@pytest.fixture
def p2():
    return FakeUser("Bob", 1002)


@pytest.fixture
def fake_ladder():
    return FakeLadder(guild_id=99, results_channel="results")
