#!/usr/bin/env python3
"""
Abstract base class for games in the Axi engine.
"""

from abc import ABC, abstractmethod

class AbstractGame(ABC):
    """
    Abstract base class that all games must implement.
    """
    
    def __init__(self, players, config=None):
        """
        Initialize a new game.
        
        Args:
            players (list): List of player objects
            config (dict, optional): Game-specific configuration
        """
        self.players = players
        self.config = config or {}
        self.result = None
        self.state = None
        self.round = 0
        
    @abstractmethod
    def setup(self):
        """Set up the game with initial state."""
        pass
        
    @abstractmethod
    def get_player_move(self, player, game_state):
        """
        Get a move from the specified player given the current game state.
        
        Args:
            player: The player object
            game_state: The current state of the game
            
        Returns:
            The move chosen by the player
        """
        pass
        
    @abstractmethod
    def apply_move(self, player, move):
        """
        Apply a player's move to the game state.
        
        Args:
            player: The player who made the move
            move: The move to apply
            
        Returns:
            Updated game state
        """
        pass
        
    @abstractmethod
    def is_game_over(self):
        """
        Check if the game is over.
        
        Returns:
            bool: True if the game is over, False otherwise
        """
        pass
        
    @abstractmethod
    def get_result(self):
        """
        Get the final result of the game.
        
        Returns:
            dict: Game result with winners, scores, etc.
        """
        pass
        
    def run(self):
        """
        Run the game from start to finish.
        
        Returns:
            The final game result
        """
        self.setup()
        
        while not self.is_game_over():
            self.round += 1
            
            for player in self.players:
                move = self.get_player_move(player, self.state)
                self.apply_move(player, move)
                
                if self.is_game_over():
                    break
        
        return self.get_result()