from random import Random, randrange
from sys import maxsize

MATCH_STATUS_ASLEEP = 0
MATCH_STATUS_CALLED = 1
MATCH_STATUS_ACTIVE = 2
MATCH_STATUS_COMPLETED = 3

USER_STATUS_QUEUED = 0
USER_STATUS_CALLED = 1
USER_STATUS_BREAK = 2

supported_ladder_formats = [
    "friendlies",
    "glicko",
    "openskill",
    "danisen"]


seed = randrange(maxsize)
rng = Random(seed)
