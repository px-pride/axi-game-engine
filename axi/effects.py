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
