from os import getenv
from dotenv import load_dotenv
import axi.handlers.discord_handler as discord_handler
import axi.handlers.database_handler as database_handler
from axi.double_blind import DoubleBlind
from pickle import dumps, loads
from json import load

load_dotenv()
TOKEN = getenv('DISCORD_TOKEN')
dm_games = dict()
thread_games = dict()

def add_dm_game(game_cls):
    game_key = game_cls.__name__
    dm_games[game_key] = game_cls
    database_handler.add_game(game_key)

add_dm_game(DoubleBlind)

def add_thread_game(game_config):
    game_info = load(open(game_config))
    if not isinstance(game_info, dict) or "name" not in game_info:
        print(f"Invalid JSON config file: {game_config}.")
        return
    game_key = game_info["name"]
    thread_games[game_key] = game_info
    database_handler.add_game(game_key)

def load_profile(user, game_name):
    entry = database_handler.load_entry_where(game_name, "user_id", user.uid.id)
    if not entry:
        return None
    profile = loads(entry[1])
    return profile

def save_profile(user, game_name, profile):
    # multiple rows for one user bug
    database_handler.add_entry(game_name, [user.uid.id, dumps(profile)])

def run():
    discord_handler.bot.run(TOKEN)

