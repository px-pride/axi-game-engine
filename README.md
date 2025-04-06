# Axi Game Engine

A framework for creating and running game tournaments with support for different game modes, ratings systems, and tournament formats.

## Features

- Abstract game interfaces for creating various game types
- Multiple rating systems (Glicko, Danisen, Plackett-Luce)
- Tournament management and scheduling
- Discord integration for announcements
- CPU player implementations
- Database handling for persistent data

## Examples

The `examples` directory contains sample games implemented with the Axi engine:

- Rock Paper Scissors
- Wonder Wand (a more complex example game)

## Usage

See `example_main.py` for a basic implementation example.

```python
from axi.axi import Axi

# Load configuration file
config_file = "examples/rps_example_league.json"

# Initialize Axi game engine
axi = Axi(config_file)

# Run the tournament
axi.run()
```

## License

[License information here]