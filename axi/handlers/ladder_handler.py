#!/usr/bin/env python3
"""
Ladder handler for Axi game engine.
Manages rankings and ratings for players.
"""

import importlib
import logging

class LadderHandler:
    """
    Handles player rankings and ratings using various rating systems.
    """
    
    def __init__(self, config):
        """
        Initialize the ladder handler.
        
        Args:
            config (dict): Configuration for the ladder
        """
        self.config = config
        self.logger = logging.getLogger("axi.ladder")
        
        self.ratings = {}
        self.rating_system = None
        
        self._load_rating_system()
        
    def _load_rating_system(self):
        """Load the specified rating system."""
        system_name = self.config.get("rating_system", "glicko_timeless")
        
        # Map system names to module paths and class names
        systems = {
            "glicko_timeless": ("axi.ratings.glicko_timeless", "GlickoTimeless"),
            "danisen": ("axi.ratings.danisen", "Danisen"),
            "plackett_luce": ("axi.ratings.plackett_luce_extended", "PlackettLuceExtended")
        }
        
        if system_name not in systems:
            self.logger.error(f"Unknown rating system: {system_name}")
            raise ValueError(f"Unknown rating system: {system_name}")
        
        module_path, class_name = systems[system_name]
        
        try:
            module = importlib.import_module(module_path)
            rating_class = getattr(module, class_name)
            self.rating_system = rating_class(self.config.get("config", {}))
            self.logger.info(f"Loaded rating system: {system_name}")
        except Exception as e:
            self.logger.error(f"Failed to load rating system: {e}")
            raise
            
    def initialize_player(self, player_id):
        """
        Initialize a new player in the ladder.
        
        Args:
            player_id: The ID of the player to initialize
        """
        if player_id not in self.ratings:
            self.ratings[player_id] = self.rating_system.get_initial_rating()
            self.logger.info(f"Initialized player {player_id} with rating {self.ratings[player_id]}")
            
    def update_ratings(self, match_result):
        """
        Update ratings based on a match result.
        
        Args:
            match_result (dict): The result of a match
        """
        player_ids = match_result.get("player_ids", [])
        winner = match_result.get("winner")
        scores = match_result.get("scores", {})
        
        # Initialize any new players
        for player_id in player_ids:
            if player_id not in self.ratings:
                self.initialize_player(player_id)
        
        # Update ratings based on the result
        updated_ratings = self.rating_system.update_ratings(
            self.ratings,
            player_ids,
            winner,
            scores
        )
        
        self.ratings.update(updated_ratings)
        self.logger.info(f"Updated ratings after match: {updated_ratings}")
        
    def get_standings(self):
        """
        Get the current ladder standings.
        
        Returns:
            list: Players sorted by their ratings
        """
        sorted_players = sorted(
            self.ratings.items(),
            key=lambda x: self.rating_system.get_sort_key(x[1]),
            reverse=True
        )
        
        standings = []
        for rank, (player_id, rating) in enumerate(sorted_players, 1):
            standings.append({
                "rank": rank,
                "player_id": player_id,
                "rating": rating,
                "display": self.rating_system.get_display_rating(rating)
            })
            
        return standings