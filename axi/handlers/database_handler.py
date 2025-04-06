#!/usr/bin/env python3
"""
Database handler for Axi game engine.
Manages persistent storage of game data, user profiles, and tournament results.
"""

import json
import os
import logging
import sqlite3
from pathlib import Path

class DatabaseHandler:
    """
    Handles persistent storage for the Axi game engine.
    Supports JSON and SQLite storage backends.
    """
    
    def __init__(self, config):
        """
        Initialize the database handler.
        
        Args:
            config (dict): Configuration for the database
        """
        self.config = config
        self.logger = logging.getLogger("axi.database")
        self.db_type = self.config.get("type", "json")
        self.connection = None
        
        # Ensure data directory exists
        data_path = self.config.get("path", "data/axi_data.json")
        Path(os.path.dirname(data_path)).mkdir(parents=True, exist_ok=True)
        
        self._initialize_storage()
        
    def _initialize_storage(self):
        """Initialize the storage backend based on configuration."""
        if self.db_type == "json":
            self._initialize_json_storage()
        elif self.db_type == "sqlite":
            self._initialize_sqlite_storage()
        else:
            self.logger.error(f"Unsupported database type: {self.db_type}")
            raise ValueError(f"Unsupported database type: {self.db_type}")
    
    def _initialize_json_storage(self):
        """Initialize JSON file storage."""
        self.data_file = self.config.get("path", "data/axi_data.json")
        
        # Create empty data structure if file doesn't exist
        if not os.path.exists(self.data_file):
            self.data = {
                "users": {},
                "matches": [],
                "tournaments": {},
                "ladders": {}
            }
            self._save_json_data()
            self.logger.info(f"Created new JSON database at {self.data_file}")
        else:
            self._load_json_data()
            self.logger.info(f"Loaded existing JSON database from {self.data_file}")
    
    def _initialize_sqlite_storage(self):
        """Initialize SQLite database storage."""
        db_file = self.config.get("path", "data/axi_data.db")
        self.connection = sqlite3.connect(db_file)
        
        # Create tables if they don't exist
        cursor = self.connection.cursor()
        
        # Users table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT,
            data TEXT
        )
        ''')
        
        # Matches table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            id TEXT PRIMARY KEY,
            tournament_id TEXT,
            player1_id TEXT,
            player2_id TEXT,
            winner_id TEXT,
            scores TEXT,
            timestamp TEXT,
            data TEXT
        )
        ''')
        
        # Tournaments table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tournaments (
            id TEXT PRIMARY KEY,
            name TEXT,
            start_date TEXT,
            end_date TEXT,
            data TEXT
        )
        ''')
        
        # Ladders table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS ladders (
            id TEXT PRIMARY KEY,
            name TEXT,
            ratings TEXT,
            data TEXT
        )
        ''')
        
        self.connection.commit()
        self.logger.info(f"Initialized SQLite database at {db_file}")
    
    def _load_json_data(self):
        """Load data from JSON file."""
        try:
            with open(self.data_file, 'r') as f:
                self.data = json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load JSON data: {e}")
            self.data = {
                "users": {},
                "matches": [],
                "tournaments": {},
                "ladders": {}
            }
    
    def _save_json_data(self):
        """Save data to JSON file."""
        try:
            with open(self.data_file, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save JSON data: {e}")
    
    def save_user(self, user_id, user_data):
        """
        Save user data to the database.
        
        Args:
            user_id: The ID of the user
            user_data (dict): User data to save
        """
        if self.db_type == "json":
            self.data["users"][user_id] = user_data
            self._save_json_data()
            self.logger.debug(f"Saved user {user_id} to JSON database")
        elif self.db_type == "sqlite":
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO users (id, name, data) VALUES (?, ?, ?)",
                (user_id, user_data.get("name", ""), json.dumps(user_data))
            )
            self.connection.commit()
            self.logger.debug(f"Saved user {user_id} to SQLite database")
    
    def get_user(self, user_id):
        """
        Get user data from the database.
        
        Args:
            user_id: The ID of the user
            
        Returns:
            dict: User data, or None if not found
        """
        if self.db_type == "json":
            return self.data["users"].get(user_id)
        elif self.db_type == "sqlite":
            cursor = self.connection.cursor()
            cursor.execute("SELECT data FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            if result:
                return json.loads(result[0])
            return None
    
    def get_all_users(self):
        """
        Get all users from the database.
        
        Returns:
            dict: Mapping of user IDs to user data
        """
        if self.db_type == "json":
            return self.data["users"]
        elif self.db_type == "sqlite":
            cursor = self.connection.cursor()
            cursor.execute("SELECT id, data FROM users")
            results = cursor.fetchall()
            return {row[0]: json.loads(row[1]) for row in results}
    
    def save_match(self, match_data):
        """
        Save match data to the database.
        
        Args:
            match_data (dict): Match data to save
        """
        if self.db_type == "json":
            self.data["matches"].append(match_data)
            self._save_json_data()
            self.logger.debug(f"Saved match to JSON database")
        elif self.db_type == "sqlite":
            cursor = self.connection.cursor()
            match_id = match_data.get("id", "")
            tournament_id = match_data.get("tournament_id", "")
            player1_id = match_data.get("player_ids", [""])[0]
            player2_id = match_data.get("player_ids", ["", ""])[1] if len(match_data.get("player_ids", [])) > 1 else ""
            winner_id = match_data.get("winner", "")
            scores = json.dumps(match_data.get("scores", {}))
            timestamp = match_data.get("timestamp", "")
            
            cursor.execute(
                """
                INSERT OR REPLACE INTO matches 
                (id, tournament_id, player1_id, player2_id, winner_id, scores, timestamp, data) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (match_id, tournament_id, player1_id, player2_id, winner_id, scores, timestamp, json.dumps(match_data))
            )
            self.connection.commit()
            self.logger.debug(f"Saved match to SQLite database")
    
    def get_matches(self, tournament_id=None, player_id=None):
        """
        Get matches from the database, optionally filtered by tournament or player.
        
        Args:
            tournament_id (optional): Filter by tournament ID
            player_id (optional): Filter by player ID
            
        Returns:
            list: Matching match data
        """
        if self.db_type == "json":
            matches = self.data["matches"]
            
            if tournament_id:
                matches = [m for m in matches if m.get("tournament_id") == tournament_id]
            
            if player_id:
                matches = [m for m in matches if player_id in m.get("player_ids", [])]
                
            return matches
        elif self.db_type == "sqlite":
            cursor = self.connection.cursor()
            query = "SELECT data FROM matches"
            params = []
            
            if tournament_id or player_id:
                query += " WHERE"
                
                if tournament_id:
                    query += " tournament_id = ?"
                    params.append(tournament_id)
                    
                if player_id:
                    if tournament_id:
                        query += " AND"
                    query += " (player1_id = ? OR player2_id = ?)"
                    params.extend([player_id, player_id])
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            return [json.loads(row[0]) for row in results]
    
    def save_ladder(self, ladder_id, ladder_data):
        """
        Save ladder data to the database.
        
        Args:
            ladder_id: The ID of the ladder
            ladder_data (dict): Ladder data to save
        """
        if self.db_type == "json":
            self.data["ladders"][ladder_id] = ladder_data
            self._save_json_data()
            self.logger.debug(f"Saved ladder {ladder_id} to JSON database")
        elif self.db_type == "sqlite":
            cursor = self.connection.cursor()
            name = ladder_data.get("name", "")
            ratings = json.dumps(ladder_data.get("ratings", {}))
            
            cursor.execute(
                "INSERT OR REPLACE INTO ladders (id, name, ratings, data) VALUES (?, ?, ?, ?)",
                (ladder_id, name, ratings, json.dumps(ladder_data))
            )
            self.connection.commit()
            self.logger.debug(f"Saved ladder {ladder_id} to SQLite database")
    
    def get_ladder(self, ladder_id):
        """
        Get ladder data from the database.
        
        Args:
            ladder_id: The ID of the ladder
            
        Returns:
            dict: Ladder data, or None if not found
        """
        if self.db_type == "json":
            return self.data["ladders"].get(ladder_id)
        elif self.db_type == "sqlite":
            cursor = self.connection.cursor()
            cursor.execute("SELECT data FROM ladders WHERE id = ?", (ladder_id,))
            result = cursor.fetchone()
            if result:
                return json.loads(result[0])
            return None
    
    def save_tournament(self, tournament_id, tournament_data):
        """
        Save tournament data to the database.
        
        Args:
            tournament_id: The ID of the tournament
            tournament_data (dict): Tournament data to save
        """
        if self.db_type == "json":
            self.data["tournaments"][tournament_id] = tournament_data
            self._save_json_data()
            self.logger.debug(f"Saved tournament {tournament_id} to JSON database")
        elif self.db_type == "sqlite":
            cursor = self.connection.cursor()
            name = tournament_data.get("name", "")
            start_date = tournament_data.get("start_date", "")
            end_date = tournament_data.get("end_date", "")
            
            cursor.execute(
                """
                INSERT OR REPLACE INTO tournaments 
                (id, name, start_date, end_date, data) 
                VALUES (?, ?, ?, ?, ?)
                """,
                (tournament_id, name, start_date, end_date, json.dumps(tournament_data))
            )
            self.connection.commit()
            self.logger.debug(f"Saved tournament {tournament_id} to SQLite database")
    
    def get_tournament(self, tournament_id):
        """
        Get tournament data from the database.
        
        Args:
            tournament_id: The ID of the tournament
            
        Returns:
            dict: Tournament data, or None if not found
        """
        if self.db_type == "json":
            return self.data["tournaments"].get(tournament_id)
        elif self.db_type == "sqlite":
            cursor = self.connection.cursor()
            cursor.execute("SELECT data FROM tournaments WHERE id = ?", (tournament_id,))
            result = cursor.fetchone()
            if result:
                return json.loads(result[0])
            return None
    
    def get_all_tournaments(self):
        """
        Get all tournaments from the database.
        
        Returns:
            dict: Mapping of tournament IDs to tournament data
        """
        if self.db_type == "json":
            return self.data["tournaments"]
        elif self.db_type == "sqlite":
            cursor = self.connection.cursor()
            cursor.execute("SELECT id, data FROM tournaments")
            results = cursor.fetchall()
            return {row[0]: json.loads(row[1]) for row in results}
            
    def close(self):
        """Close database connections if applicable."""
        if self.db_type == "sqlite" and self.connection:
            self.connection.close()
            self.logger.info("Closed SQLite database connection")
    
    def __del__(self):
        """Ensure database connections are closed on deletion."""
        self.close()