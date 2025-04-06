#!/usr/bin/env python3
"""
Axi - A game engine for running tournaments and leagues with various game types.
"""

import json
import os
import importlib
import logging

# Configure basic logging if not already configured
if not logging.root.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
from .handlers.database_handler import DatabaseHandler
from .handlers.discord_handler import DiscordHandler
from .handlers.ladder_handler import LadderHandler
from .handlers.match_handler import MatchHandler
from .handlers.schedule_handler import ScheduleHandler
from .handlers.user_handler import UserHandler
from .ladder import Ladder

class Axi:
    """
    Main Axi game engine class.
    Handles configuration, game loading, and tournament execution.
    """
    
    def __init__(self, config_file):
        """
        Initialize the Axi engine with a configuration file.
        
        Args:
            config_file (str): Path to the configuration JSON file
        """
        self.config_file = config_file
        self.logger = logging.getLogger("axi")
        self.load_config()
        self.initialize_handlers()
        
    def load_config(self):
        """Load configuration from the specified file."""
        try:
            with open(self.config_file, 'r') as f:
                self.config = json.load(f)
            self.logger.info(f"Loaded configuration from {self.config_file}")
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            raise
            
    def initialize_handlers(self):
        """Initialize all the necessary handlers."""
        self.db_handler = DatabaseHandler(self.config.get("database", {}))
        self.discord_handler = DiscordHandler(self.config.get("discord", {}))
        self.user_handler = UserHandler(self.db_handler, self.config.get("users", {}))
        self.ladder_handler = LadderHandler(self.config.get("ladder", {}))
        self.match_handler = MatchHandler(self.config)
        self.schedule_handler = ScheduleHandler(self.config.get("schedule", {}))
        
    def load_game(self):
        """Load the game module specified in the configuration."""
        game_module = self.config.get("game", {}).get("module", "")
        game_class = self.config.get("game", {}).get("class", "")
        
        if not game_module or not game_class:
            self.logger.error("Game module or class not specified in config")
            raise ValueError("Game module or class not specified in config")
            
        try:
            module = importlib.import_module(game_module)
            self.game_class = getattr(module, game_class)
            self.logger.info(f"Loaded game {game_class} from {game_module}")
        except Exception as e:
            self.logger.error(f"Failed to load game: {e}")
            raise
            
    def run(self):
        """Run the tournament according to the configuration."""
        self.logger.info("Starting Axi tournament")
        self.load_game()
        
        # Create ladder based on configuration
        ladder = Ladder(self.config.get("ladder", {}), self.game_class)
        
        # Initialize schedule
        schedule = self.schedule_handler.create_schedule(
            self.user_handler.get_users(),
            self.config.get("schedule", {})
        )
        
        # Run matches according to schedule
        for match in schedule:
            result = self.match_handler.run_match(match, self.game_class)
            ladder.update(match, result)
            
            # Post results to Discord if enabled
            if self.config.get("discord", {}).get("enabled", False):
                self.discord_handler.post_match_result(match, result)
                
        # Post final standings to Discord if enabled
        if self.config.get("discord", {}).get("enabled", False):
            self.discord_handler.post_final_standings(ladder.get_standings())
            
        self.logger.info("Tournament completed successfully")
        return ladder.get_standings()