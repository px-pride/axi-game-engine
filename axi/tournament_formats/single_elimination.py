"""SingleElimination tournament format.

Standard knockout bracket: players paired 1-vs-N seeded; losers eliminated.
Padded to a power of 2 with bye sentinels.

Preset registration at module bottom: 'fast' and 'se' both resolve to
SingleElimination(stream=False, bo5=8).
"""

import math

from axi.match_graph import MatchGraph
from axi.tournament_presets import register_preset


class _ByeUser:
    """Sentinel player for bracket padding.

    Implements the minimum AxiUser surface MatchGraph needs (uid.id) plus
    is_bye() returning True so MatchGraph.call_match auto-resolves the
    match without launching a real game.
    """

    def __init__(self, idx):
        self.uid = type("Uid", (), {"id": -1 - idx})()
        self._idx = idx

    def is_bye(self):
        return True

    def __str__(self):
        return f"__BYE__{self._idx}"

    def __repr__(self):
        return f"__BYE__{self._idx}"


class SingleElimination(MatchGraph):
    """Single-elimination bracket. Pads to 2^N with byes, standard seeding.

    Constructor params:
        tournament : owning Tournament
        players    : list of AxiUser-like objects (or _ByeUser for byes)
        stream     : False (no stream), True (default thresh=6), or int
                     (stream when temp_players <= threshold)
        bo5        : int. -1 = dynamic with default threshold=8.
                     N > 0 = switch to BO5 once temp_players <= N.
                     N == 0 disables BO5 escalation entirely (all BO3).
    """

    def __init__(self, tournament, players, stream=False, bo5=8):
        super().__init__(tournament, players, stream=stream)
        # Pad to next power-of-2, minimum 4.
        n = max(2, len(self.players))
        self.num_players = max(4, 2 ** math.ceil(math.log2(n)))
        byes_needed = self.num_players - len(self.players)
        for i in range(byes_needed):
            self.players.append(_ByeUser(i))

        # bo5: -1 → dynamic (threshold = 8). Else use given value.
        self.bo5_threshold = 8 if bo5 == -1 else bo5

        # stream: True → default threshold 6; int → explicit; False → 0 (off).
        if stream is True:
            self.stream_threshold = 6
        elif isinstance(stream, int) and not isinstance(stream, bool):
            self.stream_threshold = stream
        else:
            self.stream_threshold = 0

    def __repr__(self):
        return "SINGLE ELIMINATION"

    def generate_bracket(self):
        """Build the bracket DAG. Returns initial round matches to call."""
        temp_players = self.num_players
        layer = {}
        wr = 1
        matches_to_call = []

        # Round 1: 1-vs-N seeding pairs (players[i], players[N-1-i]).
        round_matches = []
        for i in range(temp_players // 2):
            j = temp_players - 1 - i
            node = self.add_node(
                players=[self.players[i], self.players[j]],
                best_of=self._choose_best_of(temp_players),
                loser_gets=temp_players,
                label=self._label_for(temp_players, wr),
                game=self._game_name(),
            )
            self._maybe_mark_streamed(node, temp_players, i)
            matches_to_call.append(node)
            round_matches.append(node)
            layer[i] = node
        self.matches_by_round[round_matches[0].label] = round_matches

        # Subsequent rounds: pair (layer[i], layer[temp_players - 1 - i]).
        temp_players //= 2
        wr += 1
        last_match = None
        while temp_players >= 2:
            round_matches = []
            for i in range(temp_players // 2):
                j = temp_players - 1 - i
                node = self.add_node(
                    best_of=self._choose_best_of(temp_players),
                    loser_gets=temp_players,
                    label=self._label_for(temp_players, wr),
                    game=self._game_name(),
                )
                self._maybe_mark_streamed(node, temp_players, i)
                self.link_parent(node, layer[i], "W")
                self.link_parent(node, layer[j], "W")
                last_match = node
                round_matches.append(node)
                # We'll overwrite layer in a second pass to avoid corrupting
                # indices mid-iteration.
            # Replace layer with new round's nodes, keyed 0..n-1.
            layer = {i: round_matches[i] for i in range(len(round_matches))}
            if round_matches:
                self.matches_by_round[round_matches[0].label] = round_matches
            temp_players //= 2
            wr += 1

        # Link the final match to the victory_node.
        if last_match is not None:
            self.link_parent(self.victory_node, last_match, "W")
        elif matches_to_call:
            # 2-player bracket: the round-1 match IS the final.
            self.link_parent(self.victory_node, matches_to_call[0], "W")

        return matches_to_call

    def _choose_best_of(self, temp_players):
        if self.bo5_threshold > 0 and temp_players <= self.bo5_threshold:
            return 5
        return 3

    def _label_for(self, temp_players, wr):
        if temp_players == 2:
            return "WINNERS FINALS"
        if temp_players <= 4:
            return "WINNERS SEMIS"
        if temp_players <= 8:
            return "WINNERS QUARTERS"
        return f"WINNERS ROUND {wr}"

    def _maybe_mark_streamed(self, node, temp_players, i):
        if self.stream_threshold <= 0:
            return
        is_last_of_round = (i == temp_players // 2 - 1)
        if temp_players <= self.stream_threshold or is_last_of_round:
            node.streamed = True
            self.stream_candidates.append(node)

    def _game_name(self):
        return getattr(self.tournament, "game", "rps")


# ---------------------------------------------------------------------------
# Preset registration
# ---------------------------------------------------------------------------

def _se_factory(stream=False, bo5=8):
    def factory(tournament, players):
        return SingleElimination(tournament, players, stream=stream, bo5=bo5)
    return factory


@register_preset("fast")
def _preset_fast(_t):
    return [_se_factory(stream=False, bo5=8)], "Single elimination."


@register_preset("se")
def _preset_se(_t):
    return [_se_factory(stream=False, bo5=8)], "Single elimination."
