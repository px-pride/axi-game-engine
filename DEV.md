# Development Journal

## Initial Setup - April 6, 2025

- Created the basic structure for the Axi game engine
- Implemented the core AbstractGame class
- Created a sample Rock-Paper-Scissors implementation
- Set up the main Axi engine class with handlers
- Implemented ladder and rating system framework
- Added SimpleCPU implementation for AI players
- Created configuration files and examples

## Handler Implementations - April 6, 2025

- Implemented all the required handlers:
  - [x] DatabaseHandler - JSON and SQLite storage backends
  - [x] DiscordHandler - Discord integration for tournament announcements
  - [x] MatchHandler - Running matches between players
  - [x] ScheduleHandler - Tournament scheduling with various formats
  - [x] UserHandler - User management and CPU player creation
- Implemented the Ladder system for player rankings
- Added Glicko-2 timeless rating system

## Bug Fixes - April 6, 2025

- Fixed logger initialization in Axi class
- Fixed player handling in ScheduleHandler and MatchHandler 
- Added proper error handling to example_main.py
- Implemented basic logging configuration

## Next Steps

- [ ] Implement the remaining rating systems:
  - [x] GlickoTimeless
  - [ ] Danisen
  - [ ] PlackettLuceExtended
- [ ] Add more detailed documentation and usage examples
- [ ] Create unit tests for core components
- [ ] Implement a more complex game example (Wonder Wand)
- [ ] Add CLI interface for tournament management
- [ ] Implement proper Discord bot integration using discord.py

## Known Issues

- Discord integration is mocked and doesn't actually connect to Discord
- Only implemented one rating system (Glicko-2 timeless)
- No unit tests yet
- Some edge cases might not be properly handled

## Design Decisions

- Chose to implement a handler-based architecture for flexibility
- Used abstract base classes to enforce game interface implementation
- Decided to support multiple rating systems rather than forcing a single approach
- Separated CPU player logic from game logic to allow for different AI strategies
- Used a mix of static configuration and dynamic object creation for flexibility
- Implemented a simplified version of Discord integration that logs to files instead of actually posting to Discord
- Created a modular system where components can be swapped out or extended easily