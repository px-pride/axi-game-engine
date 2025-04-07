# Axi Game Engine: Discord Testing Tutorial

This tutorial explains how to use the built-in Discord testing system in the Axi game engine. This system allows you to develop and test Discord integration features without requiring an actual Discord connection.

## Introduction

The Axi game engine includes functionality to post tournament announcements, match results, and standings to Discord. However, during development and testing, it's often impractical to connect to a real Discord server. The non-Discord testing system provides a way to:

1. Verify that Discord messages are formatted correctly
2. Confirm that messages are sent at the appropriate times
3. Test Discord integration without requiring Discord credentials
4. Capture Discord messages for verification and debugging

## How It Works

The test system consists of a `TestDiscordHandler` class that replaces the regular `DiscordHandler` when in test mode. Instead of sending messages to Discord, it:

1. Logs messages to JSON files in a test-specific directory
2. Stores messages in memory for easy verification
3. Provides methods to verify message content and formatting
4. Simulates all Discord functionality without requiring an actual connection

## Basic Setup

To use the test Discord system, you need to enable it in your configuration file:

```json
{
  "discord": {
    "enabled": true,
    "test_mode": true,
    "token": "test_token",      // Not a real token, just a placeholder
    "channel_id": "test_channel" // Not a real channel, just a placeholder
  }
}
```

When the Axi engine sees `"test_mode": true` in the configuration, it automatically uses the `TestDiscordHandler` instead of the standard `DiscordHandler`.

## Using the Test System

### 1. Creating a Test Configuration

You can create a test configuration programmatically:

```python
import json

# Start with an existing config
with open("examples/rps_example_league.json", 'r') as f:
    config = json.load(f)

# Enable Discord test mode
if "discord" not in config:
    config["discord"] = {}

config["discord"]["enabled"] = True
config["discord"]["test_mode"] = True
config["discord"]["token"] = "test_token"
config["discord"]["channel_id"] = "test_channel_id"

# Write to a temporary file
test_config_file = "examples/test_discord_config.json"
with open(test_config_file, 'w') as f:
    json.dump(config, f, indent=2)
```

### 2. Initializing Axi with Test Mode

Once you have a configuration with test mode enabled, initialize Axi as usual:

```python
from axi.axi import Axi

# Initialize Axi with test configuration
axi = Axi("examples/test_discord_config.json")

# Verify TestDiscordHandler was initialized
if hasattr(axi, 'discord_handler') and hasattr(axi.discord_handler, 'verify_message_count'):
    print("TestDiscordHandler initialized successfully")
```

### 3. Posting Test Messages

You can post test messages directly using the discord handler:

```python
# Create test tournament data
tournament_data = {
    "name": "Test Tournament",
    "description": "A tournament for testing Discord integration",
    "start_date": "2025-04-06",
    "end_date": "2025-04-07",
    "format": "Round Robin"
}

# Post a tournament announcement
axi.discord_handler.post_tournament_announcement(tournament_data)
```

### 4. Verifying Messages

The test handler provides methods to verify that messages were sent and formatted correctly:

```python
# Verify a message was sent
success = axi.discord_handler.verify_message_count("tournament_announcement", 1)
if success:
    print("Verified tournament announcement was sent")

# Verify message content
success = axi.discord_handler.verify_message_content(
    "tournament_announcement", 
    0,  # Index of the message (0 = first message)
    **{"embeds.0.title": "Tournament Announcement: Test Tournament"}
)
if success:
    print("Verified tournament announcement content")
```

### 5. Accessing Logged Messages

You can access logged messages for more detailed inspection:

```python
# Get all messages of a specific type
messages = axi.discord_handler.get_messages("tournament_announcement")
print(f"Found {len(messages)} tournament announcements")

# Get the latest message
latest = axi.discord_handler.get_latest_message("tournament_announcement")
if latest:
    print(f"Latest announcement title: {latest['embeds'][0]['title']}")
```

## Finding Logged Messages

The test handler stores messages in JSON files in a test-specific directory:

```
logs/discord_test/[test_mode]/[timestamp]/[message_type]_[timestamp].json
```

For example:
```
logs/discord_test/default/20250406165708/tournament_announcement_2025-04-06 16-57-08.json
```

Each JSON file contains:
- Timestamp: When the message was sent
- Type: The type of message (e.g., "tournament_announcement")
- Content: The full message content that would have been sent to Discord

## Complete Example

Here's a complete example of running a tournament with the test Discord handler and verifying the results:

```python
import sys
import os
import json
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("test_discord")

# Import Axi
from axi.axi import Axi
from axi.testing.test_discord_handler import TestDiscordHandler

def run_test():
    # Create test configuration
    config_file = "examples/rps_example_league.json"
    with open(config_file, 'r') as f:
        config = json.load(f)
    
    # Enable Discord test mode
    if "discord" not in config:
        config["discord"] = {}
    
    config["discord"]["enabled"] = True
    config["discord"]["test_mode"] = True
    config["discord"]["token"] = "test_token"
    config["discord"]["channel_id"] = "test_channel_id"
    
    test_config_file = "examples/test_discord_config.json"
    with open(test_config_file, 'w') as f:
        json.dump(config, f, indent=2)
    
    # Initialize Axi with test configuration
    axi = Axi(test_config_file)
    
    # Post a test tournament announcement
    tournament_data = {
        "name": "Test Tournament",
        "description": "A tournament for testing Discord integration",
        "start_date": datetime.now().isoformat(),
        "end_date": datetime.now().isoformat(),
        "format": "Round Robin"
    }
    axi.discord_handler.post_tournament_announcement(tournament_data)
    
    # Verify message was sent
    axi.discord_handler.verify_message_count("tournament_announcement", 1)
    axi.discord_handler.verify_message_content(
        "tournament_announcement", 0,
        **{"embeds.0.title": "Tournament Announcement: Test Tournament"}
    )
    
    # Run the tournament
    standings = axi.run()
    
    # Check match result messages
    match_count = axi.discord_handler.get_message_count("match_result")
    logger.info(f"Tournament generated {match_count} match result messages")
    
    # Check final standings message
    axi.discord_handler.verify_message_count("final_standings", 1)
    
    # Get the latest standings message and print it
    standings_message = axi.discord_handler.get_latest_message("final_standings")
    if standings_message:
        print(json.dumps(standings_message, indent=2))
    
    return 0

if __name__ == "__main__":
    sys.exit(run_test())
```

## Advanced Features

### Regex Content Verification

You can use regex patterns to verify message content:

```python
# Verify using regex pattern
axi.discord_handler.verify_message_content(
    "match_result", 0,
    **{"embeds.0.title": "regex:Match Result: CPU-\\d+ vs CPU-\\d+"}
)
```

### Clearing Messages

You can clear stored messages to start fresh:

```python
# Clear all messages
axi.discord_handler.clear_messages()

# Clear only specific message types
axi.discord_handler.clear_messages("tournament_announcement")
```

### Loading Messages from Logs

If you need to reload messages from log files:

```python
# Load all messages from log files
axi.discord_handler.load_messages_from_logs()
```

## Troubleshooting

### Common Issues

1. **Messages not being sent**: Make sure both `"enabled": true` and `"test_mode": true` are set in the Discord configuration.

2. **Verification failures**: Check that you're looking for the right message type and that the expected content matches exactly (including case sensitivity).

3. **Missing log files**: Ensure the logs directory exists and is writable. The TestDiscordHandler will attempt to create necessary directories, but may fail if permissions are insufficient.

## Extending the Test System

The test system can be extended to support new message types or verification methods:

1. Add new message types to the `messages` dictionary in the `TestDiscordHandler.__init__` method
2. Create new verification methods as needed
3. Update the related Discord posting methods

## Conclusion

The non-Discord test system provides a convenient way to develop and test Discord integration features without requiring an actual Discord connection. By using this system, you can ensure that your Discord messages are correctly formatted and sent at the appropriate times during tournament execution.

For more information, see the implementation in `axi/testing/test_discord_handler.py` and the example in `examples/test_discord.py`.