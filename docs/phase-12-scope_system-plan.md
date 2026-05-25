# Phase 12: Scope/role system

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 12.

Adds the **scope** concept for tournament targeting — when multiple
tournaments run simultaneously in a server, scope (a normalized
channel name) disambiguates which one a command refers to. Source has
both a 3-tier role hierarchy (SU/ADMIN/STAFF via role-name matching)
and the scope concept; we **adopt scope but KEEP target's existing
`@has_permissions(ban_members=True)` admin gating** — no custom role
hierarchy.

## Scope

- New `axi/handlers/scope_handler.py` containing:
  - `ScopeState` with `default_scopes`, `scopes`, `scopes_by_guild`
    dicts (mirrors source).
  - `channel_to_scope(channel)` — uppercase + strip `-BRACKET` suffix.
    Handles Discord `Thread` objects by reading their parent channel.
  - `get_scope(caller, guild, channel)` — resolves the active scope
    for a (caller, guild, channel) triple.
  - `get_all_scopes(guild)` — returns all known scopes in the guild.
  - `set_scope(caller, guild, channel, scope, admin=False)` — bind
    a caller's active scope; if `admin` (or caller has admin
    permission), also set the guild-wide default.
  - `set_default_scope(guild, scope)` — guild-wide default scope.
- New slash commands in `axi/handlers/discord_handler.py`:
  - `/setscope <scope>` — set the caller's per-(caller,guild) scope.
  - `/setdefaultscope <scope>` — set the guild-wide default (admin
    only, via existing `@has_permissions(ban_members=True)`).
  - `/getscope` — print the active scope for the calling user.
  - `/allscopes` — print all known scopes in the guild.
- `Tournament.scope` (already exists, set in `__init__`) is now the
  canonical key for scope→tournament lookup via `TournamentState`.
- Adapter routing: when an admin command is invoked, the handler
  resolves the active scope via `scope_handler.get_scope(...)` and
  uses it to find the relevant Tournament/Ladder.

## What we deliberately skip from source

Source's 3-tier role hierarchy (`User.is_su()` / `is_admin()` /
`is_staff()` via Discord role-name string matching like `"SU"` /
`"ADMIN"` / `"STAFF"` per guild). We use Discord's native permission
system instead: `@has_permissions(ban_members=True)` for admin
commands (already in use throughout `axi/handlers/discord_handler.py`).

Rationale: role-name string matching is brittle (admins must create
specifically-named roles), permission-bit gating leverages Discord's
own permission model and works out of the box.

## Files

| File | Change |
|---|---|
| `axi/handlers/scope_handler.py` (NEW) | ScopeState + ops. |
| `axi/handlers/discord_handler.py` | 4 new slash commands; resolve scope before routing scoped operations. |
| `tests/test_scope_handler.py` (NEW) | Channel-to-scope normalization, per-caller scoping, default scope, all-scopes listing, scope routing. |

## `axi/handlers/scope_handler.py` shape

```python
"""Scope handler (Phase 12).

Pure-layer scope state + normalization. Tournament targeting uses
the channel name (uppercased, BRACKET-stripped) as the canonical
scope key. Per-caller scope overrides the guild default.
"""

from collections import defaultdict


DEFAULT_SCOPE = "DEFAULT_SCOPE"


class ScopeState:
    def __init__(self):
        # guild_id → scope (default for this guild)
        self.default_scopes = defaultdict(lambda: DEFAULT_SCOPE)
        # (caller_id, guild_id) → scope (per-user override)
        self.scopes = defaultdict(lambda: DEFAULT_SCOPE)
        # guild_id → [scope, ...] (all known scopes in this guild)
        self.scopes_by_guild = defaultdict(list)

    def reset(self):
        self.default_scopes.clear()
        self.scopes.clear()
        self.scopes_by_guild.clear()


state = ScopeState()


def channel_to_scope(channel):
    """Normalize a Discord channel (or Thread) to a scope string.

    Uppercase the channel name; strip trailing '-BRACKET'. Threads
    map to their parent channel's scope.
    """
    if channel is None:
        return DEFAULT_SCOPE
    # Threads: source uses str(channel.parent). Target replicates.
    parent = getattr(channel, "parent", None)
    name = str(parent) if parent is not None else str(channel)
    name = name.upper()
    if name.endswith("-BRACKET"):
        name = name[: -len("-BRACKET")]
    return name


def get_scope(caller_id, guild_id, channel):
    """Resolve the active scope for a (caller, guild, channel) triple.

    Priority order:
      1. Per-caller scope override (state.scopes[(caller_id, guild_id)]).
      2. Channel-derived scope (channel_to_scope).
      3. Guild default (state.default_scopes[guild_id]).
    """
    # Per-caller override wins if set.
    if (caller_id, guild_id) in state.scopes:
        return state.scopes[(caller_id, guild_id)]
    # Otherwise derive from channel.
    scope = channel_to_scope(channel)
    # Register the scope as known for this guild.
    if scope not in state.scopes_by_guild[guild_id]:
        state.scopes_by_guild[guild_id].append(scope)
    return scope


def get_all_scopes(guild_id):
    return list(state.scopes_by_guild[guild_id])


def set_scope(caller_id, guild_id, scope, admin=False):
    """Bind the caller's per-(caller,guild) scope.

    `admin=True` also sets the guild-wide default. The slash command
    layer determines admin status via Discord's permission system.
    """
    state.scopes[(caller_id, guild_id)] = scope
    if scope not in state.scopes_by_guild[guild_id]:
        state.scopes_by_guild[guild_id].append(scope)
    if admin:
        set_default_scope(guild_id, scope)


def set_default_scope(guild_id, scope):
    """Set the guild-wide default scope. Used when no per-caller
    override is set."""
    state.default_scopes[guild_id] = scope
    if scope not in state.scopes_by_guild[guild_id]:
        state.scopes_by_guild[guild_id].append(scope)
```

## Slash commands (in discord_handler.py)

```python
@bot.tree.command(name="setscope",
                  description="Set your active tournament scope.")
async def setscope(ctx, scope: str):
    scope_handler.set_scope(
        ctx.user.id, ctx.guild.id, scope.upper(), admin=False)
    await ctx.response.send_message(
        f"Your scope is now `{scope.upper()}`.")


@bot.tree.command(name="setdefaultscope",
                  description="Set the guild's default tournament scope (admin only).")
@has_permissions(ban_members=True)
async def setdefaultscope(ctx, scope: str):
    scope_handler.set_scope(
        ctx.user.id, ctx.guild.id, scope.upper(), admin=True)
    await ctx.response.send_message(
        f"Default scope for this guild is now `{scope.upper()}`.")


@bot.tree.command(name="getscope",
                  description="Print your active tournament scope.")
async def getscope(ctx):
    scope = scope_handler.get_scope(
        ctx.user.id, ctx.guild.id, ctx.channel)
    await ctx.response.send_message(f"Your active scope: `{scope}`")


@bot.tree.command(name="allscopes",
                  description="List all known tournament scopes in this guild.")
async def allscopes(ctx):
    scopes = scope_handler.get_all_scopes(ctx.guild.id)
    if not scopes:
        await ctx.response.send_message("No scopes registered yet.")
        return
    lines = "\n".join(f"- `{s}`" for s in scopes)
    await ctx.response.send_message(f"Scopes in this guild:\n{lines}")
```

## Test plan

`tests/test_scope_handler.py`:

1. **`TestChannelToScope`** — uppercases name; strips `-BRACKET`;
   handles Thread (uses parent); None returns DEFAULT_SCOPE.

2. **`TestGetScope`** — channel-derived when no override; per-caller
   override wins over channel; new scope registered in
   scopes_by_guild.

3. **`TestSetScope`** — per-(caller, guild) binding; admin=True also
   sets default_scopes for the guild.

4. **`TestSetDefaultScope`** — direct API path; updates
   default_scopes; appears in scopes_by_guild.

5. **`TestGetAllScopes`** — returns list per guild; empty for unknown
   guild; dedup (same scope set twice doesn't duplicate).

6. **`TestPerGuildIsolation`** — same scope across different guilds
   stays separate.

7. **`TestScopeStateReset`** — clears all state cleanly.

8. **`TestIntegrationWithTournamentState`** —
   `scope_handler.get_scope(...)` returns a string matching a
   Tournament's `.scope` field, and `TournamentState.get_tournament_by_scope`
   returns the right tournament.

Full suite must still pass.

## Major decisions

### A. Skip source's role hierarchy

Already settled by the card. Discord's `@has_permissions(ban_members=True)`
on admin commands replaces SU/ADMIN/STAFF role-name matching.

### B. `DEFAULT_SCOPE` sentinel for unknown scope

Source uses `"DEFAULT_SCOPE"` string. We follow. Returned when
channel is None or no override is set and no scope is derivable.

### C. Per-caller scope wins over channel-derived scope

Matches source. Lets a streamer/admin operate on a different scope
than the channel they're typing in (e.g. running `/setscope MAIN`
in a private channel then using bracket-management commands).

### D. `admin` flag explicit, not auto-detected

Source auto-detects admin status via `caller.is_admin()`. We require
explicit `admin=True` from the caller; the slash command layer
decides based on Discord permissions (e.g. `/setdefaultscope`'s
`@has_permissions(ban_members=True)` decorator).

### E. Scope strings normalized to UPPERCASE

All inputs upper-cased, both at `channel_to_scope` time and in
`/setscope` / `/setdefaultscope` slash commands. Internal comparisons
are case-sensitive on the uppercased form.

### F. `scopes_by_guild` is just a deduplicated list

Order matters for `/allscopes` display (registration order).
List + membership check via `if scope not in scopes_by_guild[gid]`.

### G. No DB persistence in Phase 12

Scope state is in-memory only. If admins want scopes to survive
restarts, they re-issue `/setdefaultscope` after restart. Phase 11
checkpointing could be extended in a follow-up, but Phase 12 keeps
the scope handler simple.

## Resolved questions

1. **What if `channel_to_scope` is called with a thread that has no
   parent?** Falls back to `str(channel)` (the thread's own name).
   Acceptable since `parent is None` is rare.

2. **What's `DEFAULT_SCOPE` used for?** Sentinel for "no scope set."
   Operations checking the active scope should treat it as "no
   tournament selected" and prompt the caller to set one (or use
   the channel-derived scope).

3. **Can a caller's scope be reset to "use channel default"?** Not
   in Phase 12 — once `set_scope` is called, the per-caller override
   persists. Phase 14 admin commands can add `/resetscope`.

4. **Scope-routing in handlers (ladder, tournament, checkin)?**
   Phase 12 exposes the handler API. Updating each caller to route
   through scope is a Phase 14 task; Phase 12 lays the groundwork.

## What's deferred

- **DB persistence for scope state** — Phase 11 checkpointing
  framework can be extended later if needed.
- **`/resetscope`** — clears per-caller override, falls back to
  channel default. Phase 14 admin commands.
- **Migrating existing commands** to use scope_handler.get_scope —
  Phase 14 wave.
- **Scope-aware tournament_state lookup** — TournamentState already
  has `get_tournament_by_scope(scope)`. Phase 12 just provides the
  scope-resolution layer; integration with the slash commands lands
  in Phase 14.
