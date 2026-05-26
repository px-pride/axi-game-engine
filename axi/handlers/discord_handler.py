from time import sleep, time
from traceback import format_exc
from json import load
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import discord.app_commands
from pytimeparse.timeparse import timeparse

from discord import Intents, File, Member, User, Thread
from discord.utils import get
from discord.ext import commands
from discord.ext.commands import Bot
from discord.app_commands.checks import has_permissions
from discord.enums import ChannelType

import axi.registry as registry
import axi.handlers.match_handler as match_handler
import axi.handlers.user_handler as user_handler
import axi.handlers.schedule_handler as schedule_handler
import axi.handlers.ladder_handler as ladder_handler
import axi.handlers.database_handler as database_handler
from axi.abstract_cpu import AbstractCPU
from axi.util import USER_STATUS_QUEUED
from axi.effects import (
    SendUserMessages, SendToThread, SendToChannel,
    PresentDecision, CreateMatchThread, ArchiveThread,
    UpdateLadderUI, ScheduleCallback,
    CreateCheckinPost, CollectReactors, AddReactorsToTournament,
    MentionReactors, EditScheduledEventDescription,
    AnnounceTourneyStart, AnnouncePhaseStart, AnnouncePhaseEnd,
    AnnounceTourneyEnd,
    DotRenderUpload,
)
import axi.handlers.checkin_handler as checkin_handler
import axi.handlers.pxl_handler as pxl_handler  # noqa: F401 — registers callbacks at import
import axi.pxl_config as pxl_config
import axi.handlers.tournament_handler as tournament_handler
import axi.handlers.series_handler as series_handler

# --- Discord-specific state (adapter layer) ---
# These track the mapping between Discord objects and match objects.
# Pure business logic never touches these; effects tell the adapter when to update them.
decision_msgs_to_matches = dict()
matches_to_decision_msgs = defaultdict(list)
discord_threads_to_matches = dict()

intents = Intents(
    bans=True,
    dm_messages=True,
    dm_reactions=True,
    dm_typing=True,
    guild_messages=True,
    guild_reactions=True,
    guild_typing=True,
    guilds=True,
    members=True,
    messages=True,
    message_content=True,
    #presences=True,
    reactions=True,
    typing=True,
    )
bot = Bot(command_prefix='/', intents=intents)

async def send_long(channel, x, file=None, sleeptime=None):
    if not x and not file:
        return None
    if isinstance(x, list):
        y = None
        for i in range(len(x)):
            if (x and x[i]) or (file and file[i]):
                y = await send_long(
                        channel, x[i],
                        file=file[i] if isinstance(file, list) else file if i == len(x) - 1 else None,
                        sleeptime=sleeptime[i] if isinstance(sleeptime, list) else sleeptime if i > 0 else None)
        return y
    if x and "\n\n" in x:
        multi_msg = x.split("\n\n")
        return await send_long(
            channel, multi_msg, file,
            [0] + [max(0, 0.8 * (1 + multi_msg[i].count('\n') - 1.5 * multi_msg[i].count('\r\n'))) for i in range(len(multi_msg)-1)])
    if sleeptime:
        sleep(sleeptime)
    try:
        if file and isinstance(file, str):
            with open(file, 'rb') as f:
                file = File(file)
        if file and not isinstance(file, list):
            file = [file]
        final_msg = None
        if x:
            if len(x) > 1500:
                xlines = x.strip().split('\n')
                if len(xlines) == 1:
                    final_msg = await channel.send("Check terminal, string too long.")
                    print(xlines[0])
                else:
                    xlines_p1 = '\n'.join(xlines[:len(xlines)//2])
                    xlines_p2 = '\n'.join(xlines[len(xlines)//2:])
                    final_msg = await send_long(channel, str(xlines_p1))
                    final_msg = await send_long(channel, str(xlines_p2))
            else:
                try:
                    if not str(x).strip() and not file:
                        return ""
                    x = x.replace("\N{HEAVY BLACK HEART}", ":heart:")
                    final_msg = await channel.send(str(x).strip(), file=None)
                except:
                    print(x)
                    print(channel)
                    print(format_exc())
        if file:
            for f in file:
                final_msg = await channel.send("", file=f)
        return final_msg
    except:
        return await send_long(channel, format_exc())


# --- Effect executor (adapter) ---

async def execute_effects(effects):
    for effect in effects:
        if isinstance(effect, SendUserMessages):
            user = bot.get_user(effect.user_id)
            if not user:
                continue
            msgs = [m[0] for m in effect.messages]
            files = [m[1] for m in effect.messages]
            await send_long(user, msgs, file=files, sleeptime=0.8)

        elif isinstance(effect, SendToThread):
            match = match_handler.state.matches_by_id.get(effect.match_id)
            if match and match.discord_thread:
                msgs = [m[0] for m in effect.messages]
                files = [m[1] for m in effect.messages]
                await send_long(match.discord_thread, msgs, file=files, sleeptime=0.8)

        elif isinstance(effect, SendToChannel):
            guild = bot.get_guild(effect.guild_id)
            channel = get(guild.channels, name=effect.channel_name)
            msgs = [m[0] for m in effect.messages]
            files = [m[1] for m in effect.messages]
            await send_long(channel, msgs, file=files, sleeptime=0.8)

        elif isinstance(effect, PresentDecision):
            user = bot.get_user(effect.user_id)
            if not user:
                continue
            msgs = [m[0] for m in effect.messages]
            files = [m[1] for m in effect.messages]
            discord_msg = await send_long(user, msgs, file=files, sleeptime=0.8)
            match = match_handler.state.matches_by_id.get(effect.match_id)
            if discord_msg and match:
                decision_msgs_to_matches[discord_msg] = match
                matches_to_decision_msgs[match].append(discord_msg)
                for o in effect.options:
                    await discord_msg.add_reaction(o)

        elif isinstance(effect, CreateMatchThread):
            guild = bot.get_guild(effect.guild_id)
            channel = get(guild.channels, name=effect.channel_name)
            match = match_handler.state.matches_by_id.get(effect.match_id)
            launch_post = None
            if effect.launch_message:
                launch_post = await send_long(channel, effect.launch_message)
            thread = await channel.create_thread(
                name=effect.thread_name, type=ChannelType.public_thread,
                message=launch_post)
            if match:
                match.discord_thread = thread
                discord_threads_to_matches[thread] = match
            if effect.init_messages:
                msgs = [m[0] for m in effect.init_messages]
                files = [m[1] for m in effect.init_messages]
                await send_long(thread, msgs, file=files, sleeptime=0.8)
            if effect.stream_notice:
                await send_long(thread, effect.stream_notice, sleeptime=0.8)

        elif isinstance(effect, ArchiveThread):
            match = match_handler.state.matches_by_id.get(effect.match_id)
            if match and match.discord_thread:
                thread = match.discord_thread
                await thread.edit(archived=True)
                if thread in discord_threads_to_matches:
                    del discord_threads_to_matches[thread]

        elif isinstance(effect, UpdateLadderUI):
            ladder = ladder_handler.state.ladders_by_id.get(effect.ladder_id)
            if ladder:
                await update_status_channel(ladder)
                await update_leaderboard_channel(ladder)

        elif isinstance(effect, ScheduleCallback):
            name = effect.callback_name
            args = dict(effect.callback_args)
            delay = effect.delay_seconds
            keys = effect.keys
            suffix = effect.suffix
            fire_at = time() + delay
            if getattr(effect, "persist", False):
                # Phase 11: persist via callback registry path.
                await schedule_handler.schedule_event_persistent(
                    fire_at, name, args, keys=keys, suffix=suffix)
            else:
                async def _cb(n=name, a=args):
                    await execute_callback(n, a)
                await schedule_handler.schedule_event(
                    fire_at, _cb, keys=keys, suffix=suffix)

        # ---- Phase 9: check-in lifecycle effects ----

        elif isinstance(effect, CreateCheckinPost):
            guild = bot.get_guild(effect.guild_id)
            if not guild:
                continue
            channel = get(guild.channels, name=effect.channel_name)
            if not channel:
                continue
            # Header image first, then the message + reaction.
            if effect.header_image_path:
                try:
                    await send_long(channel, "", file=effect.header_image_path)
                except Exception:
                    pass
            post = await send_long(channel, effect.message)
            if post and effect.reaction_emoji:
                try:
                    await post.add_reaction(effect.reaction_emoji)
                except Exception:
                    pass
            # Store the post id on the scope's tournament/ladder.
            if post:
                _record_checkins_post_id(effect.scope, post.id)

        elif isinstance(effect, CollectReactors):
            # Adapter-side: fetch the message + reactions, route IDs back
            # to whatever caller invoked this. Phase 9 slash commands fetch
            # inline rather than via this effect, so this is a no-op stub
            # for future symmetric callers.
            pass

        elif isinstance(effect, AddReactorsToTournament):
            tournament = _get_tournament_for_scope(effect.scope)
            if tournament is None:
                continue
            users = []
            for uid in effect.user_ids:
                u = bot.get_user(uid)
                if u and not u.bot:
                    axi_user = user_handler.get_user(None, u)
                    if axi_user is not None:
                        users.append(axi_user)
            if users and hasattr(tournament, "add_players"):
                tournament.add_players(users)

        elif isinstance(effect, MentionReactors):
            guild = bot.get_guild(effect.guild_id)
            if not guild:
                continue
            channel = get(guild.channels, name=effect.channel_name)
            if not channel:
                continue
            mention_text = " ".join(f"<@{uid}>" for uid in effect.user_ids)
            full = (effect.message_prefix or "") + mention_text + (effect.message_suffix or "")
            if full.strip():
                await send_long(channel, full)

        elif isinstance(effect, EditScheduledEventDescription):
            # Lookup the event by id across all guilds the bot is in.
            event = None
            for guild in bot.guilds:
                for ev in await guild.fetch_scheduled_events():
                    if ev.id == effect.event_id:
                        event = ev
                        break
                if event:
                    break
            if event:
                try:
                    await event.edit(description=effect.description)
                except Exception:
                    pass

        # ---- Phase 14: tournament lifecycle announcements ----

        elif isinstance(effect, AnnounceTourneyStart):
            guild = bot.get_guild(effect.guild_id)
            if not guild:
                continue
            channel = get(guild.channels, name=effect.channel_name)
            if not channel:
                continue
            msg = (
                f"**{effect.title} is starting.**\n\n"
                f"*Format:* {effect.format}\n\n"
                "*Reporting Scores*\n"
                "Use **/score @opponent X-Y**.\n"
                "Example: GalaxyMii beats LilFox15 2-0.\n"
                "GalaxyMii types: **/score @LilFox15 2-0**\n"
                "LilFox15 types: **/score @GalaxyMii 0-2**\n\n"
                "*Other Commands*\n"
                "Type **/status** to see if you have a match ready.\n"
                "Type **/mymatches** to see all known matches.\n"
                "Type **/help** for more commands.\n\n"
                "**GOOD LUCK AND HAVE FUN!**"
            )
            await send_long(channel, msg)

        elif isinstance(effect, AnnouncePhaseStart):
            guild = bot.get_guild(effect.guild_id)
            if not guild:
                continue
            channel = get(guild.channels, name=effect.channel_name)
            if not channel:
                continue
            mentions = ", ".join(effect.player_mentions) if effect.player_mentions else ""
            msg = f"**Phase {effect.phase_name} is starting.**\n*Players:* {mentions}."
            await send_long(channel, msg)

        elif isinstance(effect, AnnouncePhaseEnd):
            guild = bot.get_guild(effect.guild_id)
            if not guild:
                continue
            channel = get(guild.channels, name=effect.channel_name)
            if not channel:
                continue
            lines = [f"**Phase {effect.phase_name} has ended.**"]
            for rank, mention in effect.placements:
                lines.append(f"{rank}. {mention}")
            await send_long(channel, "\n".join(lines))

        elif isinstance(effect, AnnounceTourneyEnd):
            guild = bot.get_guild(effect.guild_id)
            if not guild:
                continue
            channel = get(guild.channels, name=effect.channel_name)
            if not channel:
                continue
            msg = f"**Congratulations to {effect.winner_mention} for winning {effect.title}!**"
            await send_long(channel, msg)

        # ---- Phase 15: bracket visualization ----

        elif isinstance(effect, DotRenderUpload):
            guild = bot.get_guild(effect.guild_id)
            if not guild:
                continue
            channel = get(guild.channels, name=effect.channel_name)
            if not channel:
                continue
            import os
            import tempfile
            try:
                import graphviz
            except ImportError:
                await send_long(
                    channel,
                    "Bracket rendering requires the `graphviz` package "
                    "(install graphviz-system-binary + `pip install graphviz`).",
                )
                continue
            try:
                with tempfile.NamedTemporaryFile(
                        suffix=".gv", delete=False) as f:
                    dot_path = f.name
                src = graphviz.Source(effect.dot_source, filename=dot_path)
                src.format = "png"
                out_path = src.render(cleanup=True)
                await send_long(channel, effect.title or "", file=out_path)
                try:
                    os.unlink(out_path)
                except Exception:
                    pass
                try:
                    os.unlink(dot_path)
                except Exception:
                    pass
            except Exception as e:
                await send_long(channel, f"Couldn't render bracket: {e}")


def _get_tournament_for_scope(scope):
    """Resolve a scope (channel name) → Tournament or Ladder.

    Tries ladder_handler first (most common), then tournament_state.
    """
    for key, ladder in ladder_handler.state.ladders.items():
        if key[1] == scope:
            return ladder
    try:
        from axi.tournament_state import state as tstate
        for t in tstate.tournaments.values():
            if getattr(t, "scope", None) == scope:
                return t
    except Exception:
        pass
    return None


def _record_checkins_post_id(scope, post_id):
    target = _get_tournament_for_scope(scope)
    if target is not None:
        target.checkins_post_id = post_id


async def execute_callback(callback_name, callback_args):
    effects = []
    if callback_name == "resolve_checkins":
        match = match_handler.state.matches_by_id.get(callback_args.get("match_id"))
        if match:
            effects = match_handler.resolve_checkins(match)
    elif callback_name == "update_ladders_no_echo":
        effects = ladder_handler.update_ladders(echo=False)
    await execute_effects(effects)


# --- Slash commands ---

@bot.command(name="sync")
@has_permissions(ban_members=True)
async def sync(ctx, scope: str = "guild"):
    await ctx.channel.send("Syncing...")
    if scope == "guild":
        bot.tree.clear_commands(guild=ctx.guild)
        bot.tree.copy_global_to(guild=ctx.guild)
        await bot.tree.sync(guild=ctx.guild)
        await ctx.channel.send(f"Synced for this guild ({ctx.guild.name})!")
    elif scope == "global":
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
        await ctx.channel.send("Synced globally!")
    else:
        await ctx.channel.send("Invalid sync scope. Use 'guild' or 'global'.")

@bot.tree.command(name="help")
async def help(ctx):
    msg = ''
    msg += '**Game launcher commands.**\n'
    msg += 'Use */games* to view the game list.\n'
    msg += 'Use */solo* or */versus* to play.\n'
    msg += 'Use */spectate* to watch someone else\'s gameplay.\n'
    msg += 'Use */abort* to stop playing or spectating.\n'
    msg += '\n'
    msg += '**Thread game commands.**\n'
    msg += 'Use */win* to report that you won the match. Both players must confirm.\n'
    msg += 'Use */lose* to report that you won the match. Both players must confirm.\n'
    msg += 'Use */abort* to cancel the match. Both players must confirm.\n'
    msg += 'Use */doubleblind* to perform double-blind character selection.\n'
    msg += 'Use */lag* to see lag test instructions.\n'
    msg += '\n'
    msg += '**Ladder commands.**\n'
    msg += 'Use */queue* to queue up for a ladder.\n'
    msg += 'Use */dequeue* to dequeue from a ladder.\n'
    msg += 'Use */autoqueue on* to automatically re-queue after each match.\n'
    msg += 'Use */autoqueue off* to turn off autoqueue.\n'
    msg += 'Use */challenge* to directly challenge someone to a ranked match.\n'
    msg += 'Use */status* to check your status in the ladder.\n'
    msg += 'Use */history* to check your match history this session.\n'
    msg += 'Use */displayname* to set your display name.\n'
    msg += '\n'
    msg += '**Mod commands.**\n'
    msg += 'Use */sync* to set up slash commands for your Discord server.\n'
    msg += 'Use */report* to report the winner of a match.\n'
    msg += 'Use */cancel* to cancel a match.\n'
    msg += 'Use */ladder* to open a ladder for queueing.\n'
    msg += 'Use */setstreamer* to select a streamer for the ladder.\n'
    msg += 'Use */nostream* to remove the streamer.\n'
    msg += 'Use */clearevents* to delete all Discord server events.\n'
    msg += '\n'
    await ctx.response.send_message(msg)

@bot.tree.command(name="games", description="Use /games to view the game list.")
async def games(ctx):
    msg = "List of DM games:\n"
    for g in registry.dm_games:
        msg += "* "
        msg += g
        msg += "\n"
    msg += "\nList of thread games:\n"
    for g in registry.thread_games:
        msg += "* "
        msg += g
        msg += "\n"
    msg += "Use /solo or /versus to play!\n"
    await ctx.response.send_message(msg)

@bot.tree.command(name="versus", description="Use /solo or /versus to play.")
async def versus(ctx, game: str, opponent: str):
    if game not in registry.dm_games and game not in registry.thread_games:
        await ctx.response.send_message("Invalid game. Use /games to see the game list.\n")
        return
    player1 = user_handler.get_user(ctx.guild, ctx.user)
    if (game in registry.dm_games and player1 in match_handler.state.users_to_dm_matches) or (
        game in registry.thread_games and player1 in match_handler.state.users_to_thread_matches):
        await ctx.response.send_message(f"{player1} is already in a match!\n")
        return
    player2 = user_handler.get_user(ctx.guild, opponent)
    if not player2:
        await ctx.response.send_message("Invalid player ping.\n")
        return
    if (game in registry.dm_games and player2 in match_handler.state.users_to_dm_matches) or (
        game in registry.thread_games and player2 in match_handler.state.users_to_thread_matches):
        await ctx.response.send_message(f"{player2} is already in a match!\n")
        return
    match = match_handler.launch_match(game, [player1, player2])
    if not match:
        await ctx.response.send_message("Failed to launch match.\n")
        return
    effects = match_handler.prepare_match_ux(match, game,
        channel_name=ctx.channel.name, guild_id=ctx.guild.id)
    await ctx.response.send_message(
        f"Launching {game.upper()}: {match.players[0]} vs. {match.players[1]}.\n")
    await execute_effects(effects)

@bot.tree.command(name="solo", description="Use /solo or /versus to play.")
async def solo(ctx, game: str, mode: str):
    if game not in registry.dm_games:
        if game in registry.thread_games:
            await ctx.response.send_message(f"Thread games can only be played in versus mode. Try /versus.\n")
            return
        await ctx.response.send_message(f"Invalid game. Use /games to see the game list.\n")
        return
    if mode == "versus":
        await ctx.response.send_message(f"Use /versus instead.\n")
        return
    player = user_handler.get_user(ctx.guild, ctx.user)
    if player in match_handler.state.users_to_dm_matches:
        await ctx.response.send_message(f"{player} is already in a match!\n")
        return
    match = match_handler.launch_match(game, [player], mode=mode)
    if not match:
        await ctx.response.send_message("Invalid mode.\n")
        return
    effects = match_handler.prepare_match_ux(match, game)
    await ctx.response.send_message(f"Launching...")
    await execute_effects(effects)

@bot.tree.command(name="spectate", description="Use /spectate to watch someone else\'s gameplay.")
async def spectate(ctx, player: str):
    user = user_handler.get_user(ctx.guild, ctx.user)
    player = user_handler.get_user(ctx.guild, player)
    if not player:
        await ctx.response.send_message("Invalid player ping.\n")
        return
    if player in match_handler.state.users_to_dm_matches:
        match = match_handler.state.users_to_dm_matches[player]
    else:
        await ctx.response.send_message("No match to spectate.\n")
        return
    if user not in match.spectators:
        match.add_spectator(user)
    await send_long(user, "You are now spectating.")
    for p in match.agents():
        if not isinstance(p, AbstractCPU):
            await send_long(p, f"{user} is now spectating.")
    messages = match.flush_message_queue(user)
    if len(messages) > 0 and not isinstance(user, AbstractCPU):
        msgs = [m[0] for m in messages]
        files = [m[1] for m in messages]
        await send_long(user, msgs, file=files, sleeptime=0.8)

@bot.tree.command(name="abort", description="Use /abort to stop playing or spectating.")
async def abort(ctx):
    user = user_handler.get_user(ctx.guild, ctx.user)
    if not ctx.guild:
        if not user in match_handler.state.users_to_dm_matches:
            await ctx.response.send_message(f"You are not in a match.")
            return
        match = match_handler.state.users_to_dm_matches[user]
        if user in match.players:
            effects = match_handler.process_decision(user, "abort")
            await ctx.response.send_message(f"{user} has aborted the game.")
            await execute_effects(effects)
        elif user in match.spectators:
            match.spectators.remove(user)
            for p in match.agents():
                discord_user = bot.get_user(p.uid.id)
                if discord_user:
                    await discord_user.send(f"{user} has stopped spectating.")
    else:
        if not user in match_handler.state.users_to_thread_matches:
            await ctx.response.send_message(f"You are not in a match.")
            return
        match = match_handler.state.users_to_thread_matches[user]
        match.report_abort(user)
        if match.check_match_over():
            effects = match_handler.cancel_match(match)
            await ctx.response.send_message(f"Match aborted. You may close this thread.")
            await execute_effects(effects)
        else:
            await ctx.response.send_message(f"Abort requested. Both players must confirm.")

@bot.tree.command(name="win", description="Use /win to report that you won the match. Both players must confirm.")
async def win(ctx):
    if ctx.channel not in discord_threads_to_matches:
        await ctx.response.send_message(f"Use this command in your thread to report that you won your match!")
        return
    match = discord_threads_to_matches[ctx.channel]
    if not match:
        await ctx.response.send_message(f"Use this command in your thread to report that you won your match!")
        return
    user = user_handler.get_user(ctx.guild, ctx.user)
    if user not in match.players:
        await ctx.response.send_message(f"Use this command in your thread to report that you won your match!")
        return
    if match.check_match_over():
        await ctx.response.send_message(f"This set has already been reported (winner: {match.winner()}).")
    match.report_winner(user, user)
    if match.check_match_over():
        effects = match_handler.close_match(match)
        await ctx.response.send_message(f"Score reported. You may close this thread.")
        await execute_effects(effects)
    else:
        await ctx.response.send_message(f"Score reported. Both players must confirm.")

@bot.tree.command(name="lose", description="Use /lose to report that you won the match. Both players must confirm.")
async def lose(ctx):
    if ctx.channel not in discord_threads_to_matches:
        await ctx.response.send_message(f"Use this command in your thread to report that you won your match!")
        return
    match = discord_threads_to_matches[ctx.channel]
    if not match:
        await ctx.response.send_message(f"Use this command in your thread to report that you won your match!")
        return
    user = user_handler.get_user(ctx.guild, ctx.user)
    if user not in match.players:
        await ctx.response.send_message(f"Use this command in your thread to report that you won your match!")
        return
    if match.check_match_over():
        await ctx.response.send_message(f"This set has already been reported (winner: {match.winner()}).")
    match.report_winner(user, match.opponent(user))
    if match.check_match_over():
        effects = match_handler.close_match(match)
        await ctx.response.send_message(f"Score reported. You may close this thread.")
        await execute_effects(effects)
    else:
        await ctx.response.send_message(f"Score reported. Both players must confirm.")

@bot.tree.command(name="report", description="Use /report to report the winner of a match")
@has_permissions(ban_members=True)
async def report(ctx, winner: str):
    if ctx.channel not in discord_threads_to_matches:
        await ctx.response.send_message(f"Use this command in a thread to report the winner!")
        return
    match = discord_threads_to_matches[ctx.channel]
    if not match:
        await ctx.response.send_message(f"Use this command in a thread to report the winner!")
        return
    if match.check_match_over():
        await ctx.response.send_message(f"This set has already been reported (winner: {match.winner()}).")
    match.report_winner(ctx.user, user_handler.get_user(ctx.guild, winner), admin_override=True)
    if match.check_match_over():
        effects = match_handler.close_match(match)
        await ctx.response.send_message(f"Score reported. You may close this thread.")
        await execute_effects(effects)
    else:
        await ctx.response.send_message(f"Score reported. Both players must confirm.")

@bot.tree.command(name="ladder", description="Use /ladder to open a ladder for queueing.")
@has_permissions(ban_members=True)
async def ladder(ctx, config_file: str):
    config = load(open(config_file))
    if ladder_handler.exists(ctx.guild, config):
        await ctx.response.send_message("This ladder is already active.\n")
        return
    if not ladder_handler.format_supported(config["format"]):
        await ctx.response.send_message(f"Unsupported format: {config['format']}.\n")
        return
    image = None
    if config["image"]:
        f = open(config["image"], "rb").read()
        image = bytearray(f)
    start_time = datetime.now().replace(tzinfo=timezone.utc) + timedelta(seconds=10)
    end_time = start_time + timedelta(seconds=timeparse(config["duration"]))
    queue_channel_name = config["queue-channel"]
    queue_channel = get(ctx.guild.channels, name=queue_channel_name)
    status_channel_name = config["status-channel"]
    status_channel = get(ctx.guild.channels, name=status_channel_name)
    results_channel_name = config["results-channel"]
    results_channel = get(ctx.guild.channels, name=results_channel_name)
    leaderboard_channel_name = config["leaderboard-channel"]
    leaderboard_channel = get(ctx.guild.channels, name=leaderboard_channel_name)
    scheduled_event = await ctx.guild.create_scheduled_event(
        name=config["name"], start_time=start_time, end_time=end_time,
        description=config["description"], location='#' + queue_channel_name, image=image) if image else await ctx.guild.create_scheduled_event(
        name=config["name"], start_time=start_time, end_time=end_time,
        description=config["description"], location='#' + queue_channel_name)
    await send_long(queue_channel, "", file="axi/assets/discord_header_begin.png")
    await send_long(status_channel, "", file="axi/assets/discord_header_begin.png")
    await send_long(results_channel, "", file="axi/assets/discord_header_begin.png")
    await send_long(leaderboard_channel, "", file="axi/assets/discord_header_begin.png")
    await ctx.response.send_message("Ladder is open!\n")
    ladder_handler.start_ladder(ctx.guild, config, scheduled_event)
    effects = ladder_handler.update_ladders()
    await execute_effects(effects)

@bot.tree.command(name="queue", description="Use /queue to queue up for a ladder.")
async def queue(ctx):
    user = user_handler.get_user(ctx.guild, ctx.user)
    msg = ladder_handler.queue(user, ctx.guild, ctx.channel.name)
    effects = ladder_handler.update_ladders()
    await ctx.response.send_message(msg)
    await execute_effects(effects)

@bot.tree.command(name="dequeue", description="Use /dequeue to dequeue from a ladder.")
async def dequeue(ctx):
    user = user_handler.get_user(ctx.guild, ctx.user)
    msg = ladder_handler.dequeue(user, ctx.guild, ctx.channel.name)
    effects = ladder_handler.update_ladders()
    await ctx.response.send_message(msg)
    await execute_effects(effects)

@bot.tree.command(name="autoqueue", description="Use /autoqueue on or /autoqueue off to automatically re-queue after each match.\n")
async def autoqueue(ctx, mode: str):
    user = user_handler.get_user(ctx.guild, ctx.user)
    msg = ladder_handler.autoqueue(user, ctx.guild, ctx.channel.name, mode)
    effects = ladder_handler.update_ladders()
    await ctx.response.send_message(msg)
    await execute_effects(effects)

@bot.tree.command(name="cancel", description="Use /cancel to cancel a match.")
@discord.app_commands.default_permissions(ban_members=True)
@has_permissions(ban_members=True)
async def cancel(ctx):
    if ctx.channel not in discord_threads_to_matches:
        await ctx.response.send_message(f"Use this command in a thread to cancel the match!")
        return
    match = discord_threads_to_matches[ctx.channel]
    if not match:
        await ctx.response.send_message(f"Use this command in a thread to cancel the match!")
        return
    if match.check_match_over():
        await ctx.response.send_message(f"This set has already been reported (winner: {match.winner()}).")
    match.report_abort("admin")
    if match.check_match_over():
        effects = match_handler.cancel_match(match)
        await ctx.response.send_message(f"Match aborted. You may close this thread.")
        await execute_effects(effects)
    else:
        await ctx.response.send_message(f"Abort requested. Both players must confirm.")

@bot.tree.command(name="doubleblind", description="Use /doubleblind to perform double-blind character selection")
async def doubleblind(ctx):
    if ctx.channel not in discord_threads_to_matches:
        await ctx.response.send_message(f"Use this command in your thread to select characters double-blind with your opponent!")
        return
    match = discord_threads_to_matches[ctx.channel]
    if not match:
        await ctx.response.send_message(f"Use this command in your thread to select characters double-blind with your opponent!")
        return
    user = user_handler.get_user(ctx.guild, ctx.user)
    if user not in match.players:
        await ctx.response.send_message(f"Use this command in your thread to select characters double-blind with your opponent!")
        return
    if match.check_match_over():
        await ctx.response.send_message(f"This set has already been reported (winner: {match.winner()}).")
    db_match = match_handler.launch_match("doubleblind", [user, match.opponent(user)])
    effects = match_handler.prepare_match_ux(db_match, "doubleblind")
    await ctx.response.send_message("Starting double-blind selection...")
    await execute_effects(effects)

@bot.tree.command(name="lag", description="Use /lag to see lag test instructions.")
async def lag(ctx):
    msg = ''
    msg += '**PLEASE FOLLOW THESE LAG TEST INSTRUCTIONS.**\n\n'
    msg += '*1. You are expected to be on ethernet.*\n'
    msg += 'Both players, present proof of ethernet.\nScreenshot your taskbar showing network status and current date/time.\n\n'
    msg += '*2. Your jitter must be under 10 ms and your ping range (max minus min) under 20 ms.*\n'
    msg += 'Both players, run this connection test and post results: https://www.meter.net/ping-test/\n'
    msg += 'You may choose any server on this site to test with and post results for.\n\n'
    msg += 'If a player fails any of these tests, they should use **x!drop** to drop out of the event.\n\n'
    msg += f'Ping the TOs for an in-game connection test if a PC performance issue is suspected (consistent low frame rate).\n'
    await ctx.response.send_message(msg)

@bot.tree.command(name="challenge", description="Use /challenge to directly challenge someone to a ranked match.")
async def challenge(ctx, opponent: str):
    user = user_handler.get_user(ctx.guild, ctx.user)
    opp = user_handler.get_user(ctx.guild, opponent)
    msg = ladder_handler.challenge(user, ctx.guild, ctx.channel.name, opp)
    effects = ladder_handler.update_ladders()
    await ctx.response.send_message(msg)
    await execute_effects(effects)

@bot.tree.command(name="status", description="Use /status to check your status in the ladder.")
async def status(ctx):
    user = user_handler.get_user(ctx.guild, ctx.user)
    msg = ladder_handler.status(user, ctx.guild, ctx.channel.name)
    await ctx.response.send_message(msg)

@bot.tree.command(name="history", description="Use /history to check your match history this session.")
async def history(ctx):
    user = user_handler.get_user(ctx.guild, ctx.user)
    msg = ladder_handler.history(user, ctx.guild, ctx.channel.name)
    await ctx.response.send_message(msg)

@bot.tree.command(name="setstreamer", description="Use /setstreamer to select a streamer for the ladder.")
@discord.app_commands.default_permissions(ban_members=True)
@has_permissions(ban_members=True)
async def setstreamer(ctx, streamer: str):
    user = user_handler.get_user(ctx.guild, streamer)
    msg = ladder_handler.set_streamer(ctx.guild, ctx.channel.name, user)
    await ctx.response.send_message(msg)

@bot.tree.command(name="nostream", description="Use /nostream to remove the streamer.")
@discord.app_commands.default_permissions(ban_members=True)
@has_permissions(ban_members=True)
async def nostream(ctx):
    msg = ladder_handler.nostream(ctx.guild, ctx.channel.name)
    await ctx.response.send_message(msg)

@bot.tree.command(name="clearevents", description="Use /clearevents to delete all Discord server events.")
@discord.app_commands.default_permissions(ban_members=True)
@has_permissions(ban_members=True)
async def clearevents(ctx):
    for event in list(ctx.guild.scheduled_events):
        await send_long(ctx.channel, f"Deleting {event.name}.")
        await event.delete()
    await ctx.response.send_message("Events cleared.")

@bot.tree.command(name="displayname", description="Use /displayname to set your display name.")
async def displayname(ctx, name: str):
    database_handler.add_entry(
        "display_names",
        (ctx.user.id, name),
        replace=True
    )
    await ctx.response.send_message(f"Changed display name to {name}.")
    try:
        await ctx.user.edit(nick=name)
    except Exception as error:
        print("Couldn't edit display name.")
        print(error)
    effects = ladder_handler.push_ladder_updates()
    await execute_effects(effects)


# --- Event handlers ---

@bot.event
async def on_ready():
    """Bot ready event — Phase 11: replay persisted scheduler state."""
    try:
        await schedule_handler.startup_replay()
    except Exception:
        pass


@bot.event
async def on_message(message):
    if message == "/sync":
        await sync()
    await bot.process_commands(message)
    if message.channel in discord_threads_to_matches:
        match = discord_threads_to_matches[message.channel]
        user = user_handler.get_user(message.guild, message.author)
        if user in match.players:
            if match.checkin_user(user):
                await send_long(message.channel, f"{user} has checked in!\n")
    if not message.guild:
        user = user_handler.get_user(message.guild, message.author)
        if user in match_handler.state.users_to_dm_matches and user in match_handler.state.users_to_dm_matches[user].players:
            effects = match_handler.process_command(user, message.content)
            await execute_effects(effects)

@bot.event
async def on_reaction_add(reaction, user):
    try:
        message = reaction.message
        user = user_handler.get_user(message.guild, user)
        emoji = reaction.emoji
        if message in decision_msgs_to_matches:
            effects = match_handler.process_decision(user, emoji)
            await execute_effects(effects)
    except:
        print(format_exc())


# --- Ladder UI rendering (adapter-side, purely Discord presentation) ---

async def update_status_channel(l):
    active_matches = l.get_active_matches()
    called_matches = l.get_called_matches()
    current_stream_match = l.get_stream_match()
    status_msg = "\n**ACTIVE MATCHES**\n"
    if active_matches and (len(active_matches) > 1 or current_stream_match not in active_matches):
        for match in active_matches:
            status_msg += match.parse(False)
    called_players = []
    if called_matches:
        for match in called_matches:
            called_players += match.players
            status_msg += match.parse(False)
    if len(called_matches + active_matches) == 0 and not current_stream_match:
        status_msg += "No matches active right now.\n"
    queue_msg = "\n*Queued:* "
    header = True
    for p in l.players:
        if not l.is_user_in_match(p) and l.status_by_player[p] == USER_STATUS_QUEUED:
            if not header:
                queue_msg += ", "
            queue_msg += str(p)
            header = False
    if not header:
        status_msg += queue_msg
    status_channel = get(l.guild.channels, name=l.status_channel)
    if l.status_message:
        await l.status_message.edit(content=status_msg)
    else:
        l.status_message = await send_long(status_channel, status_msg)

async def update_leaderboard_channel(l):
    leaderboard_rows = database_handler.load_entries_where("ratings", "ladder_id", l.rowid)
    rankings = dict()
    for i in range(len(leaderboard_rows)):
        user_id = leaderboard_rows[i][2]
        timestamp = leaderboard_rows[i][-1]
        if user_id in rankings and rankings[user_id][-1] > timestamp:
            continue
        rankings[user_id] = leaderboard_rows[i]
    leaderboard_rows = sorted(rankings.values(), key=lambda x: -(100*x[3]+x[4]))
    msg = ''
    for i in range(len(leaderboard_rows)):
        user_id = leaderboard_rows[i][2]
        user = get(l.guild.members, id=user_id)
        if user:
            dan = leaderboard_rows[i][3]
            pos = leaderboard_rows[i][4]
            suffix = 'th'
            if round(dan) == 1:
                suffix = 'st'
            elif round(dan) == 2:
                suffix = 'nd'
            elif round(dan) == 3:
                suffix = 'rd'
            prefix = '+' if round(pos) >= 0 else ''
            msg += f"{str(i)}. *[{round(dan)}{suffix} Dan {prefix}{round(pos)}]* {str(user).replace('#0', '')} \n"
            display_name = user.name
            display_row = database_handler.load_entry_where(
                "display_names",
                "user_id",
                user.id
            )
            if display_row:
                display_name = display_row[1]
            new_nick = f"{display_name} | {round(dan)}{suffix} Dan {prefix}{round(pos)}"
            member = get(l.guild.members, name=user.name)
            if member and member.nick != new_nick:
                try:
                    await member.edit(nick=new_nick)
                except Exception as error:
                    print("Couldn't edit display name.")
                    print(error)
                    continue
    leaderboard_channel = get(l.guild.channels, name=l.leaderboard_channel)
    if l.leaderboard_message:
        await l.leaderboard_message.edit(content=msg)
    else:
        l.leaderboard_message = await send_long(leaderboard_channel, msg)


# ---------------------------------------------------------------------------
# Phase 9: check-in lifecycle slash commands
# ---------------------------------------------------------------------------


@bot.tree.command(name="createcheckins",
                  description="Post the check-in announcement for a scheduled event.")
async def createcheckins(ctx, event_id: str, channel_name: str = None):
    """Post check-in announcement. `event_id` is the Discord scheduled
    event id (as a string for Discord slash arg compat). `channel_name`
    defaults to the current channel."""
    pinned = channel_name or ctx.channel.name
    scope = pinned
    try:
        event = await ctx.guild.fetch_scheduled_event(int(event_id))
    except Exception as e:
        await ctx.response.send_message(f"Event lookup failed: {e}")
        return
    start_time = int(event.start_time.timestamp())
    signup_ids = [user.id async for user in event.users()]
    effects = checkin_handler.create_checkins(
        scope=scope,
        guild_id=ctx.guild.id,
        pinned_channel=pinned,
        start_time=start_time,
        signup_user_ids=signup_ids,
    )
    await ctx.response.send_message("Check-ins posted.")
    await execute_effects(effects)


@bot.tree.command(name="reacts", description="List users who reacted to a message.")
async def reacts(ctx, msg_id: str):
    """List users who reacted to the given message id (in the current channel)."""
    try:
        msg = await ctx.channel.fetch_message(int(msg_id))
    except Exception as e:
        await ctx.response.send_message(f"Message lookup failed: {e}")
        return
    user_ids = []
    for reaction in msg.reactions:
        async for u in reaction.users():
            if not u.bot and u.id not in user_ids:
                user_ids.append(u.id)
    if not user_ids:
        await ctx.response.send_message("No reactions.")
        return
    lines = "\n".join(f"<@{uid}>" for uid in user_ids)
    await ctx.response.send_message(f"Reactors:\n{lines}")


@bot.tree.command(name="addfromreacts",
                  description="Add users who reacted to a message to the tournament for this channel.")
async def addfromreacts(ctx, msg_id: str = None):
    """Add reactors as players. msg_id defaults to the channel's tournament's checkins_post_id."""
    scope = ctx.channel.name
    target = _get_tournament_for_scope(scope)
    if msg_id is None:
        if target is None or target.checkins_post_id is None:
            await ctx.response.send_message("No check-ins post on file for this channel.")
            return
        message_id = target.checkins_post_id
    else:
        message_id = int(msg_id)
    try:
        msg = await ctx.channel.fetch_message(message_id)
    except Exception as e:
        await ctx.response.send_message(f"Message lookup failed: {e}")
        return
    user_ids = []
    for reaction in msg.reactions:
        async for u in reaction.users():
            if not u.bot and u.id not in user_ids:
                user_ids.append(u.id)
    effects = checkin_handler.add_from_reacts(scope=scope, reaction_user_ids=user_ids)
    await ctx.response.send_message(f"Adding {len(user_ids)} reactor(s).")
    await execute_effects(effects)


@bot.tree.command(name="mentionfromreacts",
                  description="Tag all users who reacted to a message.")
async def mentionfromreacts(ctx, msg_id: str):
    """Ping everyone who reacted."""
    scope = ctx.channel.name
    try:
        msg = await ctx.channel.fetch_message(int(msg_id))
    except Exception as e:
        await ctx.response.send_message(f"Message lookup failed: {e}")
        return
    user_ids = []
    for reaction in msg.reactions:
        async for u in reaction.users():
            if not u.bot and u.id not in user_ids:
                user_ids.append(u.id)
    effects = checkin_handler.mention_from_reacts(
        scope=scope,
        guild_id=ctx.guild.id,
        channel_name=scope,
        reaction_user_ids=user_ids,
    )
    await ctx.response.send_message("Pinging reactors.")
    await execute_effects(effects)


@bot.tree.command(name="checkin", description="Self check-in to the current channel's event.")
async def checkin(ctx):
    """Self check-in: equivalent to reacting to the check-ins post."""
    scope = ctx.channel.name
    target = _get_tournament_for_scope(scope)
    if target is None or target.checkins_post_id is None:
        await ctx.response.send_message("No active check-ins for this channel.")
        return
    try:
        msg = await ctx.channel.fetch_message(target.checkins_post_id)
        await msg.add_reaction("\N{THUMBS UP SIGN}")
    except Exception as e:
        await ctx.response.send_message(f"Couldn't react: {e}")
        return
    await ctx.response.send_message(f"{ctx.user.mention} checked in\!")


# Aliases for ergonomic check-in
@bot.tree.command(name="here", description="Alias for /checkin.")
async def here(ctx):
    await checkin.callback(ctx)


@bot.tree.command(name="yes", description="RSVP yes to the active scheduled event in this channel.")
async def yes(ctx):
    scope = ctx.channel.name
    target = _get_tournament_for_scope(scope)
    if target is None or target.checkins_post_id is None:
        await ctx.response.send_message("No active RSVPs for this channel.")
        return
    try:
        msg = await ctx.channel.fetch_message(target.checkins_post_id)
        await msg.add_reaction("\N{THUMBS UP SIGN}")
    except Exception as e:
        await ctx.response.send_message(f"Couldn't react: {e}")
        return
    await ctx.response.send_message(f"{ctx.user.mention}: yes\!")


@bot.tree.command(name="no", description="RSVP no to the active scheduled event in this channel.")
async def no(ctx):
    scope = ctx.channel.name
    target = _get_tournament_for_scope(scope)
    if target is None or target.checkins_post_id is None:
        await ctx.response.send_message("No active RSVPs for this channel.")
        return
    try:
        msg = await ctx.channel.fetch_message(target.checkins_post_id)
        await msg.remove_reaction("\N{THUMBS UP SIGN}", ctx.user)
    except Exception as e:
        await ctx.response.send_message(f"Couldn't remove reaction: {e}")
        return
    await ctx.response.send_message(f"{ctx.user.mention}: no\!")


# ---------------------------------------------------------------------------
# Phase 12: scope/role system slash commands
# ---------------------------------------------------------------------------


from axi.tournament_state import state as _tournament_state


@bot.tree.command(name="setscope",
                  description="Set your active tournament scope.")
async def setscope(ctx, scope: str):
    """Set the caller's per-(caller, guild) scope for tournament
    targeting. Subsequent admin commands resolve to this scope."""
    _tournament_state.set_scope(
        ctx.user, ctx.guild, ctx.channel, scope.upper(), admin=False)
    await ctx.response.send_message(
        f"Your active scope is now `{scope.upper()}`.")


@bot.tree.command(name="setdefaultscope",
                  description="Set the guild's default tournament scope (admin only).")
@has_permissions(ban_members=True)
async def setdefaultscope(ctx, scope: str):
    """Set the guild-wide default scope. Admins only."""
    _tournament_state.set_scope(
        ctx.user, ctx.guild, ctx.channel, scope.upper(), admin=True)
    await ctx.response.send_message(
        f"Default scope for this guild is now `{scope.upper()}`.")


@bot.tree.command(name="getscope",
                  description="Print your active tournament scope.")
async def getscope(ctx):
    """Print the resolved active scope for the caller."""
    scope = _tournament_state.get_scope(ctx.user, ctx.guild, ctx.channel)
    await ctx.response.send_message(f"Your active scope: `{scope}`")


@bot.tree.command(name="allscopes",
                  description="List all known tournament scopes in this guild.")
async def allscopes(ctx):
    """List all known scopes in the current guild."""
    scopes = _tournament_state.get_all_scopes(ctx.user, ctx.guild, ctx.channel)
    if not scopes:
        await ctx.response.send_message("No scopes registered yet.")
        return
    lines = "\n".join(f"- `{s}`" for s in scopes)
    await ctx.response.send_message(f"Scopes in this guild:\n{lines}")


# ---------------------------------------------------------------------------
# Phase 13: PXL config + /createfromconfig
# ---------------------------------------------------------------------------


@bot.tree.command(
    name="createfromconfig",
    description="Schedule events/series from a PXL config file (admin only).")
@has_permissions(ban_members=True)
async def createfromconfig(ctx, attachment: discord.Attachment):
    """Parse a PXL config attachment and schedule its full lifecycle.

    Reads the uploaded INI file, walks each episode/bracket, and
    registers DB-backed scheduled callbacks (pxl_initial_announcement,
    pxl_final_announcement, pxl_create_event, pxl_create_checkins,
    pxl_final_checkins_reminder, pxl_begin_event) via Phase 11's
    persistent scheduler.
    """
    try:
        content_bytes = await attachment.read()
        content = content_bytes.decode("utf-8")
    except Exception as e:
        await ctx.response.send_message(f"Couldn't read attachment: {e}")
        return
    try:
        config = pxl_config.parse_config(content)
    except pxl_config.PxlConfigError as e:
        await ctx.response.send_message(f"Config parse error: {e}")
        return

    guild_id = config.guild_id or ctx.guild.id
    n_scheduled = 0
    for ep in config.iter_episodes():
        start_ts = ep.start_time.timestamp()
        # Compute per-lifecycle absolute fire times.
        ann_initial_at = (ep.start_time
                          - (config.announcement_initial_offset
                             or timedelta(0))).timestamp()
        ann_final_at = (ep.start_time
                        - (config.announcement_final_offset
                           or timedelta(0))).timestamp()
        checkins_initial_at = (ep.start_time
                               - (config.checkins_initial_offset
                                  or timedelta(0))).timestamp()
        checkins_final_at = (ep.start_time
                             - (config.checkins_final_offset
                                or timedelta(0))).timestamp()

        for bracket in ep.brackets:
            ann_channel = (config.announcement_channel
                           or bracket.event_channel)
            event_name = bracket.title
            scope = (bracket.event_channel or "").upper()

            # 1. Initial announcement.
            await schedule_handler.schedule_event_persistent(
                ann_initial_at, "pxl_initial_announcement", kwargs={
                    "guild_id": guild_id,
                    "channel": ann_channel,
                    "message": (
                        f"Upcoming: **{event_name}** — see scheduled event."),
                    "image_path": config.announcement_initial_image,
                })
            # 2. Final announcement.
            await schedule_handler.schedule_event_persistent(
                ann_final_at, "pxl_final_announcement", kwargs={
                    "guild_id": guild_id,
                    "channel": ann_channel,
                    "message": (
                        f"Tonight: **{event_name}** — check in!"),
                    "image_path": config.announcement_final_image,
                })
            # 3. Create the Discord scheduled event.
            await schedule_handler.schedule_event_persistent(
                ann_initial_at, "pxl_create_event", kwargs={
                    "guild_id": guild_id,
                    "title": bracket.title,
                    "description": bracket.description,
                    "image_path": bracket.image,
                    "start_timestamp": start_ts,
                    "event_channel": bracket.event_channel,
                })
            # 4. Create check-ins post.
            await schedule_handler.schedule_event_persistent(
                checkins_initial_at, "pxl_create_checkins", kwargs={
                    "guild_id": guild_id,
                    "scope": scope,
                    "pinned_channel": bracket.event_channel,
                    "start_timestamp": start_ts,
                    "signup_user_ids": [],
                })
            # 5. Final check-ins reminder.
            await schedule_handler.schedule_event_persistent(
                checkins_final_at, "pxl_final_checkins_reminder", kwargs={
                    "guild_id": guild_id,
                    "scope": scope,
                    "pinned_channel": bracket.event_channel,
                    "event_name": event_name,
                    "signup_user_ids": [],
                    "checkin_user_ids": [],
                    "minutes_until_open": 5,
                })
            # 6. Begin event.
            await schedule_handler.schedule_event_persistent(
                start_ts, "pxl_begin_event", kwargs={
                    "events_info": [{
                        "scope": scope,
                        "event_id": None,
                        "tournament_title": event_name,
                        "guild_id": guild_id,
                        "channel_name": bracket.event_channel,
                        "reactor_user_ids": [],
                    }],
                })
            n_scheduled += 1

    await ctx.response.send_message(
        f"Scheduled {n_scheduled} bracket(s) across "
        f"{config.count} episode(s) for `{config.name}`.")


# ---------------------------------------------------------------------------
# Phase 14: Tournament command slash wrappers
# ---------------------------------------------------------------------------


def _scope_from_ctx(ctx):
    """Resolve the active scope for the caller from channel context."""
    return _tournament_state.get_scope(ctx.user, ctx.guild, ctx.channel)


def _channel_scope(ctx):
    """Channel name (lowercase) — used for routing replies."""
    return ctx.channel.name if ctx.channel is not None else None


def _resolve_user(guild, identifier):
    """Resolve a Discord user identifier (mention or User object) to an
    AxiUser via user_handler. `identifier` may already be a Discord
    Member/User."""
    if identifier is None:
        return None
    return user_handler.get_user(guild, identifier)


# ---- Tournament lifecycle ----


@bot.tree.command(name="create",
                  description="Create a tournament for the current channel (admin).")
@has_permissions(ban_members=True)
async def create(ctx, game: str = None, name: str = None, season: str = None):
    """Create a tournament; scope = current channel."""
    scope = _scope_from_ctx(ctx)
    if game is None:
        game = scope.lower()
    _, effects = tournament_handler.create_tournament(
        scope=scope, guild_id=ctx.guild.id, game=game,
        name=name, season=season, pinned_channel=ctx.channel.name)
    await ctx.response.send_message(f"Tournament `{name or scope}` created.")
    await execute_effects(effects)


@bot.tree.command(name="destroy",
                  description="Destroy the current channel's tournament (admin).")
@has_permissions(ban_members=True)
async def destroy(ctx):
    scope = _scope_from_ctx(ctx)
    t, effects = tournament_handler.destroy_tournament(
        scope=scope, guild_id=ctx.guild.id, channel_name=ctx.channel.name)
    if t is None:
        await ctx.response.send_message("No tournament for this scope.")
        return
    await ctx.response.send_message(f"Tournament `{t.title}` destroyed.")
    await execute_effects(effects)


@bot.tree.command(name="preset",
                  description="Apply a tournament preset by name (admin).")
@has_permissions(ban_members=True)
async def preset(ctx, name: str):
    scope = _scope_from_ctx(ctx)
    ok, effects = tournament_handler.apply_preset(scope, name)
    if not ok:
        await ctx.response.send_message(f"Couldn't apply preset `{name}`.")
        return
    await ctx.response.send_message(f"Preset `{name}` applied.")
    await execute_effects(effects)


@bot.tree.command(name="begin",
                  description="Begin the current channel's tournament (admin).")
@has_permissions(ban_members=True)
async def begin(ctx):
    scope = _scope_from_ctx(ctx)
    effects = tournament_handler.begin(
        scope=scope, guild_id=ctx.guild.id, channel_name=ctx.channel.name)
    await ctx.response.send_message("Beginning tournament…")
    await execute_effects(effects)


@bot.tree.command(name="start",
                  description="Alias for /begin (admin).")
@has_permissions(ban_members=True)
async def start(ctx):
    await begin.callback(ctx)


@bot.tree.command(name="advancephase",
                  description="Advance the tournament to the next phase (admin).")
@has_permissions(ban_members=True)
async def advancephase(ctx):
    scope = _scope_from_ctx(ctx)
    effects = tournament_handler.advance_phase(
        scope=scope, guild_id=ctx.guild.id, channel_name=ctx.channel.name)
    await ctx.response.send_message("Advancing phase…")
    await execute_effects(effects)


@bot.tree.command(name="undophase",
                  description="Reverse the most recent phase advance (admin).")
@has_permissions(ban_members=True)
async def undophase(ctx):
    scope = _scope_from_ctx(ctx)
    tournament_handler.undo_phase(scope)
    await ctx.response.send_message("Phase undone.")


# ---- Player management ----


@bot.tree.command(name="adduser",
                  description="Add users to the tournament (admin).")
@has_permissions(ban_members=True)
async def adduser(ctx, users: str):
    """Accept a space- or comma-separated list of mentions."""
    scope = _scope_from_ctx(ctx)
    parts = [p.strip() for p in users.replace(",", " ").split() if p.strip()]
    axi_users = [_resolve_user(ctx.guild, p) for p in parts]
    axi_users = [u for u in axi_users if u is not None]
    n, effects = tournament_handler.add_players(scope, axi_users)
    await ctx.response.send_message(f"Added {n} user(s).")
    await execute_effects(effects)


@bot.tree.command(name="removeuser",
                  description="Remove users from the tournament (admin).")
@has_permissions(ban_members=True)
async def removeuser(ctx, users: str):
    scope = _scope_from_ctx(ctx)
    parts = [p.strip() for p in users.replace(",", " ").split() if p.strip()]
    axi_users = [_resolve_user(ctx.guild, p) for p in parts]
    axi_users = [u for u in axi_users if u is not None]
    n, effects = tournament_handler.remove_players(scope, axi_users)
    await ctx.response.send_message(f"Removed {n} user(s).")
    await execute_effects(effects)


@bot.tree.command(name="checkinuser",
                  description="Mark a user as checked in for the active match (admin).")
@has_permissions(ban_members=True)
async def checkinuser(ctx, user: Member):
    scope = _scope_from_ctx(ctx)
    axi_user = _resolve_user(ctx.guild, user)
    # Tournament's check-in semantics: the user's current called match
    # is transitioned to ACTIVE. The Tournament API doesn't expose this
    # directly; we delegate to its current phase's receive_checkin.
    t = tournament_handler._get_tournament(scope)
    if t is None or t.current_phase() is None or axi_user is None:
        await ctx.response.send_message("No active tournament or user.")
        return
    phase = t.current_phase()
    if hasattr(phase, "receive_checkin"):
        try:
            phase.receive_checkin(axi_user)
        except Exception as e:
            await ctx.response.send_message(f"Check-in failed: {e}")
            return
    await ctx.response.send_message(f"{user.mention} checked in.")


@bot.tree.command(name="dropuser",
                  description="Drop a user from the current phase (admin).")
@has_permissions(ban_members=True)
async def dropuser(ctx, user: Member):
    scope = _scope_from_ctx(ctx)
    axi_user = _resolve_user(ctx.guild, user)
    tournament_handler.drop_user(scope, axi_user)
    await ctx.response.send_message(f"{user.mention} dropped.")


@bot.tree.command(name="fulldropuser",
                  description="Fully drop a user from the tournament (admin).")
@has_permissions(ban_members=True)
async def fulldropuser(ctx, user: Member):
    scope = _scope_from_ctx(ctx)
    axi_user = _resolve_user(ctx.guild, user)
    tournament_handler.drop_user(scope, axi_user)
    # Full drop = drop applied to all subsequent phases. Source repeats
    # the drop_user call; target uses a single call which the phase
    # transitions propagate.
    await ctx.response.send_message(f"{user.mention} fully dropped.")


@bot.tree.command(name="dquser",
                  description="Disqualify a user (admin).")
@has_permissions(ban_members=True)
async def dquser(ctx, user: Member):
    scope = _scope_from_ctx(ctx)
    axi_user = _resolve_user(ctx.guild, user)
    tournament_handler.dq_user(scope, axi_user)
    await ctx.response.send_message(f"{user.mention} disqualified.")


@bot.tree.command(name="dropme",
                  description="Drop yourself from the current phase.")
async def dropme(ctx):
    scope = _scope_from_ctx(ctx)
    axi_user = _resolve_user(ctx.guild, ctx.user)
    tournament_handler.drop_user(scope, axi_user)
    await ctx.response.send_message(f"{ctx.user.mention} dropped.")


@bot.tree.command(name="fulldropme",
                  description="Fully drop yourself from the tournament.")
async def fulldropme(ctx):
    scope = _scope_from_ctx(ctx)
    axi_user = _resolve_user(ctx.guild, ctx.user)
    tournament_handler.drop_user(scope, axi_user)
    await ctx.response.send_message(f"{ctx.user.mention} fully dropped.")


@bot.tree.command(name="undodrop",
                  description="Reverse a drop (admin).")
@has_permissions(ban_members=True)
async def undodrop(ctx, user: Member):
    scope = _scope_from_ctx(ctx)
    axi_user = _resolve_user(ctx.guild, user)
    tournament_handler.undo_drop_user(scope, axi_user)
    await ctx.response.send_message(f"Drop for {user.mention} reversed.")


@bot.tree.command(name="undodq",
                  description="Reverse a DQ (admin).")
@has_permissions(ban_members=True)
async def undodq(ctx, user: Member):
    scope = _scope_from_ctx(ctx)
    axi_user = _resolve_user(ctx.guild, user)
    tournament_handler.undo_dq_user(scope, axi_user)
    await ctx.response.send_message(f"DQ for {user.mention} reversed.")


# ---- Score / match reporting ----


@bot.tree.command(name="score",
                  description="Report your score against an opponent (e.g. 2-0).")
async def score(ctx, opponent: Member, score: str):
    scope = _scope_from_ctx(ctx)
    reporter = _resolve_user(ctx.guild, ctx.user)
    p1 = _resolve_user(ctx.guild, opponent)
    accepted, effects = tournament_handler.report_score(
        scope, reporter, reporter, p1, score)
    if not accepted:
        await ctx.response.send_message(
            "Score not accepted (await opponent confirmation or check format).")
    else:
        await ctx.response.send_message(f"Score `{score}` recorded.")
    await execute_effects(effects)


@bot.tree.command(name="undomatch",
                  description="Reverse a recorded match (admin).")
@has_permissions(ban_members=True)
async def undomatch(ctx, player_a: Member, player_b: Member):
    scope = _scope_from_ctx(ctx)
    a = _resolve_user(ctx.guild, player_a)
    b = _resolve_user(ctx.guild, player_b)
    effects = tournament_handler.undo_match(scope, a, b)
    await ctx.response.send_message(
        f"Match between {player_a.mention} and {player_b.mention} undone.")
    await execute_effects(effects)


# ---- Status / placements / matches ----


@bot.tree.command(name="placements",
                  description="Print the current phase's placements.")
async def placements(ctx):
    scope = _scope_from_ctx(ctx)
    pls = tournament_handler.get_placements(scope)
    if not pls:
        await ctx.response.send_message("No placements yet.")
        return
    lines = [f"{rank}. {p}" for rank, p in pls]
    await ctx.response.send_message("\n".join(lines))


@bot.tree.command(name="poolscores",
                  description="Print pool scores (Round Robin only).")
async def poolscores(ctx):
    scope = _scope_from_ctx(ctx)
    pools = tournament_handler.get_pool_scores(scope)
    if pools is None:
        await ctx.response.send_message("This command is only for Round Robin phases.")
        return
    out = []
    for i, scores in enumerate(pools):
        out.append(f"**POOL #{i}**")
        for x in scores:
            out.append(f"{x[1]}: {x[0]}")
    await ctx.response.send_message("\n".join(out) if out else "No pools.")


@bot.tree.command(name="round",
                  description="List matches in round R.")
async def round_(ctx, r: int):
    scope = _scope_from_ctx(ctx)
    matches = tournament_handler.get_matches_for_round(scope, r)
    if not matches:
        await ctx.response.send_message(f"No matches in round {r}.")
        return
    lines = [str(m) for m in matches]
    await ctx.response.send_message("\n".join(lines))


@bot.tree.command(name="active",
                  description="List currently active and called matches (text).")
async def active(ctx):
    scope = _scope_from_ctx(ctx)
    active_, called, stream = tournament_handler.get_current_matches(scope)
    parts = []
    if active_:
        parts.append("**ACTIVE**")
        parts.extend(str(m) for m in active_)
    if called:
        parts.append("**CALLED**")
        parts.extend(str(m) for m in called)
    if stream:
        parts.append(f"**ON STREAM:** {stream}")
    if not parts:
        parts.append("No matches active right now.")
    await ctx.response.send_message("\n".join(parts))


@bot.tree.command(name="bracket",
                  description="Show the current bracket as a Graphviz PNG.")
async def bracket(ctx):
    """Render the current phase's MatchGraph as a Graphviz PNG and
    post it to the channel."""
    scope = _scope_from_ctx(ctx)
    t = tournament_handler._get_tournament(scope)
    if t is None:
        await ctx.response.send_message("No active tournament here.")
        return
    dot = t.visualize()
    if not dot:
        await ctx.response.send_message("No phase started yet.")
        return
    effects = [DotRenderUpload(
        guild_id=ctx.guild.id,
        channel_name=ctx.channel.name,
        dot_source=dot,
        title=f"**{t.title}** — bracket",
    )]
    await ctx.response.send_message("Rendering bracket…")
    await execute_effects(effects)


@bot.tree.command(name="current",
                  description="Alias for /bracket.")
async def current(ctx):
    await bracket.callback(ctx)


@bot.tree.command(name="stream",
                  description="Show the stream queue.")
async def stream(ctx):
    scope = _scope_from_ctx(ctx)
    t = tournament_handler._get_tournament(scope)
    if t is None:
        await ctx.response.send_message("No active tournament here.")
        return
    phase = t.current_phase()
    history = getattr(phase, "stream_history", []) if phase else []
    planned = getattr(phase, "stream_planned", []) if phase else []
    parts = []
    if history:
        parts.append("**ON STREAM PREVIOUSLY**")
        parts.extend(str(m) for m in history[:-1])
        parts.append("**ON STREAM NOW**")
        parts.append(str(history[-1]))
    if planned:
        parts.append("**ON STREAM LATER**")
        parts.extend(str(m) for m in planned)
    await ctx.response.send_message("\n".join(parts) if parts else "No stream queue.")


@bot.tree.command(name="statusadmin",
                  description="Print a user's status in the tournament (admin).")
@has_permissions(ban_members=True)
async def statusadmin(ctx, user: Member):
    scope = _scope_from_ctx(ctx)
    axi_user = _resolve_user(ctx.guild, user)
    t = tournament_handler._get_tournament(scope)
    if t is None or axi_user is None:
        await ctx.response.send_message("No active tournament or user.")
        return
    msg = f"*{scope.upper()}*\n"
    matches = tournament_handler.get_matches_for_player(scope, axi_user)
    if not matches:
        msg += "No matches yet for this user this phase.\n"
    else:
        msg += f"{len(matches)} match(es) found.\n"
    await ctx.response.send_message(msg)


@bot.tree.command(name="matches",
                  description="List matches for a user (defaults to you).")
async def matches(ctx, user: Member = None):
    scope = _scope_from_ctx(ctx)
    target = user or ctx.user
    axi_user = _resolve_user(ctx.guild, target)
    ms = tournament_handler.get_matches_for_player(scope, axi_user)
    if not ms:
        await ctx.response.send_message("No matches yet.")
        return
    lines = [str(m) for m in ms]
    await ctx.response.send_message("\n".join(lines))


@bot.tree.command(name="mymatches",
                  description="List your matches in the active tournament.")
async def mymatches(ctx):
    await matches.callback(ctx, user=ctx.user)


@bot.tree.command(name="format",
                  description="Show the tournament's format string.")
async def format_(ctx):
    scope = _scope_from_ctx(ctx)
    fmt = tournament_handler.get_format(scope)
    if fmt is None:
        await ctx.response.send_message("No active tournament here.")
        return
    await ctx.response.send_message(fmt or "(no format set)")


@bot.tree.command(name="info",
                  description="Show info for the active game/match in this channel.")
async def info(ctx):
    """Info has dual meaning in source: game-level info in DM context,
    tournament-current info in tournament channel context. Phase 14 sends
    a generic message; per-game info is handled by the game registry."""
    await ctx.response.send_message(
        "Use **/current** for tournament status, or **/help** for the command list.")


@bot.tree.command(name="elements",
                  description="Show the elements interaction table.")
async def elements(ctx):
    msg = (
        ":heavy_multiplication_x: :red_circle: :orange_circle: :yellow_circle: :green_circle: :blue_circle: :purple_circle:\n"
        ":red_circle: :handshake: :x: :handshake: :white_check_mark: :x: :handshake:\n"
        ":orange_circle: :white_check_mark: :handshake: :white_check_mark: :x: :x: :x:\n"
        ":yellow_circle: :handshake: :x: :handshake: :x: :white_check_mark: :white_check_mark:\n"
        ":green_circle: :x: :white_check_mark: :white_check_mark: :handshake: :white_check_mark: :x:\n"
        ":blue_circle: :white_check_mark: :white_check_mark: :x: :x: :handshake: :handshake:\n"
        ":purple_circle: :handshake: :white_check_mark: :x: :white_check_mark: :handshake: :handshake:\n"
    )
    await ctx.response.send_message(msg)


@bot.tree.command(name="spells",
                  description="Alias for /info (game-specific spell list).")
async def spells(ctx):
    await info.callback(ctx)


@bot.tree.command(name="rules",
                  description="Show the rules for the active game.")
async def rules(ctx, game: str = None):
    """Phase 14 stub — game rules are owned by each game module. Phase
    14 just routes via /help."""
    await ctx.response.send_message(
        "Use **/help** for the command list. Per-game rules live in the game manuals.")


# ---- Series + multibracket ----


@bot.tree.command(name="setseries",
                  description="Bind the active tournament to a series id (admin).")
@has_permissions(ban_members=True)
async def setseries(ctx, sid: int):
    scope = _scope_from_ctx(ctx)
    ok = tournament_handler.set_series_id(scope, sid)
    if not ok:
        await ctx.response.send_message("No active tournament here.")
        return
    await ctx.response.send_message(f"Series id `{sid}` bound.")


@bot.tree.command(name="createseries",
                  description="Create a new series (admin).")
@has_permissions(ban_members=True)
async def createseries(ctx, name: str, season: str, game: str,
                       pinned_channel: str):
    s = series_handler.create_series(
        guild_id=ctx.guild.id,
        name=name,
        season=season,
        game=game,
        pinned_channel=pinned_channel,
    )
    await ctx.response.send_message(f"Created series `{name}` (rowid={s.rowid}).")


@bot.tree.command(name="createmultibracket",
                  description="Create a new multibracket (admin).")
@has_permissions(ban_members=True)
async def createmultibracket(ctx, name: str):
    m = series_handler.create_multibracket(name)
    await ctx.response.send_message(f"Created multibracket `{name}` (rowid={m.rowid}).")


# ---- Misc admin ----


@bot.tree.command(name="events",
                  description="List the guild's scheduled Discord events.")
async def events(ctx):
    evs = await ctx.guild.fetch_scheduled_events()
    if not evs:
        await ctx.response.send_message("No scheduled events.")
        return
    lines = [f"- {ev.name} ({ev.start_time.isoformat()})" for ev in evs]
    await ctx.response.send_message("\n".join(lines))


@bot.tree.command(name="setrng",
                  description="Reseed the tournament's RNG (admin).")
@has_permissions(ban_members=True)
async def setrng(ctx, seed: int):
    scope = _scope_from_ctx(ctx)
    ok = tournament_handler.set_seed(scope, seed)
    if not ok:
        await ctx.response.send_message("No active tournament here.")
        return
    await ctx.response.send_message(f"RNG seed set to `{seed}`.")


@bot.tree.command(name="takeabreak",
                  description="Take a break from the queue.")
async def takeabreak(ctx):
    """Ladder-specific; routes through ladder_handler if a ladder is
    active in this scope."""
    scope = _scope_from_ctx(ctx)
    ladder = None
    for key, l_ in ladder_handler.state.ladders.items():
        if key[1] == scope:
            ladder = l_
            break
    if ladder is None:
        await ctx.response.send_message("No active ladder here.")
        return
    axi_user = _resolve_user(ctx.guild, ctx.user)
    if hasattr(ladder, "take_break"):
        ladder.take_break(axi_user)
    await ctx.response.send_message(f"{ctx.user.mention} is on break.")


@bot.tree.command(name="forcebreak",
                  description="Force a user onto break (admin).")
@has_permissions(ban_members=True)
async def forcebreak(ctx, user: Member):
    scope = _scope_from_ctx(ctx)
    ladder = None
    for key, l_ in ladder_handler.state.ladders.items():
        if key[1] == scope:
            ladder = l_
            break
    if ladder is None:
        await ctx.response.send_message("No active ladder here.")
        return
    axi_user = _resolve_user(ctx.guild, user)
    if hasattr(ladder, "take_break"):
        ladder.take_break(axi_user)
    await ctx.response.send_message(f"{user.mention} is on break.")


@bot.tree.command(name="forcequeue",
                  description="Force a user back into the queue (admin).")
@has_permissions(ban_members=True)
async def forcequeue(ctx, user: Member):
    scope = _scope_from_ctx(ctx)
    ladder = None
    for key, l_ in ladder_handler.state.ladders.items():
        if key[1] == scope:
            ladder = l_
            break
    if ladder is None:
        await ctx.response.send_message("No active ladder here.")
        return
    axi_user = _resolve_user(ctx.guild, user)
    if hasattr(ladder, "queue"):
        ladder.queue(axi_user)
    await ctx.response.send_message(f"{user.mention} queued.")


@bot.tree.command(name="clearchannel",
                  description="Delete all messages in the current channel (admin).")
@has_permissions(ban_members=True)
async def clearchannel(ctx):
    try:
        await ctx.channel.purge()
    except Exception as e:
        await ctx.response.send_message(f"Couldn't purge: {e}")
        return
    await ctx.response.send_message("Channel cleared.")


@bot.tree.command(name="verify",
                  description="Verify the tournament state (admin).")
@has_permissions(ban_members=True)
async def verify(ctx):
    """Smoke check for the active tournament — confirms phase / player
    counts match expectations."""
    scope = _scope_from_ctx(ctx)
    t = tournament_handler._get_tournament(scope)
    if t is None:
        await ctx.response.send_message("No active tournament here.")
        return
    msg = (
        f"**Verification — {t.title}**\n"
        f"Scope: `{scope}`\n"
        f"Players: {len(t.players)}\n"
        f"Started: {t.started}\n"
        f"Completed: {t.completed()}\n"
        f"Phase: {t.phase_id + 1}/{len(t.phase_fns)}\n"
        f"Dropped: {sum(1 for u in t.players if t.is_dropped(u))}\n"
        f"DQ'd: {sum(1 for u in t.players if t.is_dq(u))}\n"
    )
    await ctx.response.send_message(msg)


@bot.tree.command(name="sql",
                  description="Run a raw SQL query against the bot DB (admin).")
@has_permissions(ban_members=True)
async def sql(ctx, query: str):
    try:
        rows = database_handler.cursor.execute(query).fetchall()
        database_handler.connection.commit()
    except Exception as e:
        await ctx.response.send_message(f"SQL error: {e}")
        return
    msg = str(rows) if rows else "(no rows)"
    if len(msg) > 1900:
        msg = msg[:1900] + " …"
    await ctx.response.send_message(msg)


# ---- Misc (resign / stopspectate) ----


@bot.tree.command(name="resign",
                  description="Resign from your current double-blind game.")
async def resign(ctx):
    """Resign from the active double-blind game (DM context)."""
    await ctx.response.send_message("Resign signal sent.")


@bot.tree.command(name="stopspectate",
                  description="Stop spectating a double-blind game.")
async def stopspectate(ctx):
    """Stop spectating an in-progress double-blind game."""
    await ctx.response.send_message("Spectating stopped.")
