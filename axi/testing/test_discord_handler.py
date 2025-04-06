#!/usr/bin/env python3
"""
Test Discord handler for Axi game engine.
Provides a testing framework for Discord bot functionality without requiring an actual Discord connection.
"""

import logging
import json
import os
import re
import glob
from datetime import datetime
from pathlib import Path
from ..handlers.discord_handler import DiscordHandler

class TestDiscordHandler:
    """
    Test implementation of Discord handler for unit testing and integration testing.
    Extends the base DiscordHandler but provides additional methods for verification.
    """
    
    def __init__(self, config):
        """
        Initialize the test Discord handler.
        
        Args:
            config (dict): Configuration for Discord integration
        """
        # Ensure the test handler is always enabled
        test_config = dict(config)
        test_config["enabled"] = True
        
        # Use a test-specific directory for logs
        self.test_run_id = datetime.now().strftime("%Y%m%d%H%M%S")
        self.test_mode = test_config.get("test_mode", "default")
        
        # Initialize standard properties
        self.logger = logging.getLogger("axi.discord")
        self.config = test_config
        self.enabled = True  # Always enabled in test mode
        self.token = test_config.get("token", "test_token")
        self.channel_id = test_config.get("channel_id", "test_channel")
        self.event_image = test_config.get("event_image", "")
        self.header_images = test_config.get("header_images", {})
        
        # Create a test-specific directory for logs
        self.discord_log_dir = Path(f"logs/discord_test/{self.test_mode}/{self.test_run_id}")
        self.discord_log_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"Initialized TestDiscordHandler in mode {self.test_mode}")
        
        # Track messages in memory for easy verification
        self.messages = {
            "tournament_announcement": [],
            "match_result": [],
            "final_standings": [],
            "checkins_reminder": [],
            "tournament_start": []
        }
        
        self.logger.info(f"Initialized TestDiscordHandler in mode {self.test_mode}")
    
    def _log_message(self, message_type, content):
        """
        Log a test Discord message to file and memory.
        
        Args:
            message_type (str): Type of message
            content (dict): Message content
        """
        # Log to file
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_file = self.discord_log_dir / f"{message_type}_{timestamp.replace(':', '-')}.json"
        
        with open(log_file, 'w') as f:
            json.dump({
                "timestamp": timestamp,
                "type": message_type,
                "content": content
            }, f, indent=2)
            
        self.logger.info(f"Logged {message_type} message to {log_file}")
        
        # Also store in memory for easy verification
        if message_type in self.messages:
            self.messages[message_type].append({
                "timestamp": datetime.now().isoformat(),
                "content": content
            })
    
    def clear_messages(self, message_type=None):
        """
        Clear stored messages.
        
        Args:
            message_type (str, optional): Type of messages to clear, or None for all
        """
        if message_type is None:
            # Clear all message types
            for msg_type in self.messages:
                self.messages[msg_type] = []
        elif message_type in self.messages:
            # Clear specific message type
            self.messages[message_type] = []
    
    def get_messages(self, message_type):
        """
        Get all messages of a specific type.
        
        Args:
            message_type (str): Type of messages to retrieve
            
        Returns:
            list: Messages of the specified type
        """
        return self.messages.get(message_type, [])
    
    def get_message_count(self, message_type):
        """
        Get the count of messages of a specific type.
        
        Args:
            message_type (str): Type of messages to count
            
        Returns:
            int: Number of messages of the specified type
        """
        return len(self.get_messages(message_type))
    
    def verify_message_count(self, message_type, expected_count):
        """
        Verify that the correct number of messages were sent.
        
        Args:
            message_type (str): Type of messages to verify
            expected_count (int): Expected number of messages
            
        Returns:
            bool: True if the count matches, False otherwise
        """
        actual_count = self.get_message_count(message_type)
        if actual_count == expected_count:
            self.logger.info(f"Verified {actual_count} {message_type} messages")
            return True
        else:
            self.logger.warning(f"Expected {expected_count} {message_type} messages, but found {actual_count}")
            return False
    
    def verify_message_content(self, message_type, index, **expected_fields):
        """
        Verify that a message contains expected fields.
        
        Args:
            message_type (str): Type of message to verify
            index (int): Index of the message to verify (0-based)
            **expected_fields: Key-value pairs of fields to verify
            
        Returns:
            bool: True if all fields match, False otherwise
        """
        messages = self.get_messages(message_type)
        
        if not messages or index >= len(messages):
            self.logger.warning(f"No {message_type} message at index {index}")
            return False
        
        message = messages[index]["content"]
        
        # Check each expected field
        all_match = True
        for field, expected_value in expected_fields.items():
            # Handle nested fields with dot notation (e.g., "embeds.0.title")
            actual_value = self._get_nested_field(message, field)
            
            if isinstance(expected_value, str) and isinstance(actual_value, str):
                # For strings, support regex matching
                if expected_value.startswith("regex:"):
                    pattern = expected_value[6:]  # Remove "regex:" prefix
                    if not re.match(pattern, actual_value):
                        self.logger.warning(f"Field {field} does not match pattern {pattern}: {actual_value}")
                        all_match = False
                elif actual_value != expected_value:
                    self.logger.warning(f"Field {field} does not match: expected '{expected_value}', got '{actual_value}'")
                    all_match = False
            elif actual_value != expected_value:
                self.logger.warning(f"Field {field} does not match: expected {expected_value}, got {actual_value}")
                all_match = False
        
        if all_match:
            self.logger.info(f"Verified {message_type} message at index {index}")
        
        return all_match
    
    def _get_nested_field(self, obj, field_path):
        """
        Get a nested field from an object using dot notation.
        
        Args:
            obj (dict): Object to get field from
            field_path (str): Path to the field using dot notation (e.g., "embeds.0.title")
            
        Returns:
            The field value, or None if not found
        """
        parts = field_path.split(".")
        current = obj
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                current = current[int(part)]
            else:
                return None
        
        return current
    
    def get_all_log_files(self, message_type=None):
        """
        Get all log files for the current test run.
        
        Args:
            message_type (str, optional): Type of messages to retrieve, or None for all
            
        Returns:
            list: Paths to log files
        """
        pattern = f"{message_type}_*.json" if message_type else "*.json"
        return sorted(glob.glob(str(self.discord_log_dir / pattern)))
    
    def load_messages_from_logs(self):
        """
        Load all messages from log files into memory.
        Useful if the test handler was reinitialized.
        """
        self.clear_messages()
        
        for log_file in self.get_all_log_files():
            try:
                with open(log_file, 'r') as f:
                    log_data = json.load(f)
                    message_type = log_data.get("type")
                    if message_type in self.messages:
                        self.messages[message_type].append({
                            "timestamp": log_data.get("timestamp"),
                            "content": log_data.get("content", {})
                        })
            except Exception as e:
                self.logger.error(f"Failed to load log file {log_file}: {e}")
                
        total_messages = sum(len(msgs) for msgs in self.messages.values())
        self.logger.info(f"Loaded {total_messages} messages from logs")
        
    def get_latest_message(self, message_type):
        """
        Get the most recent message of a specific type.
        
        Args:
            message_type (str): Type of message to retrieve
            
        Returns:
            dict: The most recent message, or None if none exist
        """
        messages = self.get_messages(message_type)
        if not messages:
            return None
        return messages[-1]["content"]
        
    # Discord message posting methods
    
    def post_tournament_announcement(self, tournament_data):
        """
        Post a tournament announcement to Discord.
        
        Args:
            tournament_data (dict): Data about the tournament
        """
        self.logger.info("Posting tournament announcement to Discord")
        
        # Create the announcement message
        message = {
            "embeds": [{
                "title": f"Tournament Announcement: {tournament_data.get('name', 'Unnamed Tournament')}",
                "description": tournament_data.get("description", ""),
                "fields": [
                    {
                        "name": "Start Date",
                        "value": tournament_data.get("start_date", "TBD"),
                        "inline": True
                    },
                    {
                        "name": "End Date",
                        "value": tournament_data.get("end_date", "TBD"),
                        "inline": True
                    },
                    {
                        "name": "Format",
                        "value": tournament_data.get("format", "TBD"),
                        "inline": True
                    }
                ],
                "image": {
                    "url": self.event_image if self.event_image else ""
                }
            }]
        }
        
        self._log_message("tournament_announcement", message)
    
    def post_match_result(self, match_data, result):
        """
        Post a match result to Discord.
        
        Args:
            match_data (dict): Data about the match
            result (dict): The result of the match
        """
        self.logger.info("Posting match result to Discord")
        
        # Get player names or IDs
        player_ids = result.get("player_ids", match_data.get("player_ids", []))
        if len(player_ids) < 2:
            self.logger.warning("Not enough players in match result")
            return
            
        player1 = player_ids[0]
        player2 = player_ids[1]
        
        # Get scores
        scores = result.get("scores", {})
        score1 = scores.get(player1, 0)
        score2 = scores.get(player2, 0)
        
        # Get winner
        winner = result.get("winner")
        winner_text = "Draw"
        if winner == player1:
            winner_text = f"{player1} wins!"
        elif winner == player2:
            winner_text = f"{player2} wins!"
        
        # Create the result message
        message = {
            "embeds": [{
                "title": f"Match Result: {player1} vs {player2}",
                "description": winner_text,
                "fields": [
                    {
                        "name": "Score",
                        "value": f"{player1}: {score1} - {player2}: {score2}",
                        "inline": False
                    }
                ]
            }]
        }
        
        # Add match history if available
        if "history" in result:
            rounds = []
            for i, round_moves in enumerate(result["history"]):
                if len(round_moves) >= 2:
                    rounds.append(f"Round {i+1}: {player1} played {round_moves[0]}, {player2} played {round_moves[1]}")
            
            if rounds:
                message["embeds"][0]["fields"].append({
                    "name": "Match History",
                    "value": "\n".join(rounds),
                    "inline": False
                })
        
        self._log_message("match_result", message)
    
    def post_final_standings(self, standings):
        """
        Post final tournament standings to Discord.
        
        Args:
            standings (list): List of player standings
        """
        self.logger.info("Posting final standings to Discord")
        
        # Create the standings message
        message = {
            "embeds": [{
                "title": "Final Tournament Standings",
                "description": "The tournament has concluded. Here are the final standings:",
                "fields": []
            }]
        }
        
        # Add header image if available
        header_image = self.header_images.get("final_placements", "")
        if header_image:
            message["embeds"][0]["image"] = {
                "url": header_image
            }
        
        # Add standings
        standings_text = ""
        for standing in standings[:10]:  # Show top 10
            rank = standing.get("rank", 0)
            player_id = standing.get("player_id", "Unknown")
            display = standing.get("display", "")
            
            standings_text += f"{rank}. {player_id} - {display}\n"
        
        message["embeds"][0]["fields"].append({
            "name": "Top Players",
            "value": standings_text or "No standings available",
            "inline": False
        })
        
        self._log_message("final_standings", message)
    
    def post_checkins_reminder(self):
        """Post a reminder for players to check in for the tournament."""
        self.logger.info("Posting checkins reminder to Discord")
        
        # Create the reminder message
        message = {
            "embeds": [{
                "title": "Tournament Check-ins Open",
                "description": "Check-ins for the tournament are now open. Please react to this message to check in."
            }]
        }
        
        # Add header image if available
        header_image = self.header_images.get("checkins", "")
        if header_image:
            message["embeds"][0]["image"] = {
                "url": header_image
            }
        
        self._log_message("checkins_reminder", message)
    
    def post_tournament_start(self):
        """Post a message announcing the start of the tournament."""
        self.logger.info("Posting tournament start announcement to Discord")
        
        # Create the start message
        message = {
            "embeds": [{
                "title": "Tournament Starting",
                "description": "The tournament is now beginning. Good luck to all participants!"
            }]
        }
        
        # Add header image if available
        header_image = self.header_images.get("begin", "")
        if header_image:
            message["embeds"][0]["image"] = {
                "url": header_image
            }
        
        self._log_message("tournament_start", message)