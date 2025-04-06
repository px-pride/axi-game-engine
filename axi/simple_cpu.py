#!/usr/bin/env python3
"""
A simple CPU player implementation for the Axi game engine.
"""

import random
import logging

class SimpleCPU:
    """
    A simple CPU player that makes random moves or can be configured
    with specific move probabilities.
    """
    
    def __init__(self, player_id, config=None):
        """
        Initialize a new CPU player.
        
        Args:
            player_id: Unique identifier for the player
            config (dict, optional): Configuration for the CPU's behavior
        """
        self.id = player_id
        self.config = config or {}
        self.name = self.config.get("name", f"CPU-{player_id}")
        self.logger = logging.getLogger(f"axi.cpu.{player_id}")
        
        # Move probabilities can be configured for different game types
        self.move_probabilities = self.config.get("move_probabilities", {})
        
    def get_move(self, game_state):
        """
        Get a move from the CPU player.
        
        Args:
            game_state: The current state of the game
            
        Returns:
            The chosen move
        """
        game_type = self._detect_game_type(game_state)
        available_moves = self._get_available_moves(game_state, game_type)
        
        # Use specific probabilities if configured for this game type
        if game_type in self.move_probabilities:
            move = self._weighted_choice(
                available_moves,
                self.move_probabilities[game_type]
            )
            self.logger.debug(f"CPU {self.id} chose {move} using probabilities")
            return move
            
        # Otherwise, choose randomly
        move = random.choice(available_moves)
        self.logger.debug(f"CPU {self.id} chose random move: {move}")
        return move
        
    def _detect_game_type(self, game_state):
        """
        Attempt to detect the type of game being played.
        
        Args:
            game_state: The current state of the game
            
        Returns:
            str: The detected game type
        """
        # A simple detection mechanism based on game state structure
        if isinstance(game_state, dict):
            if "history" in game_state and any(
                move in ["rock", "paper", "scissors"] 
                for round_moves in game_state.get("history", [])
                for move in round_moves
                if move
            ):
                return "rock_paper_scissors"
                
        # Default game type
        return "unknown"
        
    def _get_available_moves(self, game_state, game_type):
        """
        Get the available moves for the current game state.
        
        Args:
            game_state: The current state of the game
            game_type: The detected game type
            
        Returns:
            list: Available moves
        """
        # Different games have different available moves
        if game_type == "rock_paper_scissors":
            return ["rock", "paper", "scissors"]
            
        # For unknown games, try to infer available moves from the game state
        # or return a default move
        return ["default_move"]
        
    def _weighted_choice(self, moves, probabilities):
        """
        Choose a move based on weighted probabilities.
        
        Args:
            moves (list): Available moves
            probabilities (dict): Mapping of moves to probabilities
            
        Returns:
            The chosen move
        """
        # Filter to only include probabilities for available moves
        valid_probs = {move: probabilities.get(move, 0) for move in moves}
        
        # If no valid probabilities, default to equal probability
        if not any(valid_probs.values()):
            return random.choice(moves)
            
        # Choose based on weighted probabilities
        total = sum(valid_probs.values())
        r = random.random() * total
        
        cumulative = 0
        for move, prob in valid_probs.items():
            cumulative += prob
            if r <= cumulative:
                return move
                
        # Fallback to random choice (should not reach here)
        return random.choice(moves)