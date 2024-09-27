from collections import defaultdict
from copy import copy
from discord.utils import get
from axi.abstract_cpu import AbstractCPU
import axi.handlers.discord_handler as discord_handler
import axi.handlers.ladder_handler as ladder_handler
import axi.axi as axi
from axi.thread_game import ThreadGame
from axi.abstract_dm_game import AbstractDmGame

users_to_dm_matches = dict()
users_to_thread_matches = dict()
decision_msgs_to_matches = dict()
matches_to_decision_msgs = defaultdict(lambda: [])
discord_threads_to_matches = dict()

def launch_match(name, players, mode="versus", ladder=None, best_of=1, checkin_timer=None, label="UNRANKED"):
    match = None
    if name in axi.dm_games:
        candidate = axi.dm_games[name](
            players, mode=mode, ladder=ladder, best_of=best_of, checkin_timer=checkin_timer, label=label)
        if not candidate.validate_mode():
            return None
        match = candidate
        match.initialize_match_state()
        match.initialize_message_queue()
        match.refresh_decisions()
        for p in players:
            users_to_dm_matches[p] = match
    elif name in axi.thread_games:
        match = ThreadGame(axi.thread_games[name],
            players, mode=mode, ladder=ladder, best_of=best_of, checkin_timer=checkin_timer, label=label)
        for p in players:
            users_to_thread_matches[p] = match
    return match

async def process_decision(user, decision):
    if isinstance(user, AbstractCPU):
        match = user.match
    elif user in users_to_dm_matches:
        match = users_to_dm_matches[user]
    else:
        return
    accepted = match.validate_decision(user, decision)
    messages = match.flush_message_queue(user)
    if len(messages) > 0 and not isinstance(user, AbstractCPU):
        msgs = [m[0] for m in messages]
        files = [m[1] for m in messages]
        await discord_handler.send_long(user, msgs, file=files, sleeptime=0.8)
    if decision == "abort" and user in users_to_dm_matches:
        del users_to_dm_matches[user]
    if not accepted:
        return
    if match.check_all_decisions_in():
        if match.check_match_over():
            await close_match(match)
        else:
            for dm in matches_to_decision_msgs[match]:
                del decision_msgs_to_matches[dm]
            matches_to_decision_msgs[match] = []
            await process_round(match)

async def process_command(user, command):
    if isinstance(user, AbstractCPU):
        match = user.match
    elif user in users_to_dm_matches:
        match = users_to_dm_matches[user]
    else:
        return
    if match.receive_command(user, command):
        messages = match.flush_message_queue(user)
        if len(messages) > 0 and not isinstance(user, AbstractCPU):
            msgs = [m[0] for m in messages]
            files = [m[1] for m in messages]
            await discord_handler.send_long(user, msgs, file=files, sleeptime=0.8)

async def process_round(match):
    match.match_step()
    discord_messages = dict()
    for p in match.agents():
        messages = match.flush_message_queue(p)
        if len(messages) > 0 and not isinstance(p, AbstractCPU):
            msgs = [m[0] for m in messages]
            files = [m[1] for m in messages]
            discord_messages[p] = await discord_handler.send_long(p, msgs, file=files, sleeptime=0.8)
    match.refresh_decisions()
    if match.check_match_over():
        await close_match(match)
    else:
        for p in match.players:
            if match.expected_num_decisions[p] > 0:
                if isinstance(p, AbstractCPU):
                    decision = p.compute(copy(match.get_options(p)))
                    await process_decision(p, decision)
                else:
                    decision_msgs_to_matches[discord_messages[p]] = match
                    matches_to_decision_msgs[match].append(discord_messages[p])
                    for o in match.get_options(p):
                        await discord_messages[p].add_reaction(o)

async def close_match(match):
    if isinstance(match, AbstractDmGame):
        for p in match.agents():
            messages = match.flush_message_queue(p)
            if len(messages) > 0 and not isinstance(p, AbstractCPU):
                msgs = [m[0] for m in messages]
                files = [m[1] for m in messages]
                await discord_handler.send_long(p, msgs, file=files, sleeptime=0.8)
        for p in match.agents():
            if p in users_to_dm_matches and users_to_dm_matches[p] == match:
                del users_to_dm_matches[p]
    elif isinstance(match, ThreadGame):
        await match.discord_thread.edit(archived=True)
        await discord_handler.send_long(
            get(match.ladder.guild.channels, name=match.ladder.results_channel),
            f"{match.winner()} defeats {match.loser()}!\n")
        del discord_threads_to_matches[match.discord_thread]
        for p in match.agents():
            if p in users_to_thread_matches and users_to_thread_matches[p] == match:
                del users_to_thread_matches[p]
    if match.ladder:
        match.ladder.advance(match)
        await ladder_handler.update_ladders()

async def cancel_match(match):
    if isinstance(match, ThreadGame):
        await match.discord_thread.edit(archived=True)
        del discord_threads_to_matches[match.discord_thread]
    for p in match.agents():
        if p in users_to_dm_matches and users_to_dm_matches[p] == match:
            del users_to_dm_matches[p]
        elif p in users_to_thread_matches and users_to_thread_matches[p] == match:
            del users_to_thread_matches[p]
    if match.ladder:
        match.ladder.abort(match)
        await ladder_handler.update_ladders()

async def resolve_checkins(match):
    if isinstance(match, ThreadGame):
        for p in match.players:
            if p not in match.checkins:
                await discord_handler.send_long(
                    match.discord_thread, f"Check-in timer expired. Aborting match.\n")
                await cancel_match(match)
                return False
    return True
