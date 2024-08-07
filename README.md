# Axi Game Engine
Python engine for Discord bot games. 1v1 focus.

## How does it work?
Once you've set up your bot and invited it to your Discord server, it serves as a launcher for the various games you've written. You can see in `example_main.py` that our example launcher contains two games from the `examples` directory: Rock-Paper-Scissors and Wonder Wand.

The bot is powered primarily by slash commands. If you are using your bot for the first time, you will need to use the command `/sync` so that Discord properly recognizes the rest of your slash commands. Once your bot is synced, you are able to play your games. `/solo` lets you explore each game's single-player modes and `/versus` lets you ping an opponent to fight them directly. `/spectate` lets you spectate other players' games. `/abort` exits you from playing or spectating.

Games occur in DMs with the bot. The bot conveys information about the game state at each step, and players input their decisions by reacting with emojis.

## What features does it have?
* Single-player, multiplayer, and spectator modes.
* Interactions with database and Discord API abstracted out.
* Support for playing against CPUs, with some basic CPUs built in.
* Loading and saving customizable user profiles.
* Message queue system with automatic flushing.
* In-game text commands.

## How do I try it?
A version of this engine currently runs on our Discord servers, featuring the games provided in the `examples` directory.

You can join our main Discord here: https://discord.gg/EYXxETutEJ

We also have a developer/tester Discord. Please DM me if you would like access. My Discord handle is @px_pride.

## What is Wonder Wand?
Wonder Wand is a game written to explore the possibilities of more complex Discord games. Inspired by Pokemon and card games, Wonder Wand is a turn-based tactics game emphasizing customization, resource management, and reading your opponent. Give it a shot in our Discord!

## How do I write my own games?
Extend `AbstractDmGame` and implement the various abstract methods. These methods get called by the handlers automatically as needed.

## How do I write my own CPU?
Extend `AbstractCPU` and implement the `compute()` method. This method gets called whenever the CPU needs to make a decision. 

## How do I power my own bot with this code?
To create your own Discord bot, you must acquire a token from the Discord Developer Portal. https://discord.com/developers/applications

You can then host and run the code. A template script `example_main.py` has been provided. We recommend using a Vultr server. https://vultr.com
