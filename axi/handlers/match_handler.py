#!/usr/bin/env python3
"""
Match handler for Axi game engine.
Handles running matches between players.
"""

import logging
import uuid
from datetime import datetime

class MatchHandler:
    """
    Handles running matches between players for the Axi game engine.
    """
    
    def __init__(self, config):
        """
        Initialize the match handler.
        
        Args:
            config (dict): Configuration for matches
        """
        self.config = config
        self.logger = logging.getLogger("axi.match")
        self.match_config = self.config.get("match", {})
        
    def run_match(self, match_data, game_class):
        """
        Run a match between players using the specified game class.
        
        Args:
            match_data (dict): Data about the match to run
            game_class: The game class to instantiate
            
        Returns:
            dict: The result of the match
        """
        player_ids = match_data.get("player_ids", [])
        players = match_data.get("players", [])
        
        if not player_ids and not players:
            self.logger.error("No players specified for match")
            raise ValueError("No players specified for match")
            
        if not players and player_ids:
            # If only IDs are provided, we need to resolve them to player objects
            players = self._resolve_players(player_ids)
            
        if not player_ids and players:
            # If only player objects are provided, extract IDs
            player_ids = [player.id for player in players]
        
        self.logger.info(f"Running match between players: {', '.join(player_ids)}")
        
        # Create game instance
        game_config = self.match_config.get("game_config", {})
        game = game_class(players, game_config)
        
        # Run the game
        result = game.run()
        
        # Add match metadata to result
        match_id = match_data.get("id", str(uuid.uuid4()))
        tournament_id = match_data.get("tournament_id", "")
        timestamp = datetime.now().isoformat()
        
        result.update({
            "match_id": match_id,
            "tournament_id": tournament_id,
            "player_ids": player_ids,
            "timestamp": timestamp
        })
        
        self.logger.info(f"Match {match_id} completed with result: {result.get('winner', 'No winner')}")
        return result
    
    def _resolve_players(self, player_ids):
        """
        Resolve player IDs to player objects.
        
        This creates actual player instances for use in games.
        
        Args:
            player_ids (list): List of player IDs
            
        Returns:
            list: List of player objects
        """
        players = []
        
        # Try to use the user_handler if available in the engine
        if hasattr(self, 'user_handler') and self.user_handler:
            return self.user_handler.get_player_instances(player_ids)
            
        # Fallback to creating simple player instances
        for player_id in player_ids:
            # Check if it's a CPU player
            if player_id.startswith("CPU-"):
                try:
                    # Import only when needed to avoid circular imports
                    from ..simple_cpu import SimpleCPU
                    player = SimpleCPU(player_id)
                except ImportError:
                    # If import fails, create a basic player
                    player = type('Player', (), {
                        'id': player_id, 
                        'name': player_id,
                        'get_move': lambda game_state: None  # Default move method
                    })
            else:
                # Create a simple player object
                player = type('Player', (), {
                    'id': player_id, 
                    'name': player_id
                })
                
            players.append(player)
            
        return players
    
    def validate_match_result(self, match_data, result):
        """
        Validate that a match result is consistent and valid.
        
        Args:
            match_data (dict): Data about the match
            result (dict): The result to validate
            
        Returns:
            bool: True if the result is valid, False otherwise
        """
        # Check that player IDs match
        match_player_ids = set(match_data.get("player_ids", []))
        result_player_ids = set(result.get("player_ids", []))
        
        if match_player_ids and result_player_ids and match_player_ids != result_player_ids:
            self.logger.error(f"Player IDs in result don't match match data: {match_player_ids} vs {result_player_ids}")
            return False
            
        # Check that winner is one of the players (or None for a draw)
        winner = result.get("winner")
        if winner is not None and winner not in result_player_ids:
            self.logger.error(f"Winner {winner} is not one of the players: {result_player_ids}")
            return False
            
        # Check that scores are provided for all players
        scores = result.get("scores", {})
        if not all(player_id in scores for player_id in result_player_ids):
            self.logger.error(f"Scores not provided for all players: {scores} vs {result_player_ids}")
            return False
            
        return True