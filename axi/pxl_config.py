"""PXL config parser (Phase 13).

Pure-layer module — no Discord imports. Parses an INI-style PXL config
file describing an event, series, or multi-bracket series, and yields
one resolved spec per (episode, bracket) for scheduling.

The PXL INI dialect uses nested double-bracket sections:

    [Series Name]
    GUILD_ID = ...
    FIRST_DATE = 5/6/2023
    FIRST_TIME = 12:25 PM
    COUNT = 3
    FREQUENCY = 1 week

        [[default]]
        TITLE = $NAME $EPISODE: $GAME
        GAMES = rps
        ...

        [[2]]
        GAMES = nasb, rivals
        ...

Subsections (`[[X]]`) describe per-episode overrides; `[[default]]`
applies to every episode, and `[[N]]` overrides episode N. The parser
preprocesses `[[X]]` to flat `[Section.X]` form before handing to
stdlib `configparser`, then re-nests in the resulting dict.

`PxlConfig.iter_episodes()` yields one `EpisodeSpec` per scheduled
episode, with `start_time` resolved and a list of `BracketSpec`
entries (one per game in that episode), each with `$NAME` / `$EPISODE`
/ `$GAME` substitution already applied to TITLE / DESCRIPTION.
"""

import configparser
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


class PxlConfigError(Exception):
    """Raised on malformed or missing-required-key PXL configs."""


# ---------------------------------------------------------------------------
# Inline parsers (kept inline so tests don't depend on pytimeparse mocks)
# ---------------------------------------------------------------------------


_TIMEDELTA_UNITS = {
    "second": 1, "seconds": 1, "sec": 1, "secs": 1, "s": 1,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60, "m": 60,
    "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600, "h": 3600,
    "day": 86400, "days": 86400, "d": 86400,
    "week": 604800, "weeks": 604800, "w": 604800,
}


def parse_timedelta(text):
    """Parse a string like '30 minutes' / '75 seconds' / '1 week' into
    a `timedelta`. Returns None on empty input. Raises PxlConfigError
    on un-parseable values."""
    if text is None or text == "":
        return None
    if isinstance(text, timedelta):
        return text
    s = str(text).strip().lower()
    # Match "<number> <unit>" pairs.
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([a-z]+)", s)
    if not match:
        # Try compact ("30m", "2h").
        match = re.fullmatch(r"(\d+(?:\.\d+)?)([a-z]+)", s)
    if not match:
        raise PxlConfigError(f"Unparseable timedelta: {text!r}")
    n, unit = match.groups()
    if unit not in _TIMEDELTA_UNITS:
        raise PxlConfigError(f"Unknown time unit: {unit!r}")
    return timedelta(seconds=float(n) * _TIMEDELTA_UNITS[unit])


_KNOWN_TZ_ABBREVS = (
    "EST", "EDT", "CST", "CDT", "MST", "MDT", "PST", "PDT",
    "PT", "ET", "CT", "MT", "UTC", "GMT", "BST", "CET", "CEST",
    "JST", "KST", "IST", "AEST", "AEDT",
)
_TZ_SUFFIX_RE = re.compile(
    r"\s+(?:" + "|".join(_KNOWN_TZ_ABBREVS) + r")$",
    re.IGNORECASE,
)


def parse_datetime(date_str, time_str):
    """Parse a (date, time) pair into a naive `datetime`.

    Accepts `M/D/YYYY` or `M/D/YY` for date; `H:MM [AM|PM]` for time.
    Strips trailing TZ abbreviation (EST/PST/PT/…) and assumes the
    bot's local timezone (PT per SOUL). Returns None if either piece
    is missing.
    """
    if not date_str or not time_str:
        return None
    if isinstance(date_str, datetime):
        return date_str
    date_str = str(date_str).strip()
    time_str = _TZ_SUFFIX_RE.sub("", str(time_str).strip())
    # Try a couple of common formats.
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%y %I:%M %p",
                "%m/%d/%Y %H:%M",   "%m/%d/%y %H:%M"):
        try:
            return datetime.strptime(f"{date_str} {time_str}", fmt)
        except ValueError:
            continue
    raise PxlConfigError(
        f"Unparseable datetime: date={date_str!r} time={time_str!r}")


def parse_list(text):
    """Split a comma-separated value into a list of stripped strings.
    Returns [text] if no comma. Returns [] for empty/None input."""
    if text is None or text == "":
        return []
    if isinstance(text, list):
        return text
    parts = [p.strip() for p in str(text).split(",")]
    return [p for p in parts if p]


def substitute_vars(text, name, episode, game):
    """Replace $NAME / $EPISODE / $GAME tokens in `text`. No-op if
    `text` is None or empty."""
    if not text:
        return text
    return (str(text)
            .replace("$NAME", str(name))
            .replace("$EPISODE", str(episode))
            .replace("$GAME", str(game).upper()))


def resolve_episode(default_dict, override_dict):
    """Merge [[default]] dict with a [[N]] override dict. Override
    wins per key. Either may be None."""
    merged = dict(default_dict or {})
    if override_dict:
        merged.update(override_dict)
    return merged


# ---------------------------------------------------------------------------
# INI preprocessing — [[X]] subsections → [Section.X]
# ---------------------------------------------------------------------------


_TOP_SECTION_RE = re.compile(r"^\s*\[([^\[\]]+)\]\s*$")
_SUB_SECTION_RE = re.compile(r"^\s*\[\[([^\[\]]+)\]\]\s*$")


def preprocess_ini(text):
    """Rewrite `[[X]]` lines as `[<current-section>.X]` so stdlib
    configparser can parse them. Lines outside any top-level section
    pass through unchanged.

    Also strips leading whitespace from key lines (the source PXL
    configs indent both keys and subsections to make the file
    visually nested).
    """
    out_lines = []
    current_section = None
    in_triple_quote = False
    triple_quote_kind = None
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        # Allow leading-quote multiline value to pass through verbatim.
        if in_triple_quote:
            out_lines.append(raw_line)
            if triple_quote_kind in stripped:
                # End triple-quoted value.
                in_triple_quote = False
                triple_quote_kind = None
            continue
        # Detect start of triple-quoted value (e.g. DESCRIPTION = ''').
        # We only need to know not to re-process subsection-looking
        # lines that appear inside quoted text. configparser handles
        # quoted values fine on its own afterward.
        m_sub = _SUB_SECTION_RE.match(raw_line)
        if m_sub:
            sub = m_sub.group(1).strip()
            if current_section is None:
                # `[[X]]` with no top-level section above — treat as a
                # top-level section with the literal name.
                out_lines.append(f"[{sub}]")
            else:
                out_lines.append(f"[{current_section}.{sub}]")
            continue
        m_top = _TOP_SECTION_RE.match(raw_line)
        if m_top:
            current_section = m_top.group(1).strip()
            out_lines.append(f"[{current_section}]")
            continue
        # Track triple-quoted multi-line values so subsection-like
        # lines inside them aren't rewritten.
        for q in ("'''", '"""'):
            if q in stripped:
                # An opening and closing quote on the same line cancels.
                if stripped.count(q) >= 2:
                    break
                in_triple_quote = True
                triple_quote_kind = q
                break
        # De-indent key lines so configparser doesn't treat them as
        # continuations of the previous value.
        if "=" in raw_line and current_section is not None:
            out_lines.append(raw_line.lstrip())
        else:
            out_lines.append(raw_line)
    return "\n".join(out_lines)


def _strip_triple_quotes(value):
    """Strip `'''` / `\"\"\"` from a configparser-loaded value, if present."""
    if value is None:
        return value
    s = str(value).strip()
    for q in ("'''", '"""'):
        if s.startswith(q) and s.endswith(q) and len(s) >= 2 * len(q):
            return s[len(q):-len(q)].strip()
    return s


def _parse_to_nested(text):
    """Parse `text` into a nested dict:
        {section_name: {"_keys": {...}, "_subsections": {subname: {...}}}}
    """
    flat = preprocess_ini(text)
    cp = configparser.ConfigParser(
        interpolation=None,
        delimiters=("=",),
        comment_prefixes=(";", "#"),
        strict=False,
        empty_lines_in_values=False,
    )
    # ConfigParser lowercases keys by default; preserve case.
    cp.optionxform = lambda opt: opt
    cp.read_string(flat)

    result = {}
    for section_name in cp.sections():
        if "." in section_name:
            top, sub = section_name.split(".", 1)
            result.setdefault(top, {"_keys": {}, "_subsections": {}})
            sub_keys = {k: _strip_triple_quotes(v) for k, v in cp.items(section_name)}
            result[top]["_subsections"][sub] = sub_keys
        else:
            result.setdefault(section_name, {"_keys": {}, "_subsections": {}})
            for k, v in cp.items(section_name):
                result[section_name]["_keys"][k] = _strip_triple_quotes(v)
    return result


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BracketSpec:
    """One bracket within an episode. Strings are post-substitution.

    For single-bracket configs (sample_0, sample_1), each episode has
    exactly one BracketSpec. For multi-bracket configs (sample_2/3),
    each episode has len(games) BracketSpecs.
    """
    title: str
    description: str
    game: str
    roles: list                  # list[str]
    image: Optional[str]
    event_channel: Optional[str]
    format: Optional[str]


@dataclass
class EpisodeSpec:
    """One scheduled occurrence of an event/series episode."""
    episode_index: int           # 1-indexed
    start_time: datetime
    brackets: list               # list[BracketSpec]


@dataclass
class PxlConfig:
    """Parsed PXL config — top-level spec + zero or more subsections.

    `kind` is "EVENT" (single-shot, [EVENT] section), "SERIES" (single
    bracket, [SERIES] section), or "MULTI" (multi-bracket, named
    section like [Testing Series]). The name field stores the
    section header.

    Use `iter_episodes()` to enumerate concrete scheduled instances
    (after resolving default + override + variable substitution).
    """
    kind: str
    name: str
    raw: dict                                         # parsed nested dict

    # Common fields:
    guild_id: Optional[int] = None
    announcement_channel: Optional[str] = None
    announcement_initial_image: Optional[str] = None
    announcement_final_image: Optional[str] = None
    announcement_initial_offset: Optional[timedelta] = None
    announcement_final_offset: Optional[timedelta] = None
    checkins_initial_offset: Optional[timedelta] = None
    checkins_final_offset: Optional[timedelta] = None

    # Recurrence:
    count: int = 1
    frequency: Optional[timedelta] = None
    first_datetime: Optional[datetime] = None

    # Event-level (single-event only):
    event_datetime: Optional[datetime] = None
    duration: Optional[timedelta] = None
    image: Optional[str] = None
    channel: Optional[str] = None
    description: Optional[str] = None

    # Subsection lists (multi-bracket):
    default: dict = field(default_factory=dict)       # [[default]] block
    overrides: dict = field(default_factory=dict)     # {2: {...}, 3: {...}}

    def iter_episodes(self):
        """Yield one EpisodeSpec per scheduled episode."""
        if self.kind == "EVENT":
            yield from self._iter_event_episodes()
        else:
            yield from self._iter_series_episodes()

    def _iter_event_episodes(self):
        """Single-shot [EVENT] — yields one EpisodeSpec with one BracketSpec."""
        if self.event_datetime is None:
            return
        bracket = BracketSpec(
            title=self.name,
            description=self.description or "",
            game="",
            roles=[],
            image=self.image,
            event_channel=self.channel,
            format=None,
        )
        yield EpisodeSpec(
            episode_index=1,
            start_time=self.event_datetime,
            brackets=[bracket],
        )

    def _iter_series_episodes(self):
        """[SERIES] or [Series Name] — yields one EpisodeSpec per
        episode (count total). Each EpisodeSpec has one BracketSpec per
        game in that episode."""
        if self.first_datetime is None:
            return
        for k in range(self.count):
            episode_idx = k + 1
            start = self.first_datetime
            if self.frequency is not None:
                start = start + self.frequency * k
            # Resolve effective spec for this episode.
            override = self.overrides.get(episode_idx, {})
            effective = resolve_episode(self.default, override)
            # SERIES section has its fields directly on `self` (no
            # default subsection). MULTI has them in `self.default`.
            title_formula = (effective.get("TITLE") or self.raw.get("TITLE")
                             or self.name)
            description_formula = (effective.get("DESCRIPTION")
                                   or self.description or "")
            games = parse_list(effective.get("GAMES") or self.raw.get("GAME"))
            if not games:
                games = [""]
            roles = parse_list(effective.get("ROLES"))
            images = parse_list(effective.get("IMAGES")) or (
                [self.image] if self.image else [])
            event_channels = parse_list(
                effective.get("EVENT_CHANNELS")
                or effective.get("EVENT_CHANNEL")
                or self.raw.get("EVENT_CHANNEL")
                or "")
            formats = parse_list(effective.get("FORMATS"))

            brackets = []
            for i, game in enumerate(games):
                title = substitute_vars(
                    title_formula, self.name, episode_idx, game)
                description = substitute_vars(
                    description_formula, self.name, episode_idx, game)
                image = images[i] if i < len(images) else (
                    images[0] if images else None)
                event_channel = (event_channels[i] if i < len(event_channels)
                                 else (event_channels[0]
                                       if event_channels else None))
                format_ = (formats[i] if i < len(formats)
                           else (formats[0] if formats else None))
                brackets.append(BracketSpec(
                    title=title,
                    description=description,
                    game=game,
                    roles=roles,
                    image=image,
                    event_channel=event_channel,
                    format=format_,
                ))
            yield EpisodeSpec(
                episode_index=episode_idx,
                start_time=start,
                brackets=brackets,
            )


# ---------------------------------------------------------------------------
# Top-level parse_config
# ---------------------------------------------------------------------------


def parse_config(text_or_path):
    """Parse a PXL config (file path OR raw INI text) into a PxlConfig.

    Auto-detects which by checking for a newline / `[` in the input;
    a `[` at the start indicates inline text.
    """
    if text_or_path is None or text_or_path == "":
        raise PxlConfigError("Empty config input.")
    text = _read_text_or_path(text_or_path)
    nested = _parse_to_nested(text)
    if not nested:
        raise PxlConfigError("Config has no sections.")

    # Top-level section: the FIRST one in the file (ConfigParser
    # preserves order). [ANNOUNCEMENTS] / [CHECKINS] are sub-sections
    # for [EVENT] only.
    sections = list(nested.keys())
    top = sections[0]
    top_data = nested[top]
    top_keys = top_data["_keys"]
    top_subs = top_data["_subsections"]

    # Sibling sections that exist alongside an [EVENT].
    siblings = {s: nested[s] for s in sections[1:]}

    kind = _infer_kind(top, top_data, siblings)
    cfg = PxlConfig(kind=kind, name=top_keys.get("NAME", top), raw=top_keys)

    # ----- Pull common keys -----
    cfg.guild_id = _maybe_int(top_keys.get("GUILD_ID"))
    cfg.announcement_channel = _strip_hash(
        top_keys.get("ANNOUNCEMENT_CHANNEL"))
    cfg.announcement_initial_image = top_keys.get("ANNOUNCEMENT_INITIAL_IMAGE")
    cfg.announcement_final_image = top_keys.get("ANNOUNCEMENT_FINAL_IMAGE")
    cfg.announcement_initial_offset = parse_timedelta(
        top_keys.get("ANNOUNCEMENT_INITIAL_OFFSET"))
    cfg.announcement_final_offset = parse_timedelta(
        top_keys.get("ANNOUNCEMENT_FINAL_OFFSET"))
    cfg.checkins_initial_offset = parse_timedelta(
        top_keys.get("CHECKINS_INITIAL_OFFSET"))
    cfg.checkins_final_offset = parse_timedelta(
        top_keys.get("CHECKINS_FINAL_OFFSET"))
    cfg.image = top_keys.get("IMAGE")
    cfg.description = top_keys.get("DESCRIPTION")
    cfg.channel = _strip_hash(top_keys.get("CHANNEL"))

    # ----- Kind-specific parsing -----
    if kind == "EVENT":
        cfg.event_datetime = parse_datetime(
            top_keys.get("DATE"), top_keys.get("TIME"))
        cfg.duration = parse_timedelta(top_keys.get("DURATION"))
        # Inline [ANNOUNCEMENTS] / [CHECKINS] sibling sections
        # overwrite the top-level offset fields if present.
        ann = siblings.get("ANNOUNCEMENTS", {}).get("_keys", {})
        if ann:
            cfg.announcement_channel = (
                _strip_hash(ann.get("CHANNEL"))
                or cfg.announcement_channel)
            ann_initial = parse_datetime(
                ann.get("INITIAL_DATE"), ann.get("INITIAL_TIME"))
            ann_final = parse_datetime(
                ann.get("FINAL_DATE"), ann.get("FINAL_TIME"))
            if cfg.event_datetime is not None:
                if ann_initial is not None:
                    cfg.announcement_initial_offset = (
                        cfg.event_datetime - ann_initial)
                if ann_final is not None:
                    cfg.announcement_final_offset = (
                        cfg.event_datetime - ann_final)
        chk = siblings.get("CHECKINS", {}).get("_keys", {})
        if chk:
            chk_initial = parse_datetime(
                chk.get("INITIAL_DATE"), chk.get("INITIAL_TIME"))
            chk_final = parse_datetime(
                chk.get("FINAL_DATE"), chk.get("FINAL_TIME"))
            if cfg.event_datetime is not None:
                if chk_initial is not None:
                    cfg.checkins_initial_offset = (
                        cfg.event_datetime - chk_initial)
                if chk_final is not None:
                    cfg.checkins_final_offset = (
                        cfg.event_datetime - chk_final)

    else:
        # SERIES or MULTI
        cfg.count = _maybe_int(top_keys.get("COUNT")) or 1
        cfg.frequency = parse_timedelta(top_keys.get("FREQUENCY"))
        cfg.first_datetime = parse_datetime(
            top_keys.get("FIRST_DATE"), top_keys.get("FIRST_TIME"))
        if kind == "MULTI":
            cfg.default = top_subs.get("default", {})
            for sub_name, sub_keys in top_subs.items():
                if sub_name == "default":
                    continue
                try:
                    n = int(sub_name)
                except ValueError:
                    continue
                cfg.overrides[n] = sub_keys
    return cfg


def _read_text_or_path(text_or_path):
    """Heuristically: if input contains a newline or starts with `[`,
    it's inline. Otherwise treat it as a file path."""
    if isinstance(text_or_path, (bytes, bytearray)):
        return text_or_path.decode("utf-8")
    s = str(text_or_path)
    if "\n" in s or s.lstrip().startswith("["):
        return s
    with open(s, "r") as f:
        return f.read()


def _infer_kind(top_section_name, top_data, siblings):
    """Determine EVENT vs SERIES vs MULTI kind based on the section
    header (EVENT/SERIES) and presence of [[…]] subsections."""
    if top_section_name == "EVENT":
        return "EVENT"
    if top_data["_subsections"]:
        return "MULTI"
    return "SERIES"


def _maybe_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _strip_hash(value):
    if value is None:
        return None
    return str(value).lstrip("#")
