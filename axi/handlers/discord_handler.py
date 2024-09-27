from time import sleep, time
from traceback import format_exc
from copy import copy
from json import load
from datetime import datetime, timedelta, timezone
from pytimeparse.timeparse import timeparse

from discord import Intents, File, Member, User, Thread
from discord.utils import get
from discord.ext import commands
from discord.ext.commands import Bot
from discord.app_commands.checks import has_permissions
from discord.enums import ChannelType

import axi.axi as axi
import axi.handlers.match_handler as match_handler
import axi.handlers.user_handler as user_handler
import axi.handlers.schedule_handler as schedule_handler
import axi.handlers.ladder_handler as ladder_handler
import axi.handlers.database_handler as database_handler
from axi.abstract_cpu import AbstractCPU
from axi.abstract_dm_game import AbstractDmGame
from axi.thread_game import ThreadGame
from axi.util import USER_STATUS_QUEUED

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

@bot.command(name="sync")
@has_permissions(ban_members=True)
# No global sync currently.
async def sync(ctx):
    await ctx.channel.send("Syncing...")
    bot.tree.copy_global_to(guild=ctx.guild)
    await bot.tree.sync(guild=ctx.guild)
    await bot.tree.sync()
    await ctx.channel.send("Synced!")

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
    msg += 'Use */sync* to set up slash commands for your Discover server.\n'
    msg += 'Use */report* to report the winner of a match.\n'
    msg += 'Use */cancel* to cancel a match.\n'
    msg += 'Use */ladder* to open a ladder for queueing.\n'
    msg += 'Use */setstreamer* to select a streamer for the ladder.\n'
    msg += 'Use */clearevents* to delete all Discord server events.\n'
    msg += '\n'
    await ctx.response.send_message(msg)

@bot.tree.command(name="games")
async def games(ctx):
    msg = "List of DM games:\n"
    for g in axi.dm_games:
        msg += "* "
        msg += g
        msg += "\n"
    msg += "\nList of thread games:\n"
    for g in axi.thread_games:
        msg += "* "
        msg += g
        msg += "\n"
    msg += "Use /solo or /versus to play!\n"
    await ctx.response.send_message(msg)

@bot.tree.command(name="versus")
async def versus(ctx, game: str, opponent: str):
    if game not in axi.dm_games and game not in axi.thread_games:
        await ctx.response.send_message("Invalid game. Use /games to see the game list.\n")
        return
    player1 = user_handler.get_user(ctx.guild, ctx.user)
    if (game in axi.dm_games and player1 in match_handler.users_to_dm_matches) or (
        game in axi.thread_games and player1 in match_handler.users_to_thread_matches):
        await ctx.response.send_message(f"{player1} is already in a match!\n")
        return
    player2 = user_handler.get_user(ctx.guild, opponent)
    if not player2:
        await ctx.response.send_message("Invalid player ping.\n")
        return
    if (game in axi.dm_games and player2 in match_handler.users_to_dm_matches) or (
        game in axi.thread_games and player2 in match_handler.users_to_thread_matches):
        await ctx.response.send_message(f"{player2} is already in a match!\n")
        return
    match = match_handler.launch_match(game, [player1, player2])
    await create_versus_match_ux(match, game, ctx.channel, ctx=ctx)

async def create_versus_match_ux(match, game, channel, ctx=None):
    launch_msg = f"Launching {game.upper()}: {match.players[0]} vs. {match.players[1]}.\n"
    call_post = await ctx.response.send_message(launch_msg) if ctx else await send_long(channel, launch_msg, sleeptime=0.8)
    if game in axi.dm_games:
        for p in match.players:
            discord_message = None
            messages = match.flush_message_queue(p)
            if len(messages) > 0 and not isinstance(p, AbstractCPU):
                msgs = [m[0] for m in messages]
                files = [m[1] for m in messages]
                discord_message = await send_long(p, msgs, file=files, sleeptime=0.8)
            if match.expected_num_decisions[p] > 0:
                if isinstance(p, AbstractCPU):
                    decision = p.compute(copy(match.get_options(p)))
                    await match_handler.process_decision(p, decision)
                else:
                    match_handler.decision_msgs_to_matches[discord_message] = match
                    match_handler.matches_to_decision_msgs[match].append(discord_message)
                    for o in match.get_options(p):
                        await discord_message.add_reaction(o)
    else:
        thread_name = f"{match.players[0]} vs. {match.players[1]}"
        match.discord_thread = await channel.create_thread(
            name=thread_name, type=ChannelType.public_thread, message=call_post)
        match_handler.discord_threads_to_matches[match.discord_thread] = match
        messages = match.match_init_msg()
        if len(messages) > 0:
            msgs = [m[0] for m in messages]
            files = [m[1] for m in messages]
            await send_long(match.discord_thread, msgs, file=files, sleeptime=0.8)
        if match.streamed and match.ladder and ladder_handler.streamers[match.ladder]:
            msg = ''
            msg += ':tv: :tv: :tv: :tv: :tv: :tv: :tv: :tv: :tv: :tv:\n'
            msg += f'**STREAMED.** '
            msg += f'Please wait for {ladder_handler.streamers[match.ladder].parse(mention=True)} to spectate!'
            msg += '\n:tv: :tv: :tv: :tv: :tv: :tv: :tv: :tv: :tv: :tv:\n'
            msg += '\n'
            await send_long(match.discord_thread, msg, file='', sleeptime=0.8)

@bot.tree.command(name="solo")
async def solo(ctx, game: str, mode: str):
    if game not in axi.dm_games:
        if game in axi.thread_games:
            await ctx.response.send_message(f"Thread games can only be played in versus mode. Try /versus.\n")
            return
        await ctx.response.send_message(f"Invalid game. Use /games to see the game list.\n")
        return
    if mode == "versus":
        await ctx.response.send_message(f"Use /versus instead.\n")
        return
    player = user_handler.get_user(ctx.guild, ctx.user)
    if player in match_handler.users_to_dm_matches:
        await ctx.response.send_message(f"{player} is already in a match!\n")
        return
    match = match_handler.launch_match(game, [player], mode=mode)
    if not match:
        await ctx.response.send_message("Invalid mode.\n")
        return
    await ctx.response.send_message(f"Launching...")
    discord_message = None
    messages = match.flush_message_queue(player)
    if len(messages) > 0 and not isinstance(player, AbstractCPU):
        msgs = [m[0] for m in messages]
        files = [m[1] for m in messages]
        discord_message = await send_long(player, msgs, file=files, sleeptime=0.8)
    for p in match.players:
        if match.expected_num_decisions[p] > 0:
            if isinstance(p, AbstractCPU):
                decision = p.compute(copy(match.get_options(p)))
                await match_handler.process_decision(p, decision)
            else:
                match_handler.decision_msgs_to_matches[discord_message] = match
                match_handler.matches_to_decision_msgs[match].append(discord_message)
                for o in match.get_options(p):
                    await discord_message.add_reaction(o)

@bot.tree.command(name="spectate")
async def spectate(ctx, player: str):
    user = user_handler.get_user(ctx.guild, ctx.user)
    player = user_handler.get_user(ctx.guild, player)
    if not player:
        await ctx.response.send_message("Invalid player ping.\n")
        return
    if player in match_handler.users_to_dm_matches:
        match = match_handler.users_to_dm_matches[player]
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

@bot.tree.command(name="abort")
async def abort(ctx):
    user = user_handler.get_user(ctx.guild, ctx.user)
    if not ctx.guild:
        if not user in match_handler.users_to_dm_matches:
            await ctx.response.send_message(f"You are not in a match.")
            return
        match = match_handler.users_to_dm_matches[user]
        if user in match.players:
            await match_handler.process_decision(user, "abort")
            await ctx.response.send_message(f"{user} has aborted the game.")
        elif user in match.spectators:
            match.spectators.remove(user)
            for p in match.agents():
                await p.uid.send(f"{user} has stopped spectating.")
    else:
        if not user in match_handler.users_to_thread_matches:
            await ctx.response.send_message(f"You are not in a match.")
            return
        match = match_handler.users_to_thread_matches[user]
        match.report_abort(user)
        if match.check_match_over():
            await ctx.response.send_message(f"Match aborted. You may close this thread.")
            await match_handler.cancel_match(match)
        else:
            await ctx.response.send_message(f"Abort requested. Both players must confirm.")

@bot.tree.command(name="win")
async def win(ctx):
    if ctx.channel not in match_handler.discord_threads_to_matches:
        await ctx.response.send_message(f"Use this command in your thread to report that you won your match!")
        return
    match = match_handler.discord_threads_to_matches[ctx.channel]
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
        await ctx.response.send_message(f"Score reported. You may close this thread.")
        await match_handler.close_match(match)
    else:
        await ctx.response.send_message(f"Score reported. Both players must confirm.")

@bot.tree.command(name="lose")
async def lose(ctx):
    if ctx.channel not in match_handler.discord_threads_to_matches:
        await ctx.response.send_message(f"Use this command in your thread to report that you won your match!")
        return
    match = match_handler.discord_threads_to_matches[ctx.channel]
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
        await ctx.response.send_message(f"Score reported. You may close this thread.")
        await match_handler.close_match(match)
    else:
        await ctx.response.send_message(f"Score reported. Both players must confirm.")

@bot.tree.command(name="report")
@has_permissions(ban_members=True)
async def report(ctx, winner: str):
    if ctx.channel not in match_handler.discord_threads_to_matches:
        await ctx.response.send_message(f"Use this command in a thread to report the winner!")
        return
    match = match_handler.discord_threads_to_matches[ctx.channel]
    if not match:
        await ctx.response.send_message(f"Use this command in a thread to report the winner!")
        return
    if match.check_match_over():
        await ctx.response.send_message(f"This set has already been reported (winner: {match.winner()}).")
    match.report_winner(ctx.user, user_handler.get_user(ctx.guild, winner), admin_override=True)
    if match.check_match_over():
        await ctx.response.send_message(f"Score reported. You may close this thread.")
        await match_handler.close_match(match)
    else:
        await ctx.response.send_message(f"Score reported. Both players must confirm.")

@bot.tree.command(name="ladder")
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
    await ladder_handler.update_ladders()

@bot.tree.command(name="queue")
async def queue(ctx):
    msg = await ladder_handler.queue(ctx.user, ctx.guild, ctx.channel.name)
    await ctx.response.send_message(msg)
    await ladder_handler.update_ladders()

@bot.tree.command(name="dequeue")
async def dequeue(ctx):
    msg = await ladder_handler.dequeue(ctx.user, ctx.guild, ctx.channel.name)
    await ctx.response.send_message(msg)
    await ladder_handler.update_ladders()

@bot.tree.command(name="autoqueue")
async def autoqueue(ctx, mode: str):
    msg = await ladder_handler.autoqueue(ctx.user, ctx.guild, ctx.channel.name, mode)
    await ctx.response.send_message(msg)
    await ladder_handler.update_ladders()

@bot.tree.command(name="cancel")
@has_permissions(ban_members=True)
async def cancel(ctx):
    if ctx.channel not in match_handler.discord_threads_to_matches:
        await ctx.response.send_message(f"Use this command in a thread to cancel the match!")
        return
    match = match_handler.discord_threads_to_matches[ctx.channel]
    if not match:
        await ctx.response.send_message(f"Use this command in a thread to cancel the match!")
        return
    if match.check_match_over():
        await ctx.response.send_message(f"This set has already been reported (winner: {match.winner()}).")
    match.report_abort("admin")
    if match.check_match_over():
        await ctx.response.send_message(f"Match aborted. You may close this thread.")
        await match_handler.cancel_match(match)
    else:
        await ctx.response.send_message(f"Abort requested. Both players must confirm.")

@bot.tree.command(name="doubleblind")
async def doubleblind(ctx):
    if ctx.channel not in match_handler.discord_threads_to_matches:
        await ctx.response.send_message(f"Use this command in your thread to select characters double-blind with your opponent!")
        return
    match = match_handler.discord_threads_to_matches[ctx.channel]
    if not match:
        await ctx.response.send_message(f"Use this command in your thread to select characters double-blind with your opponent!")
        return
    user = user_handler.get_user(ctx.guild, ctx.user)
    if user not in match.players:
        await ctx.response.send_message(f"Use this command in your thread to select characters double-blind with your opponent!")
        return
    if match.check_match_over():
        await ctx.response.send_message(f"This set has already been reported (winner: {match.winner()}).")
    match = match_handler.launch_match("doubleblind", [user, match.opponent(user)])
    await create_versus_match_ux(match, "doubleblind", ctx.channel, ctx=ctx)

@bot.tree.command(name="lag")
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

@bot.tree.command(name="challenge")
async def challenge(ctx, opponent: str):
    msg = await ladder_handler.challenge(ctx.user, ctx.guild, ctx.channel.name, opponent)
    await ctx.response.send_message(msg)
    await ladder_handler.update_ladders()

@bot.tree.command(name="status")
async def status(ctx):
    msg = await ladder_handler.status(ctx.user, ctx.guild, ctx.channel.name)
    await ctx.response.send_message(msg)

@bot.tree.command(name="history")
async def history(ctx):
    msg = await ladder_handler.history(ctx.user, ctx.guild, ctx.channel.name)
    await ctx.response.send_message(msg)

@bot.tree.command(name="setstreamer")
@has_permissions(ban_members=True)
async def setstreamer(ctx, streamer: str):
    msg = ladder_handler.set_streamer(ctx.guild, ctx.channel.name, streamer)
    await ctx.response.send_message(msg)

@bot.tree.command(name="clearevents")
@has_permissions(ban_members=True)
async def clearevents(ctx):
    for event in list(ctx.guild.scheduled_events):
        await send_long(ctx.channel, f"Deleting {event.name}.")
        await event.delete()
    await ctx.response.send_message("Events cleared.")

@bot.tree.command(name="displayname")
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
    await ladder_handler.push_ladder_updates()

@bot.event
async def on_message(message):
    if message == "/sync":
        await sync()
    await bot.process_commands(message)
    if message.channel in match_handler.discord_threads_to_matches:
        match = match_handler.discord_threads_to_matches[message.channel]
        user = user_handler.get_user(message.guild, message.author)
        if user in match.players:
            if match.checkin_user(user):
                await send_long(message.channel, f"{user} has checked in!\n")
    if not message.guild:
        user = user_handler.get_user(message.guild, message.author)
        if user in match_handler.users_to_dm_matches and user in match_handler.users_to_dm_matches[user].players:
            await match_handler.process_command(user, message.content)

@bot.event
async def on_reaction_add(reaction, user):
    try:
        message = reaction.message
        user = user_handler.get_user(message.guild, user)
        emoji = reaction.emoji
        if message in match_handler.decision_msgs_to_matches:
            await match_handler.process_decision(user, emoji)
    except:
        print(format_exc())

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
            msg += f"*[{round(dan)}{suffix} Dan {prefix}{round(pos)}]* {user}\n"
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

