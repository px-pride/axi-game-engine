# Axi Game Engine Pseudocode

This document outlines the high-level pseudocode for the main components of the Axi game engine.

## Main Engine Loop

```
function AXI_MAIN(config_file):
    config = LOAD_CONFIG(config_file)
    game_class = LOAD_GAME_MODULE(config.game)
    
    players = INITIALIZE_PLAYERS(config.users)
    ladder = INITIALIZE_LADDER(config.ladder)
    schedule = CREATE_SCHEDULE(players, config.schedule)
    
    for match in schedule:
        player1, player2 = GET_PLAYERS(match, players)
        game = INITIALIZE_GAME(game_class, [player1, player2], config.game)
        result = RUN_MATCH(game)
        
        UPDATE_LADDER(ladder, result)
        STORE_RESULT(result)
        
        if config.discord.enabled:
            POST_RESULT_TO_DISCORD(result)
    
    final_standings = GET_STANDINGS(ladder)
    
    if config.discord.enabled:
        POST_STANDINGS_TO_DISCORD(final_standings)
        
    return final_standings
```

## Game Execution

```
function RUN_MATCH(game):
    game.setup()
    
    while not game.is_game_over():
        for player in game.players:
            move = game.get_player_move(player, game.state)
            game.apply_move(player, move)
            
            if game.is_game_over():
                break
    
    return game.get_result()
```

## Ladder Updates

```
function UPDATE_LADDER(ladder, match_result):
    player_ids = match_result.player_ids
    winner = match_result.winner
    scores = match_result.scores
    
    current_ratings = {}
    for player_id in player_ids:
        current_ratings[player_id] = ladder.get_rating(player_id)
    
    new_ratings = CALCULATE_NEW_RATINGS(
        current_ratings, 
        player_ids,
        winner,
        scores,
        ladder.rating_system
    )
    
    for player_id, new_rating in new_ratings.items():
        ladder.set_rating(player_id, new_rating)
```

## Schedule Creation

```
function CREATE_ROUND_ROBIN_SCHEDULE(players, rounds):
    schedule = []
    
    for round in range(rounds):
        for i in range(len(players)):
            for j in range(i + 1, len(players)):
                match = {
                    "round": round,
                    "player1": players[i],
                    "player2": players[j]
                }
                schedule.append(match)
    
    return schedule
```

## CPU Player Decision Making

```
function CPU_GET_MOVE(cpu_player, game_state):
    game_type = DETECT_GAME_TYPE(game_state)
    available_moves = GET_AVAILABLE_MOVES(game_state, game_type)
    
    if cpu_player.has_move_probabilities(game_type):
        probabilities = cpu_player.get_move_probabilities(game_type)
        return WEIGHTED_RANDOM_CHOICE(available_moves, probabilities)
    else:
        return RANDOM_CHOICE(available_moves)
```

## Rating Calculation (Glicko-2 Example)

```
function CALCULATE_GLICKO_RATINGS(ratings, matches):
    for player_id, rating in ratings.items():
        opponents = []
        results = []
        
        for match in matches:
            if player_id in match.player_ids:
                opponent_id = GET_OPPONENT(match, player_id)
                opponent_rating = ratings[opponent_id]
                opponents.append(opponent_rating)
                
                result = 0.5  # Draw
                if match.winner == player_id:
                    result = 1.0  # Win
                elif match.winner is not None:
                    result = 0.0  # Loss
                
                results.append(result)
        
        new_rating = GLICKO2_UPDATE(
            rating.rating,
            rating.rd,
            rating.vol,
            opponents,
            results
        )
        
        ratings[player_id] = new_rating
    
    return ratings
```