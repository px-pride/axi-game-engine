# Axi Game Engine Documentation

Welcome to the Axi Game Engine! This document will guide you through the codebase and help you understand how all the components work together.

## Introduction

Axi is a flexible engine for creating and running game tournaments with various game types. Whether you're building a simple game like Rock-Paper-Scissors or a complex turn-based strategy game, Axi provides the framework to run matches, track player progress, maintain rankings, and even integrate with services like Discord for tournament announcements.

## The Big Picture

At its core, Axi is about managing competitions between players across multiple game sessions. Here's the general flow:

1. **Configuration**: Everything starts with a configuration file that defines the game, tournament structure, and integrated services.
2. **Game Definition**: Games implement the AbstractGame interface to standardize how moves are made and results are determined.
3. **Tournament Execution**: The engine schedules matches, runs games, and updates player rankings based on results.
4. **Results and Reporting**: Final standings are calculated and can be reported through various channels like Discord.

## Key Components

### The Axi Class

The journey begins in `axi/axi.py` with the main `Axi` class. This is the central coordinator that:

- Loads configuration from a JSON file
- Initializes all the necessary handlers
- Dynamically loads the specified game class
- Runs the tournament according to the schedule
- Reports results through configured channels

### Game Abstraction

The `AbstractGame` class in `axi/abstract_game.py` defines the interface that all games must implement. This includes methods for:

- Setting up the game (`setup()`)
- Getting player moves (`get_player_move()`)
- Applying moves to the game state (`apply_move()`)
- Checking if the game is over (`is_game_over()`)
- Getting the final result (`get_result()`)

The standardized `run()` method ties these together into a complete game loop.

### Players and CPUs

Players in Axi can be human or AI-controlled. The `SimpleCPU` class in `axi/simple_cpu.py` demonstrates a basic AI implementation that can make random moves or follow configured probability distributions.

Players are uniquely identified and their progress is tracked across tournaments. The `UserHandler` manages player registration and data.

### Ladder and Ratings

The ladder system in `axi/ladder.py` tracks player rankings using various rating algorithms. The `LadderHandler` in `axi/handlers/ladder_handler.py` manages the interface between matches and the rating system.

Axi supports multiple rating systems:
- **Glicko Timeless**: A variation of the Glicko-2 rating system
- **Danisen**: A traditional dan/kyu ranking system
- **Plackett-Luce Extended**: A probabilistic model for ranking

### Tournament Structure

The `ScheduleHandler` creates match schedules based on the tournament format (round-robin, swiss, etc.). The `MatchHandler` then executes these matches using the game implementation.

### Integration Handlers

Various handlers connect Axi to external services:
- `DatabaseHandler`: Manages persistent storage
- `DiscordHandler`: Posts announcements and results to Discord
- `LadderHandler`: Updates and tracks player ratings
- `MatchHandler`: Runs matches between players
- `ScheduleHandler`: Creates tournament schedules
- `UserHandler`: Manages player information

### Testing Framework

The engine includes built-in testing support:

- `TestDiscordHandler`: A specialized version of the Discord handler for testing Discord integration without requiring an actual Discord connection. It provides methods for verifying that messages are correctly formatted and sent at the appropriate times.

To use the testing framework, set `"test_mode": true` in the Discord configuration section. This will automatically use the `TestDiscordHandler` instead of the regular `DiscordHandler`. See `examples/test_discord.py` for a demonstration.

## Walking Through an Example

Let's trace the execution of a simple Rock-Paper-Scissors tournament:

1. The process begins in `example_main.py`, which loads a configuration file and initializes an `Axi` instance.
2. The `Axi` instance loads the `RockPaperScissors` game class and creates CPU players.
3. A round-robin schedule is created, pairing each player against every other player.
4. For each match:
   - A new `RockPaperScissors` game is created with two players
   - The game runs until completion, with each player making moves
   - The result is used to update player ratings in the ladder
   - Results may be posted to Discord if configured
5. After all matches, final standings are calculated and reported.

## Extending Axi

The engine is designed for extensibility:

1. **Creating New Games**: Implement `AbstractGame` with your game logic
2. **Custom Rating Systems**: Add new rating algorithms in the `ratings` package
3. **Tournament Formats**: Extend scheduling options in `ScheduleHandler`
4. **Service Integration**: Add new handlers or extend existing ones

## Conclusion

Axi provides a flexible framework for running game tournaments. By standardizing the interfaces between games, players, and tournament structures, it allows developers to focus on game-specific logic while handling the complexities of tournament management behind the scenes.

As you explore the codebase, start with the configuration files to understand the options available, then dive into the game implementations to see how they leverage the engine's capabilities.