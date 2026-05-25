"""PXL config callbacks (Phase 13).

Pure-layer handler — defines the six PXL lifecycle callbacks and
registers them under string names with the schedule_handler callback
registry so `/createfromconfig` can persist them through DB-backed
scheduling and survive restarts (Phase 11).

Each callback receives plain JSON-serializable kwargs (the values the
slash command captured at submission time) and emits effects. The
Discord adapter consumes effects and performs the actual Discord
calls.

Lifecycle (per source: discord_manager.py:1167–1186):
  pxl_initial_announcement
  pxl_final_announcement
  pxl_create_event
  pxl_create_checkins
  pxl_final_checkins_reminder
  pxl_begin_event
"""

import axi.handlers.checkin_handler as checkin_handler
import axi.handlers.schedule_handler as schedule_handler
from axi.effects import (
    EditScheduledEventDescription,
    SendToChannel,
)


# ---------------------------------------------------------------------------
# Effect-emitting callbacks
# ---------------------------------------------------------------------------


def pxl_initial_announcement(guild_id, channel, message, image_path=None):
    """Initial announcement (~1 hour before start).

    Emits SendToChannel with the upcoming-event header image + message.
    """
    return [SendToChannel(
        guild_id=guild_id,
        channel_name=channel.lstrip("#") if channel else None,
        messages=[
            ("", image_path),
            (message, None),
        ],
    )]


def pxl_final_announcement(guild_id, channel, message, image_path=None):
    """Final announcement (~minutes before start).

    Emits SendToChannel with the tonight-event header image + message.
    """
    return [SendToChannel(
        guild_id=guild_id,
        channel_name=channel.lstrip("#") if channel else None,
        messages=[
            ("", image_path),
            (message, None),
        ],
    )]


def pxl_create_event(guild_id, title, description, image_path,
                     start_timestamp, event_channel):
    """Create the Discord scheduled event itself.

    Phase 13 returns a placeholder effect — actual Discord scheduled-
    event creation goes through the adapter, which has access to
    guild.create_scheduled_event(...). The adapter pulls (title,
    description, start, channel) from this kwargs dict.

    For Phase 13 we just emit a SendToChannel announcing the upcoming
    event — adapter wiring for true `guild.create_scheduled_event`
    can come in a Phase-14 admin command.
    """
    msg = f"**Scheduled event:** {title}\n\n{description}"
    return [SendToChannel(
        guild_id=guild_id,
        channel_name=event_channel.lstrip("#") if event_channel else None,
        messages=[(msg, image_path)],
    )]


def pxl_create_checkins(guild_id, scope, pinned_channel, start_timestamp,
                        signup_user_ids=None):
    """Post the check-in announcement at the scheduled time.

    Delegates to checkin_handler.create_checkins which returns the
    CreateCheckinPost effect.
    """
    return checkin_handler.create_checkins(
        scope=scope,
        guild_id=guild_id,
        pinned_channel=pinned_channel.lstrip("#") if pinned_channel else None,
        start_time=start_timestamp,
        signup_user_ids=signup_user_ids or [],
    )


def pxl_final_checkins_reminder(guild_id, scope, pinned_channel, event_name,
                                signup_user_ids=None, checkin_user_ids=None,
                                minutes_until_open=5):
    """5-minutes-out reminder ping for RSVPed users who haven't
    checked in yet."""
    return checkin_handler.final_reminder(
        scope=scope,
        guild_id=guild_id,
        pinned_channel=pinned_channel.lstrip("#") if pinned_channel else None,
        event_name=event_name,
        signup_user_ids=signup_user_ids or [],
        checkin_user_ids=checkin_user_ids or [],
        minutes_until_open=minutes_until_open,
    )


def pxl_begin_event(events_info):
    """Begin the event(s) — flips scheduled event description, adds
    checked-in reactors as players, posts begin header image.

    `events_info` is a list of per-bracket dicts (see
    checkin_handler.begin_all_events).
    """
    return checkin_handler.begin_all_events(events_info)


# ---------------------------------------------------------------------------
# Register at import time
# ---------------------------------------------------------------------------


schedule_handler.register_callback(
    "pxl_initial_announcement", pxl_initial_announcement)
schedule_handler.register_callback(
    "pxl_final_announcement", pxl_final_announcement)
schedule_handler.register_callback(
    "pxl_create_event", pxl_create_event)
schedule_handler.register_callback(
    "pxl_create_checkins", pxl_create_checkins)
schedule_handler.register_callback(
    "pxl_final_checkins_reminder", pxl_final_checkins_reminder)
schedule_handler.register_callback(
    "pxl_begin_event", pxl_begin_event)
