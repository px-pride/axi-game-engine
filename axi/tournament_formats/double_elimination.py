"""DoubleElimination tournament format.

Extends SingleElimination with a parallel losers bracket, GRAND FINALS,
and a DEADASS FINALS reset match (which only fires when LF winner beats
WF winner in GF).

Preset registration at module bottom: classic, de, side.
"""

from axi.tournament_formats.single_elimination import SingleElimination, _ByeUser
from axi.tournament_presets import register_preset
from axi.util import MATCH_STATUS_COMPLETED


class DoubleElimination(SingleElimination):
    """Double-elimination bracket.

    Constructor params:
        tournament : owning Tournament
        players    : list of players (padded to 2^N by SE)
        stream     : same semantics as SingleElimination
        bo5        : -1 = ALL matches BO5; N>0 = threshold; 0 = no BO5
                     escalation. (Note: differs slightly from SE where
                     -1 maps to threshold=8. DE's -1 means truly all-BO5
                     to match source preset_classic.)
        winner_loser_split : seeds beyond this index auto-DQ in round 1
                             (sent to losers bracket via dq). None or
                             num_players → no auto-DQ. Even values trigger
                             a snake-swap of the dropped seeds.
    """

    def __init__(self, tournament, players, stream=False, bo5=16,
                 winner_loser_split=None):
        super().__init__(tournament, players, stream=stream, bo5=bo5)

        # Remember the raw user input so generate_bracket can detect
        # the "all BO5" semantic for the winners bracket too.
        self._raw_bo5 = bo5
        # DE-specific bo5 semantics: -1 means "all BO5"
        # (super already stored bo5_threshold; override here).
        if bo5 == -1:
            # Effectively infinite threshold → all matches BO5.
            self.bo5_threshold = self.num_players + 1
        # else: super stored bo5_threshold correctly.

        if winner_loser_split is None:
            winner_loser_split = self.num_players
        elif winner_loser_split % 2 == 0 and winner_loser_split < self.num_players:
            # Snake-swap dropped seeds: swap (i, i+1) for every other pair
            # starting at winner_loser_split.
            for i in range(winner_loser_split, self.num_players, 2):
                if i + 1 < self.num_players:
                    self.players[i], self.players[i + 1] = (
                        self.players[i + 1], self.players[i],
                    )
        self.winner_loser_split = winner_loser_split

        # References populated in generate_bracket; used by complete_match override.
        self._wf = None
        self._gf = None
        self._reset = None

    def __repr__(self):
        return "DOUBLE ELIMINATION"

    def begin(self):
        effects = super().begin()
        effects += self._drop_losers()
        return effects

    def generate_bracket(self, stream_threshold=None, bo5_threshold=None,
                         link_victory=True):
        # Winners bracket: threshold for WB is the user's threshold scaled
        # down to 2/3 (source's design — deeper matches stream/upgrade more
        # eagerly). Override SE's defaults; do NOT link WB final to victory.
        wb_stream = self.stream_threshold * 2 // 3
        if self._raw_bo5 == -1:
            # "all BO5" — preserve through WB by keeping the effectively
            # infinite threshold instead of scaling it down.
            wb_bo5 = self.bo5_threshold
        else:
            wb_bo5 = self.bo5_threshold * 2 // 3
        wr1 = super().generate_bracket(
            stream_threshold=wb_stream,
            bo5_threshold=wb_bo5,
            link_victory=False,
        )

        wf = self._get_finals_simple(wr1)
        lr1 = self._generate_losers_bracket(wr1)
        lf = self._get_finals_simple(lr1)

        gf = self.add_node(
            best_of=5, loser_gets=2,
            label="GRAND FINALS", game=self._game_name(),
        )
        self.link_parent(gf, wf, "W")
        self.link_parent(gf, lf, "W")

        reset = self.add_node(
            best_of=5, loser_gets=2,
            label="DEADASS FINALS", game=self._game_name(),
        )
        self.link_parent(reset, wf, "W")
        self.link_parent(reset, gf, "W")

        if self.stream_threshold > 0:
            for n in (gf, reset):
                n.streamed = True
                self.stream_candidates.append(n)

        self.link_parent(self.victory_node, reset, "W")

        # Stash references for complete_match override.
        self._wf = wf
        self._gf = gf
        self._reset = reset

        return wr1

    def complete_match(self, node):
        effects = super().complete_match(node)
        # Reset short-circuit: if WF winner won GF, the reset is structurally
        # redundant — mark it COMPLETED with the WF winner and propagate to
        # victory_node.
        if (node is self._gf
                and self._wf is not None
                and self._wf.completed()
                and self._reset is not None
                and not self._reset.completed()):
            if self._wf.winner() is node.winner():
                winner = node.winner()
                self._reset.players = [winner]
                self._reset.score = [1, 0]
                self._reset.status = MATCH_STATUS_COMPLETED
                # Propagate to victory_node
                self.victory_node.players = [winner]
                self.victory_node.status = MATCH_STATUS_COMPLETED
                self.placements_dict[winner] = 1
        return effects

    # -- helpers --

    def _get_finals_simple(self, round_matches):
        """Walk W-children from round-1 down to the final match."""
        if not round_matches:
            return None
        node = round_matches[0]
        while True:
            w_child = None
            for child_id, flag in node.children.items():
                if flag == "W":
                    candidate = self.nodes_by_id.get(child_id)
                    # Skip GF/DEADASS — they're cross-bracket sentinels.
                    if candidate is None:
                        continue
                    if candidate.label in ("GRAND FINALS", "DEADASS FINALS"):
                        continue
                    w_child = candidate
                    break
            if w_child is None:
                return node
            node = w_child

    def _drop_losers(self):
        """Auto-DQ seeds beyond winner_loser_split in round 1."""
        effects = []
        if self.winner_loser_split >= self.num_players:
            return effects
        for i in range(self.num_players - 1, self.winner_loser_split - 1, -1):
            p = self.players[i]
            if isinstance(p, _ByeUser):
                continue
            match = self.current_match_by_player.get(p)
            if match is None or len(match.players) != 2:
                continue
            if not match.label.startswith("WINNERS"):
                continue
            match.streamed = False
            if match in self.stream_candidates:
                self.stream_candidates.remove(match)
            if self.stream_match is match:
                self.stream_match = None
            self.tournament.dq_user(p)
            effects += self.auto_resolve_non_match(match, reason="dq")
        return effects

    def _next_w_children(self, wr):
        """For each node in wr (in pairs), return the W-child of the lower-indexed
        node. Used to walk forward through the winners bracket layer-by-layer."""
        next_wr = []
        for i in range(len(wr) // 2):
            children = wr[i].children
            for child_id, flag in children.items():
                if flag == "W":
                    next_wr.append(self.nodes_by_id[child_id])
                    break
        return next_wr

    def _adjust_oddeven(self, j, parity_threshold_inclusive):
        """Source's even/odd correction inside losers-bracket pairing."""
        # This is the source pattern when temp_players >= 6 (or > 6 in one
        # branch). Caller passes the original `j` and we return the adjusted.
        return j - 1 if j % 2 == 1 else j + 1

    def _generate_losers_bracket(self, wr1):
        """Port of source's generate_losers_bracket. Returns lr1 (the
        first round of losers matches).
        """
        temp_players = self.num_players
        wr = list(wr1)
        # Precompute next_wr if we'll need it later.
        next_wr = self._next_w_children(wr) if temp_players > 3 else []

        cutoff = temp_players // 2
        num_rounds = temp_players // 4
        layer = {}
        lr = 1
        matches_per_round = []

        for i in range(cutoff, cutoff + num_rounds):
            j = temp_players * 3 // 2 - 1 - i
            if temp_players >= 6:
                j = self._adjust_oddeven(j, 6)
            label = "LOSERS SEMIS" if temp_players == 4 else f"LOSERS ROUND {lr}"
            node = self.add_node(
                best_of=self._choose_best_of(temp_players),
                loser_gets=temp_players,
                label=label,
                game=self._game_name(),
            )
            if self.stream_threshold > 0 and temp_players <= self.stream_threshold:
                node.streamed = True
                self.stream_candidates.append(node)
            # Parents from wr (reverse-indexed: wr[2*cutoff - 1 - i])
            self.link_parent(node, wr[2 * cutoff - 1 - i], "L")
            self.link_parent(node, wr[2 * cutoff - 1 - j], "L")
            layer[i] = node
            layer[j] = node
            matches_per_round.append(node)

        lr1 = list(matches_per_round)
        if matches_per_round:
            self.matches_by_round[matches_per_round[0].label] = matches_per_round

        while temp_players > 3:
            # ---- W-L layer ----
            temp_players = temp_players * 3 // 4
            wr = next_wr
            if temp_players > 3:
                next_wr = self._next_w_children(wr)
            cutoff = temp_players // 3
            lr += 1
            matches_per_round = []

            for i in range(cutoff, cutoff + num_rounds):
                j = temp_players * 4 // 3 - 1 - i
                if temp_players >= 6:
                    j = self._adjust_oddeven(j, 6)
                if temp_players == 3:
                    label = "LOSERS FINALS"
                elif temp_players == 6:
                    label = "LOSERS QUARTERS"
                else:
                    label = f"LOSERS ROUND {lr}"
                node = self.add_node(
                    best_of=self._choose_best_of(temp_players),
                    loser_gets=temp_players,
                    label=label,
                    game=self._game_name(),
                )
                if self.stream_threshold > 0 and temp_players <= self.stream_threshold:
                    node.streamed = True
                    self.stream_candidates.append(node)
                # Parents: WB layer-loser, and previous LB layer winner.
                if (2 * cutoff - 1 - i) < len(wr) and wr[2 * cutoff - 1 - i] is not None:
                    self.link_parent(node, wr[2 * cutoff - 1 - i], "L")
                if j in layer:
                    self.link_parent(node, layer[j], "W")
                layer[i] = node
                layer[j] = node
                matches_per_round.append(node)

            if matches_per_round:
                self.matches_by_round[matches_per_round[0].label] = matches_per_round

            if temp_players > 3:
                # ---- L-L layer ----
                temp_players = temp_players * 2 // 3
                num_rounds //= 2
                lr += 1
                matches_per_round = []

                for i in range(cutoff, cutoff + num_rounds):
                    j = temp_players * 3 // 2 - 1 - i
                    if temp_players > 6:
                        j = self._adjust_oddeven(j, 7)
                    label = "LOSERS SEMIS" if temp_players == 4 else f"LOSERS ROUND {lr}"
                    node = self.add_node(
                        best_of=self._choose_best_of(temp_players),
                        loser_gets=temp_players,
                        label=label,
                        game=self._game_name(),
                    )
                    if self.stream_threshold > 0 and temp_players <= self.stream_threshold:
                        node.streamed = True
                        self.stream_candidates.append(node)
                    if i in layer:
                        self.link_parent(node, layer[i], "W")
                    if j in layer:
                        self.link_parent(node, layer[j], "W")
                    layer[i] = node
                    layer[j] = node
                    matches_per_round.append(node)

                if matches_per_round:
                    self.matches_by_round[matches_per_round[0].label] = matches_per_round

        return lr1


# ---------------------------------------------------------------------------
# Preset registration
# ---------------------------------------------------------------------------


def _de_factory(stream=False, bo5=16, winner_loser_split=None):
    def factory(tournament, players):
        return DoubleElimination(
            tournament, players,
            stream=stream, bo5=bo5,
            winner_loser_split=winner_loser_split,
        )
    return factory


@register_preset("classic")
def _preset_classic(_t):
    return [_de_factory(stream=6, bo5=-1)], "Double elimination."


@register_preset("de")
def _preset_de(_t):
    return [_de_factory(stream=6, bo5=-1)], "Double elimination."


@register_preset("side")
def _preset_side(_t):
    return [_de_factory(stream=False, bo5=-1)], "Double elimination."
