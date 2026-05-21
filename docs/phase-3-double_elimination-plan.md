# Phase 3: DoubleElimination — Detailed Design

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 3.

This phase introduces `DoubleElimination` — extends `SingleElimination`
(Phase 2) with a parallel losers bracket, Grand Finals, and an optional
Deadass Finals reset match.

## Scope

- Build `DoubleElimination(SingleElimination)` in
  `axi/tournament_formats/double_elimination.py`.
- Register presets: `classic`, `de`, `side`.
- Extend `SingleElimination.generate_bracket` with optional override args
  so the DE constructor can drive the winners-bracket portion without
  duplicating SE logic.

## Algorithm (port of `/tmp/claude-1001/tourney-inspect/double_elimination.py`)

### Constructor

- Inherits `SingleElimination`. Default `bo5=16`, `winner_loser_split=None`.
- If `winner_loser_split is None`, it defaults to `self.num_players` (no
  split — every player starts in winners).
- If `winner_loser_split` is **even and < num_players**, perform DE's
  internal snake swap on player indices from `winner_loser_split` to the
  end, swapping every other pair `(players[i], players[i+1])`. This is
  the seeding adjustment that drops the bottom seeds into the losers
  bracket more fairly.

### `begin()`

- Calls `super().begin()` (which builds the bracket via
  `generate_bracket()` and calls round-1 matches).
- Then calls `drop_losers()` to auto-DQ all seeds beyond
  `winner_loser_split`.

### `generate_bracket()`

1. Call `super().generate_bracket(stream_threshold_override, bo5_threshold_override, link_victory=False)`
   to build the winners bracket without linking the WF to victory_node.
   - `stream_threshold_override = self.stream_threshold * 2 // 3` (winners
     bracket uses a lowered stream threshold; default 6 * 2 // 3 = 4).
   - `bo5_threshold_override = self.bo5_threshold * 2 // 3` (default 16 *
     2 // 3 = 10, with the source's `+0.01` floor-correction implicit in
     integer division). When `bo5_threshold == 0`, override = 0 (no BO5).
2. Locate the WF (winners final) via `_get_finals_simple(wr1)` — traverse
   children from any round-1 node down to the leaf with no W-child.
3. Generate losers bracket via `_generate_losers_bracket(wr1)` (returns
   `lr1`, the list of losers round-1 nodes).
4. Locate the LF (losers final) via `_get_finals_simple(lr1)`.
5. Create the **GRAND FINALS** node: parents `{wf_id: "W", lf_id: "W"}`,
   `best_of=5`, `loser_gets=2`, label "GRAND FINALS".
6. Create the **DEADASS FINALS** (reset) node: parents `{wf_id: "W", gf_id: "W"}`,
   `best_of=5`, `loser_gets=2`, label "DEADASS FINALS".
7. If `self.stream_threshold > 0`, mark both GF and reset as streamed.
8. Link `self.victory_node` to the reset with flag "W".
9. Return `wr1` (initial matches to call).

### `drop_losers()`

For each seed `i` in `range(num_players-1, winner_loser_split-1, -1)`:
- Skip if the player is a `_ByeUser`.
- Find their current round-1 match.
- Auto-DQ them: rather than the source's `report_score("DQ-0", admin)`,
  call `self.tournament.dq_user(player)` and re-run `call_match(match)` —
  Phase 1's bye/drop/dq check in `call_match` will auto-resolve.

  Or simpler: skip running the match at all. Mark the match streamed=False,
  remove from stream_candidates if present, then `auto_resolve_non_match(match, reason="dq")`.

### `_get_finals_simple(round_matches)`

Traverse W-child links from any round-1 node down to find the final node:

```python
def _get_finals_simple(self, round_matches):
    if not round_matches:
        return None
    node = round_matches[0]
    while True:
        # Find the W-child of this node
        w_child = None
        for child_id, flag in node.children.items():
            if flag == "W":
                w_child = self.nodes_by_id[child_id]
                break
        if w_child is None:
            return node
        node = w_child
```

### `_generate_losers_bracket(wr1)` — the complex part

The losers bracket alternates between two layer types as `temp_players`
shrinks from `num_players` down to 3:

**Initial layer (round 1 of losers):**

```
temp_players = num_players
cutoff       = temp_players // 2
num_rounds   = temp_players // 4

for i in range(cutoff, cutoff + num_rounds):
    j = temp_players * 3 // 2 - 1 - i
    if temp_players >= 6:
        # Even/odd adjustment to avoid double jeopardy
        j = j - 1 if j % 2 == 1 else j + 1
    create node with parents (wr1_reverse[2*cutoff - 1 - i], 'L'),
                             (wr1_reverse[2*cutoff - 1 - j], 'L')
    label "LOSERS SEMIS" if temp_players == 4 else "LOSERS ROUND <lr>"
```

`wr1_reverse` here means `wr1` indexed in reverse — source uses
`wr[2*cutoff - 1 - i]` which is just the i-th match from the END.

**Subsequent layers — alternating W-L and L-L:**

The while loop iterates `while temp_players > 3`:

1. **Winner-Loser layer** (every iteration):
   - `temp_players = temp_players * 3 // 4`
   - `wr = next_wr` (the next round of winners bracket — children of current wr)
   - `cutoff = temp_players // 3`
   - For `i in range(cutoff, cutoff + num_rounds)`:
     - `j = temp_players * 4 // 3 - 1 - i`
     - Even/odd adjust if `temp_players >= 6`
     - Parents: `(wr[2*cutoff - 1 - i], 'L')`, `(layer[j], 'W')`
     - Label: "LOSERS FINALS" if temp_players==3, "LOSERS QUARTERS" if
       temp_players==6, else "LOSERS ROUND <lr>"
2. **Loser-Loser layer** (only when temp_players > 3 after W-L):
   - `temp_players = temp_players * 2 // 3`
   - `num_rounds //= 2`
   - For `i in range(cutoff, cutoff + num_rounds)`:
     - `j = temp_players * 3 // 2 - 1 - i`
     - Even/odd adjust if `temp_players > 6`
     - Parents: `(layer[i], 'W')`, `(layer[j], 'W')`
     - Label: "LOSERS SEMIS" if temp_players==4, else "LOSERS ROUND <lr>"

The `layer` dict is shared across iterations; both `i` and `j` keys map
to the newly-created node so that subsequent rounds can look up by
either index.

**Returns** `lr1` — the first round of losers matches.

## Adapted differences from source

- **Use Phase 1 `add_node` + `link_parent`.** Source uses raw
  `MatchNode(self.tourney, )` and `add_parent`.
- **DQ handling**: source uses `report_score_for_player(p, "DQ-0", admin_user)`.
  Phase 1 doesn't have admin-override DQ via score. Use
  `self.tournament.dq_user(player)` and `auto_resolve_non_match(match, "dq")`
  instead — same effect, no special score parsing.
- **`SingleElimination.generate_bracket` signature extension** (small
  Phase 2 change, additive):
  ```python
  def generate_bracket(self, stream_threshold=None, bo5_threshold=None,
                       link_victory=True):
  ```
  - When called with no args (Phase 2 default), behavior unchanged.
  - DoubleElimination calls with `link_victory=False` and explicit
    overrides for both thresholds.
- **Reset match handling**: source unconditionally creates the reset
  node. When WF wins GF, the reset is structurally redundant — the same
  player is both incoming children. We need to short-circuit:
  - Override `complete_match`: when the completing node is GF, check if
    `GF.winner() == WF.winner()`. If so, mark reset COMPLETED with that
    winner without launching. Otherwise, populate reset normally.
- **Stream / BO5 threshold transformation**: source uses
  `self.stream*2//3+0.01` and `self.bo5*2//3+0.01` as floats. Our
  integer-arithmetic equivalent is `self.stream_threshold * 2 // 3`
  (drops the `+0.01` since the source's float was just to make integer
  divisions work with `<=` correctly).

## Class signature

```python
import math

from axi.tournament_formats.single_elimination import SingleElimination, _ByeUser
from axi.tournament_presets import register_preset


class DoubleElimination(SingleElimination):
    """Double-elimination bracket: extends SingleElimination with losers
    bracket, Grand Finals, and a Deadass Finals reset match."""

    def __init__(self, tournament, players, stream=False, bo5=16,
                 winner_loser_split=None):
        super().__init__(tournament, players, stream=stream, bo5=bo5)
        if winner_loser_split is None:
            winner_loser_split = self.num_players
        elif winner_loser_split % 2 == 0:
            # Snake-swap the dropped players to spread them fairly
            for i in range(winner_loser_split, self.num_players, 2):
                if i + 1 < self.num_players:
                    self.players[i], self.players[i+1] = (
                        self.players[i+1], self.players[i]
                    )
        self.winner_loser_split = winner_loser_split

    def __repr__(self):
        return "DOUBLE ELIMINATION"

    def begin(self):
        effects = super().begin()
        effects += self._drop_losers()
        return effects

    def generate_bracket(self):
        # Build winners bracket with overrides; don't link to victory.
        wr1 = super().generate_bracket(
            stream_threshold=self.stream_threshold * 2 // 3,
            bo5_threshold=self.bo5_threshold * 2 // 3,
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
        return wr1

    def complete_match(self, node):
        # If this is the Grand Finals AND WF winner won GF, short-circuit the reset.
        effects = super().complete_match(node)
        if node.label == "GRAND FINALS":
            wf = self._get_finals_simple(self.matches_by_round.get("WINNERS ROUND 1", []) or
                                          self.matches_by_round.get("WINNERS QUARTERS", []) or
                                          self.matches_by_round.get("WINNERS SEMIS", []) or
                                          self.matches_by_round.get("WINNERS FINALS", []))
            reset = next(
                (n for n in self.nodes_by_id.values() if n.label == "DEADASS FINALS"),
                None,
            )
            if reset is not None and wf is not None and node.winner() == wf.winner():
                # WF won GF; bypass reset by marking it completed with WF winner.
                reset.players = [node.winner()]
                reset.score = [1, 0]
                effects += super().complete_match(reset)
        return effects

    # ---- internal helpers (porting source's private logic) ----

    def _get_finals_simple(self, round_matches):
        if not round_matches:
            return None
        node = round_matches[0]
        while True:
            w_child = None
            for child_id, flag in node.children.items():
                if flag == "W":
                    w_child = self.nodes_by_id[child_id]
                    break
            if w_child is None:
                return node
            node = w_child

    def _drop_losers(self):
        effects = []
        for i in range(self.num_players - 1, self.winner_loser_split - 1, -1):
            p = self.players[i]
            if isinstance(p, _ByeUser):
                continue
            match = self.current_match_by_player.get(p)
            if match is not None and len(match.players) == 2 \
                    and match.label.startswith("WINNERS"):
                # Remove from stream candidates / stream_match
                match.streamed = False
                if match in self.stream_candidates:
                    self.stream_candidates.remove(match)
                if self.stream_match is match:
                    self.stream_match = None
                # DQ the dropped player
                self.tournament.dq_user(p)
                effects += self.auto_resolve_non_match(match, reason="dq")
        return effects

    def _generate_losers_bracket(self, wr1):
        # See design doc for the algorithm; ported with minor adaptations.
        # Maintain `layer` dict mapping seed-index -> losers node;
        # alternate W-L and L-L layers until LOSERS FINALS (temp_players=3).
        # Implementation lives here; see design doc for full pseudocode.
        ...
```

The `_generate_losers_bracket` body is the largest single chunk — it
needs careful porting from source lines 78–198. Code in the design doc
is abbreviated to keep this readable; implementation is straightforward
mechanical translation:
- Replace `MatchNode(self.tourney, )` with `self.add_node(...)`.
- Replace `match.add_parent(X, flag)` with `self.link_parent(match, X, flag)`.
- Replace `match.best_of = 5 if self.bo5 < 0 or temp_players <= self.bo5 else 3`
  with `match.best_of = self._choose_best_of(temp_players)` — same semantics.

## Preset registration

```python
def _de_factory(stream=False, bo5=16, winner_loser_split=None):
    def factory(tournament, players):
        return DoubleElimination(tournament, players,
                                 stream=stream, bo5=bo5,
                                 winner_loser_split=winner_loser_split)
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
```

## Files to add / modify

```
NEW  axi/tournament_formats/double_elimination.py
MOD  axi/tournament_formats/single_elimination.py
     (additive: generate_bracket gains optional stream_threshold/
     bo5_threshold/link_victory args; default behavior unchanged.)
```

## Test Plan

`tests/test_double_elimination.py`:

### Construction sizes

- **Size 4**: 2 WB-R1 (semis), 1 WF, then LR1 (the round-1 losers match
  is also a LOSERS SEMI? need to check). Verify total node count.
- **Size 8**: 4 WB-quarters, 2 WB-semis, 1 WF, plus losers, GF, reset.
  Source's behavior: losers structure should produce ~7 losers matches.
- **Size 16**: 8 + 4 + 2 + 1 = 15 winners; ~14 losers; + GF + reset =
  ~31 total bracket nodes.

### Winners/losers linkage

- WB-R1 loser flows to LB-R1 via "L" edge.
- LB winners advance through the losers bracket.
- WF "W" edge points to GF.
- LF "W" edge points to GF.

### Grand Finals + Deadass Finals reset

- After WF + LF complete, GF has both winners as players.
- GF "W" edge points to reset's player-receive.
- **WF wins GF**: reset auto-completes without launching, victory_node
  has WF winner as players[0].
- **LF wins GF**: reset becomes active, has WF.winner + LF.winner (which
  is GF.winner) as players. Reset's winner becomes the tournament champion.

### Winner-loser split

- `winner_loser_split=None`: no auto-DQ; all players start in winners.
- `winner_loser_split=8` on 16-player bracket: seeds 8-15 auto-DQ via
  `drop_losers`; they appear in `non_matches` with reason "dq" and their
  round-1 opponents advance.
- `winner_loser_split=8` (even): snake swap applied to seeds 8-15 before
  bracket generation. Verify the swap reorders pairs.

### BO5 escalation transformation

- Default (`bo5=16`): winners-bracket uses threshold `16*2//3 = 10`;
  losers uses 16. So 16-player WB: round 1 (16) BO3, rest BO5.
- `bo5=-1`: dynamic — winners threshold becomes 8*2//3 = 5; losers
  threshold = 8. (Wait, `bo5=-1` in Phase 2 maps to threshold 8 in our
  storage. So `*2//3 = 5`.)
- Confirm BO5 counts match expected for each setting.

### Stream marking transformation

- `stream=6`: winners threshold 6*2//3 = 4; losers = 6. GF + reset
  always streamed when stream_threshold > 0.
- `stream=False`: no streaming.

### Preset registration

- `classic`, `de`, `side` all registered.
- `classic` and `de` produce identical factories; `side` differs (no stream).

## Resolved questions (no open items)

1. **WB threshold transformation**: kept as `* 2 // 3` (integer-arith
   equivalent of source's `* 2/3 + 0.01`).
2. **Reset short-circuit**: handled in `DoubleElimination.complete_match`
   override, checking if GF winner == WF winner.
3. **DQ via dq_user instead of "DQ-0" score**: cleaner port using Phase 1's
   `auto_resolve_non_match` path.
4. **`SingleElimination.generate_bracket` extension**: additive optional
   kwargs (`stream_threshold`, `bo5_threshold`, `link_victory`); Phase 2
   behavior preserved when called with no args.

## What's deferred

- `reduce_double_jeopardy` (Tournament-level swap for RR→DE seeding) —
  belongs to Phase 4 (RoundRobin pools feeding DE).
- `preset_standard`, `top4`, `top6`, `grands`, `daily`, `phase2` — RR+DE
  composite presets in Phase 4.
- Bracket visualization — Phase 15.
