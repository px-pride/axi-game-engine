from axi.axi import add_dm_game, add_thread_game, run
from axi.thread_game import ThreadGame
from examples.rock_paper_scissors import RockPaperScissors
from examples.wonder_wand.wonder_wand import WonderWand

# Add DM-based games by passing in a class.
add_dm_game(RockPaperScissors)
add_dm_game(WonderWand)

# Add thread-based games by passing in a config file.
add_thread_game("examples/rushrev.json")

# Launch the core loop.
run()
