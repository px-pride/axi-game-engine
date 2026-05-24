from time import time
from copy import copy
from axi.ladder import Ladder
from axi.util import supported_ladder_formats, rng, USER_STATUS_QUEUED, USER_STATUS_BREAK, USER_STATUS_CALLED
from axi.effects import UpdateLadderUI, ScheduleCallback
import axi.handlers.database_handler as database_handler
import axi.handlers.match_handler as match_handler

class LadderState:
    def __init__(self):
        self.ladders = dict()
        self.ladders_by_id = dict()
        self.streamers = dict()
        self.stream_pairs = dict()
        self.stream_history = dict()
        self.downtime_minimum = 20

state = LadderState()

def exists(guild, config):
    scope = config["queue-channel"]
    return (guild, scope) in state.ladders

def format_supported(fmt):
    return fmt in supported_ladder_formats

#async def create_tournament(self, caller, guild, channel, game, pinned_channel, name=None, season=None):
def start_ladder(guild, config, scheduled_event):
    scope = config["queue-channel"]
    ladder = Ladder(guild, config, scheduled_event)
    state.ladders[(guild, scope)] = ladder
    state.ladders_by_id[id(ladder)] = ladder
    state.stream_pairs[ladder] = None
    state.streamers[ladder] = None
    state.stream_history[ladder] = []
    #end_event = lambda g=ctx.guild, c=config: end_ladder(g, c)
    #await schedule_handler.schedule_event(end_time.timestamp(), end_event)
    add_to_db(ladder)
    ladder.begin()
    return ladder

def add_to_db(ladder):
    if not database_handler.load_entry_where("guilds", "guild_id", ladder.guild.id):
        database_handler.add_entry("guilds", [
            ladder.guild.id,
            ladder.guild.name,
        ])
    ladder_row = database_handler.load_entry_multiwhere("ladders", [
        ("guild_id", ladder.guild.id),
        ("name", ladder.name)])
    if ladder_row:
        ladder.rowid = ladder_row[0]
    else:
        ladder.rowid = database_handler.add_entry("ladders", ladder.get_db_entry())

def matchmaking():
    effects = []

    # Clear stream match if needed.
    for l in state.ladders.values():
        if state.stream_pairs[l] and l.get_matches_by_pair(state.stream_pairs[l][0], state.stream_pairs[l][1])[-1].completed():
            state.stream_pairs[l] = None

    # Identify available players by ladder.
    unoccupied = dict()
    queued_players = dict()
    occupied = set()
    for phase in state.ladders.values():
        if not phase.completed():
            for p in phase.players:
                if p in occupied:
                    continue
                if phase.is_user_in_match(p):
                    occupied.add(p)
                    if p in unoccupied:
                        del unoccupied[p]
                    if p in queued_players:
                        del queued_players[p]
                    continue
                if phase.status_by_player[p] == USER_STATUS_QUEUED:
                    if p in unoccupied:
                        unoccupied[p].append(phase)
                    else:
                        unoccupied[p] = [phase]
                    if p in queued_players:
                        queued_players[p].append(phase)
                    else:
                        queued_players[p] = [phase]

    # Estimate best hypothesis.
    best_score = 0
    best_pairings = dict()
    best_set_stream_match = dict()
    for k in range(1000):
        setting = dict()
        for l in state.ladders.values():
            if not l.completed():
                setting[l] = []
        for p in unoccupied:
            l = rng.choice(unoccupied[p])
            setting[l].append(p)

        # Create hypothesis.
        pairings = dict()
        set_stream_match = dict()
        drowning = dict()
        for l in state.ladders.values():
            if not l.completed():
                pairings[l] = generate_pairing_hypothesis(l, setting[l])
                set_stream_match[l] = select_random_stream_match(l, pairings[l]) if state.streamers[l] else None
                # Phase 7: per-ladder drowning set for scoring weights.
                # Friendlies (base Ladder) returns no drowning; LadderElim
                # returns its lava-derived partition.
                _afloat, drowning_list = l.afloat_and_drowning(setting[l], [])
                drowning[l] = set(drowning_list)

        # Score hypothesis with stream match.
        score = score_hypothesis(
            pairings, set_stream_match, drowning)
        if score >= best_score:
            best_score = score
            best_pairings = pairings
            best_set_stream_match = set_stream_match

    # Finalize best hypothesis.
    results = dict()
    for l in best_pairings:
        nodes, _internal_effects = l.matchmaking(
            best_pairings[l][0], best_pairings[l][1], best_set_stream_match[l])
        results[l] = nodes
        state.stream_pairs[l] = best_set_stream_match[l]
        if best_set_stream_match[l]:
            state.stream_history[l].append(best_set_stream_match[l])
        # Checkin scheduling happens in call_matches() once we have the
        # actual Match object (id needed for the resolve_checkins callback).
    return effects

def generate_pairing_hypothesis(ladder, available):
    challenge_matches = []
    for m in ladder.challenges_on_deck:
        if m[0] in available and m[1] in available:
            challenge_matches.append(m)
        if m[0] in available:
            available.remove(m[0])
        if m[1] in available:
            available.remove(m[1])
    for m in challenge_matches:
        ladder.challenges_on_deck.remove(m)
    rng.shuffle(available)
    hypothesis = []
    for j in range(0, len(available), 2):
        p0 = available[j]
        if j + 1 == len(available):
            continue
        p1 = available[j+1]
        clock0 = ladder.query_downtime_clock(p0)
        clock1 = ladder.query_downtime_clock(p1)
        if clock0 < state.downtime_minimum or clock1 < state.downtime_minimum:
            continue
        viable = not ladder.matches_by_pair[p0][p1]
        if not viable:
            most_recently_played = p1 in ladder.matches_by_player[p0][-1].players
            most_recently_played = most_recently_played and p0 in ladder.matches_by_player[p1][-1].players
            most_recently_played = most_recently_played and ladder.player_count > 2
            if most_recently_played:
                continue
            if len(ladder.matches_by_pair[p0][p1]) > 2:
                continue
            elif len(ladder.matches_by_pair[p0][p1]) == 2:
                if ladder.matches_by_pair[p0][p1][0].winner() == ladder.matches_by_pair[p0][p1][1].winner():
                    continue
            #if not most_recently_played:
            #    late_stage = len(ladder.matches_by_player[p0]) >= min(6, ladder.player_count - 1)
            #    late_stage = len(ladder.matches_by_player[p1]) >= min(6, ladder.player_count - 1) and late_stage
            #    viable = late_stage
            viable = True
        if viable:
            hypothesis.append((p0, p1))
    return hypothesis, challenge_matches

def select_random_stream_match(l, pairings):
    matches = []
    for p in pairings[0] + pairings[1]:
        matches.append(p)
    if not matches:
        return None
    last_streamed_players = state.stream_history[l][-1] if len(state.stream_history[l]) > 0 else []
    second_last_streamed_players = state.stream_history[l][-2] if len(state.stream_history[l]) > 1 else []
    stream_match = None
    for m in matches:
        p0 = m[0]
        p1 = m[1]
        if l.player_count > 3:
            if p0 in last_streamed_players and p0 in second_last_streamed_players:
                continue
            if p1 in last_streamed_players and p1 in second_last_streamed_players:
                continue
        stream_match = m
        break
    if not stream_match:
        return None
    return stream_match

def score_hypothesis(pairings, stream_match_hypothesis, drowning=None):
    """Score a cross-ladder pairing + stream-match hypothesis.

    Phase 7 additions:
      - `drowning` arg (Dict[Ladder, Set[player]]): per-ladder drowning
        players. Adds `w_num_drowning=50` per drowning player per
        viable pair and `w_stream_drowning=50` if the stream match
        has drowning players. Defaults to empty dict.
      - `desired_stream_ladder_ratio` switched from uniform 1/N to
        source's primary-biased [0.5, 0.5/(N-1), ...] (first ladder
        in iteration order is primary).
      - Fixes the bare `ladders.values()` NameError at the old line 275.
    """
    score = 0
    printing = False

    if drowning is None:
        drowning = {}

    w_num_pairs = 100        # ++
    w_repeat_pairs = 60     # -
    w_rating_diff = 25      # -
    w_num_drowning = 50     # ++ Phase 7
    w_high_ratings = 0.2     # -
    for l in pairings:
        # Value: total number of pairs.
        score += w_num_pairs * len(pairings[l][0] + pairings[l][1])
        if printing:
            print("Number pairs: " + str(len(pairings[l][0] + pairings[l][1])))
            print("Score: " + str(w_num_pairs * len(pairings[l][0] + pairings[l][1])))
            print("Score: " + str(score))

        drowning_for_l = drowning.get(l, set())
        for x in pairings[l][0] + pairings[l][1]:
            p0 = x[0]
            p1 = x[1]

            # Devalue: repeat pairings.
            score -= w_repeat_pairs * len(l.matches_by_pair[p0][p1])
            if printing:
                print("Repeat pairs: " + str(l.matches_by_pair[p0][p1]))
                print("Score: " + str(-w_repeat_pairs * len(l.matches_by_pair[p0][p1])))
                print("Score: " + str(score))

            # Value (Phase 7): drowning players in this pair.
            for p in (p0, p1):
                if p in drowning_for_l:
                    score += w_num_drowning
                    if printing:
                        print(f"Drowning: {p}")
                        print(f"Score: {w_num_drowning}")
                        print(f"Score: {score}")

            # Devalue: pairs with high rating differences.
            score -= w_rating_diff * abs(l.ratings_by_player[p0][0] - l.ratings_by_player[p1][0]) / 100
            if printing:
                print("Rating diff: " + str(abs(l.ratings_by_player[p0][0] - l.ratings_by_player[p1][0]) / 100))
                print("Score: " + str(-w_rating_diff * abs(l.ratings_by_player[p0][0] - l.ratings_by_player[p1][0]) / 100))
                print("Score: " + str(score))
            for p in x:
                # Devalue: players with higher ratings.
                score -= w_high_ratings * l.ratings_by_player[p][0]
                if printing:
                    print("Rating: " + str(l.ratings_by_player[p][0]))
                    print("Score: " + str(-w_high_ratings * l.ratings_by_player[p][0]))
                    print("Score: " + str(score))

    w_min_total_sets = 50       # ++
    w_min_sets_per_ladder = 50  # ++

    total_sets = dict()
    min_played = dict()
    for l in pairings:
        for p in l.players:
            value = len(l.matches_by_player[p])
            for x in pairings[l][0] + pairings[l][1]:
                if p in x:
                    value += 1
                    break
            if p not in min_played:
                min_played[p] = value
            else:
                min_played[p] = min(value, min_played[p])
            if p not in total_sets:
                total_sets[p] = value
            else:
                total_sets[p] = value + total_sets[p]
    # Value: min total sets.
    score += w_min_total_sets * min(total_sets.values()) if total_sets.values() else 0
    if printing:
        print("Min Total Sets: " + str(min(total_sets.values()) if total_sets.values() else 0))
        print("Score: " + str(w_min_total_sets * min(total_sets.values()) if total_sets.values() else 0))
        print("Score: " + str(score))
    # Value: min sets per ladder.
    score += w_min_sets_per_ladder * sum(min_played.values()) / len(min_played) if min_played.values() else 0
    if printing:
        print("Min Sets Per Ladder: " + str(sum(min_played.values()) / len(min_played) if min_played.values() else 0))
        print("Score: " + str(w_min_sets_per_ladder * sum(min_played.values()) / len(min_played) if min_played.values() else 0))
        print("Score: " + str(score))

    w_stream_match_called = 80      # ++
    w_stream_drowning = 50          # ++ Phase 7
    w_stream_match_repeat = 30      # -
    w_stream_ladder_diversity = 95  # ++

    # Phase 7: primary-biased ladder ratio. First ladder in iteration
    # order gets 0.5; remaining N-1 ladders split the other 0.5 equally.
    # Fixes the prior NameError where `ladders.values()` was bare.
    ladders_list = list(state.ladders.values())
    desired_stream_ladder_ratio = {}
    if ladders_list:
        desired_stream_ladder_ratio[ladders_list[0]] = 0.5
        if len(ladders_list) > 1:
            per_secondary = 0.5 / (len(ladders_list) - 1)
            for ll in ladders_list[1:]:
                desired_stream_ladder_ratio[ll] = per_secondary
        else:
            # Single ladder: it gets the full 1.0 (was 0.5; rescale).
            desired_stream_ladder_ratio[ladders_list[0]] = 1.0

    for l_ in stream_match_hypothesis:
        stream_pair = stream_match_hypothesis[l_]
        if not stream_pair:
            continue

        # Value: stream match ready.
        score += w_stream_match_called
        if printing:
            print("Stream Pair: " + str(stream_pair))
            print("Score: " + str(w_stream_match_called))
            print("Score: " + str(score))

        # Value (Phase 7): stream match has drowning player(s).
        drowning_for_l = drowning.get(l_, set())
        for p in stream_pair:
            if p in drowning_for_l:
                score += w_stream_drowning
                if printing:
                    print(f"Stream Drowning: {p}")
                    print(f"Score: {w_stream_drowning}")
                    print(f"Score: {score}")

        for p in stream_pair:
            # Devalue: repeat players on stream.
            score -= w_stream_match_repeat * len(l_.stream_matches_by_player[p])
            if printing:
                print("Stream Match Repeat: " + str(len(l_.stream_matches_by_player[p])))
                print("Score: " + str(-w_stream_match_repeat * len(l_.stream_matches_by_player[p])))
                print("Score: " + str(score))

        # Value: stream ladder diversity.
        current_stream_ladder_ratio = dict()
        current_stream_ladder_sum = 0.0
        for l in state.ladders.values():
            current_stream_ladder_ratio[l] = len(l.stream_history) + 0.1
            if l == l_:
                current_stream_ladder_ratio[l] += 1
            current_stream_ladder_sum += current_stream_ladder_ratio[l]
        for l in state.ladders.values():
            current_stream_ladder_ratio[l] /= current_stream_ladder_sum
            score += w_stream_ladder_diversity * abs(
                current_stream_ladder_ratio[l] - desired_stream_ladder_ratio[l])
            if printing:
                print("Stream Ladder Diversity: " + str(abs(
                    current_stream_ladder_ratio[l] - desired_stream_ladder_ratio[l])))
                print("Score: " + str(w_stream_ladder_diversity * abs(
                    current_stream_ladder_ratio[l] - desired_stream_ladder_ratio[l])))
                print("Score: " + str(score))
    return score

def get_ladders_in_guild(guild):
    result = []
    for x in state.ladders:
        if x[0] != guild:
            continue
        result.append(x[1])
    return result

def queue(user, guild, channel):
    msg = ''
    scope = channel
    if (guild, scope) not in state.ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant to queue up in one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = state.ladders[(guild, scope)]
    if phase.completed():
        msg += f"Sorry, the ladder is closed.\n"
    elif user not in phase.status_by_player:
        if phase.add_new_player(user):
            msg += f"{user} has joined {phase.name}! You will be pinged for a match shortly.\n"
            phase.queue(user)
        else:
            msg += f"Sorry, the ladder is closed.\n"
    elif phase.status_by_player[user] == USER_STATUS_BREAK:
        msg += f"{user} has queued up! You will be pinged for a match shortly.\n"
        phase.queue(user)
    elif phase.status_by_player[user] == USER_STATUS_QUEUED:
        msg += f"{user} is already queued up! You will be pinged for a match shortly.\n"
    elif phase.status_by_player[user] == USER_STATUS_CALLED:
        msg += f"{user} is in a match!\n"
    return msg

def dequeue(user, guild, channel):
    msg = ''
    scope = channel
    if (guild, scope) not in state.ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = state.ladders[(guild, scope)]
    if phase.completed():
        msg += f"Sorry, the ladder is closed.\n"
    elif user not in phase.status_by_player or phase.status_by_player[user] == USER_STATUS_BREAK:
        msg += f"{user} is not currently queued.\n"
    else:
        msg += f"{user} has dequeued.\n"
        phase.dequeue(user)
    return msg

def autoqueue(user, guild, channel, mode):
    msg = ''
    scope = channel
    if (guild, scope) not in state.ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = state.ladders[(guild, scope)]
    if phase.completed():
        msg += f"Sorry, the ladder is closed.\n"
    elif user not in phase.status_by_player:
        if phase.add_new_player(user):
            msg += f"{user} has joined {phase.name}!\n"
            if mode == "on":
                phase.autoqueue_by_player[user] = True
                msg += f"{user} has turned autoqueue on.\n"
                msg += queue(user, guild, channel)
            elif mode == "off":
                phase.autoqueue_by_player[user] = False
                msg += f"{user} has turned autoqueue off.\n"
            else:
                msg += f'Autoqueue mode must be "on" or "off".\n'
        else:
            msg += f"Sorry, the ladder is closed.\n"
    elif phase.status_by_player[user] == USER_STATUS_BREAK:
        if mode == "on":
            phase.autoqueue_by_player[user] = True
            msg += f"{user} has turned autoqueue on.\n"
            msg += queue(user, guild, channel)
        elif mode == "off":
            phase.autoqueue_by_player[user] = False
            msg += f"{user} has turned autoqueue off.\n"
        else:
            msg += f'Autoqueue mode must be "on" or "off".\n'
    elif phase.status_by_player[user] == USER_STATUS_QUEUED:
        if mode == "on":
            phase.autoqueue_by_player[user] = True
            msg += f"{user} has turned autoqueue on.\n"
        elif mode == "off":
            phase.autoqueue_by_player[user] = False
            msg += f"{user} has turned autoqueue off.\n"
            msg += dequeue(user, guild, channel)
        else:
            msg += f'Autoqueue mode must be "on" or "off".\n'
    elif phase.status_by_player[user] == USER_STATUS_CALLED:
        if mode == "on":
            phase.autoqueue_by_player[user] = True
            msg += f"{user} has turned autoqueue on.\n"
        elif mode == "off":
            phase.autoqueue_by_player[user] = False
            msg += f"{user} has turned autoqueue off.\n"
        else:
            msg += f'Autoqueue mode must be "on" or "off".\n'
    return msg

def update_ladders(echo=True):
    effects = []
    if echo:
        effects.append(ScheduleCallback(
            delay_seconds=state.downtime_minimum + 5,
            callback_name="update_ladders_no_echo",
            callback_args={}))
    effects += matchmaking()
    effects += call_matches()
    effects += push_ladder_updates()
    return effects

def call_matches():
    """Consume each ladder's pending MatchNodes:
      - launch the underlying Match via match_handler.launch_match
      - register node↔match in tournament_state
      - prepare Discord UX (CreateMatchThread / PresentDecision / ...)
      - schedule the checkin resolver callback

    Post-Phase-5a Ladder.matchmaking populates `called_matches` with
    MatchNodes (not real Match objects). Phase 5a's flow: defer the
    `launch_match` call to here, then map node↔match in tournament_state
    so `match_handler.close_match → ladder.advance(match)` can find
    the MatchNode again.
    """
    from axi.tournament_state import state as tournament_state
    effects = []
    for l in state.ladders.values():
        called = copy(l.called_matches)
        for node in called:
            actual_match = match_handler.launch_match(
                l.game, node.players,
                mode=node.mode,
                ladder=l,
                best_of=node.best_of,
                checkin_timer=node.checkin_timer,
                label=node.label,
            )
            if actual_match is None:
                l.called_matches.remove(node)
                continue
            tournament_state.map_node_to_match(node.node_id, id(actual_match))
            actual_match.streamed = node.streamed

            launch_msg = f"Launching {l.game.upper()}: {node.players[0]} vs. {node.players[1]}.\n"
            stream_notice = None
            if node.streamed and state.streamers.get(l):
                streamer = state.streamers[l]
                stream_notice = (
                    ':tv: :tv: :tv: :tv: :tv: :tv: :tv: :tv: :tv: :tv:\n'
                    f'**STREAMED.** Please wait for {streamer.parse(mention=True)} to spectate!'
                    '\n:tv: :tv: :tv: :tv: :tv: :tv: :tv: :tv: :tv: :tv:\n\n')
            effects += match_handler.prepare_match_ux(
                actual_match, l.game,
                channel_name=l.queue_channel,
                guild_id=l.guild.id,
                stream_notice=stream_notice,
                launch_message=launch_msg)
            if node.checkin_timer:
                effects.append(ScheduleCallback(
                    delay_seconds=node.checkin_timer,
                    callback_name="resolve_checkins",
                    callback_args={"match_id": id(actual_match)},
                    keys=node.players,
                    suffix="checkin"))
            l.called_matches.remove(node)
    return effects

def status(user, guild, channel):
    msg = ''
    scope = channel
    if (guild, scope) not in state.ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = state.ladders[(guild, scope)]
    if phase.completed():
        msg += f"Sorry, the ladder is closed.\n"
    else:
        if user not in phase.status_by_player and not phase.add_new_player(user):
            msg += f"Sorry, the ladder is closed.\n"
        else:
            match = phase.get_current_match_by_player(user)
            if match:
                msg += f"Your match against {match.opponent(user)} is ready!\n"
                msg += "Go to the thread in which you were pinged.\n"
            else:
                ladder_status = phase.status_by_player[user]
                if ladder_status == USER_STATUS_BREAK:
                    msg += "You are not currently queued for matchmaking! Use */queue* to queue up.\n"
                elif ladder_status == USER_STATUS_QUEUED:
                    msg += "You are queued up for matchmaking! You will be pinged when a match is available.\n"
                    autoq = phase.autoqueue_by_player[user]
                    if autoq:
                        msg += "You have autoqueue turned on. You can turn it off with */autoqueue off*.\n"
                    else:
                        msg += "You have autoqueue turned off. You can turn it on with */autoqueue on*.\n"
                else:
                    msg += f"Weird status: {ladder_status}"
    return msg

def history(user, guild, channel):
    msg = ''
    scope = channel
    if (guild, scope) not in state.ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = state.ladders[(guild, scope)]
    if user not in phase.status_by_player and not phase.add_new_player(user):
        msg += f"Sorry, the ladder is closed.\n"
    else:
        from axi.tournament_state import state as tournament_state
        nodes = phase.get_matches_by_player(user)
        if not nodes:
            msg += "No matches yet.\n"
        else:
            for node in nodes:
                match_id = tournament_state.get_match_for_node(node.node_id)
                actual = match_handler.state.matches_by_id.get(match_id)
                if actual is not None and hasattr(actual, "description"):
                    msg += actual.description(pov=user)
                else:
                    # Fallback to MatchNode info if the underlying Match was archived.
                    msg += f"{node.label}: {node.players[0]} vs {node.players[1]} ({node.score[0]}-{node.score[1]})\n"
        msg += "\n"
    return msg

def set_streamer(guild, channel, user):
    msg = ''
    scope = channel
    if (guild, scope) not in state.ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = state.ladders[(guild, scope)]
    if phase.completed():
        msg += f"Sorry, the ladder is closed.\n"
    else:
        state.streamers[phase] = user
        phase.streamed = True
        msg += f"Streamer set to {user} for {phase.name}.\n"
    return msg

def nostream(guild, channel):
    msg = ''
    scope = channel
    if (guild, scope) not in state.ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = state.ladders[(guild, scope)]
    if phase.completed():
        msg += f"Sorry, the ladder is closed.\n"
    else:
        state.streamers[phase] = None
        phase.streamed = False
        msg += f"Streamer successfully removed.\n"
    return msg

def challenge(user, guild, channel, opp):
    msg = ''
    scope = channel
    if (guild, scope) not in state.ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = state.ladders[(guild, scope)]
    if phase.completed():
        msg += f"Sorry, the ladder is closed.\n"
        return msg
    if user == opp:
        msg += "You can't challenge yourself!\n"
        return msg
    if user not in phase.status_by_player and not phase.add_new_player(user):
        msg += f"Sorry, the ladder is closed.\n"
        return msg
    if opp not in phase.status_by_player and not phase.add_new_player(opp):
        msg += f"Sorry, the ladder is closed.\n"
        return msg
    accepted, rejected = phase.challenge(user, opp)
    if rejected:
        msg += "You two have played each other enough today."
        return msg
    if accepted:
        queue(user, guild, channel)
        queue(opp, guild, channel)
        msg += f"{user} has accepted {opp}'s challenge!\nMatch on deck.\n"
        return msg
    else:
        msg += f"{user} has challenged {opp.parse(mention=True)}!\n{opp}, use */challenge @{user}* to accept.\n"
        return msg

def update_ratings_db(ladder, players):
    for p in players:
        database_handler.update_entry_multiwhere(
            "ratings",
            [("ladder_id", ladder.rowid), ("player_id", p.uid.id)],
            [ladder.rowid,
             p.uid.id,
             ladder.ratings_by_player[p][0],
             ladder.ratings_by_player[p][1]])

def load_from_ratings_db(ladder, p):
    ratings_row = database_handler.load_entry_multiwhere(
        "ratings", [
            ("ladder_id", ladder.rowid),
            ("player_id", p.uid.id),
        ])
    if ratings_row:
        return (ratings_row[3], ratings_row[4])
    return None

def push_ladder_updates():
    return [UpdateLadderUI(ladder_id=id(l)) for l in state.ladders.values()]
