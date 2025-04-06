#!/usr/bin/env python3
"""
User handler for Axi game engine.
Manages user accounts, profiles, and CPU players.
"""

import logging
import uuid
import random
import string

class UserHandler:
    """
    Handles user management for the Axi game engine.
    Manages user registrations, profiles, and CPU players.
    """
    
    def __init__(self, db_handler, config):
        """
        Initialize the user handler.
        
        Args:
            db_handler: Database handler for persistent storage
            config (dict): Configuration for the user handler
        """
        self.db_handler = db_handler
        self.config = config
        self.logger = logging.getLogger("axi.user")
        
        self.users = {}
        self._load_users()
        self._create_cpu_players()
        
    def _load_users(self):
        """Load users from the database."""
        try:
            loaded_users = self.db_handler.get_all_users()
            if loaded_users:
                self.users = loaded_users
                self.logger.info(f"Loaded {len(self.users)} users from database")
            else:
                self.logger.info("No users found in database")
        except Exception as e:
            self.logger.error(f"Failed to load users from database: {e}")
            
    def _create_cpu_players(self):
        """Create CPU players based on configuration."""
        cpu_count = self.config.get("cpu_players", 0)
        if cpu_count <= 0:
            return
            
        cpu_player_class = self.config.get("cpu_player_class", "axi.simple_cpu.SimpleCPU")
        cpu_config = self.config.get("cpu_config", {})
        
        for i in range(cpu_count):
            # Create a unique ID for this CPU player
            cpu_id = f"CPU-{i+1}"
            
            # Check if this CPU already exists
            if cpu_id in self.users:
                self.logger.info(f"CPU player {cpu_id} already exists")
                continue
                
            # Create CPU configuration
            cpu_name = cpu_config.get("name_format", "CPU-{id}").format(id=i+1)
            cpu_data = {
                "id": cpu_id,
                "name": cpu_name,
                "type": "cpu",
                "class": cpu_player_class,
                "config": cpu_config.get("player_config", {})
            }
            
            # Add personality if enabled
            if cpu_config.get("personalities", False):
                cpu_data["personality"] = self._generate_cpu_personality()
                
            # Store the CPU player
            self.users[cpu_id] = cpu_data
            self.db_handler.save_user(cpu_id, cpu_data)
            
            self.logger.info(f"Created CPU player {cpu_id} ({cpu_name})")
            
    def _generate_cpu_personality(self):
        """Generate a random personality for a CPU player."""
        # This is a simple example - in a real game, you might have more complex personality traits
        personalities = [
            "aggressive", "defensive", "balanced", "random", "strategic",
            "cautious", "reckless", "adaptive", "predictable", "unpredictable"
        ]
        
        # Select a primary personality
        primary = random.choice(personalities)
        
        # Sometimes add a secondary trait
        if random.random() < 0.5:
            secondary = random.choice([p for p in personalities if p != primary])
            return f"{primary}-{secondary}"
        else:
            return primary
            
    def register_user(self, user_data):
        """
        Register a new user.
        
        Args:
            user_data (dict): User data including name, etc.
            
        Returns:
            str: The ID of the newly registered user
        """
        # Generate a unique ID for the user
        user_id = user_data.get("id", f"user-{str(uuid.uuid4())[:8]}")
        
        # Check if user already exists
        if user_id in self.users:
            self.logger.warning(f"User {user_id} already exists")
            return user_id
            
        # Add default fields if not provided
        if "name" not in user_data:
            user_data["name"] = user_id
            
        if "type" not in user_data:
            user_data["type"] = "human"
            
        if "created_at" not in user_data:
            from datetime import datetime
            user_data["created_at"] = datetime.now().isoformat()
            
        # Store the user
        self.users[user_id] = user_data
        self.db_handler.save_user(user_id, user_data)
        
        self.logger.info(f"Registered new user {user_id} ({user_data.get('name')})")
        return user_id
        
    def get_user(self, user_id):
        """
        Get a user by ID.
        
        Args:
            user_id: The ID of the user
            
        Returns:
            dict: User data, or None if not found
        """
        if user_id in self.users:
            return self.users[user_id]
            
        # Try loading from database
        user_data = self.db_handler.get_user(user_id)
        if user_data:
            self.users[user_id] = user_data
            return user_data
            
        self.logger.warning(f"User {user_id} not found")
        return None
        
    def get_users(self, user_type=None):
        """
        Get all users, optionally filtered by type.
        
        Args:
            user_type (optional): Filter by user type ("human" or "cpu")
            
        Returns:
            dict: Mapping of user IDs to user data
        """
        if user_type is None:
            return self.users
            
        return {
            user_id: user_data
            for user_id, user_data in self.users.items()
            if user_data.get("type") == user_type
        }
        
    def update_user(self, user_id, update_data):
        """
        Update a user's data.
        
        Args:
            user_id: The ID of the user to update
            update_data (dict): New data to update
            
        Returns:
            bool: True if successful, False otherwise
        """
        if user_id not in self.users:
            self.logger.warning(f"Cannot update non-existent user {user_id}")
            return False
            
        # Update user data
        user_data = self.users[user_id]
        user_data.update(update_data)
        
        # Store updated data
        self.users[user_id] = user_data
        self.db_handler.save_user(user_id, user_data)
        
        self.logger.info(f"Updated user {user_id}")
        return True
        
    def delete_user(self, user_id):
        """
        Delete a user.
        
        Args:
            user_id: The ID of the user to delete
            
        Returns:
            bool: True if successful, False otherwise
        """
        if user_id not in self.users:
            self.logger.warning(f"Cannot delete non-existent user {user_id}")
            return False
            
        # Check if this is a CPU player
        if self.users[user_id].get("type") == "cpu":
            self.logger.warning(f"Cannot delete CPU player {user_id}")
            return False
            
        # Remove from memory
        del self.users[user_id]
        
        # Remove from database
        # (In a real implementation, you might want to soft-delete instead)
        try:
            # This assumes the database handler has a delete_user method
            # If it doesn't, you'll need to implement a different approach
            if hasattr(self.db_handler, "delete_user"):
                self.db_handler.delete_user(user_id)
            else:
                # Fallback: save an empty or marked-as-deleted record
                self.db_handler.save_user(user_id, {"id": user_id, "deleted": True})
                
            self.logger.info(f"Deleted user {user_id}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to delete user {user_id} from database: {e}")
            return False
    
    def get_or_create_user(self, user_id, default_data=None):
        """
        Get a user by ID, or create if not found.
        
        Args:
            user_id: The ID of the user
            default_data (dict, optional): Default data for a new user
            
        Returns:
            dict: User data
        """
        user = self.get_user(user_id)
        if user:
            return user
            
        # User not found, create a new one
        if default_data is None:
            default_data = {}
            
        default_data["id"] = user_id
        return self.register_user(default_data)
        
    def get_player_instances(self, player_ids):
        """
        Get player instances for the given player IDs.
        
        This creates actual player objects from user data, including CPU players.
        
        Args:
            player_ids (list): List of player IDs
            
        Returns:
            list: List of player instances
        """
        players = []
        
        for player_id in player_ids:
            user_data = self.get_user(player_id)
            
            if not user_data:
                self.logger.warning(f"User {player_id} not found, skipping")
                continue
                
            # Create the appropriate type of player
            if user_data.get("type") == "cpu":
                player = self._create_cpu_instance(user_data)
            else:
                player = self._create_human_instance(user_data)
                
            if player:
                players.append(player)
                
        return players
        
    def _create_cpu_instance(self, user_data):
        """
        Create a CPU player instance from user data.
        
        Args:
            user_data (dict): User data for a CPU player
            
        Returns:
            object: CPU player instance
        """
        cpu_class_path = user_data.get("class", "axi.simple_cpu.SimpleCPU")
        config = user_data.get("config", {})
        
        try:
            # Import the CPU class dynamically
            module_path, class_name = cpu_class_path.rsplit(".", 1)
            module = __import__(module_path, fromlist=[class_name])
            cpu_class = getattr(module, class_name)
            
            # Create an instance
            return cpu_class(user_data["id"], config)
        except Exception as e:
            self.logger.error(f"Failed to create CPU instance for {user_data['id']}: {e}")
            return None
            
    def _create_human_instance(self, user_data):
        """
        Create a human player instance from user data.
        
        Args:
            user_data (dict): User data for a human player
            
        Returns:
            object: Human player instance
        """
        # In a real implementation, this might create a more sophisticated player object
        # For now, we'll just create a simple object with the necessary attributes
        player = type('Player', (), {
            'id': user_data["id"],
            'name': user_data.get("name", user_data["id"]),
            'is_human': True
        })
        
        return player