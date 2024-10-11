from time import time, sleep
from copy import copy
from discord.utils import get
from axi.ladder import Ladder
from axi.util import supported_ladder_formats, rng, USER_STATUS_QUEUED, USER_STATUS_BREAK, USER_STATUS_CALLED
from axi.thread_game import ThreadGame
import axi.handlers.user_handler as user_handler
import axi.handlers.database_handler as database_handler
import axi.handlers.schedule_handler as schedule_handler
import axi.handlers.discord_handler as discord_handler
import axi.handlers.match_handler as match_handler

ladders = dict()
death_row = dict()
streamers = dict()
stream_pairs = dict()
stream_history = dict()
event_name = None
downtime_minimum = 20

def get_db_entry():
    return (
        event_name,
    )

def exists(guild, config):
    scope = config["queue-channel"]
    return (guild, scope) in ladders

def format_supported(fmt):
    return fmt in supported_ladder_formats

#async def create_tournament(self, caller, guild, channel, game, pinned_channel, name=None, season=None):
def start_ladder(guild, config, scheduled_event):
    scope = config["queue-channel"]
    ladder = Ladder(guild, config, scheduled_event)
    ladders[(guild, scope)] = ladder
    stream_pairs[ladder] = None
    streamers[ladder] = None
    stream_history[ladder] = []
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

async def matchmaking():
    # Clear stream match if needed.
    for l in ladders.values():
        if stream_pairs[l] and l.get_matches_by_pair(stream_pairs[l][0], stream_pairs[l][1])[-1].check_match_over():
            stream_pairs[l] = None

    # Identify available players by ladder.
    unoccupied = dict()
    queued_players = dict()
    occupied = set()
    for phase in ladders.values():
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
        for l in ladders.values():
            if not l.completed():
                setting[l] = []
        for p in unoccupied:
            l = rng.choice(unoccupied[p])
            setting[l].append(p)

        # Create hypothesis.
        pairings = dict()
        set_stream_match = dict()
        for l in ladders.values():
            if not l.completed():
                pairings[l] = generate_pairing_hypothesis(l, setting[l])
                set_stream_match[l] = select_random_stream_match(l, pairings[l]) if streamers[l] else None

        # Score hypothesis with stream match.
        score = score_hypothesis(
            pairings, set_stream_match)
        if score >= best_score:
            best_score = score
            best_pairings = pairings
            best_set_stream_match = set_stream_match

    # Finalize best hypothesis.
    results = dict()
    for l in best_pairings:
        results[l] = l.matchmaking(best_pairings[l][0], best_pairings[l][1], best_set_stream_match[l])
        stream_pairs[l] = best_set_stream_match[l]
        if best_set_stream_match[l]:
            stream_history[l].append(best_set_stream_match[l])
        start_time = time()
        for m in results[l]:
            await schedule_handler.schedule_event(
                start_time + m.checkin_timer,
                lambda m_=m:
                    match_handler.resolve_checkins(m_), [m])
    return results

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
        if clock0 < downtime_minimum or clock1 < downtime_minimum:
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
    last_streamed_players = stream_history[l][-1] if len(stream_history[l]) > 0 else []
    second_last_streamed_players = stream_history[l][-2] if len(stream_history[l]) > 1 else []
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

def score_hypothesis(pairings, stream_match_hypothesis):
    score = 0
    printing = False

    w_num_pairs = 100        # ++
    w_repeat_pairs = 60     # -
    w_rating_diff = 25      # -
    w_high_ratings = 0.2     # -
    for l in pairings:
        # Value: total number of pairs.
        score += w_num_pairs * len(pairings[l][0] + pairings[l][1])
        if printing:
            print("Number pairs: " + str(len(pairings[l][0] + pairings[l][1])))
            print("Score: " + str(w_num_pairs * len(pairings[l][0] + pairings[l][1])))
            print("Score: " + str(score))

        for x in pairings[l][0] + pairings[l][1]:
            p0 = x[0]
            p1 = x[1]

            # Devalue: repeat pairings.
            score -= w_repeat_pairs * len(l.matches_by_pair[p0][p1])
            if printing:
                print("Repeat pairs: " + str(l.matches_by_pair[p0][p1]))
                print("Score: " + str(-w_repeat_pairs * len(l.matches_by_pair[p0][p1])))
                print("Score: " + str(score))

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
    w_stream_match_repeat = 30      # -
    w_stream_ladder_diversity = 95  # ++
    desired_stream_ladder_ratio = {l: 1.0 / len(ladders) for l in ladders.values()}

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
        for l in ladders.values():
            current_stream_ladder_ratio[l] = len(l.stream_history) + 0.1
            if l == l_:
                current_stream_ladder_ratio[l] += 1
            current_stream_ladder_sum += current_stream_ladder_ratio[l]
        for l in ladders.values():
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
    for x in ladders:
        if x[0] != guild:
            continue
        result.append(x[1])
    return result

async def queue(caller, guild, channel):
    user = user_handler.get_user(guild, caller)
    msg = ''
    scope = channel
    if (guild, scope) not in ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant to queue up in one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = ladders[(guild, scope)]
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

async def dequeue(caller, guild, channel):
    user = user_handler.get_user(guild, caller)
    msg = ''
    scope = channel
    if (guild, scope) not in ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = ladders[(guild, scope)]
    if phase.completed():
        msg += f"Sorry, the ladder is closed.\n"
    elif user not in phase.status_by_player or phase.status_by_player[user] == USER_STATUS_BREAK:
        msg += f"{user} is not currently queued.\n"
    else:
        msg += f"{user} has dequeued.\n"
        phase.dequeue(user)
    return msg

async def autoqueue(caller, guild, channel, mode):
    user = user_handler.get_user(guild, caller)
    msg = ''
    scope = channel
    if (guild, scope) not in ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = ladders[(guild, scope)]
    if phase.completed():
        msg += f"Sorry, the ladder is closed.\n"
    elif user not in phase.status_by_player:
        if phase.add_new_player(user):
            msg += f"{user} has joined {phase.name}!\n"
            if mode == "on":
                phase.autoqueue_by_player[user] = True
                msg += f"{user} has turned autoqueue on.\n"
                msg += await queue(caller, guild, channel)
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
            msg += await queue(caller, guild, channel)
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
            msg += await dequeue(caller, guild, channel)
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

async def update_ladders(echo=True):
    if echo:
        await schedule_handler.schedule_event(
            time() + downtime_minimum + 5,
            lambda: update_ladders(echo=False))
    await matchmaking()
    await call_matches()
    await push_ladder_updates()

async def call_matches():
    for l in ladders.values():
        called = copy(l.called_matches)
        channel = get(l.guild.channels, name=l.queue_channel)
        for m in called:
            await discord_handler.create_versus_match_ux(m, l.game, channel)
            l.called_matches.remove(m)

async def status(caller, guild, channel):
    user = user_handler.get_user(guild, caller)
    msg = ''
    scope = channel
    if (guild, scope) not in ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = ladders[(guild, scope)]
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

async def history(caller, guild, channel):
    user = user_handler.get_user(guild, caller)
    msg = ''
    scope = channel
    if (guild, scope) not in ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = ladders[(guild, scope)]
    if user not in phase.status_by_player and not phase.add_new_player(user):
        msg += f"Sorry, the ladder is closed.\n"
    else:
        matches = phase.get_matches_by_player(user)
        if not matches:
            msg += "No matches yet.\n"
        else:
            for match in matches:
                msg += match.description(pov=user)
        msg += "\n"
    return msg

def set_streamer(guild, channel, username):
    msg = ''
    scope = channel
    if (guild, scope) not in ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = ladders[(guild, scope)]
    if phase.completed():
        msg += f"Sorry, the ladder is closed.\n"
    else:
        user = user_handler.get_user(guild, username)
        streamers[phase] = user
        phase.streamed = True
        msg += f"Streamer set to {user} for {phase.name}.\n"
    return msg

def nostream(guild, channel):
    msg = ''
    scope = channel
    if (guild, scope) not in ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = ladders[(guild, scope)]
    if phase.completed():
        msg += f"Sorry, the ladder is closed.\n"
    else:
        streamers[phase] = None
        phase.streamed = False
        msg += f"Streamer successfully removed.\n"
    return msg

async def challenge(caller, guild, channel, opponent):
    user = user_handler.get_user(guild, caller)
    opp = user_handler.get_user(guild, opponent)
    msg = ''
    scope = channel
    if (guild, scope) not in ladders:
        options = get_ladders_in_guild(guild)
        if not options:
            msg += "No active ladders on this server.\n"
            return msg
        msg += f"No active ladder in this channel. Maybe you meant one of these channels:\n"
        for x in options:
            msg += f"* {x}\n"
        return msg
    msg = ""
    phase = ladders[(guild, scope)]
    if phase.completed():
        msg += f"Sorry, the ladder is closed.\n"
        return msg
    if user == opponent:
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
        await queue(caller, guild, channel)
        await queue(opponent, guild, channel)
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

async def push_ladder_updates():
    for l in ladders.values():
        await discord_handler.update_status_channel(l)
        await discord_handler.update_leaderboard_channel(l)

