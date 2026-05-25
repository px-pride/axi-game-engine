# Phase 13: PXL config + /createfromconfig command

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 13.

Phase 13 adds the PXL config parser + `/createfromconfig` command —
admins can describe an entire event lineage (one-off, recurring
series, or multi-bracket series) in a single INI file and have the
bot schedule the full lifecycle (events, check-ins, reminders,
tournament begin) automatically.

## Scope

- New `axi/pxl_config.py` containing:
  - `parse_config(path_or_string)` → returns a `PxlConfig` dataclass
    capturing the parsed event/series spec (or list of multibracket
    specs for the [[N]] override case).
  - Two-level INI parsing via Python's `configparser` (with
    multi-line value support and stripped quotes for triple-quoted
    descriptions).
  - Subsection override resolution: `[[N]]` inherits from
    `[[default]]` and overrides specified keys.
  - Variable substitution: `$NAME` / `$EPISODE` / `$GAME` in TITLE +
    DESCRIPTION strings.
  - Type coercion for keys: DATE/TIME/FIRST_DATE/FIRST_TIME →
    `datetime`, DURATION/_OFFSET → `timedelta`, COUNT/FREQUENCY →
    int/timedelta, GUILD_ID → int, GAMES/ROLES/IMAGES/EVENT_CHANNELS
    → list (comma-separated).
- New `/createfromconfig` slash command in
  `axi/handlers/discord_handler.py` that:
  - Accepts a file attachment or inline path.
  - Calls `pxl_config.parse_config(...)`.
  - For each resolved episode + bracket, computes the absolute
    fire-time and registers DB-backed scheduled callbacks (Phase 11):
    `pxl_create_event`, `pxl_initial_announcement`,
    `pxl_final_announcement`, `pxl_create_checkins`,
    `pxl_final_checkins_reminder`, `pxl_begin_event`.
- New `axi/handlers/pxl_handler.py` with the PXL-specific callbacks
  registered with `schedule_handler.register_callback(...)` at
  import time. Each callback:
  - Resolves Discord refs via `bot.get_guild(...)` etc.
  - Delegates to existing handlers (event creation, check-ins
    create/reminder, begin) via their effect-emitting flow.

## Files

| File | Change |
|---|---|
| `axi/pxl_config.py` (NEW) | Parser + PxlConfig dataclass + resolution. |
| `axi/handlers/pxl_handler.py` (NEW) | Scheduled callbacks registered with schedule_handler at import. |
| `axi/handlers/discord_handler.py` | New `/createfromconfig` slash command. |
| `tests/test_pxl_config.py` (NEW) | Parser tests against the 4 sample configs + override + substitution. |

## INI dialect + parsing

Python's `configparser.ConfigParser` is close but doesn't natively
support double-bracketed nested sections (`[[default]]`,
`[[N]]`). We adopt the lightweight rewrite approach:

1. Read the file as text.
2. Identify nested-section blocks: a `[[X]]` line opens a subsection
   under the most recent `[Section]`.
3. Convert nested sections to flat `[Section.X]` form so
   `configparser` can parse them.
4. After parsing, walk the flat sections and re-nest into a dict tree:
   ```python
   {
       "Section": {
           # top-level keys
           "_subsections": {
               "default": {...},
               "2": {...},
           }
       }
   }
   ```

This preserves the source PXL author's mental model while leveraging
stdlib. No yaml dep needed.

## `PxlConfig` dataclass

```python
@dataclass
class PxlConfig:
    """Parsed PXL config — top-level spec + zero or more subsections."""
    kind: str                     # "EVENT" | "SERIES" | "MULTI"
    name: str                     # section name (e.g. "Testing Series")
    raw: dict                     # full parsed dict for advanced access
    # Common shared fields (extracted from top-level + defaults):
    guild_id: int
    announcement_channel: Optional[str]
    announcement_initial_image: Optional[str]
    announcement_final_image: Optional[str]
    announcement_initial_offset: Optional[timedelta]
    announcement_final_offset: Optional[timedelta]
    checkins_initial_offset: Optional[timedelta]
    checkins_final_offset: Optional[timedelta]
    # Recurrence:
    count: int = 1
    frequency: Optional[timedelta] = None
    first_date: Optional[datetime] = None
    first_time: Optional[str] = None
    # Event-level (single-bracket only):
    date: Optional[datetime] = None
    time: Optional[str] = None
    duration: Optional[timedelta] = None
    image: Optional[str] = None
    # Subsection lists (multi-bracket):
    default: Optional[dict] = None       # [[default]] block
    overrides: Dict[int, dict] = field(default_factory=dict)  # {2: {...}, 3: {...}}
```

## Variable substitution

```python
def substitute_vars(text, name, episode, game):
    """Replace $NAME / $EPISODE / $GAME in a string."""
    if not text:
        return text
    return (text
            .replace("$NAME", name)
            .replace("$EPISODE", str(episode))
            .replace("$GAME", game))
```

Applied to TITLE and DESCRIPTION at episode-resolution time, with
the right (name, episode_index, game) for each bracket within each
episode.

## Subsection override resolution

```python
def resolve_episode(default_dict, override_dict):
    """Merge [[default]] with [[N]] override — override wins per key."""
    merged = dict(default_dict)
    if override_dict:
        merged.update(override_dict)
    return merged
```

Episode N's effective spec = `resolve_episode(default, overrides.get(N, {}))`.
Episode 1 (first episode) uses `[[default]]` alone (no override).

## `/createfromconfig` slash command

```python
@bot.tree.command(
    name="createfromconfig",
    description="Schedule an event/series from a PXL config file (admin only).")
@has_permissions(ban_members=True)
async def createfromconfig(ctx, attachment: discord.Attachment):
    """Parse PXL config + schedule the full lifecycle."""
    content = (await attachment.read()).decode("utf-8")
    config = pxl_config.parse_config(content)

    # For each (episode_index, bracket_spec) in config.iter_brackets():
    #   compute absolute fire times for:
    #     - initial announcement (event_time - announcement_initial_offset)
    #     - final announcement (event_time - announcement_final_offset)
    #     - create event
    #     - create checkins (event_time - checkins_initial_offset)
    #     - final checkins reminder (event_time - checkins_final_offset)
    #     - begin event (event_time)
    #   register each via schedule_handler.schedule_event_persistent
    #   with callback_name="pxl_initial_announcement" / etc and
    #   callback_args including all the resolved spec details.

    for spec in config.iter_episodes():
        ...schedule lifecycle for this episode...

    await ctx.response.send_message(
        f"Scheduled {len(list(config.iter_episodes()))} episode(s).")
```

## Callbacks registered in pxl_handler.py

Each callback re-fetches Discord refs at fire time and delegates to
the existing handler effect path:

```python
schedule_handler.register_callback(
    "pxl_initial_announcement", _pxl_initial_announcement_cb)
schedule_handler.register_callback(
    "pxl_final_announcement", _pxl_final_announcement_cb)
schedule_handler.register_callback(
    "pxl_create_event", _pxl_create_event_cb)
schedule_handler.register_callback(
    "pxl_create_checkins", _pxl_create_checkins_cb)
schedule_handler.register_callback(
    "pxl_final_checkins_reminder", _pxl_final_checkins_reminder_cb)
schedule_handler.register_callback(
    "pxl_begin_event", _pxl_begin_event_cb)
```

Each callback signature:

```python
async def _pxl_initial_announcement_cb(
        guild_id, channel, image_path, message):
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    channel_obj = discord.utils.get(guild.text_channels, name=channel)
    if not channel_obj:
        return
    await send_long(channel_obj, message, file=image_path)
```

## Test plan

`tests/test_pxl_config.py`:

1. **`TestParseSample0`** — `[EVENT]` single-bracket. Parses NAME,
   DESCRIPTION (multiline), CHANNEL, DATE/TIME, DURATION, IMAGE,
   [ANNOUNCEMENTS] + [CHECKINS] subsections.

2. **`TestParseSample1`** — `[SERIES]` recurring single-bracket.
   Verifies FIRST_DATE/FIRST_TIME + COUNT + FREQUENCY are parsed,
   and COUNT episodes generated.

3. **`TestParseSample2`** — `[Series Name]` multi-bracket with
   `[[default]]` + `[[2]]` override. Verifies:
   - Default keys propagated to episode 1.
   - Episode 2 has GAMES=["nasb", "rivals"], ROLES override.
   - Variable substitution in TITLE/DESCRIPTION.

4. **`TestParseSample3`** — most complex variant; verify it parses
   without crash and exposes overrides for each [[N]] subsection.

5. **`TestSubstituteVars`** — `substitute_vars("$NAME #$EPISODE",
   "PXL", 3, "rps")` → `"PXL #3"`.

6. **`TestResolveEpisode`** — default + override merge: override
   wins per key.

7. **`TestParseTimedelta`** — DURATION="30 minutes" → `timedelta`;
   ANNOUNCEMENT_INITIAL_OFFSET="75 seconds" → `timedelta(seconds=75)`.

8. **`TestParseGamesList`** — `"rps"` → `["rps"]`; `"nasb, rivals"`
   → `["nasb", "rivals"]`.

9. **`TestNestedSectionConversion`** — `[[default]]` lines are
   correctly flattened to `[Section.default]` and re-nested into
   the result dict.

10. **`TestEpisodeIteration`** — `config.iter_episodes()` yields
    `count` episodes, each with resolved spec + substituted vars.

11. **`TestMissingRequiredKey`** — config without GUILD_ID raises
    `PxlConfigError`.

Skip Discord-coupled tests (the `/createfromconfig` slash command +
callback invocations); pure parser + resolver is what's tested.

## Major decisions

### A. Stdlib `configparser` with text preprocessing

Add a thin preprocess pass that converts `[[X]]` → `[Section.X]`
before handing to `configparser`. After parsing, re-build the nested
dict. No yaml / no toml dep — stays light.

### B. PXL dataclass + iter_episodes generator

`config.iter_episodes()` yields one dict-per-episode (already
resolved with default + override + variable substitution). Slash
command iterates and schedules. Keeps the parser purely declarative.

### C. Time parsing via `pytimeparse` for relative + `datetime.strptime` for absolute

DURATION/OFFSET are relative ("30 minutes") — use `pytimeparse`.
DATE/TIME are absolute ("4/7/2023" + "6:00 PM EST") — combine via
`datetime.strptime` with explicit format string. Timezone handling:
strip EST/PST suffix and assume the bot's local timezone (PT per
SOUL); document the limitation.

### D. `count=1` defaults to single-shot event

If `[EVENT]` (single event, no recurrence), `count=1`,
`frequency=None`, no FIRST_DATE — falls back to DATE/TIME directly.

If `[SERIES]` or `[Series Name]`, `count` is required and
`frequency` specifies the gap between episodes.

### E. Variable substitution NOT applied to non-string fields

Only TITLE / DESCRIPTION strings get `$NAME` / `$EPISODE` / `$GAME`
substitution. Other fields use the literal value from the spec.

### F. Image paths kept as filesystem paths

PXL configs reference local images (e.g.
`D:/Pride_Axioms/AI/axi/discord_event_cover_rps.png`). We pass them
through to the existing `send_long(channel, "", file=path)` call —
the adapter loads the bytes when posting. Phase 13 doesn't move
images into the repo or normalize paths.

### G. Multi-bracket episode 1 = `[[default]]` alone

Source's semantics. Episode 1 has no override; its spec = default
spec. Override blocks apply at `[[2]]`, `[[3]]`, etc.

## What's deferred

- **PXL config DB persistence** — for now configs are read live
  from attachment each time `/createfromconfig` runs. Phase 11
  checkpointing covers state recovery; Phase 13 doesn't add a
  `configs` table.
- **Per-bracket effect re-execution after restart** — Phase 11's
  scheduled_callbacks framework handles the schedule layer; PXL
  callbacks just register through it.
- **`/listconfigs` / `/editconfig`** — Phase 14 admin commands.
- **Time zone handling beyond PT** — defer to Phase 14 if
  multi-timezone admins need it.
- **YAML or TOML support** — stick with INI for source compat.

## Resolved questions

1. **What's the canonical config storage location?** Discord
   attachment to `/createfromconfig`. No filesystem path needed at
   the bot side.

2. **Can a config schedule events that fire before now?** Parser
   accepts past dates; `schedule_event_persistent` will skip them
   on next `startup_replay`. Phase 13 doesn't validate against
   wall-clock at parse time.

3. **What if [[2]] overrides keys that don't exist in [[default]]?**
   The keys exist in the merged dict — override wins regardless.
   Tested by `TestResolveEpisode`.

4. **What's the relationship between PXL config and the scope
   system (Phase 12)?** The bracket's CHANNEL / EVENT_CHANNELS
   field becomes the scope after channel_to_scope normalization.
   `/createfromconfig` doesn't need to call `set_scope`
   explicitly — the channel-derived path will resolve correctly.

5. **What format is FREQUENCY?** A `pytimeparse`-parseable string
   like `"3 minutes"`, `"24 hours"`, `"1 week"`. Sample 2 uses
   `"3 minutes"`.

6. **Timezone handling?** Strip the trailing timezone abbrev
   (EST/PST/etc.) and assume bot's local tz (PT). Document as a
   limitation. Phase 14 admin commands could add explicit override.

7. **Inline content vs. attachment in `/createfromconfig`?** Phase
   13 only supports attachment. Inline string can be added later
   if needed.
