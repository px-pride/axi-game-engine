from collections import defaultdict
from copy import copy
from axi.abstract_cpu import AbstractCPU
import axi.handlers.discord_handler as discord_handler
import axi.axi as axi

users_to_matches = dict()
decision_msgs_to_matches = dict()
matches_to_decision_msgs = defaultdict(lambda: [])

def launch_match(name, players, mode="versus"):
    if name in axi.games:
        match = axi.games[name](players, mode=mode)
        if match.validate_mode():
            match.initialize_match_state()
            match.initialize_message_queue()
            match.refresh_decisions()
            for p in players:
                users_to_matches[p] = match
            return match
    return None

async def process_decision(user, decision):
    if isinstance(user, AbstractCPU):
        match = user.match
    elif user in users_to_matches:
        match = users_to_matches[user]
    else:
        return
    accepted = match.validate_decision(user, decision)
    messages = match.flush_message_queue(user)
    if len(messages) > 0 and not isinstance(user, AbstractCPU):
        msgs = [m[0] for m in messages]
        files = [m[1] for m in messages]
        await discord_handler.send_long(user, msgs, file=files, sleeptime=0.8)
    if decision == "abort" and user in users_to_matches:
        del users_to_matches[user]
    if not accepted:
        return
    if match.check_all_decisions_in():
        match_over = match.check_match_over()
        if match_over:
            for p in match.agents():
                messages = match.flush_message_queue(p)
                if len(messages) > 0 and not isinstance(p, AbstractCPU):
                    msgs = [m[0] for m in messages]
                    files = [m[1] for m in messages]
                    await discord_handler.send_long(p, msgs, file=files, sleeptime=0.8)
                if p in users_to_matches and users_to_matches[p] == match:
                    del users_to_matches[p]
        else:
            for dm in matches_to_decision_msgs[match]:
                del decision_msgs_to_matches[dm]
            matches_to_decision_msgs[match] = []
            await process_round(match)

async def process_command(user, command):
    if isinstance(user, AbstractCPU):
        match = user.match
    elif user in users_to_matches:
        match = users_to_matches[user]
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
    match_over = match.check_match_over()
    if match_over:
        for p in match.agents():
            messages = match.flush_message_queue(p)
            if len(messages) > 0 and not isinstance(p, AbstractCPU):
                msgs = [m[0] for m in messages]
                files = [m[1] for m in messages]
                await discord_handler.send_long(p, msgs, file=files, sleeptime=0.8)
            if p in users_to_matches and users_to_matches[p] == match:
                del users_to_matches[p]
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
