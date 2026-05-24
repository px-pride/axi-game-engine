from dataclasses import dataclass, field


@dataclass
class SendUserMessages:
    """Send text/file messages to a user via DM."""
    user_id: int
    messages: list       # [(text, file_path), ...]


@dataclass
class SendToThread:
    """Send messages to a match's thread."""
    match_id: int
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
    match_id: int
    messages: list       # [(text, file_path), ...]
    options: list        # [emoji, ...]


@dataclass
class CreateMatchThread:
    """Create a Discord thread for a thread game match."""
    match_id: int
    guild_id: int
    channel_name: str
    thread_name: str
    init_messages: list  # [(text, file_path), ...]
    stream_notice: str = None
    launch_message: str = None


@dataclass
class ArchiveThread:
    """Archive a match's Discord thread."""
    match_id: int


@dataclass
class UpdateLadderUI:
    """Refresh status channel and leaderboard channel for a ladder."""
    ladder_id: int


@dataclass
class ScheduleCallback:
    """Schedule a delayed operation."""
    delay_seconds: float
    callback_name: str   # identifies which operation to run
    callback_args: dict = field(default_factory=dict)
    keys: list = None     # deduplication keys for schedule_handler
    suffix: str = None    # deduplication suffix for schedule_handler


@dataclass
class LaunchTournamentMatch:
    """Tournament asks the adapter to launch a match for a bracket node.

    The adapter calls match_handler.launch_match(...,
    completion_callback=on_match_complete) and records the resulting Match
    in tournament_state.state.nodes_to_matches[node_id]."""
    node_id: str
    tournament_id: str
    graph_id: str
    players: list             # list[user_id: int]
    game: str
    mode: str
    best_of: int
    label: str
    stream: bool


@dataclass
class AnnounceBracket:
    """Emit a bracket announcement (text + optional image) to a channel.
    Adapter decides formatting (text-only vs Graphviz PNG)."""
    guild_id: int
    channel_name: str
    text: str
    image_path: str = None


@dataclass
class CallMatchForStream:
    """Designate a specific bracket match as the next streamed match."""
    node_id: str


@dataclass
class ArchiveTournamentMatch:
    """Tournament asks the adapter to archive the match's thread/DM artifacts."""
    node_id: str


@dataclass
class UpdateTournamentUI:
    """Refresh the tournament's status / placements display."""
    tournament_id: str


@dataclass
class UpdateLavaUI:
    """Refresh the lava-level display for a LadderElimination phase."""
    tournament_id: str
    graph_id: str
    lava_level: float
    placement_snapshot: int
    players_in_danger: list   # [user_id: int]


# ---------------------------------------------------------------------------
# Phase 9: Event check-in lifecycle effects
# ---------------------------------------------------------------------------


@dataclass
class CreateCheckinPost:
    """Post the check-in announcement (header image + message + reaction).

    Adapter posts the header image first, then the message, then attaches
    the reaction emoji to the message. Adapter captures the message id
    and writes it back via the supplied callback / handler routing.
    """
    guild_id: int
    channel_name: str
    header_image_path: str        # e.g. "axi/assets/discord_header_checkins.png"
    message: str
    reaction_emoji: str           # e.g. "\N{THUMBS UP SIGN}"
    scope: str                    # for adapter to route back the message_id


@dataclass
class CollectReactors:
    """Adapter fetches users who reacted to the given message and routes
    them back via checkin_handler. Returns nothing directly; the adapter
    inlines the fetch + handler dispatch."""
    guild_id: int
    channel_name: str
    message_id: int


@dataclass
class AddReactorsToTournament:
    """Add a list of users (by id) to the tournament for this scope.

    The adapter resolves user_ids → AxiUser instances, then calls
    `tournament.add_players(users)` for the scope's active tournament.
    """
    scope: str
    user_ids: list                # list[int]


@dataclass
class MentionReactors:
    """Post a message mentioning all users who reacted (typically used
    for the 5-min-out reminder)."""
    guild_id: int
    channel_name: str
    user_ids: list                # list[int]
    message_prefix: str = ""      # optional leading text
    message_suffix: str = ""      # optional trailing text


@dataclass
class EditScheduledEventDescription:
    """Edit a Discord scheduled event's description (e.g. flip to
    'CHECK-INS ARE OPEN!' then 'THE LADDER HAS BEGUN!')."""
    event_id: int
    description: str
