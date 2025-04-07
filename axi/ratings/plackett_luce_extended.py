#!/usr/bin/env python3
"""
Plackett-Luce Extended rating system for Axi game engine.
A probabilistic model for ranking based on pairwise comparisons.
"""

import logging
import math
import numpy as np

class PlackettLuceExtended:
    """
    An extended version of the Plackett-Luce model for ranking players.
    
    The Plackett-Luce model is a probability model for rankings, where
    each player has a strength parameter that determines their probability
    of winning against other players. This extended version adds support
    for draws and rating volatility.
    """
    
    def __init__(self, config=None):
        """
        Initialize the Plackett-Luce Extended rating system.
        
        Args:
            config (dict, optional): Configuration parameters
        """
        self.config = config or {}
        self.logger = logging.getLogger("axi.ratings.plackett_luce")
        
        # Default configuration
        self.initial_rating = self.config.get("initial_rating", 1000)
        self.initial_volatility = self.config.get("initial_volatility", 100)
        self.k_factor = self.config.get("k_factor", 20)
        self.draw_weight = self.config.get("draw_weight", 0.5)
        self.drift_factor = self.config.get("drift_factor", 0.05)
        self.volatility_decay = self.config.get("volatility_decay", 0.9)
        
    def get_initial_rating(self):
        """
        Get the initial rating for a new player.
        
        Returns:
            dict: Initial rating data
        """
        return {
            "rating": self.initial_rating,
            "volatility": self.initial_volatility,
            "match_count": 0
        }
        
    def get_sort_key(self, rating_data):
        """
        Get a value to sort ratings by (higher is better).
        
        Args:
            rating_data (dict): Rating data
            
        Returns:
            float: Sort key
        """
        # In Plackett-Luce, higher rating is better
        return rating_data.get("rating", self.initial_rating)
        
    def get_display_rating(self, rating_data):
        """
        Get a human-readable rating.
        
        Args:
            rating_data (dict): Rating data
            
        Returns:
            str: Display rating
        """
        rating = rating_data.get("rating", self.initial_rating)
        volatility = rating_data.get("volatility", self.initial_volatility)
        match_count = rating_data.get("match_count", 0)
        
        # Format as rating ± volatility (matches)
        return f"{int(round(rating))} ± {int(round(volatility))} ({match_count} matches)"
        
    def update_ratings(self, ratings, player_ids, winner, scores):
        """
        Update ratings based on a match result.
        
        Args:
            ratings (dict): Current ratings for all players
            player_ids (list): IDs of players in the match
            winner: ID of the winning player, or None for a draw
            scores (dict): Scores for each player
            
        Returns:
            dict: Updated ratings for players in the match
        """
        # If we don't have at least 2 players, we can't update ratings
        if len(player_ids) < 2:
            self.logger.warning("At least 2 players required to update ratings")
            return ratings
            
        # Get current ratings for all players in the match
        player_ratings = {}
        for player_id in player_ids:
            if player_id in ratings:
                player_ratings[player_id] = ratings[player_id]
            else:
                player_ratings[player_id] = self.get_initial_rating()
                
        # Calculate expected outcomes for all player pairs
        expected_outcomes = {}
        for i, player1 in enumerate(player_ids):
            for player2 in player_ids[i+1:]:
                # Calculate probability of player1 winning against player2
                p1_wins = self._win_probability(player_ratings[player1], player_ratings[player2])
                expected_outcomes[(player1, player2)] = p1_wins
                expected_outcomes[(player2, player1)] = 1 - p1_wins
                
        # Determine actual outcomes
        actual_outcomes = {}
        for i, player1 in enumerate(player_ids):
            for player2 in player_ids[i+1:]:
                if winner is None:
                    # Draw - each player gets draw_weight
                    actual_outcomes[(player1, player2)] = self.draw_weight
                    actual_outcomes[(player2, player1)] = self.draw_weight
                elif winner == player1:
                    # Player 1 wins
                    actual_outcomes[(player1, player2)] = 1
                    actual_outcomes[(player2, player1)] = 0
                elif winner == player2:
                    # Player 2 wins
                    actual_outcomes[(player1, player2)] = 0
                    actual_outcomes[(player2, player1)] = 1
                else:
                    # Neither player won (could happen in multi-player games)
                    actual_outcomes[(player1, player2)] = 0
                    actual_outcomes[(player2, player1)] = 0
                    
        # Update ratings based on differences between expected and actual outcomes
        updated_ratings = {}
        for player_id in player_ids:
            # Get current rating data
            old_rating = player_ratings[player_id]
            
            # Calculate rating change
            rating_change = 0
            for opponent_id in player_ids:
                if opponent_id == player_id:
                    continue
                
                # Get expected and actual outcomes
                pair_key = (player_id, opponent_id)
                expected = expected_outcomes.get(pair_key, 0.5)
                actual = actual_outcomes.get(pair_key, 0.5)
                
                # Calculate change based on difference and K-factor
                k = self._get_k_factor(old_rating)
                rating_change += k * (actual - expected)
                
            # Calculate new rating and volatility
            new_rating = old_rating.get("rating", self.initial_rating) + rating_change
            new_volatility = self._update_volatility(old_rating, abs(rating_change))
            new_match_count = old_rating.get("match_count", 0) + 1
            
            # Update player's rating
            updated_ratings[player_id] = {
                "rating": new_rating,
                "volatility": new_volatility,
                "match_count": new_match_count
            }
            
        return updated_ratings
    
    def _win_probability(self, player1_rating, player2_rating):
        """
        Calculate the probability of player1 winning against player2.
        
        Args:
            player1_rating (dict): Rating data for player 1
            player2_rating (dict): Rating data for player 2
            
        Returns:
            float: Probability of player1 winning
        """
        r1 = player1_rating.get("rating", self.initial_rating)
        r2 = player2_rating.get("rating", self.initial_rating)
        
        # Use a logistic function to calculate win probability
        diff = r1 - r2
        return 1 / (1 + math.exp(-diff / 400))
    
    def _get_k_factor(self, rating_data):
        """
        Get the K-factor for a player based on their rating data.
        
        The K-factor determines how much a player's rating changes after each match.
        It's adjusted based on match count and volatility.
        
        Args:
            rating_data (dict): Rating data
            
        Returns:
            float: K-factor value
        """
        base_k = self.k_factor
        match_count = rating_data.get("match_count", 0)
        volatility = rating_data.get("volatility", self.initial_volatility)
        
        # New players have higher K-factor
        if match_count < 10:
            base_k *= 2
        elif match_count < 20:
            base_k *= 1.5
            
        # Adjust based on volatility
        volatility_factor = volatility / self.initial_volatility
        
        return base_k * volatility_factor
    
    def _update_volatility(self, rating_data, rating_change):
        """
        Update a player's rating volatility based on the rating change.
        
        Args:
            rating_data (dict): Current rating data
            rating_change (float): Absolute value of rating change
            
        Returns:
            float: Updated volatility
        """
        current_volatility = rating_data.get("volatility", self.initial_volatility)
        match_count = rating_data.get("match_count", 0)
        
        # Calculate expected volatility based on rating change
        expected_volatility = rating_change / (self._get_k_factor(rating_data) * 0.5)
        
        # New volatility is a weighted average of current and expected
        # Weight decreases with more matches (converges to expected)
        weight = max(0.1, math.exp(-match_count * self.drift_factor))
        new_volatility = (weight * current_volatility + 
                          (1 - weight) * expected_volatility + 
                          self.volatility_decay * current_volatility) / 2
        
        # Ensure volatility stays within reasonable bounds
        min_volatility = 20
        max_volatility = 200
        
        return max(min_volatility, min(max_volatility, new_volatility))