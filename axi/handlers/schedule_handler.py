#!/usr/bin/env python3
"""
Schedule handler for Axi game engine.
Handles creating and managing tournament schedules.
"""

import logging
import random
import math
import uuid
from datetime import datetime, timedelta

class ScheduleHandler:
    """
    Handles creating and managing tournament schedules for the Axi game engine.
    """
    
    def __init__(self, config):
        """
        Initialize the schedule handler.
        
        Args:
            config (dict): Configuration for the scheduler
        """
        self.config = config
        self.logger = logging.getLogger("axi.schedule")
        
    def create_schedule(self, players, config=None):
        """
        Create a tournament schedule for the given players.
        
        Args:
            players (list): List of players or player IDs
            config (dict, optional): Configuration overrides
            
        Returns:
            list: List of scheduled matches
        """
        if config is None:
            config = self.config
            
        # If players is a dict (like from a user handler), extract the values
        if isinstance(players, dict):
            players = list(players.values())
            
        # Extract player IDs if player objects were provided
        player_ids = []
        for player in players:
            if isinstance(player, str):
                player_ids.append(player)
            elif hasattr(player, 'id'):
                player_ids.append(player.id)
            else:
                self.logger.warning(f"Unrecognized player object format: {player}")
                
        if not player_ids:
            self.logger.error("No valid players provided")
            raise ValueError("No valid players provided")
            
        self.logger.info(f"Creating schedule for {len(player_ids)} players")
        
        # Determine which type of schedule to create
        schedule_type = config.get("type", "round_robin")
        
        if schedule_type == "round_robin":
            return self._create_round_robin(player_ids, config)
        elif schedule_type == "swiss":
            return self._create_swiss(player_ids, config)
        elif schedule_type == "single_elimination":
            return self._create_single_elimination(player_ids, config)
        elif schedule_type == "double_elimination":
            return self._create_double_elimination(player_ids, config)
        else:
            self.logger.error(f"Unknown schedule type: {schedule_type}")
            raise ValueError(f"Unknown schedule type: {schedule_type}")
    
    def _create_round_robin(self, player_ids, config):
        """
        Create a round-robin schedule where each player plays against every other player.
        
        Args:
            player_ids (list): List of player IDs
            config (dict): Configuration for the schedule
            
        Returns:
            list: List of scheduled matches
        """
        rounds = config.get("rounds", 1)
        schedule = []
        
        for round_num in range(rounds):
            self.logger.info(f"Creating round {round_num + 1} of round-robin schedule")
            
            # For each round, each player plays against every other player
            for i in range(len(player_ids)):
                for j in range(i + 1, len(player_ids)):
                    match = {
                        "id": str(uuid.uuid4()),
                        "player_ids": [player_ids[i], player_ids[j]],
                        "round": round_num,
                        "tournament_id": config.get("tournament_id", ""),
                        "scheduled_time": None  # To be filled in later if needed
                    }
                    schedule.append(match)
        
        # Randomize match order within rounds if specified
        if config.get("randomize", False):
            random.shuffle(schedule)
            
        # Set scheduled times if a start time is provided
        start_time = config.get("start_time")
        if start_time:
            self._assign_match_times(schedule, start_time, config)
            
        self.logger.info(f"Created round-robin schedule with {len(schedule)} matches")
        return schedule
    
    def _create_swiss(self, player_ids, config):
        """
        Create a Swiss-system tournament schedule.
        
        Args:
            player_ids (list): List of player IDs
            config (dict): Configuration for the schedule
            
        Returns:
            list: List of scheduled matches for the first round only
            
        Note: Swiss system requires updating the schedule after each round
        based on results, so only the first round is created initially.
        """
        rounds = config.get("rounds", math.ceil(math.log2(len(player_ids))))
        schedule = []
        
        # For the first round, randomly pair players
        random.shuffle(player_ids)
        
        # If odd number of players, one gets a bye
        has_bye = len(player_ids) % 2 == 1
        
        for i in range(0, len(player_ids) - (1 if has_bye else 0), 2):
            match = {
                "id": str(uuid.uuid4()),
                "player_ids": [player_ids[i], player_ids[i + 1]],
                "round": 0,
                "tournament_id": config.get("tournament_id", ""),
                "scheduled_time": None  # To be filled in later if needed
            }
            schedule.append(match)
            
        # If odd number of players, last player gets a bye
        if has_bye:
            match = {
                "id": str(uuid.uuid4()),
                "player_ids": [player_ids[-1], "BYE"],
                "round": 0,
                "tournament_id": config.get("tournament_id", ""),
                "scheduled_time": None,
                "is_bye": True
            }
            schedule.append(match)
            
        # Set scheduled times if a start time is provided
        start_time = config.get("start_time")
        if start_time:
            self._assign_match_times(schedule, start_time, config)
            
        self.logger.info(f"Created first round of Swiss schedule with {len(schedule)} matches")
        return schedule
    
    def _create_single_elimination(self, player_ids, config):
        """
        Create a single-elimination tournament bracket.
        
        Args:
            player_ids (list): List of player IDs
            config (dict): Configuration for the schedule
            
        Returns:
            list: List of scheduled matches for the first round only
            
        Note: Only the first round is created initially. Subsequent rounds
        depend on the winners of previous rounds.
        """
        # Determine the number of rounds needed
        num_players = len(player_ids)
        rounds_needed = math.ceil(math.log2(num_players))
        bracket_size = 2 ** rounds_needed
        
        # Randomize player order if desired
        if config.get("randomize", True):
            random.shuffle(player_ids)
            
        # Assign seeds if a seeding function is provided
        if "seeding" in config:
            # In a real implementation, this would use the provided seeding function
            # For now, we'll just use the players in the order they're provided
            pass
            
        # Create a list of all matches in the bracket
        schedule = []
        
        # Fill in the first round with actual players, and byes if necessary
        first_round_matches = bracket_size // 2
        for i in range(first_round_matches):
            player1_idx = i
            player2_idx = bracket_size - 1 - i
            
            player1 = player_ids[player1_idx] if player1_idx < num_players else "BYE"
            player2 = player_ids[player2_idx] if player2_idx < num_players else "BYE"
            
            # If both players are BYE, skip this match
            if player1 == "BYE" and player2 == "BYE":
                continue
                
            # If one player is BYE, the other automatically advances
            is_bye = player1 == "BYE" or player2 == "BYE"
            
            match = {
                "id": str(uuid.uuid4()),
                "player_ids": [player1, player2],
                "round": 0,
                "match_number": i,
                "tournament_id": config.get("tournament_id", ""),
                "scheduled_time": None,
                "is_bye": is_bye,
                "next_match": (i // 2) if i % 2 == 0 else ((i - 1) // 2)
            }
            schedule.append(match)
            
        # Set scheduled times if a start time is provided
        start_time = config.get("start_time")
        if start_time:
            self._assign_match_times(schedule, start_time, config)
            
        self.logger.info(f"Created single-elimination bracket with {len(schedule)} first-round matches")
        return schedule
    
    def _create_double_elimination(self, player_ids, config):
        """
        Create a double-elimination tournament bracket.
        
        Args:
            player_ids (list): List of player IDs
            config (dict): Configuration for the schedule
            
        Returns:
            list: List of scheduled matches for the first round only
            
        Note: This is a simplified version that only creates the first round.
        A full implementation would be more complex.
        """
        # Start with a single-elimination bracket for the first round
        winners_bracket = self._create_single_elimination(player_ids, config)
        
        # In a real implementation, we would also create the losers bracket
        # and set up the connections between the brackets
        
        return winners_bracket
    
    def _assign_match_times(self, schedule, start_time, config):
        """
        Assign scheduled times to matches.
        
        Args:
            schedule (list): List of matches
            start_time: Starting time for the first match
            config (dict): Configuration for timing
        """
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time)
            
        match_duration = config.get("match_duration", 30)  # Minutes per match
        matches_per_round = config.get("matches_per_round", 1)  # Concurrent matches
        
        # Group matches by round
        rounds = {}
        for match in schedule:
            round_num = match.get("round", 0)
            if round_num not in rounds:
                rounds[round_num] = []
            rounds[round_num].append(match)
            
        current_time = start_time
        
        for round_num in sorted(rounds.keys()):
            round_matches = rounds[round_num]
            
            # Assign times to matches in this round
            for i, match in enumerate(round_matches):
                # Calculate which time slot this match belongs in
                time_slot = i // matches_per_round
                match_time = current_time + timedelta(minutes=time_slot * match_duration)
                match["scheduled_time"] = match_time.isoformat()
                
            # Move to the next round start time
            round_duration = math.ceil(len(round_matches) / matches_per_round) * match_duration
            current_time += timedelta(minutes=round_duration)
            
    def update_swiss_schedule(self, current_schedule, results, player_standings, config=None):
        """
        Update a Swiss tournament schedule for the next round based on results.
        
        Args:
            current_schedule (list): Current schedule
            results (list): Results from the current round
            player_standings (list): Current player standings
            config (dict, optional): Configuration overrides
            
        Returns:
            list: Updated schedule with next round matches
        """
        if config is None:
            config = self.config
            
        # In a real implementation, this would pair players based on their standings
        # For now, we'll just return an empty list to indicate not implemented
        self.logger.warning("Swiss schedule updating not fully implemented")
        return []
    
    def update_elimination_bracket(self, current_schedule, results, config=None):
        """
        Update an elimination bracket based on match results.
        
        Args:
            current_schedule (list): Current schedule
            results (list): Results from the current round
            config (dict, optional): Configuration overrides
            
        Returns:
            list: Updated schedule with next round matches
        """
        if config is None:
            config = self.config
            
        # In a real implementation, this would create the next round of matches
        # based on the winners (and losers for double-elimination)
        # For now, we'll just return an empty list to indicate not implemented
        self.logger.warning("Elimination bracket updating not fully implemented")
        return []