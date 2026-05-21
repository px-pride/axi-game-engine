from collections import defaultdict
from copy import copy
from axi.abstract_cpu import AbstractCPU
from axi.effects import (
    SendUserMessages, SendToThread, SendToChannel,
    PresentDecision, CreateMatchThread, ArchiveThread,
    UpdateLadderUI, ScheduleCallback,
)
import axi.registry as registry
from axi.thread_game import ThreadGame
from axi.abstract_dm_game import AbstractDmGame

class MatchState:
    def __init__(self):
        self.users_to_dm_matches = dict()
        self.users_to_thread_matches = dict()
        self.matches_by_id = dict()
        # match_id -> Callable[[match, winner, score], list[Effect]]
        # Optional per-match completion callback (e.g. tournament integration).
        self.completion_callbacks = dict()

state = MatchState()


def launch_match(name, players, mode="versus", ladder=None, best_of=1, checkin_timer=None, label="UNRANKED",
                 completion_callback=None):
    match = None
    if name in registry.dm_games:
        candidate = registry.dm_games[name](
            players, mode=mode, ladder=ladder, best_of=best_of, checkin_timer=checkin_timer, label=label)
        if not candidate.validate_mode():
            return None
        match = candidate
        match.initialize_match_state()
        match.initialize_message_queue()
        match.refresh_decisions()
        for p in players:
            state.users_to_dm_matches[p] = match
    elif name in registry.thread_games:
        match = ThreadGame(registry.thread_games[name],
            players, mode=mode, ladder=ladder, best_of=best_of, checkin_timer=checkin_timer, label=label)
        for p in players:
            state.users_to_thread_matches[p] = match
    if match:
        state.matches_by_id[id(match)] = match
        if completion_callback is not None:
            state.completion_callbacks[id(match)] = completion_callback
    return match


def prepare_match_ux(match, game_name, channel_name=None, guild_id=None, stream_notice=None, launch_message=None):
    """Generate effects for setting up match UX after launch_match. Pure function."""
    effects = []
    if game_name in registry.dm_games:
        for p in match.players:
            messages = match.flush_message_queue(p)
            if isinstance(p, AbstractCPU):
                if match.expected_num_decisions[p] > 0:
                    decision = p.compute(copy(match.get_options(p)))
                    effects += process_decision(p, decision)
            else:
                if match.expected_num_decisions[p] > 0:
                    effects.append(PresentDecision(
                        user_id=p.uid.id,
                        match_id=id(match),
                        messages=messages,
                        options=match.get_options(p)))
                elif messages:
                    effects.append(SendUserMessages(
                        user_id=p.uid.id,
                        messages=messages))
    else:
        thread_name = f"{match.players[0]} vs. {match.players[1]}"
        init_messages = match.match_init_msg()
        effects.append(CreateMatchThread(
            match_id=id(match),
            guild_id=guild_id,
            channel_name=channel_name,
            thread_name=thread_name,
            init_messages=init_messages,
            stream_notice=stream_notice,
            launch_message=launch_message))
    return effects


def process_decision(user, decision):
    effects = []
    if isinstance(user, AbstractCPU):
        match = user.match
    elif user in state.users_to_dm_matches:
        match = state.users_to_dm_matches[user]
    else:
        return effects
    accepted = match.validate_decision(user, decision)
    messages = match.flush_message_queue(user)
    if len(messages) > 0 and not isinstance(user, AbstractCPU):
        effects.append(SendUserMessages(user_id=user.uid.id, messages=messages))
    if decision == "abort" and user in state.users_to_dm_matches:
        del state.users_to_dm_matches[user]
    if not accepted:
        return effects
    if match.check_all_decisions_in():
        if match.check_match_over():
            effects += close_match(match)
        else:
            effects += process_round(match)
    return effects


def process_round(match):
    effects = []
    match.match_step()

    # Capture per-agent messages from the round
    agent_messages = {}
    for p in match.agents():
        messages = match.flush_message_queue(p)
        if messages and not isinstance(p, AbstractCPU):
            agent_messages[p] = messages

    match.refresh_decisions()

    if match.check_match_over():
        # Send round results first, then close_match sends game-over messages
        for p, msgs in agent_messages.items():
            effects.append(SendUserMessages(user_id=p.uid.id, messages=msgs))
        effects += close_match(match)
    else:
        for p in match.agents():
            if isinstance(p, AbstractCPU):
                if p in match.players and match.expected_num_decisions[p] > 0:
                    decision = p.compute(copy(match.get_options(p)))
                    effects += process_decision(p, decision)
                continue
            msgs = agent_messages.get(p, [])
            if p in match.players and match.expected_num_decisions[p] > 0:
                effects.append(PresentDecision(
                    user_id=p.uid.id,
                    match_id=id(match),
                    messages=msgs,
                    options=match.get_options(p)))
            elif msgs:
                effects.append(SendUserMessages(
                    user_id=p.uid.id,
                    messages=msgs))

    return effects


def close_match(match):
    effects = []
    if isinstance(match, AbstractDmGame):
        for p in match.agents():
            messages = match.flush_message_queue(p)
            if len(messages) > 0 and not isinstance(p, AbstractCPU):
                effects.append(SendUserMessages(user_id=p.uid.id, messages=messages))
        for p in match.agents():
            if p in state.users_to_dm_matches and state.users_to_dm_matches[p] == match:
                del state.users_to_dm_matches[p]
    elif isinstance(match, ThreadGame):
        effects.append(ArchiveThread(match_id=id(match)))
        effects.append(SendToChannel(
            guild_id=match.ladder.guild.id,
            channel_name=match.ladder.results_channel,
            messages=[(f"{match.winner()} defeats {match.loser()}!\n", None)]))
        for p in match.agents():
            if p in state.users_to_thread_matches and state.users_to_thread_matches[p] == match:
                del state.users_to_thread_matches[p]
    if match.ladder:
        match.ladder.advance(match)
        effects.append(UpdateLadderUI(ladder_id=id(match.ladder)))
    callback = state.completion_callbacks.pop(id(match), None)
    if callback is not None:
        try:
            winner = match.winner() if hasattr(match, "winner") else None
            score = getattr(match, "score", None)
            callback_effects = callback(match, winner, score)
            if callback_effects:
                effects += callback_effects
        except Exception:
            pass
    return effects


def cancel_match(match):
    effects = []
    if isinstance(match, ThreadGame):
        effects.append(ArchiveThread(match_id=id(match)))
    for p in match.agents():
        if p in state.users_to_dm_matches and state.users_to_dm_matches[p] == match:
            del state.users_to_dm_matches[p]
        elif p in state.users_to_thread_matches and state.users_to_thread_matches[p] == match:
            del state.users_to_thread_matches[p]
    if match.ladder:
        match.ladder.abort(match)
        effects.append(UpdateLadderUI(ladder_id=id(match.ladder)))
    return effects


def resolve_checkins(match):
    effects = []
    if isinstance(match, ThreadGame):
        for p in match.players:
            if p not in match.checkins:
                effects.append(SendToThread(
                    match_id=id(match),
                    messages=[("Check-in timer expired. Aborting match.\n", None)]))
                effects += cancel_match(match)
                return effects
    return effects


def process_command(user, command):
    effects = []
    if isinstance(user, AbstractCPU):
        match = user.match
    elif user in state.users_to_dm_matches:
        match = state.users_to_dm_matches[user]
    else:
        return effects
    if match.receive_command(user, command):
        messages = match.flush_message_queue(user)
        if len(messages) > 0 and not isinstance(user, AbstractCPU):
            effects.append(SendUserMessages(user_id=user.uid.id, messages=messages))
    return effects
