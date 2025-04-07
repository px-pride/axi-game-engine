#!/usr/bin/env python3
"""
Danisen (Dan/Kyu) rating system for Axi game engine.
A traditional ranking system used in Go, martial arts, and other activities.
"""

import logging
import math

class Danisen:
    """
    A traditional dan/kyu ranking system.
    
    Ranks players in a ladder of discrete levels:
    - Kyu ranks (higher number = lower rank): 30k, 29k, ..., 1k
    - Dan ranks (higher number = higher rank): 1d, 2d, ..., 9d
    
    Points are accumulated within each rank level, and upon reaching
    threshold points, players advance to the next rank.
    """
    
    def __init__(self, config=None):
        """
        Initialize the Danisen rating system.
        
        Args:
            config (dict, optional): Configuration parameters
        """
        self.config = config or {}
        self.logger = logging.getLogger("axi.ratings.danisen")
        
        # Default configuration
        self.initial_rank = self.config.get("initial_rank", "30k")
        self.promotion_points = self.config.get("promotion_points", 100)
        self.demotion_points = self.config.get("demotion_points", -50)
        self.win_points = self.config.get("win_points", 10)
        self.loss_points = self.config.get("loss_points", -5)
        self.draw_points = self.config.get("draw_points", 3)
        
        # Define the rank order for sorting
        self.rank_order = {}
        for i in range(30, 0, -1):
            self.rank_order[f"{i}k"] = i
        for i in range(1, 10):
            self.rank_order[f"{i}d"] = i + 30
            
    def get_initial_rating(self):
        """
        Get the initial rating for a new player.
        
        Returns:
            dict: Initial rating data
        """
        return {
            "rank": self.initial_rank,
            "points": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0
        }
        
    def get_sort_key(self, rating_data):
        """
        Get a value to sort ratings by (higher is better).
        
        Args:
            rating_data (dict): Rating data
            
        Returns:
            int: Sort key value
        """
        rank = rating_data.get("rank", self.initial_rank)
        points = rating_data.get("points", 0)
        
        # Get base value from rank
        base = self.rank_order.get(rank, 0)
        
        # Add fractional value based on points within rank
        fractional = points / self.promotion_points
        
        return base + fractional
        
    def get_display_rating(self, rating_data):
        """
        Get a human-readable rating.
        
        Args:
            rating_data (dict): Rating data
            
        Returns:
            str: Display rating
        """
        rank = rating_data.get("rank", self.initial_rank)
        points = rating_data.get("points", 0)
        wins = rating_data.get("wins", 0)
        losses = rating_data.get("losses", 0)
        draws = rating_data.get("draws", 0)
        
        # Format as rank with points
        return f"{rank} ({points}/{self.promotion_points} pts, {wins}-{losses}-{draws})"
        
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
        if len(player_ids) != 2:
            self.logger.warning("Danisen is designed for 2-player games, using simplified approach for multi-player")
            
        # Update ratings for all players
        updated_ratings = {}
        
        # Handle 2-player case
        if len(player_ids) == 2:
            player1, player2 = player_ids
            
            # Get current ratings
            r1 = ratings.get(player1, self.get_initial_rating())
            r2 = ratings.get(player2, self.get_initial_rating())
            
            # Determine outcome
            if winner is None:
                # Draw
                updated_ratings[player1] = self._update_player_rating(r1, "draw")
                updated_ratings[player2] = self._update_player_rating(r2, "draw")
            elif winner == player1:
                # Player 1 wins
                updated_ratings[player1] = self._update_player_rating(r1, "win")
                updated_ratings[player2] = self._update_player_rating(r2, "loss")
            else:
                # Player 2 wins
                updated_ratings[player1] = self._update_player_rating(r1, "loss")
                updated_ratings[player2] = self._update_player_rating(r2, "win")
        else:
            # Handle multi-player case
            for player_id in player_ids:
                r = ratings.get(player_id, self.get_initial_rating())
                
                if winner is None:
                    # Draw for all players
                    updated_ratings[player_id] = self._update_player_rating(r, "draw")
                elif winner == player_id:
                    # This player won
                    updated_ratings[player_id] = self._update_player_rating(r, "win")
                else:
                    # This player lost
                    updated_ratings[player_id] = self._update_player_rating(r, "loss")
                    
        return updated_ratings
    
    def _update_player_rating(self, rating_data, outcome):
        """
        Update a player's rating based on a match outcome.
        
        Args:
            rating_data (dict): Current rating data
            outcome (str): 'win', 'loss', or 'draw'
            
        Returns:
            dict: Updated rating data
        """
        # Make a copy of the rating data to avoid modifying the original
        updated = dict(rating_data)
        
        # Update stats
        if outcome == "win":
            updated["wins"] = updated.get("wins", 0) + 1
            point_change = self.win_points
        elif outcome == "loss":
            updated["losses"] = updated.get("losses", 0) + 1
            point_change = self.loss_points
        else:  # draw
            updated["draws"] = updated.get("draws", 0) + 1
            point_change = self.draw_points
            
        # Update points
        updated["points"] = updated.get("points", 0) + point_change
        
        # Check for promotion/demotion
        current_rank = updated.get("rank", self.initial_rank)
        if updated["points"] >= self.promotion_points:
            # Promote to next rank
            updated["rank"] = self._get_next_rank(current_rank)
            updated["points"] = 0
            self.logger.info(f"Player promoted to {updated['rank']}")
        elif updated["points"] <= self.demotion_points:
            # Demote to previous rank
            updated["rank"] = self._get_previous_rank(current_rank)
            updated["points"] = self.promotion_points + updated["points"]  # Keep negative overflow
            self.logger.info(f"Player demoted to {updated['rank']}")
            
        return updated
    
    def _get_next_rank(self, rank):
        """
        Get the next higher rank.
        
        Args:
            rank (str): Current rank
            
        Returns:
            str: Next higher rank
        """
        # Extract number and type
        if rank.endswith('k'):  # Kyu rank
            number = int(rank[:-1])
            if number > 1:
                return f"{number-1}k"  # Next kyu rank (e.g., 5k -> 4k)
            else:
                return "1d"  # 1k -> 1d
        elif rank.endswith('d'):  # Dan rank
            number = int(rank[:-1])
            if number < 9:
                return f"{number+1}d"  # Next dan rank (e.g., 3d -> 4d)
            else:
                return "9d"  # Already at highest rank
        else:
            return self.initial_rank  # Invalid rank, return initial
    
    def _get_previous_rank(self, rank):
        """
        Get the next lower rank.
        
        Args:
            rank (str): Current rank
            
        Returns:
            str: Next lower rank
        """
        # Extract number and type
        if rank.endswith('k'):  # Kyu rank
            number = int(rank[:-1])
            if number < 30:
                return f"{number+1}k"  # Previous kyu rank (e.g., 5k -> 6k)
            else:
                return "30k"  # Already at lowest rank
        elif rank.endswith('d'):  # Dan rank
            number = int(rank[:-1])
            if number > 1:
                return f"{number-1}d"  # Previous dan rank (e.g., 3d -> 2d)
            else:
                return "1k"  # 1d -> 1k
        else:
            return self.initial_rank  # Invalid rank, return initial