#!/usr/bin/env python3
"""
Rock-Paper-Scissors game implementation for the Axi engine.
"""

import random
from axi.abstract_game import AbstractGame

class RockPaperScissors(AbstractGame):
    """
    A simple Rock-Paper-Scissors game implementation.
    """
    
    MOVES = ["rock", "paper", "scissors"]
    
    def setup(self):
        """Set up the game with initial state."""
        if len(self.players) != 2:
            raise ValueError("Rock-Paper-Scissors requires exactly 2 players")
            
        self.state = {
            "round": 0,
            "scores": {player.id: 0 for player in self.players},
            "history": [],
            "winner": None
        }
        
        self.max_rounds = self.config.get("max_rounds", 3)
        
    def get_player_move(self, player, game_state):
        """Get a move from the player."""
        if hasattr(player, "get_move"):
            move = player.get_move(game_state)
            if move in self.MOVES:
                return move
        
        # If player doesn't have a get_move method or returned an invalid move, choose randomly
        return random.choice(self.MOVES)
        
    def determine_winner(self, move1, move2):
        """Determine the winner of a round."""
        if move1 == move2:
            return None  # Tie
            
        if (move1 == "rock" and move2 == "scissors") or \
           (move1 == "paper" and move2 == "rock") or \
           (move1 == "scissors" and move2 == "paper"):
            return 0  # First player wins
        else:
            return 1  # Second player wins
            
    def apply_move(self, player, move):
        """Apply a player's move to the game state."""
        player_idx = self.players.index(player)
        
        # Initialize the current round's moves if this is the first player
        if len(self.state["history"]) <= self.state["round"]:
            self.state["history"].append(["", ""])
            
        # Record the player's move
        self.state["history"][self.state["round"]][player_idx] = move
        
        # If both players have moved, determine the winner of this round
        if all(self.state["history"][self.state["round"]]):
            moves = self.state["history"][self.state["round"]]
            round_winner = self.determine_winner(moves[0], moves[1])
            
            if round_winner is not None:  # Not a tie
                self.state["scores"][self.players[round_winner].id] += 1
                
            self.state["round"] += 1
            
    def is_game_over(self):
        """Check if the game is over."""
        # Game is over if we've played the maximum number of rounds
        if self.state["round"] >= self.max_rounds:
            return True
            
        # Game is over if a player has reached majority of possible wins
        needed_to_win = self.max_rounds // 2 + 1
        return any(score >= needed_to_win for score in self.state["scores"].values())
        
    def get_result(self):
        """Get the final result of the game."""
        scores = self.state["scores"]
        player_ids = [player.id for player in self.players]
        
        if scores[player_ids[0]] > scores[player_ids[1]]:
            winner = player_ids[0]
        elif scores[player_ids[1]] > scores[player_ids[0]]:
            winner = player_ids[1]
        else:
            winner = None  # Tie
            
        return {
            "winner": winner,
            "scores": scores,
            "history": self.state["history"],
            "rounds_played": self.state["round"]
        }