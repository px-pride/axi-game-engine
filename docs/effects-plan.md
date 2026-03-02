# Effects System Plan — Discord I/O Separation

## Goal

Separate Discord I/O from business logic so that match lifecycle, ladder
orchestration, and game logic can be tested by calling pure functions and
asserting on returned effect lists. No mocks, no fakes, no Discord connection
required.

---

## Current I/O Call Sites

Every Discord I/O call that is currently interleaved with business logic:

### match_handler.py

| Function | Line | I/O Operation |
|---|---|---|
| `process_decision` | 49 | `send_long(user, msgs)` — feedback DM to player |
| `process_command` | 75 | `send_long(user, msgs)` — command response DM |
| `process_round` | 85 | `send_long(p, msgs)` — round results to each agent |
| `process_round` | 96-99 | Register `decision_msgs_to_matches` + `add_reaction(o)` — present options |
| `close_match` | 108 | `send_long(p, msgs)` — final DM messages |
| `close_match` | 113 | `match.discord_thread.edit(archived=True)` — archive thread |
| `close_match` | 114-116 | `send_long(results_channel, result_text)` — post result |
| `close_match` | 123 | `ladder_handler.update_ladders()` — trigger UI refresh |
| `cancel_match` | 127 | `match.discord_thread.edit(archived=True)` — archive thread |
| `cancel_match` | 136 | `ladder_handler.update_ladders()` — trigger UI refresh |
| `resolve_checkins` | 142-143 | `send_long(thread, timeout_msg)` — checkin expired notice |

### ladder_handler.py

| Function | Line | I/O Operation |
|---|---|---|
| `matchmaking` | 131-134 | `schedule_handler.schedule_event(...)` — schedule checkin timer |
| `call_matches` | 460 | `get(l.guild.channels, ...)` — Discord channel lookup |
| `call_matches` | 462 | `discord_handler.create_versus_match_ux(...)` — full match UX |
| `push_ladder_updates` | 640-641 | `update_status_channel` + `update_leaderboard_channel` |
| `update_ladders` | 450 | `schedule_handler.schedule_event(...)` — delayed self-echo |

### discord_handler.py (adapter-side, stays as I/O)

| Function | What it does |
|---|---|
| `send_long` | Recursive message splitter + Discord send |
| `create_versus_match_ux` | Thread creation, DM init, reaction setup |
| `update_status_channel` | Build + send/edit status display |
| `update_leaderboard_channel` | Build + send/edit leaderboard, edit nicknames |

---

## Effect Types

New file: `axi/effects.py`

Each effect is a plain dataclass with no Discord imports. Effects describe
*what should happen*, not *how*.

```python
from dataclasses import dataclass, field

@dataclass
class SendUserMessages:
    """Send text/file messages to a user via DM."""
    user_id: int
    messages: list       # [(text, file_path), ...]

@dataclass
class SendToThread:
    """Send messages to a match's thread."""
    match_id: str
    messages: list       # [(text, file_path), ...]

@dataclass
class SendToChannel:
    """Send messages to a named channel in a guild."""
    guild_id: int
    channel_name: str
    messages: list       # [(text, file_path), ...]

@dataclass
class PresentDecision:
    """Send messages to a user DM and attach emoji reaction options.
    The adapter sends the messages, tracks the last message as a
    decision message for the match, and adds the emoji reactions."""
    user_id: int
    match_id: str
    messages: list       # [(text, file_path), ...]
    options: list        # [emoji, ...]

@dataclass
class CreateMatchThread:
    """Create a Discord thread for a thread game match."""
    match_id: str
    guild_id: int
    channel_name: str
    thread_name: str
    init_messages: list  # [(text, file_path), ...]
    stream_notice: str | None = None

@dataclass
class ArchiveThread:
    """Archive a match's Discord thread."""
    match_id: str

@dataclass
class UpdateLadderUI:
    """Refresh status channel and leaderboard channel for a ladder."""
    ladder_id: str

@dataclass
class ScheduleCallback:
    """Schedule a delayed operation."""
    delay_seconds: float
    callback_name: str   # identifies which operation to run
    callback_args: dict  # serializable args
```

### Why these types

- **SendUserMessages** — covers all DM sends (decision feedback, command
  responses, final match messages, spectator notifications).
- **SendToThread** — covers in-thread messages (checkin expired, etc.).
- **SendToChannel** — covers posting to results/queue channels.
- **PresentDecision** — collapses the "send messages + register decision
  message + add reactions" sequence into one semantic effect. The adapter
  handles the Discord mechanics (save returned message object, map it to the
  match, add emoji reactions). This solves the sequential dependency where
  the pure function can't know the Discord message ID.
- **CreateMatchThread** — collapses "create thread + save thread mapping +
  send init messages + optionally send stream notice" into one effect.
- **ArchiveThread** — the adapter resolves match_id to the Discord thread.
- **UpdateLadderUI** — the adapter rebuilds and posts/edits the status and
  leaderboard displays. The rendering logic (building the status string,
  leaderboard string, nickname edits) stays in the adapter since it's purely
  a Discord presentation concern.
- **ScheduleCallback** — replaces direct `schedule_handler.schedule_event()`
  calls. The adapter translates this into actual scheduling.

### What is NOT an effect

- **State mutations** (registering users, advancing ladders, updating
  ratings) — these happen inside the pure functions.
- **CPU decisions** — `AbstractCPU.compute()` is pure. The pure function
  calls it inline and recurses (see below).
- **Database writes** — these are side effects but are tightly coupled to
  state mutations. For now, DB calls stay inline in the pure functions.
  Separating DB is a future card if needed.

---

## Function Transformations

### match_handler.py

Every function becomes **sync** and returns `list[Effect]`.

#### `process_decision(user, decision) -> list[Effect]`

Current: async, calls `send_long`, may call `process_round` or `close_match`.

New:
```
def process_decision(user, decision):
    effects = []
    match = lookup_match(user)
    accepted = match.validate_decision(user, decision)
    messages = match.flush_message_queue(user)
    if messages and not isinstance(user, AbstractCPU):
        effects.append(SendUserMessages(user_id=user.uid.id, messages=messages))
    if decision == "abort":
        unregister_user(user)
    if not accepted:
        return effects
    if match.check_all_decisions_in():
        if match.check_match_over():
            effects += close_match(match)
        else:
            effects += process_round(match)
    return effects
```

#### `process_round(match) -> list[Effect]`

Current: async, sends messages, registers decision messages, adds reactions,
handles CPU recursion.

New:
```
def process_round(match):
    effects = []
    match.match_step()
    for p in match.agents():
        messages = match.flush_message_queue(p)
        if messages and not isinstance(p, AbstractCPU):
            # Messages will be sent as part of PresentDecision or just
            # SendUserMessages depending on whether player needs to decide
            pass  # see below
    match.refresh_decisions()
    if match.check_match_over():
        effects += close_match(match)
    else:
        for p in match.players:
            messages = ...  # already flushed above, need to capture per-player
            if isinstance(p, AbstractCPU):
                decision = p.compute(copy(match.get_options(p)))
                effects += process_decision(p, decision)  # recursive, pure
            else:
                if match.expected_num_decisions[p] > 0:
                    effects.append(PresentDecision(
                        user_id=p.uid.id,
                        match_id=id(match),  # or a proper match ID
                        messages=messages,
                        options=match.get_options(p)))
                elif messages:
                    effects.append(SendUserMessages(
                        user_id=p.uid.id, messages=messages))
    return effects
```

Key insight: the message flush and decision presentation must be coordinated.
Currently `process_round` flushes messages for ALL agents first, then handles
decisions. The refactored version needs to capture per-player messages before
flushing, then either wrap them in `PresentDecision` (if the player needs to
decide) or `SendUserMessages` (if they don't).

#### `close_match(match) -> list[Effect]`

Current: async, sends final DMs, archives thread, posts result, updates ladder.

New:
```
def close_match(match):
    effects = []
    if isinstance(match, AbstractDmGame):
        for p in match.agents():
            messages = match.flush_message_queue(p)
            if messages and not isinstance(p, AbstractCPU):
                effects.append(SendUserMessages(user_id=p.uid.id, messages=messages))
        unregister_dm_match(match)
    elif isinstance(match, ThreadGame):
        effects.append(ArchiveThread(match_id=id(match)))
        effects.append(SendToChannel(
            guild_id=match.ladder.guild.id,
            channel_name=match.ladder.results_channel,
            messages=[(f"{match.winner()} defeats {match.loser()}!\n", None)]))
        unregister_thread_match(match)
    if match.ladder:
        match.ladder.advance(match)
        effects.append(UpdateLadderUI(ladder_id=id(match.ladder)))
    return effects
```

#### `cancel_match(match) -> list[Effect]`

Same pattern as `close_match` — returns effects for archiving + UI update.

#### `resolve_checkins(match) -> list[Effect]`

```
def resolve_checkins(match):
    effects = []
    if isinstance(match, ThreadGame):
        for p in match.players:
            if p not in match.checkins:
                effects.append(SendToThread(
                    match_id=id(match),
                    messages=[("Check-in timer expired. Aborting match.\n", None)]))
                effects += cancel_match(match)
                return effects
    return effects
```

#### `process_command(user, command) -> list[Effect]`

```
def process_command(user, command):
    effects = []
    match = lookup_match(user)
    if match.receive_command(user, command):
        messages = match.flush_message_queue(user)
        if messages and not isinstance(user, AbstractCPU):
            effects.append(SendUserMessages(user_id=user.uid.id, messages=messages))
    return effects
```

#### `launch_match(name, players, ...) -> (match, list[Effect])`

Currently returns just the match. After refactoring, also returns effects for
the match UX setup.

For DM games:
```
effects per player:
    - PresentDecision (if human with decisions)
    - SendUserMessages (if human without decisions, e.g. spectator init)
    - CPU decisions computed inline
```

For thread games:
```
effects:
    - CreateMatchThread(...)
```

This moves `create_versus_match_ux` logic from discord_handler into the pure
layer (as effect generation), with the actual Discord operations in the adapter.

### ladder_handler.py

#### `call_matches() -> list[Effect]`

Current: iterates called matches, calls `create_versus_match_ux`.

New: returns a list of `CreateMatchThread` / `PresentDecision` effects by
calling match_handler's launch logic.

#### `update_ladders() -> list[Effect]`

Current: schedules delayed echo, runs matchmaking, calls matches, pushes UI.

New:
```
def update_ladders():
    effects = []
    matchmaking_results = matchmaking()  # pure
    effects += call_matches()
    effects.append(UpdateLadderUI(...))  # for each ladder
    effects.append(ScheduleCallback(
        delay_seconds=downtime_minimum + 5,
        callback_name="update_ladders",
        callback_args={}))
    return effects
```

#### `push_ladder_updates() -> list[Effect]`

Simply returns `[UpdateLadderUI(ladder_id=...) for l in ladders.values()]`.

#### queue, dequeue, autoqueue, status, history, challenge

These currently return message strings and are already nearly pure — they
just call `user_handler.get_user(guild, caller)` which needs Discord. Once
AxiUser is decoupled (later card), these become fully pure. For now, they
stay as-is since they return strings, not effects.

---

## Adapter: execute_effects()

New function in `discord_handler.py`:

```python
async def execute_effects(effects: list):
    for effect in effects:
        if isinstance(effect, SendUserMessages):
            user = get_user_by_id(effect.user_id)  # lookup from cache
            msgs = [m[0] for m in effect.messages]
            files = [m[1] for m in effect.messages]
            await send_long(user, msgs, file=files, sleeptime=0.8)

        elif isinstance(effect, SendToThread):
            thread = get_thread_by_match_id(effect.match_id)
            msgs = [m[0] for m in effect.messages]
            files = [m[1] for m in effect.messages]
            await send_long(thread, msgs, file=files, sleeptime=0.8)

        elif isinstance(effect, SendToChannel):
            guild = bot.get_guild(effect.guild_id)
            channel = get(guild.channels, name=effect.channel_name)
            msgs = [m[0] for m in effect.messages]
            files = [m[1] for m in effect.messages]
            await send_long(channel, msgs, file=files, sleeptime=0.8)

        elif isinstance(effect, PresentDecision):
            user = get_user_by_id(effect.user_id)
            msgs = [m[0] for m in effect.messages]
            files = [m[1] for m in effect.messages]
            discord_msg = await send_long(user, msgs, file=files, sleeptime=0.8)
            # Register for reaction tracking
            decision_msgs_to_matches[discord_msg] = get_match(effect.match_id)
            matches_to_decision_msgs[get_match(effect.match_id)].append(discord_msg)
            for o in effect.options:
                await discord_msg.add_reaction(o)

        elif isinstance(effect, CreateMatchThread):
            channel = get_channel(effect.guild_id, effect.channel_name)
            match = get_match(effect.match_id)
            thread = await channel.create_thread(
                name=effect.thread_name, type=ChannelType.public_thread)
            match.discord_thread = thread
            discord_threads_to_matches[thread] = match
            msgs = [m[0] for m in effect.init_messages]
            files = [m[1] for m in effect.init_messages]
            await send_long(thread, msgs, file=files, sleeptime=0.8)
            if effect.stream_notice:
                await send_long(thread, effect.stream_notice, sleeptime=0.8)

        elif isinstance(effect, ArchiveThread):
            match = get_match(effect.match_id)
            if match.discord_thread:
                await match.discord_thread.edit(archived=True)
                del discord_threads_to_matches[match.discord_thread]

        elif isinstance(effect, UpdateLadderUI):
            ladder = get_ladder(effect.ladder_id)
            await update_status_channel(ladder)
            await update_leaderboard_channel(ladder)

        elif isinstance(effect, ScheduleCallback):
            callback = resolve_callback(effect.callback_name)
            await schedule_handler.schedule_event(
                time() + effect.delay_seconds,
                lambda: execute_callback(effect.callback_name, effect.callback_args))
```

### Lookup helpers

The adapter needs to resolve IDs back to Discord objects. This requires
lookup tables:

- `match_id -> match object` (match_handler maintains this)
- `match_id -> Discord thread` (adapter maintains this)
- `user_id -> AxiUser` (user_handler maintains this)
- `ladder_id -> Ladder` (ladder_handler maintains this)

For now, match_id and ladder_id can be `id(obj)` (Python object ID). This is
sufficient until the "consolidate into service objects" card introduces proper
IDs.

---

## Slash Command Dispatch Pattern

Current slash commands do validation + call handler + send response. After
refactoring, the pattern becomes:

```python
@bot.tree.command(name="win")
async def win(ctx):
    # Validation (stays in discord_handler)
    if ctx.channel not in match_handler.discord_threads_to_matches:
        await ctx.response.send_message("Use this command in your thread!")
        return
    match = match_handler.discord_threads_to_matches[ctx.channel]
    user = user_handler.get_user(ctx.guild, ctx.user)
    if user not in match.players:
        await ctx.response.send_message("Use this command in your thread!")
        return

    # Business logic (pure, returns effects)
    match.report_winner(user, user)
    effects = []
    if match.check_match_over():
        effects = match_handler.close_match(match)

    # Response (stays in discord_handler)
    if match.check_match_over():
        await ctx.response.send_message("Score reported. You may close this thread.")
    else:
        await ctx.response.send_message("Score reported. Both players must confirm.")

    # Execute effects
    await execute_effects(effects)
```

The pattern is always: **validate -> call pure logic -> send command response -> execute effects**.

The `ctx.response.send_message` calls stay in the slash command handlers
because they're inherently Discord — the response to the slash command that
triggered the action. The effects handle everything else (thread archiving,
results posting, ladder UI updates, etc.).

---

## Event Handler Dispatch

```python
@bot.event
async def on_reaction_add(reaction, user):
    message = reaction.message
    user = user_handler.get_user(message.guild, user)
    emoji = reaction.emoji
    if message in decision_msgs_to_matches:
        effects = match_handler.process_decision(user, emoji)
        await execute_effects(effects)

@bot.event
async def on_message(message):
    await bot.process_commands(message)
    if message.channel in discord_threads_to_matches:
        match = discord_threads_to_matches[message.channel]
        user = user_handler.get_user(message.guild, message.author)
        if user in match.players and match.checkin_user(user):
            await send_long(message.channel, f"{user} has checked in!\n")
    if not message.guild:
        user = user_handler.get_user(message.guild, message.author)
        if user in match_handler.users_to_dm_matches:
            effects = match_handler.process_command(user, message.content)
            await execute_effects(effects)
```

---

## Tricky Patterns

### 1. PresentDecision sequential dependency

**Problem**: Sending a DM returns a Discord message object. That object must
be saved as a decision message key and have reactions added.

**Solution**: `PresentDecision` is a compound effect. The pure function says
"present these options to this user for this match." The adapter handles the
mechanics: send message, save mapping, add reactions. The pure function never
sees the Discord message object.

### 2. CPU decision recursion

**Problem**: After a round step, CPU players compute decisions immediately,
which calls `process_decision` recursively.

**Solution**: This stays as-is. `AbstractCPU.compute()` is pure. The pure
`process_decision` and `process_round` can call each other recursively
because they're both sync and pure. The recursion terminates because CPU
decisions resolve immediately (no waiting for Discord reactions). All effects
from the entire recursion chain accumulate and are returned to the adapter at
the top level.

### 3. update_ladders self-scheduling

**Problem**: `update_ladders` schedules a delayed re-call of itself.

**Solution**: `ScheduleCallback(delay_seconds=25, callback_name="update_ladders", ...)`.
The adapter resolves the callback name and schedules it. When it fires, the
adapter calls the pure function and executes the returned effects.

### 4. create_versus_match_ux compound logic

**Problem**: This function in discord_handler mixes business logic (flushing
message queues, computing CPU decisions) with Discord I/O (thread creation,
DM sending, reaction adding).

**Solution**: The business logic moves into `match_handler.launch_match()`
which now returns `(match, list[Effect])`. The effects describe what the
adapter should do. `create_versus_match_ux` becomes a thin wrapper or is
replaced entirely by `execute_effects`.

### 5. Decision message tracking

**Problem**: `decision_msgs_to_matches` and `matches_to_decision_msgs` map
Discord message objects to matches. These must stay in the Discord layer
since they're keyed by Discord objects.

**Solution**: These dicts move fully into discord_handler (the adapter layer).
match_handler no longer references them. The `PresentDecision` effect tells
the adapter to establish the mapping. When `on_reaction_add` fires, the
adapter looks up the match and calls the pure `process_decision`.

Similarly, `discord_threads_to_matches` moves fully into discord_handler.

### 6. Thread reference on ThreadGame

**Problem**: `ThreadGame.discord_thread` stores a Discord Thread object.

**Solution**: For now, the adapter sets this after creating the thread. The
pure layer refers to matches by ID, not by thread. The ArchiveThread effect
uses match_id, and the adapter resolves it. A later card (AxiUser decoupling)
can clean this up further.

---

## File Changes Summary

| File | Changes |
|---|---|
| `axi/effects.py` | **NEW** — effect dataclass definitions |
| `axi/handlers/match_handler.py` | All functions become sync, return `list[Effect]`. Remove `discord_handler` import. Remove `discord_threads_to_matches` and `decision_msgs_to_matches` dicts. |
| `axi/handlers/ladder_handler.py` | `call_matches`, `update_ladders`, `push_ladder_updates` return effects. `matchmaking` returns effects for scheduling. |
| `axi/handlers/discord_handler.py` | Add `execute_effects()`. Move `decision_msgs_to_matches`, `matches_to_decision_msgs`, `discord_threads_to_matches` here. Update all slash commands and event handlers to call pure functions + execute effects. |
| `axi/thread_game.py` | No changes needed. |
| `axi/abstract_dm_game.py` | No changes needed. |
| `axi/abstract_game.py` | No changes needed. |
| `axi/ladder.py` | No changes needed (already mostly pure). |
| All game implementations | No changes needed. |
| All rating systems | No changes needed. |

---

## What This Enables for Testing

After this refactoring:

```python
def test_process_decision_sends_feedback():
    match = RockPaperScissors([player1, player2])
    match.initialize_match_state()
    match.initialize_message_queue()
    match.refresh_decisions()
    effects = match_handler.process_decision(player1, "rock")
    send_effects = [e for e in effects if isinstance(e, SendUserMessages)]
    assert len(send_effects) == 1
    assert send_effects[0].user_id == player1.uid.id

def test_close_match_archives_thread():
    match = create_thread_match(player1, player2)
    match.report_winner(player1, player1)
    match.report_winner(player2, player1)
    effects = match_handler.close_match(match)
    archive_effects = [e for e in effects if isinstance(e, ArchiveThread)]
    assert len(archive_effects) == 1

def test_full_rps_game():
    match = RockPaperScissors([player1, player2])
    # ... setup ...
    effects = match_handler.process_decision(player1, "rock")
    # player1 decided but player2 hasn't yet
    assert not any(isinstance(e, PresentDecision) for e in effects)
    effects = match_handler.process_decision(player2, "scissors")
    # both decided, round resolves, new decisions presented
    present_effects = [e for e in effects if isinstance(e, PresentDecision)]
    assert len(present_effects) == 2  # both players get new options
```

No Discord. No mocks. No fakes. Just pure function calls and assertions on
effect lists.

---

## Implementation Order

1. Create `axi/effects.py` with all effect dataclasses.
2. Refactor `match_handler.py` — make all functions sync, return effects.
   Move Discord-specific dicts out.
3. Update `discord_handler.py` — add `execute_effects()`, absorb
   Discord-specific dicts, update slash commands and event handlers.
4. Refactor `ladder_handler.py` — make I/O functions return effects.
5. Verify the bot still runs correctly end-to-end.
