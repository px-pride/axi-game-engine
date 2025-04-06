#!/usr/bin/env python3
"""
Glicko-2 timeless rating system for Axi game engine.
A variation of the Glicko-2 rating system that doesn't decay ratings over time.
"""

import math
import logging

class GlickoTimeless:
    """
    A variation of the Glicko-2 rating system that doesn't decay ratings over time.
    """
    
    def __init__(self, config=None):
        """
        Initialize the Glicko Timeless rating system.
        
        Args:
            config (dict, optional): Configuration parameters
        """
        self.config = config or {}
        self.logger = logging.getLogger("axi.ratings.glicko")
        
        # Default Glicko-2 parameters
        self.initial_rating = self.config.get("initial_rating", 1500)
        self.initial_rd = self.config.get("initial_rd", 350)
        self.initial_volatility = self.config.get("initial_volatility", 0.06)
        self.tau = self.config.get("tau", 0.5)  # System volatility constraint
        
        # Derived constants
        self.q = math.log(10) / 400  # Conversion factor
        
    def get_initial_rating(self):
        """
        Get the initial rating for a new player.
        
        Returns:
            dict: Initial rating data
        """
        return {
            "rating": self.initial_rating,
            "rd": self.initial_rd,
            "volatility": self.initial_volatility
        }
        
    def get_sort_key(self, rating_data):
        """
        Get a value to sort ratings by (higher is better).
        
        Args:
            rating_data (dict): Rating data
            
        Returns:
            float: Sort key
        """
        # In Glicko, higher rating is better
        return rating_data["rating"]
        
    def get_display_rating(self, rating_data):
        """
        Get a human-readable rating.
        
        Args:
            rating_data (dict): Rating data
            
        Returns:
            str: Display rating
        """
        rating = rating_data["rating"]
        rd = rating_data["rd"]
        
        # Round to nearest integer and show confidence interval
        return f"{int(round(rating))} ± {int(round(rd))}"
        
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
            self.logger.warning("Glicko-2 is designed for 2-player games, using simplified approach for multi-player")
            
        # For simplicity, we'll only implement the 2-player case here
        if len(player_ids) == 2:
            player1, player2 = player_ids
            
            # Get current ratings
            r1 = ratings.get(player1, self.get_initial_rating())
            r2 = ratings.get(player2, self.get_initial_rating())
            
            # Determine outcome
            if winner is None:
                s1 = 0.5  # Draw
                s2 = 0.5
            elif winner == player1:
                s1 = 1.0  # Player 1 wins
                s2 = 0.0
            else:
                s1 = 0.0  # Player 2 wins
                s2 = 1.0
                
            # Update ratings
            new_r1 = self._update_player_rating(r1, [(r2, s1)])
            new_r2 = self._update_player_rating(r2, [(r1, s2)])
            
            return {
                player1: new_r1,
                player2: new_r2
            }
        else:
            # Handle multi-player case (simplified)
            new_ratings = {}
            
            # For each player, consider their performance against every other player
            for i, player_id in enumerate(player_ids):
                player_rating = ratings.get(player_id, self.get_initial_rating())
                opponent_results = []
                
                for j, opponent_id in enumerate(player_ids):
                    if i == j:
                        continue
                        
                    opponent_rating = ratings.get(opponent_id, self.get_initial_rating())
                    
                    # Determine outcome against this opponent
                    if winner is None:
                        s = 0.5  # Draw
                    elif winner == player_id:
                        s = 1.0  # Win
                    else:
                        s = 0.0  # Loss
                        
                    opponent_results.append((opponent_rating, s))
                    
                # Update rating based on all opponent results
                new_ratings[player_id] = self._update_player_rating(player_rating, opponent_results)
                
            return new_ratings
    
    def _update_player_rating(self, rating_data, opponent_results):
        """
        Update a player's rating based on results against opponents.
        
        Args:
            rating_data (dict): Current rating data
            opponent_results (list): List of (opponent_rating, score) tuples
            
        Returns:
            dict: Updated rating data
        """
        # Extract current rating data
        rating = rating_data["rating"]
        rd = rating_data["rd"]
        volatility = rating_data["volatility"]
        
        # Step 1: Convert to Glicko-2 scale
        mu = (rating - 1500) / 173.7178
        phi = rd / 173.7178
        
        # Step 2: Compute the quantity v
        v_sum = 0
        for opponent_data, _ in opponent_results:
            opp_rating = opponent_data["rating"]
            opp_rd = opponent_data["rd"]
            
            # Convert opponent rating to Glicko-2 scale
            opp_mu = (opp_rating - 1500) / 173.7178
            opp_phi = opp_rd / 173.7178
            
            # Compute g(phi)
            g = 1 / math.sqrt(1 + 3 * opp_phi**2 / math.pi**2)
            
            # Compute E(mu, mu_j, phi_j)
            E = 1 / (1 + math.exp(-g * (mu - opp_mu)))
            
            # Add to v_sum
            v_sum += g**2 * E * (1 - E)
            
        if v_sum == 0:
            # No valid opponents, no change in rating
            return rating_data
            
        v = 1 / v_sum
        
        # Step 3: Compute the quantity delta
        delta_sum = 0
        for opponent_data, score in opponent_results:
            opp_rating = opponent_data["rating"]
            opp_rd = opponent_data["rd"]
            
            # Convert opponent rating to Glicko-2 scale
            opp_mu = (opp_rating - 1500) / 173.7178
            opp_phi = opp_rd / 173.7178
            
            # Compute g(phi)
            g = 1 / math.sqrt(1 + 3 * opp_phi**2 / math.pi**2)
            
            # Compute E(mu, mu_j, phi_j)
            E = 1 / (1 + math.exp(-g * (mu - opp_mu)))
            
            # Add to delta_sum
            delta_sum += g * (score - E)
            
        delta = v * delta_sum
        
        # Step 4: Compute the new volatility
        a = math.log(volatility**2)
        
        def f(x):
            """Function f(x) for the volatility update."""
            ex = math.exp(x)
            term1 = ex * (delta**2 - phi**2 - v - ex) / (2 * (phi**2 + v + ex)**2)
            term2 = (x - a) / self.tau**2
            return term1 - term2
            
        # Find the value of x that minimizes f(x)
        # This is a simplified approach using a fixed-point iteration
        # with an initial estimate based on a Taylor series expansion
        A = a
        B = 0
        if delta**2 > phi**2 + v:
            B = math.log(delta**2 - phi**2 - v)
        else:
            k = 1
            while f(a - k * self.tau) < 0:
                k += 1
            B = a - k * self.tau
            
        # Iterate to find x
        fa = f(A)
        fb = f(B)
        
        while abs(B - A) > 1e-6:
            C = A + (A - B) * fa / (fb - fa)
            fc = f(C)
            
            if fc * fb < 0:
                A = B
                fa = fb
            else:
                fa = fa / 2
                
            B = C
            fb = fc
            
        # The new volatility is exp(A/2)
        new_volatility = math.exp(A / 2)
        
        # Step 5: Compute the new RD
        phi_star = math.sqrt(phi**2 + new_volatility**2)
        
        # Step 6: Compute the new rating and RD
        new_phi = 1 / math.sqrt(1/phi_star**2 + 1/v)
        new_mu = mu + new_phi**2 * delta_sum
        
        # Step 7: Convert back to original scale
        new_rating = 173.7178 * new_mu + 1500
        new_rd = 173.7178 * new_phi
        
        # Make sure RD stays in reasonable bounds
        new_rd = max(min(new_rd, self.initial_rd), 30)
        
        return {
            "rating": new_rating,
            "rd": new_rd,
            "volatility": new_volatility
        }