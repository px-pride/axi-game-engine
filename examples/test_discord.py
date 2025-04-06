#!/usr/bin/env python3
"""
Example script demonstrating the test Discord handler.
"""

import sys
import os
import json
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("test_discord")

# Handle imports - add parent directory to path for imports if running directly
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import Axi after logging is configured
from axi.axi import Axi
from axi.testing.test_discord_handler import TestDiscordHandler

def create_test_config():
    """Create a configuration with test Discord settings."""
    # Start with the default RPS config
    config_file = "examples/rps_example_league.json"
    
    with open(config_file, 'r') as f:
        config = json.load(f)
    
    # Enable Discord with test mode
    if "discord" not in config:
        config["discord"] = {}
    
    config["discord"]["enabled"] = True
    config["discord"]["test_mode"] = True
    # Add dummy values to ensure test mode works
    config["discord"]["token"] = "test_token"
    config["discord"]["channel_id"] = "test_channel_id"
    
    # Write to a temporary file
    test_config_file = "examples/test_discord_config.json"
    with open(test_config_file, 'w') as f:
        json.dump(config, f, indent=2)
        
    return test_config_file

def run_tournament_with_test_discord():
    """Run a tournament with the test Discord handler."""
    test_config_file = create_test_config()
    logger.info(f"Created test configuration file: {test_config_file}")
    
    # Initialize Axi with test configuration
    axi = Axi(test_config_file)
    
    # Verify that TestDiscordHandler was initialized
    if not isinstance(axi.discord_handler, TestDiscordHandler):
        logger.error("TestDiscordHandler was not initialized correctly")
        return 1
    
    logger.info("TestDiscordHandler initialized successfully")
    
    # Post test messages
    tournament_data = {
        "name": "Test Tournament",
        "description": "A tournament for testing Discord integration",
        "start_date": datetime.now().isoformat(),
        "end_date": datetime.now().isoformat(),
        "format": "Round Robin"
    }
    
    # Post tournament announcement
    axi.discord_handler.post_tournament_announcement(tournament_data)
    
    # Verify message was logged correctly
    if not axi.discord_handler.verify_message_count("tournament_announcement", 1):
        logger.error("Tournament announcement verification failed")
    
    if not axi.discord_handler.verify_message_content(
        "tournament_announcement", 0,
        **{"embeds.0.title": "Tournament Announcement: Test Tournament"}
    ):
        logger.error("Tournament announcement content verification failed")
    
    # Run the tournament
    logger.info("Running tournament with Discord test mode")
    standings = axi.run()
    
    # After the tournament, verify that match results were posted
    match_count = axi.discord_handler.get_message_count("match_result")
    logger.info(f"Tournament generated {match_count} match result messages")
    
    # Verify that final standings were posted
    if not axi.discord_handler.verify_message_count("final_standings", 1):
        logger.error("Final standings verification failed")
    
    # Get the latest standings message and print it
    standings_message = axi.discord_handler.get_latest_message("final_standings")
    if standings_message:
        logger.info("Final standings message content:")
        print(json.dumps(standings_message, indent=2))
    
    logger.info("Test completed successfully")
    return 0

if __name__ == "__main__":
    sys.exit(run_tournament_with_test_discord())