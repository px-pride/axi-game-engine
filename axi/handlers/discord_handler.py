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
)

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
            async def _cb(n=name, a=args):
                await execute_callback(n, a)
            await schedule_handler.schedule_event(
                time() + delay, _cb, keys=keys, suffix=suffix)


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
