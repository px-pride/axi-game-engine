"""Phase 12 tests — Scope/role system.

Covers channel normalization, scope resolution priority (per-caller >
channel > guild default), set_scope, set_default_scope, get_all_scopes,
multi-guild isolation, scope routing for multiple simultaneous
tournaments, and that the existing @has_permissions decorator pattern
is independent of scope state.
"""

import pytest

from axi.tournament import Tournament
from axi.tournament_state import (
    DEFAULT_SCOPE,
    TournamentState,
    state as tournament_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeChannel:
    def __init__(self, name, parent=None):
        self._name = name
        self.parent = parent

    def __str__(self):
        return self._name


class FakeThread:
    """A Discord Thread has .parent set to its parent channel."""
    def __init__(self, name, parent):
        self._name = name
        self.parent = parent

    def __str__(self):
        return self._name


class FakeGuild:
    def __init__(self, id):
        self.id = id


class FakeUser:
    def __init__(self, id):
        self.id = id


@pytest.fixture(autouse=True)
def _clean_state():
    tournament_state.reset()
    yield
    tournament_state.reset()


# ---------------------------------------------------------------------------
# channel_to_scope normalization
# ---------------------------------------------------------------------------


class TestChannelToScope:
    def test_uppercase(self):
        ch = FakeChannel("main")
        assert TournamentState.channel_to_scope(ch) == "MAIN"

    def test_strip_bracket_suffix(self):
        ch = FakeChannel("main-bracket")
        assert TournamentState.channel_to_scope(ch) == "MAIN"

    def test_mixed_case_with_bracket(self):
        ch = FakeChannel("PXL-Bracket")
        assert TournamentState.channel_to_scope(ch) == "PXL"

    def test_no_bracket_no_strip(self):
        ch = FakeChannel("just-a-channel")
        # Hyphenated names without -BRACKET suffix don't get stripped.
        assert TournamentState.channel_to_scope(ch) == "JUST-A-CHANNEL"

    def test_thread_uses_parent(self):
        parent = FakeChannel("main")
        thread = FakeThread("some-thread-name", parent=parent)
        assert TournamentState.channel_to_scope(thread) == "MAIN"

    def test_none_returns_default(self):
        assert TournamentState.channel_to_scope(None) == DEFAULT_SCOPE


# ---------------------------------------------------------------------------
# get_scope priority
# ---------------------------------------------------------------------------


class TestGetScope:
    def test_channel_derived_when_no_override(self):
        u = FakeUser(1001)
        g = FakeGuild(99)
        ch = FakeChannel("main-bracket")
        assert tournament_state.get_scope(u, g, ch) == "MAIN"

    def test_per_caller_override_wins(self):
        u = FakeUser(1001)
        g = FakeGuild(99)
        ch = FakeChannel("main-bracket")
        tournament_state.set_scope(u, g, ch, "CUSTOM")
        # Even though channel is "MAIN", caller override returns CUSTOM.
        assert tournament_state.get_scope(u, g, ch) == "CUSTOM"

    def test_registers_in_scopes_by_guild(self):
        u = FakeUser(1001)
        g = FakeGuild(99)
        ch = FakeChannel("alpha")
        tournament_state.get_scope(u, g, ch)
        assert "ALPHA" in tournament_state.scopes_by_guild[99]

    def test_default_scope_fallback_when_channel_none(self):
        u = FakeUser(1001)
        g = FakeGuild(99)
        tournament_state.set_default_scope(g, "GUILD_DEFAULT")
        # No channel, no per-caller — falls back to guild default.
        assert tournament_state.get_scope(u, g, None) == "GUILD_DEFAULT"


# ---------------------------------------------------------------------------
# set_scope
# ---------------------------------------------------------------------------


class TestSetScope:
    def test_per_caller_binding(self):
        u = FakeUser(1001)
        g = FakeGuild(99)
        ch = FakeChannel("main")
        tournament_state.set_scope(u, g, ch, "X")
        assert tournament_state.scopes[(1001, 99)] == "X"

    def test_admin_true_sets_default(self):
        u = FakeUser(1001)
        g = FakeGuild(99)
        ch = FakeChannel("main")
        tournament_state.set_scope(u, g, ch, "ADMIN_DEFAULT", admin=True)
        assert tournament_state.default_scopes[99] == "ADMIN_DEFAULT"

    def test_admin_false_does_not_set_default(self):
        u = FakeUser(1001)
        g = FakeGuild(99)
        ch = FakeChannel("main")
        tournament_state.set_scope(u, g, ch, "X", admin=False)
        assert tournament_state.default_scopes[99] == DEFAULT_SCOPE

    def test_uppercase_normalization(self):
        u = FakeUser(1001)
        g = FakeGuild(99)
        ch = FakeChannel("main")
        tournament_state.set_scope(u, g, ch, "lowercase")
        assert tournament_state.scopes[(1001, 99)] == "LOWERCASE"


# ---------------------------------------------------------------------------
# set_default_scope
# ---------------------------------------------------------------------------


class TestSetDefaultScope:
    def test_updates_default(self):
        g = FakeGuild(99)
        tournament_state.set_default_scope(g, "X")
        assert tournament_state.default_scopes[99] == "X"

    def test_registers_in_scopes_by_guild(self):
        g = FakeGuild(99)
        tournament_state.set_default_scope(g, "MAIN_DEFAULT")
        assert "MAIN_DEFAULT" in tournament_state.scopes_by_guild[99]

    def test_uppercase_normalization(self):
        g = FakeGuild(99)
        tournament_state.set_default_scope(g, "abc")
        assert tournament_state.default_scopes[99] == "ABC"


# ---------------------------------------------------------------------------
# get_all_scopes
# ---------------------------------------------------------------------------


class TestGetAllScopes:
    def test_empty_for_unknown_guild(self):
        u = FakeUser(1001)
        g = FakeGuild(999)
        assert tournament_state.get_all_scopes(u, g) == []

    def test_lists_registered_scopes(self):
        u = FakeUser(1001)
        g = FakeGuild(99)
        ch1 = FakeChannel("alpha")
        ch2 = FakeChannel("beta")
        tournament_state.get_scope(u, g, ch1)
        tournament_state.get_scope(u, g, ch2)
        scopes = tournament_state.get_all_scopes(u, g)
        assert "ALPHA" in scopes
        assert "BETA" in scopes

    def test_dedup(self):
        u = FakeUser(1001)
        g = FakeGuild(99)
        ch = FakeChannel("alpha")
        tournament_state.get_scope(u, g, ch)
        tournament_state.get_scope(u, g, ch)
        # ALPHA appears once.
        assert tournament_state.scopes_by_guild[99].count("ALPHA") == 1


# ---------------------------------------------------------------------------
# Per-guild isolation
# ---------------------------------------------------------------------------


class TestPerGuildIsolation:
    def test_same_scope_in_different_guilds(self):
        u = FakeUser(1001)
        g1 = FakeGuild(10)
        g2 = FakeGuild(20)
        ch1 = FakeChannel("main")
        ch2 = FakeChannel("main")
        tournament_state.get_scope(u, g1, ch1)
        tournament_state.get_scope(u, g2, ch2)
        # Both guilds have "MAIN" registered independently.
        assert "MAIN" in tournament_state.scopes_by_guild[10]
        assert "MAIN" in tournament_state.scopes_by_guild[20]

    def test_per_caller_override_isolated_per_guild(self):
        u = FakeUser(1001)
        g1 = FakeGuild(10)
        g2 = FakeGuild(20)
        ch = FakeChannel("main")
        tournament_state.set_scope(u, g1, ch, "G1_SCOPE")
        tournament_state.set_scope(u, g2, ch, "G2_SCOPE")
        assert tournament_state.get_scope(u, g1, ch) == "G1_SCOPE"
        assert tournament_state.get_scope(u, g2, ch) == "G2_SCOPE"


# ---------------------------------------------------------------------------
# Per-caller isolation
# ---------------------------------------------------------------------------


class TestPerCallerIsolation:
    def test_callers_have_independent_scopes(self):
        u1 = FakeUser(1001)
        u2 = FakeUser(1002)
        g = FakeGuild(99)
        ch = FakeChannel("main")
        tournament_state.set_scope(u1, g, ch, "U1_SCOPE")
        tournament_state.set_scope(u2, g, ch, "U2_SCOPE")
        assert tournament_state.get_scope(u1, g, ch) == "U1_SCOPE"
        assert tournament_state.get_scope(u2, g, ch) == "U2_SCOPE"


# ---------------------------------------------------------------------------
# Scope routing to Tournament
# ---------------------------------------------------------------------------


class TestScopeRouting:
    def test_disambiguates_multiple_tournaments(self):
        u = FakeUser(1001)
        g = FakeGuild(99)

        # Create two tournaments with distinct scopes.
        t1 = Tournament(title="T1", scope="ALPHA", seed=42)
        t2 = Tournament(title="T2", scope="BETA", seed=42)
        tournament_state.register_tournament(t1)
        tournament_state.register_tournament(t2)

        # Channel for ALPHA scope → resolves to t1.
        ch_alpha = FakeChannel("alpha")
        scope_a = tournament_state.get_scope(u, g, ch_alpha)
        assert scope_a == "ALPHA"
        assert tournament_state.get_tournament_by_scope(scope_a) is t1

        # Channel for BETA scope → resolves to t2.
        ch_beta = FakeChannel("beta")
        scope_b = tournament_state.get_scope(u, g, ch_beta)
        assert scope_b == "BETA"
        assert tournament_state.get_tournament_by_scope(scope_b) is t2

    def test_command_outside_scope_returns_none(self):
        u = FakeUser(1001)
        g = FakeGuild(99)
        # Register one tournament.
        t = Tournament(title="T", scope="MAIN", seed=42)
        tournament_state.register_tournament(t)

        # Channel name doesn't match any tournament.
        ch_other = FakeChannel("random")
        scope = tournament_state.get_scope(u, g, ch_other)
        assert scope == "RANDOM"
        # No tournament registered for RANDOM scope.
        assert tournament_state.get_tournament_by_scope(scope) is None


# ---------------------------------------------------------------------------
# State reset
# ---------------------------------------------------------------------------


class TestStateReset:
    def test_reset_clears_scope_state(self):
        u = FakeUser(1001)
        g = FakeGuild(99)
        ch = FakeChannel("main")
        tournament_state.set_scope(u, g, ch, "X")
        tournament_state.set_default_scope(g, "Y")
        tournament_state.reset()
        assert tournament_state.scopes == {}
        assert dict(tournament_state.default_scopes) == {}
        assert dict(tournament_state.scopes_by_guild) == {}


# ---------------------------------------------------------------------------
# Independence from has_permissions
# ---------------------------------------------------------------------------


class TestHasPermissionsIndependence:
    """Scope state should not interact with Discord's @has_permissions
    decorator — the decorator gates command invocation; scope handles
    targeting. These tests just verify no scope state is consulted in
    the permission path (a smoke check)."""

    def test_set_scope_does_not_check_permissions(self):
        """set_scope(admin=False) succeeds without any permission check
        on the caller. (The slash command layer decides admin=True/False
        based on Discord permissions before calling set_scope.)"""
        u = FakeUser(1001)
        g = FakeGuild(99)
        ch = FakeChannel("main")
        # No exception, no permission check.
        tournament_state.set_scope(u, g, ch, "X", admin=False)
        assert tournament_state.scopes[(1001, 99)] == "X"

    def test_admin_flag_explicit_in_state_api(self):
        u = FakeUser(1001)
        g = FakeGuild(99)
        ch = FakeChannel("main")
        # admin=True is a parameter the slash command layer passes;
        # state.set_scope doesn't auto-detect from caller properties.
        tournament_state.set_scope(u, g, ch, "X", admin=True)
        assert tournament_state.default_scopes[99] == "X"
