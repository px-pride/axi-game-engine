from time import sleep
from traceback import format_exc
from copy import copy
from discord import Intents, File, Member, User
from discord.utils import get
from discord.ext import commands
from discord.ext.commands import Bot

import axi.axi as axi
import axi.handlers.match_handler as match_handler
import axi.handlers.user_handler as user_handler
from axi.abstract_cpu import AbstractCPU

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
    if isinstance(x, list):
        y = None
        for i in range(len(x)):
            if (x and x[i]) or (file and file[i]):
                y = await send_long(
                        channel, x[i],
                        file=file[i] if isinstance(file, list) else file if i == len(x) - 1 else None,
                        sleeptime=sleeptime[i] if isinstance(sleeptime, list) else sleeptime if i > 0 else None)
        return y
    if "\n\n" in x:
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

@bot.command()
@commands.is_owner()
# No global sync currently.
async def sync(ctx):
    await ctx.channel.send("Syncing...")
    bot.tree.copy_global_to(guild=ctx.guild)
    await bot.tree.sync(guild=ctx.guild)
    await bot.tree.sync()
    await ctx.channel.send("Synced!")

@bot.tree.command()
async def help(ctx):
    msg = ''
    msg += 'Use /games to view the game list.\n'
    msg += 'Use /solo or /versus to play.\n'
    msg += 'Use /spectate to watch someone else\'s gameplay.\n'
    msg += 'Use /abort to stop playing or spectating.\n'
    await send_long(ctx.channel, msg)

@bot.tree.command()
async def versus(ctx, game: str, opponent: str):
    if game not in axi.games:
        await send_long(ctx.channel, f"Invalid game. Use /games to see the game list.\n")
        return
    player1 = user_handler.get_user(ctx.guild, ctx.user)
    if player1 in match_handler.users_to_matches:
        await send_long(ctx.channel, f"{player1} is already in a match!\n")
        return
    player2 = user_handler.get_user(ctx.guild, opponent)
    if not player2:
        await send_long(ctx.channel, "Invalid player ping.\n")
        return
    if player2 in match_handler.users_to_matches:
        await send_long(ctx.channel, f"{player2} is already in a match!\n")
        return
    match = match_handler.launch_match(game, [player1, player2])
    await send_long(ctx.channel, f"Launching...", sleeptime=0.8)
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

@bot.tree.command()
async def solo(ctx, game: str, mode: str):
    if game not in axi.games:
        await send_long(ctx.channel, f"Invalid game. Use /games to see the game list.\n")
        return
    if mode == "versus":
        await send_long(ctx.channel, f"Use /versus instead.\n")
        return
    player = user_handler.get_user(ctx.guild, ctx.user)
    if player in match_handler.users_to_matches:
        await send_long(ctx.channel, f"{player} is already in a match!\n")
        return
    match = match_handler.launch_match(game, [player], mode=mode)
    if not match:
        await send_long(ctx.channel, "Invalid mode.\n")
        return
    await send_long(ctx.channel, f"Launching...", sleeptime=0.8)
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

@bot.tree.command()
async def spectate(ctx, player: str):
    user = user_handler.get_user(ctx.guild, ctx.user)
    player = user_handler.get_user(ctx.guild, player)
    if not player:
        await send_long(ctx.channel, "Invalid player ping.\n")
        return
    if player in match_handler.users_to_matches:
        match = match_handler.users_to_matches[player]
    else:
        await send_long(ctx.channel, "No match to spectate.\n")
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

@bot.tree.command()
async def abort(ctx):
    user = user_handler.get_user(ctx.guild, ctx.user)
    if not user in match_handler.users_to_matches:
        await send_long(ctx.channel, f"You are not in a match.")
        return
    match = match_handler.users_to_matches[user]
    if user in match.players:
        await match_handler.process_decision(user, "abort")
        await send_long(ctx.channel, f"{user} has aborted the game.")
    elif user in match.spectators:
        match.spectators.remove(user)
        for p in match.agents():
            await p.uid.send(f"{user} has stopped spectating.")

@bot.tree.command()
async def games(ctx):
    msg = "List of games:\n"
    for g in axi.games:
        msg += "* "
        msg += g
        msg += "\n"
    msg += "Use /solo or /versus to play!\n"
    await send_long(ctx.channel, msg)

@bot.event
async def on_message(message):
    await bot.process_commands(message)
    if not message.guild:
        user = user_handler.get_user(message.guild, message.author)
        if user in match_handler.users_to_matches and user in match_handler.users_to_matches[user].players:
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

