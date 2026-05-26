# Phase 14: Tournament Discord commands

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 14.

Adds ~40 Discord slash commands wrapping the tournament-lifecycle
operations established in Phases 1-13. Each command resolves the
active tournament via the scope router (Phase 12), invokes the
appropriate Tournament / TournamentState method, and either responds
inline or emits effects through the existing `execute_effects` path.

Source commands live in `cmd_manager.py` (legacy non-Discord stub),
`io_manager.py` (the abstract `IOManager` parent that maps strings
→ methods), and `discord_manager.py` (the `DiscordManager(IOManager,
discord.Client)` child class layering Discord I/O on top). Target
already has `/versus`, `/solo`, scope commands, check-in lifecycle
commands, and PXL config; Phase 14 fills the gap.

Adds the `/help` to enumerate them all. Per source, the prefix was
`x!`. Target migrates all commands to `/` slash form for Discord
slash-command compat — no prefix variants.

## Files

| File | Change |
|---|---|
| `axi/handlers/discord_handler.py` | Add ~40 slash commands (Phase 14). Wire each to scope-routed Tournament/TournamentState. |
| `axi/handlers/tournament_handler.py` (NEW) | Pure layer — orchestrator helpers (`create_tournament`, `destroy_tournament`, `report_score`, etc.) that emit effects. Mirrors `ladder_handler` shape. |
| `axi/effects.py` | (Maybe) new effects for tourney-start/phase-start/phase-end/tourney-end announcements + bracket-result postings. |
| `tests/test_tournament_commands.py` (NEW) | End-to-end flows: /create → /preset → /adduser → /begin → /score → /placements → /advancephase → /destroy. Permission gating tests. |

## Command catalog

Each row lists: source command → target slash command, arg signature,
permissions, output destination. "Admin" = `@has_permissions
(ban_members=True)`; "Public" = open to all.

### Tournament lifecycle (create / preset / begin / advance / destroy)

| Source | Target | Args | Perms | Output |
|---|---|---|---|---|
| `x!create` | `/create` | `game: str = None, name: str = None, season: str = None` | Admin | channel: confirmation message |
| `x!destroy` | `/destroy` | (none) | Admin | channel: confirmation |
| `x!preset` | `/preset` | `name: str` (e.g. `"px"`, `"se"`, `"de"`) | Admin | channel: "Preset applied" |
| `x!begin` / `x!start` | `/begin` | `scopes: str = None` (comma-sep) | Admin | channel: tourney-start message |
| `x!advancephase` | `/advancephase` | (none) | Admin | channel: phase-start message |
| `x!undophase` | `/undophase` | (none) | Admin | channel: confirmation |

### Player management (add / remove / drop / dq / checkin)

| Source | Target | Args | Perms | Output |
|---|---|---|---|---|
| `x!adduser` | `/adduser` | `users: str` (mention or space-sep mentions) | Admin | channel: "Added N user(s)" |
| `x!removeuser` | `/removeuser` | `users: str` | Admin | channel: confirmation |
| `x!checkinuser` | `/checkinuser` | `username: User` | Admin | channel: confirmation |
| `x!dropuser` | `/dropuser` | `username: User` | Admin | channel: confirmation |
| `x!fulldropuser` | `/fulldropuser` | `username: User` | Admin | channel: confirmation |
| `x!dquser` | `/dquser` | `username: User` | Admin | channel: confirmation |
| `x!dropme` | `/dropme` | (none) | Public | channel: confirmation |
| `x!fulldropme` | `/fulldropme` | (none) | Public | channel: confirmation |
| `x!undodrop` | `/undodrop` | `username: User` | Admin | channel: confirmation |
| `x!undodq` | `/undodq` | `username: User` | Admin | channel: confirmation |

### Score / match reporting (report / score / win / lose / undomatch)

| Source | Target | Args | Perms | Output |
|---|---|---|---|---|
| `x!report` | `/report` (exists) | `winner: User, score: str` | Public | channel: confirmation |
| `x!score` | `/score` | `opponent: User, score: str` (e.g. `"2-0"`) | Public | channel: confirmation |
| `x!iwin` / `x!win` | `/win` (exists) | `score: str = None` | Public | channel: confirmation |
| `x!ilose` / `x!lose` | `/lose` (exists) | `score: str` | Public | channel: confirmation |
| `x!undomatch` | `/undomatch` | `player_a: User, player_b: User` | Admin | channel: confirmation |

### Status / placements / matches (read-only)

| Source | Target | Args | Perms | Output |
|---|---|---|---|---|
| `x!status` | `/status` (exists) | (none) | Public | channel: status text |
| `x!statusadmin` | `/statusadmin` | `username: User` | Admin | channel: status text |
| `x!matches` | `/matches` | `username: User = caller` | Public | channel: match list |
| `x!mymatches` | `/mymatches` | (none) | Public | channel: caller's matches |
| `x!placements` | `/placements` | (none) | Public | channel: ordered placements |
| `x!poolscores` | `/poolscores` | (none) | Public | channel: pool scores (RR only) |
| `x!round` | `/round` | `r: int` | Public | channel: matches in round R |
| `x!current` | `/current` | (none) | Public | channel: current matches |
| `x!bracket` | `/bracket` | (none) | Public | channel: link to bracket (Phase 15 hooks in PNG) |
| `x!stream` | `/stream` | (none) | Public | channel: stream queue |
| `x!format` | `/format` | (none) | Public | channel: tournament's format string |
| `x!info` | `/info` (per-game info) | (none) | Public | channel: current double-blind game info |

### Series + multibracket (admin organizational)

| Source | Target | Args | Perms | Output |
|---|---|---|---|---|
| `x!setseries` | `/setseries` | `sid: int` | Admin | channel: confirmation |
| `x!createseries` | `/createseries` | `name: str, season: str, game: str, pinned_channel: TextChannel` | Admin | channel: created series id |
| `x!createmultibracket` | `/createmultibracket` | `name: str` | Admin | channel: created multibracket id |

### Misc admin (events / rng / breaks / queue / sql / verify)

| Source | Target | Args | Perms | Output |
|---|---|---|---|---|
| `x!events` | `/events` | (none) | Public | channel: list of scheduled Discord events |
| `x!setrng` | `/setrng` | `seed: int` | Admin | channel: confirmation |
| `x!takeabreak` | `/takeabreak` | (none) | Public | channel: confirmation |
| `x!forcebreak` | `/forcebreak` | `username: User` | Admin | channel: confirmation |
| `x!forcequeue` | `/forcequeue` | `username: User, scopes: str = None` | Admin | channel: confirmation |
| `x!clearchannel` | `/clearchannel` | (none) | Admin | channel: deletes all messages in channel |
| `x!verify` | `/verify` | `printouts: bool = True` | Admin | channel: verification report |
| `x!sql` | `/sql` | `query: str` | Admin | channel: query rows (truncated) |

### Misc (rules / elements / spells / resign / stopspectate / setstreamer)

| Source | Target | Args | Perms | Output |
|---|---|---|---|---|
| `x!rules` | (exists in source `io_manager`) — `/help` covers it | — | Public | channel |
| `x!elements` | `/elements` | (none) | Public | channel: elements table emoji art |
| `x!spells` | `/spells` (alias of `/info`) | (none) | Public | channel: spell list for active game |
| `x!resign` | `/resign` | (none) | Public | DM: handle double-blind resign |
| `x!stopspectate` | `/stopspectate` | (none) | Public | DM: stop spectating double-blind |
| `x!setstreamer` | `/setstreamer` (exists) | `username: User` | Admin | channel: confirmation |

Total new commands added in Phase 14: **38** (target already had
`/report`, `/win`, `/lose`, `/setstreamer`, `/status`, `/setscope`,
`/setdefaultscope`, `/getscope`, `/allscopes`, `/createcheckins`,
`/reacts`, `/addfromreacts`, `/mentionfromreacts`, `/checkin`,
`/here`, `/yes`, `/no`, `/createfromconfig`, `/clearevents` from
prior phases). Net catalog after Phase 14: ~60 slash commands.

## Tournament handler (NEW pure layer)

`axi/handlers/tournament_handler.py` mirrors the
`ladder_handler` / `checkin_handler` shape: pure functions taking
(caller, guild, channel, scope, ...) and returning effects.

Key functions:

```python
def create_tournament(scope, guild_id, game, name, season=None, channel=None):
    """Create a Tournament instance, register in tournament_state,
    bind to scope. Returns effects (SendToChannel announcement)."""

def destroy_tournament(scope):
    """Remove the scope's tournament from tournament_state. Returns
    effects (channel confirmation)."""

def apply_preset(scope, preset_name):
    """Apply a tournament_presets entry to the scope's tournament.
    Returns effects (preset-applied confirmation)."""

def begin(scope):
    """Call tournament.begin() and emit phase-start announcement."""

def advance_phase(scope):
    """Call tournament.advance_phase() and emit phase-start
    announcement."""

def undo_phase(scope):
    """Reverse the most recent phase advance."""

def add_players(scope, user_ids):
    """Add players to the tournament."""

def remove_players(scope, user_ids):
    """Remove players (only valid before begin())."""

def drop_user(scope, user_id):
    """Mark a user as dropped for the current phase."""

def dq_user(scope, user_id):
    """Disqualify a user."""

def report_score(scope, reporter_id, p0_id, p1_id, score_str):
    """Validate + record the score for the active match between p0/p1."""

def undo_match(scope, p0_id, p1_id):
    """Undo a recorded match between p0/p1 (cascades through
    children)."""

def get_status(scope, user_id):
    """Return status text for a user in this tournament."""

def get_placements(scope):
    """Return ordered placements list."""

def get_matches_for_round(scope, round_n):
    """Return all matches in round R."""

def get_matches_for_player(scope, user_id):
    """Return all matches for a player."""
```

Each returns a list of effects + structured text. The Discord adapter
wraps each in a slash command, resolves the scope from `ctx.channel`
via `tournament_state.get_scope(...)`, and calls execute_effects.

## Scope routing

Each slash command computes `scope = tournament_state.get_scope(
ctx.user, ctx.guild, ctx.channel)` and then either:
- Calls `tournament_state.get_tournament_by_scope(scope)` to fetch
  the active Tournament; OR
- Calls `ladder_handler.state.ladders[(guild_id, scope)]` to fetch
  a Ladder for ladder-specific commands.

If no tournament/ladder exists for the scope, the slash command
responds with a polite "no active tournament in this channel" rather
than failing.

## Permission gating

All admin commands use Discord's existing
`@has_permissions(ban_members=True)` decorator. The source's 3-tier
role hierarchy (SU/ADMIN/STAFF) is **NOT** ported — already decided in
Phase 12. Admin commands map roughly to the source's
`self.admin_commands` + `self.staff_commands` sets.

Per source:

- **admin**: create, destroy, clearallevents, clearchannel, sql
- **staff**: setdefaultscope, preset, begin, report, adduser,
  removeuser, checkinuser, dropuser, fulldropuser, dquser,
  createcheckins, addfromreacts, mentionfromreacts, setrng,
  forcebreak, forcequeue, setseries, createseries, createmultibracket,
  createfromconfig

Phase 14 treats **both** tiers as `ban_members=True` — there's no
benefit to splitting them further when both involve "TO-level" control
over the tournament. Anyone without `ban_members` can still use the
public commands (status, matches, mymatches, placements, score, etc.).

## Effects (new dataclasses)

```python
@dataclass
class AnnouncePhaseStart:
    guild_id: int
    channel_name: str
    phase_name: str
    player_mentions: list

@dataclass
class AnnouncePhaseEnd:
    guild_id: int
    channel_name: str
    phase_name: str
    placements: list   # [(rank, user_mention)]

@dataclass
class AnnounceTourneyStart:
    guild_id: int
    channel_name: str
    title: str
    format: str

@dataclass
class AnnounceTourneyEnd:
    guild_id: int
    channel_name: str
    title: str
    winner_mention: str
```

The slash commands emit these; the adapter routes them through
`send_long(channel, text)`. Most of Phase 14's surface is text-only —
no new image effects beyond what Phase 15 brings.

## Test plan

`tests/test_tournament_commands.py`:

1. **End-to-end happy path** — simulate a full SE tournament via the
   commands: `/create rps` → `/preset se` → `/adduser ×4` →
   `/begin` → `/score ×3` → `/placements` → `/destroy`. Verify state
   transitions are correct.

2. **Scope routing per command** — for each admin command, verify
   it routes to the correct tournament when multiple tournaments
   coexist in a guild (different scopes).

3. **Permission gating** — verify each admin command's
   `@has_permissions(ban_members=True)` decorator is present. (Static
   check via inspecting `__discord_app_commands_default_member_permissions__`
   on the command object — the decorator sets this.)

4. **No-tournament edge case** — calling `/score` / `/begin` /
   `/placements` etc. when no tournament exists in scope returns a
   user-facing "no active tournament" message without error.

5. **Undo cascades** — `/undomatch` between p0/p1 reverses both their
   match and any descendants; `/undodrop` re-adds a dropped user;
   `/undodq` lifts a DQ. Each verified by checking the resulting
   Tournament state.

6. **Pure-handler tests** — `tournament_handler.create_tournament`,
   `report_score`, `add_players`, etc. tested in isolation via
   mocked guild/channel objects.

## Major decisions

### A. Slash command implementation, no prefix migration

Source's `x!` prefix commands are entirely replaced by Discord slash
commands. No backwards-compat layer. Users adapt to `/cmd` form.

### B. Admin = `ban_members=True`, no role hierarchy

Decided in Phase 12. Single admin tier; no SU/STAFF distinction.

### C. New pure-layer `tournament_handler.py`

Most slash commands today live as inline functions in
`discord_handler.py`. Phase 14 moves the orchestration logic (the
"what should happen?" decision) into a pure-layer
`tournament_handler.py` that returns effects. The slash command
becomes a thin wrapper: scope resolution → handler call → effect
dispatch.

### D. Generic /score; defer per-game score parsing nuances

Source has per-game score handling (RPS scores work differently than
Smash scores). Phase 14 treats `/score @user 2-0` as the canonical
form (X-Y); the MatchNode validation already accepts this.

### E. Skip RPS-Skew / Stance Game / wandgame / wwpve / wwcpu

Already dropped per user. Target's `/versus rps`, `/solo wonderwand`,
etc., cover per-game launchers via the existing registry.

### F. `/current` and `/bracket` are aliases (text + PNG)

Source has both. Target's `/bracket` shows the bracket image (Phase
15 implements PNG render); `/current` shows the text-status list of
active matches. They share routing but differ in output.

### G. `/sql` is admin-only and raw

Mirrors source. No SQL-injection guard — admins are trusted; we don't
expose `/sql` to public users.

### H. `/spells` aliases `/info` for the current double-blind game

Source has both as aliases. We keep both for parity.

## Resolved questions

1. **What if `/create` is called without a `game` arg?**
   Source defaults to the channel scope (e.g. `rps-bracket` → game
   = `rps`). We follow.

2. **What if `/begin` is called with `scopes` arg listing multiple
   scopes?** Source iterates and calls `beginmany(...)`. Target
   resolves each scope via `tournament_state.get_tournament_by_scope`
   and calls `begin()` on each.

3. **What's the channel argument for `/score`?** Always the channel
   where the slash command was invoked. The tournament for that
   scope is resolved automatically.

4. **What if both players type `/score` with different scores?**
   Source treats the second as a confirmation (only accepts if it
   matches the first). Target follows — `MatchNode.report_score`
   already requires reciprocal X-Y / Y-X reports.

5. **What's `/forcequeue` for in a tournament context?** Ladder /
   LadderElimination only — forces a user into the matchmaking
   queue. Tournament has no queue concept (matches are
   bracket-determined).

6. **What's `/forcebreak`?** Same; ladder-specific. Removes a user
   from the queue and marks them on break.

7. **What's `/setrng`?** Reseeds the active tournament's RNG (used
   for tiebreak coin flips). Mostly a debugging aid.

8. **`/clearchannel` semantics?** Deletes all messages in the
   current channel. Used for resetting the post-event channel.
   Admin-only. The `channel.purge()` API call requires `manage_messages`
   permission for the bot itself.

9. **What does `/info` show for tournament commands (vs. game
   commands)?** Source has overlapping semantics — both for the
   game (DM-game double-blind info) and for the tournament
   (current bracket info). We keep both but in different channels:
   `/info` in a DM channel = game info; `/info` in a tournament
   channel = `/current` aliased.

## What's deferred

- **PNG bracket rendering** — Phase 15.
- **Per-game custom score parsing** — Phase 14 uses generic X-Y.
- **DB persistence for in-memory scope/admin state** — Phase 14
  doesn't add it; Phase 11's `register_startup_callback` framework
  can be wired later if needed.
- **/listcommands** explicit catalog command — `/help` covers it.
- **/setseries** linking to existing series-by-name lookup — Phase
  14 takes `sid: int` raw; admin can use `/sql` to look up the id
  if needed. Phase 16 admin commands could add a name lookup.
- **Slash autocomplete** for preset names + game names + scope
  names — Phase 14 takes raw strings; autocomplete is a nice-to-have
  for a follow-up.
