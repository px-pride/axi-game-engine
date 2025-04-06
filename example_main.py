#!/usr/bin/env python3
"""
Example main file for running an Axi-based game engine tournament.
"""

import sys
import os
import json
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("example_main")

# Import Axi after logging is configured
from axi.axi import Axi

def main():
    """Run an example Axi tournament."""
    try:
        # Load configuration file
        config_file = "examples/rps_example_league.json"
        logger.info(f"Using configuration file: {config_file}")
        
        # Check if the config file exists
        if not os.path.exists(config_file):
            logger.error(f"Configuration file not found: {config_file}")
            return 1
            
        # Initialize Axi game engine
        logger.info("Initializing Axi game engine")
        axi = Axi(config_file)
        
        # Run the tournament
        logger.info("Running tournament")
        standings = axi.run()
        
        # Display final standings
        logger.info("Tournament completed")
        print("\nFinal Standings:")
        for standing in standings:
            print(f"{standing['rank']}. {standing['player_id']} - {standing['display']}")
            
        return 0
    except Exception as e:
        logger.exception(f"Error running tournament: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())