from os import getenv
from dotenv import load_dotenv
import axi.handlers.discord_handler as discord_handler
import axi.handlers.database_handler as database_handler
from pickle import dumps, loads

load_dotenv()
TOKEN = getenv('DISCORD_TOKEN')
games = dict()

def add_game(game_cls):
    games[game_cls.__name__] = game_cls
    database_handler.add_game(game_cls.__name__)

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

