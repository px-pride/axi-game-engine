"""Check-in lifecycle handler (Phase 9).

Pure layer — receives pre-fetched Discord data (signup user IDs,
reaction user IDs) and emits effects. The Discord adapter
(discord_handler slash commands) does the live fetching.

Lifecycle (per source: discord_manager.py:748–1038):
  create_checkins → final_reminder → add_from_reacts → begin_all_events
  → edit_events_for_close → clear_announcement
"""

from datetime import datetime

from axi.effects import (
    AddReactorsToTournament,
    CreateCheckinPost,
    EditScheduledEventDescription,
    MentionReactors,
    SendToChannel,
)


CHECKINS_HEADER_PATH = "axi/assets/discord_header_checkins.png"
BEGIN_HEADER_PATH = "axi/assets/discord_header_begin.png"
THUMBS_UP = "\N{THUMBS UP SIGN}"


def _fmt_start_time(timestamp):
    """Mirror source's strftime + ' PT.' suffix."""
    return datetime.fromtimestamp(timestamp).strftime("%A, %B %d. %I:%M %p")


def create_checkins(scope, guild_id, pinned_channel, start_time,
                    signup_user_ids):
    """Build the check-in announcement post.

    Emits CreateCheckinPost with the formatted message + thumbs-up
    reaction. The adapter captures the resulting message id and stores
    it on tournament.checkins_post_id (or ladder.checkins_post_id).
    """
    msg = f"*Ladder opens:* {_fmt_start_time(start_time)} PT.\n"
    msg += f"*Check in:* Just react to this post :+1:\n"
    if signup_user_ids:
        msg += ", ".join(f"<@{uid}>" for uid in signup_user_ids)
        msg += ", and anyone else!\n"
    return [
        CreateCheckinPost(
            guild_id=guild_id,
            channel_name=pinned_channel,
            header_image_path=CHECKINS_HEADER_PATH,
            message=msg,
            reaction_emoji=THUMBS_UP,
            scope=scope,
        ),
    ]


def final_reminder(scope, guild_id, pinned_channel, event_name,
                   signup_user_ids, checkin_user_ids,
                   minutes_until_open=5):
    """Ping RSVPs missing from checkins.

    Emits MentionReactors with the SET DIFFERENCE (signups - checkins)
    and a reminder message.
    """
    missing = list(set(signup_user_ids) - set(checkin_user_ids))
    prefix = "**ATTENTION:** "
    if missing:
        suffix = f", and anyone else who would like to enter {event_name}!\n"
    else:
        suffix = f"anyone who would like to enter {event_name}!\n"
    suffix += (
        f"{minutes_until_open} minutes until the ladder opens. "
        "React to the post above!\n"
    )
    return [
        MentionReactors(
            guild_id=guild_id,
            channel_name=pinned_channel,
            user_ids=missing,
            message_prefix=prefix,
            message_suffix=suffix,
        ),
    ]


def list_checkins(scope, guild_id, pinned_channel, checkin_user_ids):
    """Print the current check-in list."""
    msg = (
        "Check-ins are complete. If you would still like to enter, "
        "consider bribing the TOs, or groveling.\n"
        "CHECKED IN:\n"
    )
    for uid in checkin_user_ids:
        msg += f"<@{uid}>\n"
    msg += "\n"
    return [SendToChannel(
        guild_id=guild_id,
        channel_name=pinned_channel,
        messages=[(msg, None)],
    )]


def add_from_reacts(scope, reaction_user_ids):
    """Add reactors to the scoped tournament's player list.

    Emits AddReactorsToTournament — the adapter resolves user_ids →
    AxiUser instances and calls tournament.add_players(...).
    """
    return [AddReactorsToTournament(
        scope=scope,
        user_ids=list(reaction_user_ids),
    )]


def mention_from_reacts(scope, guild_id, channel_name, reaction_user_ids):
    """Post a message tagging all reactors (no extra text)."""
    return [MentionReactors(
        guild_id=guild_id,
        channel_name=channel_name,
        user_ids=list(reaction_user_ids),
    )]


def begin_all_events(events_info):
    """Begin multiple scheduled events (multibracket support).

    `events_info` is a list of dicts:
      {scope, event_id, tournament_title, guild_id, channel_name,
       reactor_user_ids}

    For each: add reactors to the tournament, emit
    EditScheduledEventDescription with the "THE LADDER HAS BEGUN!"
    description, and post the begin-header image + join-late message.
    The adapter consumes effects and calls tournament.begin() for each.
    """
    effects = []
    for info in events_info:
        effects.append(AddReactorsToTournament(
            scope=info["scope"],
            user_ids=list(info.get("reactor_user_ids", [])),
        ))
        new_desc = (
            "THE LADDER HAS BEGUN!\n"
            f"Use this command to join late: **/queue {info['tournament_title']}**"
        )
        effects.append(EditScheduledEventDescription(
            event_id=info["event_id"],
            description=new_desc,
        ))
        join_msg = f"*Joining late?* Use: **/queue {info['tournament_title']}**"
        effects.append(SendToChannel(
            guild_id=info["guild_id"],
            channel_name=info["channel_name"],
            messages=[
                (join_msg, None),
                ("", BEGIN_HEADER_PATH),
            ],
        ))
    return effects


def edit_events_for_close(events_info):
    """When a ladder/tournament closes, flip its scheduled event
    description to a closed state."""
    effects = []
    for info in events_info:
        new_desc = (
            "THE LADDER IS CLOSED.\n"
            f"Thanks for playing!"
        )
        effects.append(EditScheduledEventDescription(
            event_id=info["event_id"],
            description=new_desc,
        ))
    return effects


def clear_announcement(guild_id, announcement_channel):
    """Post the cleanup message to the announcements channel.

    Source's clear_announcement just posts a 'thanks all' style
    message. Phase 13 PXL config may parameterize.
    """
    msg = "Event over. Thanks to all who participated!\n"
    return [SendToChannel(
        guild_id=guild_id,
        channel_name=announcement_channel,
        messages=[(msg, None)],
    )]
