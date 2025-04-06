# Axi Game Engine Design Document

## Overview

Axi is a flexible game engine designed to run tournaments and leagues for various game types. The engine provides abstractions for game logic, player management, tournament scheduling, and rating systems.

## Core Components

### Game Abstraction

- `AbstractGame`: Base class that all games must implement
- `AbstractDMGame`: Extension for games with a dungeon master/GM role
- Provides standardized interfaces for:
  - Game setup
  - Move application
  - Game state management
  - Result determination

### Player Management

- Support for human and CPU players
- `SimpleCPU`: Basic CPU implementation that makes random moves
- `RandomCPU`: CPU that follows purely random strategies
- Player profiles and persistent statistics

### Tournament Structure

- `Ladder`: Manages player rankings and progression
- Rating systems:
  - Glicko-2 timeless variant
  - Danisen (dan/kyu system)
  - Extended Plackett-Luce model
- Schedule management for matches
  - Round-robin
  - Swiss tournament
  - Elimination brackets

### Game Backend

- Match execution and result tracking
- State persistence between matches
- Handling asynchronous and real-time games

### Integration

- Discord bot integration for announcements and results
- Database integration for persistent storage
- Extensible handlers for different services

## File Structure

```
axi-game-engine/
├── axi/                      # Core engine components
│   ├── abstract_game.py      # Base game classes
│   ├── abstract_cpu.py       # Base CPU player classes
│   ├── axi.py                # Main engine class
│   ├── ladder.py             # Ranking system
│   ├── assets/               # Engine assets
│   ├── handlers/             # Integration handlers
│   └── ratings/              # Rating systems
├── examples/                 # Example game implementations
│   ├── rock_paper_scissors.py
│   └── wonder_wand/          # More complex game example
│       ├── wonder_wand.py
│       └── ...
└── example_main.py           # Example runner script
```

## Workflow

1. Engine initialization with configuration
2. Game module loading and initialization
3. Player registration and initialization
4. Schedule generation
5. Match execution according to schedule
6. Rating updates based on results
7. Standings calculation and reporting

## Extension Points

The engine is designed to be extended in several ways:

1. New game implementations by subclassing `AbstractGame`
2. Custom CPU players by subclassing `AbstractCPU`
3. New rating systems in the `ratings` package
4. Additional integration handlers for external services
5. Custom tournament formats and schedulers