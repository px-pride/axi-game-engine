#!/usr/bin/env python3
"""
Ladder implementation for Axi game engine.
Manages player rankings, ratings, and standings.
"""

import logging
import importlib

class Ladder:
    """
    Manages player rankings and ratings for tournaments.
    """
    
    def __init__(self, config, game_class=None):
        """
        Initialize a new ladder.
        
        Args:
            config (dict): Configuration for the ladder
            game_class (optional): The game class this ladder is for
        """
        self.config = config
        self.game_class = game_class
        self.logger = logging.getLogger("axi.ladder")
        
        self.name = self.config.get("name", "Unnamed Ladder")
        self.rating_system_name = self.config.get("rating_system", "glicko_timeless")
        self.ratings = {}
        self.matches = []
        
        # Load the rating system
        self._load_rating_system()
        
    def _load_rating_system(self):
        """Load the specified rating system."""
        # Map system names to module paths and class names
        systems = {
            "glicko_timeless": ("axi.ratings.glicko_timeless", "GlickoTimeless"),
            "danisen": ("axi.ratings.danisen", "Danisen"),
            "plackett_luce": ("axi.ratings.plackett_luce_extended", "PlackettLuceExtended")
        }
        
        if self.rating_system_name not in systems:
            self.logger.error(f"Unknown rating system: {self.rating_system_name}")
            raise ValueError(f"Unknown rating system: {self.rating_system_name}")
        
        module_path, class_name = systems[self.rating_system_name]
        
        try:
            module = importlib.import_module(module_path)
            rating_class = getattr(module, class_name)
            self.rating_system = rating_class(self.config.get("config", {}))
            self.logger.info(f"Loaded rating system: {self.rating_system_name}")
        except Exception as e:
            self.logger.error(f"Failed to load rating system: {e}")
            raise
    
    def add_player(self, player_id):
        """
        Add a player to the ladder.
        
        Args:
            player_id: The ID of the player to add
        """
        if player_id not in self.ratings:
            self.ratings[player_id] = self.rating_system.get_initial_rating()
            self.logger.info(f"Added player {player_id} to ladder with initial rating")
    
    def get_rating(self, player_id):
        """
        Get a player's current rating.
        
        Args:
            player_id: The ID of the player
            
        Returns:
            The player's rating, or initial rating if not found
        """
        if player_id not in self.ratings:
            self.add_player(player_id)
            
        return self.ratings[player_id]
    
    def update(self, match_data, result):
        """
        Update ratings based on a match result.
        
        Args:
            match_data (dict): Data about the match
            result (dict): The result of the match
        """
        # Record the match
        self.matches.append({
            "match_data": match_data,
            "result": result
        })
        
        # Get player IDs from the result
        player_ids = result.get("player_ids", [])
        if not player_ids:
            self.logger.warning("No player IDs in result, can't update ratings")
            return
            
        # Make sure all players are in the ladder
        for player_id in player_ids:
            if player_id not in self.ratings:
                self.add_player(player_id)
        
        # Get winner and scores
        winner = result.get("winner")
        scores = result.get("scores", {})
        
        # Update ratings
        new_ratings = self.rating_system.update_ratings(
            self.ratings,
            player_ids,
            winner,
            scores
        )
        
        # Apply the new ratings
        for player_id, rating in new_ratings.items():
            self.ratings[player_id] = rating
            
        self.logger.info(f"Updated ratings after match: {new_ratings}")
    
    def get_standings(self):
        """
        Get the current ladder standings.
        
        Returns:
            list: Players sorted by their ratings
        """
        # Sort players by rating
        sorted_players = sorted(
            self.ratings.items(),
            key=lambda x: self.rating_system.get_sort_key(x[1]),
            reverse=True
        )
        
        # Create standings list
        standings = []
        for rank, (player_id, rating) in enumerate(sorted_players, 1):
            standings.append({
                "rank": rank,
                "player_id": player_id,
                "rating": rating,
                "display": self.rating_system.get_display_rating(rating)
            })
            
        return standings
    
    def get_player_history(self, player_id):
        """
        Get a player's match history.
        
        Args:
            player_id: The ID of the player
            
        Returns:
            list: The player's match history
        """
        history = []
        
        for match in self.matches:
            result = match["result"]
            if player_id in result.get("player_ids", []):
                opponent_id = next(
                    (pid for pid in result.get("player_ids", []) if pid != player_id),
                    None
                )
                
                outcome = "draw"
                if result.get("winner") == player_id:
                    outcome = "win"
                elif result.get("winner") is not None:
                    outcome = "loss"
                    
                history.append({
                    "match_id": result.get("match_id", ""),
                    "opponent_id": opponent_id,
                    "outcome": outcome,
                    "score": result.get("scores", {}).get(player_id, 0),
                    "opponent_score": result.get("scores", {}).get(opponent_id, 0),
                    "timestamp": result.get("timestamp", "")
                })
                
        return history
    
    def get_player_stats(self, player_id):
        """
        Get a player's statistics.
        
        Args:
            player_id: The ID of the player
            
        Returns:
            dict: The player's statistics
        """
        history = self.get_player_history(player_id)
        
        # Calculate statistics
        wins = sum(1 for match in history if match["outcome"] == "win")
        losses = sum(1 for match in history if match["outcome"] == "loss")
        draws = sum(1 for match in history if match["outcome"] == "draw")
        matches_played = len(history)
        
        # Calculate win rate
        win_rate = 0
        if matches_played > 0:
            win_rate = (wins + 0.5 * draws) / matches_played
            
        # Get current rating
        rating = self.get_rating(player_id)
        display_rating = self.rating_system.get_display_rating(rating)
        
        return {
            "player_id": player_id,
            "matches_played": matches_played,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "win_rate": win_rate,
            "rating": rating,
            "display_rating": display_rating
        }
    
    def save(self, db_handler, ladder_id):
        """
        Save the ladder state to the database.
        
        Args:
            db_handler: Database handler
            ladder_id: ID for this ladder in the database
        """
        ladder_data = {
            "name": self.name,
            "rating_system": self.rating_system_name,
            "ratings": self.ratings,
            "matches": self.matches,
            "config": self.config
        }
        
        db_handler.save_ladder(ladder_id, ladder_data)
        self.logger.info(f"Saved ladder {ladder_id} to database")
    
    @classmethod
    def load(cls, db_handler, ladder_id, game_class=None):
        """
        Load a ladder from the database.
        
        Args:
            db_handler: Database handler
            ladder_id: ID for the ladder in the database
            game_class (optional): The game class for this ladder
            
        Returns:
            Ladder: The loaded ladder, or None if not found
        """
        ladder_data = db_handler.get_ladder(ladder_id)
        if not ladder_data:
            return None
            
        # Create a new ladder with the saved config
        config = ladder_data.get("config", {})
        ladder = cls(config, game_class)
        
        # Load data
        ladder.name = ladder_data.get("name", ladder.name)
        ladder.ratings = ladder_data.get("ratings", {})
        ladder.matches = ladder_data.get("matches", [])
        
        return ladder