# Phase 9: Event check-in lifecycle (complete the hybrid)

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 9.

Phase 9 completes the hybrid event lifecycle: Discord scheduled
events + reaction-based check-in posts work together as a coupled
flow. The target currently uses scheduled events minimally (one
callsite in `/ladder`). Phase 9 ports the check-in flow from source
so admins can run the full "announce → check-in → reminder → begin
→ close" cycle.

## Scope

- New `axi/handlers/checkin_handler.py` — Discord-coupled handler
  (lives in `axi/handlers/`, alongside `ladder_handler` and
  `discord_handler`) for the check-in lifecycle operations.
- New slash commands in `axi/handlers/discord_handler.py`:
  - `/createcheckins` — post the check-in announcement with thumbs-up
    reaction; save message id on the tournament.
  - `/checkinsreminder` — ping RSVPs missing from checkins
    (typically 5 min before start).
  - `/addfromreacts` — read reactions on the check-in post; add
    users to the tournament's player list.
  - `/listcheckins` — print the current check-in list.
  - `/beginallevents` — for a given event time, begin all
    multi-bracket events tied to it (uses Phase 8 multibrackets).
  - `/clearannouncement` — clean up the announcement post.
- New effects in `axi/effects.py`:
  - `EditScheduledEvent(event_id, description)` — adapter calls
    `event.edit(description=...)`.
  - `FetchReactionsForCheckins(node_or_tourney_id, message_id, channel_id)`
    — adapter fetches reaction users and routes back via
    `checkin_handler.receive_reactions(...)`.
  - `MentionMissingCheckins(channel_id, user_ids, event_name)` —
    adapter posts a "5 min until ladder opens, react if you want to
    join" reminder pinging the missing users.
- `Tournament` gains `checkins_post_id: int | None = None` field
  (set when `/createcheckins` posts).
- `Ladder` gains the same field (since ladders also use the flow).
- Tests cover effect-emission shapes, list-checkins formatting, and
  `addfromreacts` integration with the existing `add_players` /
  `add_new_player` paths.

## Files

| File | Change |
|---|---|
| `axi/handlers/checkin_handler.py` (NEW) | Lifecycle ops as functions returning effect lists. |
| `axi/handlers/discord_handler.py` | Add ~6 slash commands wiring to checkin_handler. |
| `axi/effects.py` | Add 3 new effect dataclasses. |
| `axi/tournament.py` | Add `checkins_post_id: int | None = None`. |
| `axi/ladder.py` | Add `checkins_post_id = None` attribute. |
| `tests/test_checkin_handler.py` (NEW) | Effect-emission + flow tests. |

## Source ↔ target mapping

| Source method | Target equivalent |
|---|---|
| `create_checkins_post(caller, guild, channel, event, start_time)` | `checkin_handler.create_checkins(scope, event_id, start_time, signup_user_ids)` → emits `SendToChannel` + `AddReaction` |
| `final_checkins_reminder(caller, guild, channel, event)` | `checkin_handler.final_reminder(scope, event_id, event_name, signup_user_ids, current_checkin_user_ids)` → emits `MentionMissingCheckins` |
| `list_checkins(caller, guild, channel, event_id)` | `checkin_handler.list_checkins(scope, current_checkin_user_ids)` → emits `SendToChannel` |
| `addfromreacts(caller, guild, channel, msg_id)` | `checkin_handler.add_from_reacts(scope, reaction_user_ids)` → calls `tournament.add_players(...)` directly (pure) |
| `mentionfromreacts(caller, guild, channel, msg_id)` | `checkin_handler.mention_from_reacts(scope, reaction_user_ids)` → emits `SendToChannel` |
| `begin_all_events(caller, guild, scheduled_events_and_announcement)` | `checkin_handler.begin_all_events(event_ids, channel_ids)` → emits `EditScheduledEvent` per event + delegates to `tournament.begin()` |
| `get_reacts_on_msg(caller, guild, channel, msg_id)` | NOT a pure-layer concern. The Discord adapter fetches reactions when consuming `FetchReactionsForCheckins`, then routes results back to `checkin_handler.receive_reactions(...)`. |

## Architecture: pure-layer vs Discord-coupled split

Source mixes Discord I/O (`event.users()`, `channel.fetch_message`,
`reaction.users()`) with business logic in single methods. Target
separates them:

1. **Business logic** in `checkin_handler` (pure layer): given a list
   of signup user IDs and current checkin user IDs, compute the diff,
   emit a `MentionMissingCheckins` effect with the missing user IDs.
2. **Discord I/O** in the adapter (`discord_handler` slash commands):
   - Fetch the message + reactions via `channel.fetch_message(msg_id)`
     and `reaction.users()`.
   - Pass the resulting user-ID list to the pure handler.
   - Execute returned effects via `execute_effects(effects)`.

`FetchReactionsForCheckins` is the asymmetric effect: it doesn't
"send" — it requests data. The adapter resolves it inline (already
in-context) rather than via callback. So actually we can omit this
effect: the discord_handler slash command does the fetch directly,
then calls the pure handler with the result. Cleaner.

**Revised pattern:** slash commands do the Discord-side data fetch
(reaction users, event signups), then call the pure-layer handler
with extracted IDs. The handler emits effects for the response.

## Algorithm port (per command)

### `/createcheckins event_id`

Slash handler:
1. Fetch the event by id; get `event.users()` → list of signup user
   IDs.
2. Resolve the tournament for this scope.
3. Call `checkin_handler.create_checkins(scope, event_id, start_time,
   signup_user_ids)` → returns effects.
4. Execute effects. One of them sends a `SendToChannel` whose
   message-id the adapter captures and stores on `tournament.checkins_post_id`.
5. The adapter posts a thumbs-up reaction on that message (via
   `AddReaction` effect).

### `/checkinsreminder event_id`

Slash handler:
1. Fetch `event.users()` (signups) + `channel.fetch_message(checkins_post_id).reactions[0].users()` (current checkins).
2. Call `checkin_handler.final_reminder(scope, event_name, signup_user_ids,
   checkin_user_ids)` → emits `SendToChannel` with the missing-users
   ping message.

### `/addfromreacts`

Slash handler:
1. Fetch reactions on `checkins_post_id`; get user IDs (excluding bots).
2. Call `checkin_handler.add_from_reacts(scope, reaction_user_ids)`.
3. The handler resolves each user_id → User instance, calls
   `tournament.add_players(...)` or `ladder.add_new_player(user)`.

### `/listcheckins`

Slash handler:
1. Fetch reactions → user IDs.
2. Call `checkin_handler.list_checkins(scope, user_ids)` → emits
   `SendToChannel` with the formatted list.

### `/beginallevents event_time`

Slash handler:
1. Find all scheduled events at this time (multibracket support).
2. For each, call `checkin_handler.add_from_reacts` first to ingest
   late check-ins.
3. Call `tournament.begin()` for each.
4. Emit `EditScheduledEvent` per event with the "THE LADDER HAS BEGUN!"
   description.

### `/clearannouncement`

Slash handler — simple: post a cleanup message to the announcement
channel; no business logic.

## New effects

```python
@dataclass
class EditScheduledEvent:
    """Edit a Discord scheduled event's description."""
    event_id: int
    description: str


@dataclass
class MentionMissingCheckins:
    """Post a reminder pinging RSVPs missing from checkins."""
    guild_id: int
    channel_name: str
    user_ids: list           # missing users
    event_name: str
    minutes_until_open: int = 5


@dataclass
class AddReaction:
    """Add a unicode emoji reaction to a recently-sent message.
    The adapter captures the most-recent SendToChannel/SendUserMessages
    result and applies the reaction."""
    target_message_id: int
    emoji: str               # e.g. '\\N{THUMBS UP SIGN}'
```

## `axi/handlers/checkin_handler.py` shape

```python
"""Check-in lifecycle handler (Phase 9).

Pure layer — receives Discord-fetched data (signup user IDs, reaction
user IDs) and emits effects for the response. The Discord adapter
(discord_handler slash commands) does the live fetching.
"""

from axi.effects import (
    SendToChannel, AddReaction, MentionMissingCheckins,
    EditScheduledEvent,
)


def create_checkins(scope, event_id, start_time, signup_user_ids,
                    pinned_channel_name, guild_id):
    """Build the check-in announcement post + thumbs-up reaction."""
    msg = f"*Ladder opens:* {_fmt_time(start_time)} PT.\n"
    msg += "*Check in:* Just react to this post :+1:\n"
    if signup_user_ids:
        msg += ", ".join(f"<@{uid}>" for uid in signup_user_ids)
        msg += ", and anyone else!\n"
    effects = [
        SendToChannel(guild_id=guild_id,
                      channel_name=pinned_channel_name,
                      messages=[(msg, None)]),
        AddReaction(target_message_id=None,  # adapter resolves to last send
                    emoji='\N{THUMBS UP SIGN}'),
    ]
    return effects


def final_reminder(scope, event_id, event_name, signup_user_ids,
                   checkin_user_ids, pinned_channel_name, guild_id,
                   minutes_until_open=5):
    missing = list(set(signup_user_ids) - set(checkin_user_ids))
    return [
        MentionMissingCheckins(
            guild_id=guild_id,
            channel_name=pinned_channel_name,
            user_ids=missing,
            event_name=event_name,
            minutes_until_open=minutes_until_open,
        ),
    ]


def add_from_reacts(scope, reaction_user_ids, axi_users):
    """`axi_users` is a list of AxiUser instances pre-resolved from
    the reaction user IDs by the adapter. The handler calls the
    pure-layer add_players method on the tournament for this scope."""
    from axi.tournament_state import state as tstate
    tournament = tstate.get_tournament_by_scope(scope)
    if tournament is None:
        return []
    tournament.add_players(axi_users)
    return []  # No effects from a player-add by itself.


def mention_from_reacts(scope, reaction_user_ids, channel_name, guild_id):
    msg = " ".join(f"<@{uid}>" for uid in reaction_user_ids)
    return [SendToChannel(guild_id=guild_id, channel_name=channel_name,
                          messages=[(msg, None)])]


def list_checkins(scope, checkin_user_ids, pinned_channel_name, guild_id):
    msg = "Check-ins are complete. If you would still like to enter, " \
          "consider bribing the TOs, or groveling.\n"
    msg += "CHECKED IN:\n"
    for uid in checkin_user_ids:
        msg += f"<@{uid}>\n"
    msg += "\n"
    return [SendToChannel(guild_id=guild_id,
                          channel_name=pinned_channel_name,
                          messages=[(msg, None)])]


def begin_all_events(event_ids, scopes, axi_users_by_scope):
    """For each scoped tournament: add late reacters as players,
    then call tournament.begin(). Returns combined effects."""
    from axi.tournament_state import state as tstate
    effects = []
    for event_id, scope in zip(event_ids, scopes):
        tournament = tstate.get_tournament_by_scope(scope)
        if tournament is None:
            continue
        tournament.add_players(axi_users_by_scope.get(scope, []))
        effects += tournament.begin()
        effects.append(EditScheduledEvent(
            event_id=event_id,
            description=f"THE LADDER HAS BEGUN!\n"
                        f"Use this command to join late: **/queue {tournament.title}**",
        ))
    return effects


def _fmt_time(timestamp):
    from datetime import datetime
    return datetime.fromtimestamp(timestamp).strftime('%A, %B %d. %I:%M %p')
```

## Tournament + Ladder field additions

```python
# axi/tournament.py
class Tournament:
    def __init__(self, ...):
        ...
        self.checkins_post_id = None  # Set by /createcheckins

# axi/ladder.py
class Ladder(MatchGraph):
    def __init__(self, ...):
        ...
        self.checkins_post_id = None
```

Single nullable int. No DB persistence in Phase 9 (Phase 11
checkpointing handles it).

## Test plan

`tests/test_checkin_handler.py`:

1. **`TestCreateCheckins`** — given signup user IDs, returns
   `SendToChannel` with the formatted message + `AddReaction` with
   `\N{THUMBS UP SIGN}`. Single-user case + multi-user case + empty case.

2. **`TestFinalReminder`** — given signups and checkins sets, emits
   `MentionMissingCheckins` with the SET DIFFERENCE (signups - checkins).
   Empty-diff case → still emits reminder (with empty user list).

3. **`TestAddFromReacts`** — given pre-resolved AxiUsers, calls
   `tournament.add_players(...)`. Verify the tournament's `.players`
   list grew. No effects returned.

4. **`TestMentionFromReacts`** — returns `SendToChannel` with all
   user mentions space-separated.

5. **`TestListCheckins`** — returns formatted list. Empty case
   still works.

6. **`TestBeginAllEvents`** — for each scope, calls tournament.begin(),
   emits `EditScheduledEvent` with the post-begin description, returns
   combined effects.

7. **`TestEffectShapes`** — verify the 3 new effect dataclasses
   construct correctly with the documented fields.

8. **`TestTournamentCheckinsPostId`** — `Tournament` and `Ladder` both
   have `checkins_post_id = None` initially; setter sets it.

## Major decisions

### A. Pure-layer handler + Discord-coupled slash commands

`checkin_handler` does NO direct Discord I/O — only consumes
pre-fetched user IDs and emits effects. Slash commands in
`discord_handler` do the Discord-side fetching. This keeps the
"effects are pure data" invariant.

### B. `AddReaction` resolves target via "most recent send" convention

The pattern is: SendToChannel → AddReaction. The adapter applies the
reaction to the message it just posted. `target_message_id` is
nullable — if None, adapter uses the most-recent message id from the
preceding SendToChannel in the same execute_effects batch. (Phase 14
formalizes via explicit chain IDs if needed.)

### C. `FetchReactionsForCheckins` effect NOT introduced

Slash commands have direct access to `ctx.guild` / `channel.fetch_message`.
They fetch reactions inline rather than emitting a fetch effect. Keeps
the effect catalog focused on output.

### D. `checkins_post_id` on Tournament + Ladder

Source stores `tourney.checkins_post_id`. We follow. Both Tournament
and Ladder need it since both can have check-in flows. No DB
persistence in Phase 9 (Phase 11 handles).

### E. `begin_all_events` works for multibracket events

When multiple events scheduled at the same time (multibracket per
Phase 8), `begin_all_events` iterates them all. Single-event case
just iterates a 1-element list.

### F. Time formatting hard-codes PT

Source uses `strftime('%A, %B %d. %I:%M %p')` + "PT" suffix. We
follow exactly for source compat. Phase 13 PXL config can override
per-config if needed.

## Resolved questions

1. **Where do `checkins_post_id` and `scheduled_event` get persisted?**
   Phase 11 (checkpoint/undo) handles DB persistence holistically.
   Phase 9 keeps them in-memory only.

2. **Can a ladder + tournament share the same `checkins_post_id`?**
   No — each is its own scope. Distinct fields.

3. **What about emoji other than thumbs-up?** Source hardcodes
   `\\N{THUMBS UP SIGN}`. We follow. Phase 13 PXL config can override
   later.

4. **What if `event.users()` returns 0 signups?** `create_checkins`
   still posts the announcement (no signups listed; just "react to
   join").

5. **What if the check-ins post is deleted?** `addfromreacts` /
   `final_reminder` would fail at the Discord fetch step. The slash
   command catches and reports; the pure handler never sees the
   error. No state corruption since we only mutate on successful
   reaction-list ingestion.

## What's deferred

- **Phase 11 (checkpointing):** persisting `checkins_post_id` +
  scheduled_event ids across restarts.
- **Phase 13 (PXL config):** declarative event schedules
  (`/createfromconfig` parses event times + scopes + games).
- **Phase 14 (Discord cmds):** the full ~40-command admin surface
  including `/setupfromevents` (source method `setupfromevents` at
  discord_manager.py:894 — schedules the full lifecycle via the
  async scheduler).
- **Async scheduler integration** — source uses `axi._async_scheduler`
  to schedule `final_checkins_reminder` and `begin_all_events` at
  precise event times. Phase 11's DB-backed scheduler replaces this.
  Phase 9 exposes the operations as manual slash commands; admin
  triggers them at the right times until Phase 11 lands automation.
