#!/usr/bin/env python3
"""
Example main file for running an Axi-based game engine tournament.
"""

from axi.axi import Axi
import os
import json

# Load configuration file
config_file = "examples/rps_example_league.json"

# Initialize Axi game engine
axi = Axi(config_file)

# Run the tournament
axi.run()