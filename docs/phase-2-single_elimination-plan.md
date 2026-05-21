# Phase 2: SingleElimination — Detailed Design

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 2.

This phase introduces `SingleElimination` — the first concrete
`MatchGraph` subclass. Produces a standard knockout bracket where each
match's loser is eliminated.

## Scope

- Build a SingleElimination class in `axi/tournament_formats/single_elimination.py`.
- Register a preset (`fast` / `se`) via `axi/tournament_presets.py`.
- Add a __BYE__ sentinel user in `axi/axi_user.py` (or a helper) so byes
  auto-resolve via the Phase 1 `MatchGraph.call_match` bye path.

## Algorithm (port of `/tmp/claude-1001/tourney-inspect/single_elimination.py`)

1. Pad `players` to the next power of 2 ≥ max(4, len(players)) by appending
   `__BYE__N` sentinel users.
2. Build round 1 pairing: `(players[i], players[N-1-i])` for `i` in
   `range(N // 2)`. This seeds the bracket so the top seed plays the bottom
   seed (standard SE convention).
3. For each subsequent round, pair `(layer[i], layer[N//2 - 1 - i])`
   children → new node, linked via `add_parent(node, "W")`. The last round
   produces 1 node, which becomes the victory_node's only parent.
4. Match labels by round size (`temp_players`):
   - `temp_players == 2` → `"WINNERS FINALS"`
   - `temp_players ≤ 4` → `"WINNERS SEMIS"`
   - `temp_players ≤ 8` → `"WINNERS QUARTERS"`
   - else → `"WINNERS ROUND <n>"` where `n` is 1-indexed round count
5. `loser_gets = temp_players` for each match (placement tier propagates
   through Phase 1's `complete_match`).
6. Stream marking: tag `match.streamed = True` whenever
   `temp_players ≤ stream_thresh` OR the match is the last of its round
   (`i == temp_players // 2 - 1`). Streamed matches are added to
   `stream_candidates` instead of being launched immediately; the Phase 1
   `MatchGraph.begin` picks one via `call_match_for_stream`.

## Adapted differences from source

- **Use `add_node` not `MatchNode(...)` constructor.** Phase 1's
  `MatchGraph.add_node` handles UUID `node_id`, `tournament_id`/`graph_id`
  wiring, and registration in `nodes_by_id`. Direct `MatchNode(...)`
  construction would skip those.
- **Use `link_parent` (Phase 1) instead of `add_parent` (source).** Same
  semantics; Phase 1 enforces the W/L flag is valid.
- **Constructor parameters renamed for clarity:**
  - `stream` (bool|int) — `False` (no stream selection), `True` (stream
    enabled with default threshold), or `int` (stream when `temp_players
    ≤ threshold`).
  - `bo5` (int) — `-1` means dynamic (default to BO5 once `temp_players ≤
    bo5_thresh`). Default `bo5=8` matches source.
  - Both threshold-style: `stream` and `bo5` are passed as both the
    "enabled" flag and the threshold value. Source uses `stream_thresh`
    and `bo5_thresh` as separate arguments to `generate_bracket`.
- **Bye handling adapted.** Source creates real-named `User("__BYE__N")`
  objects. Phase 1's `MatchGraph.call_match` already checks
  `node.is_bye()` (via `getattr(p, "is_bye", lambda: False)()` on each
  player). To make the bye path work, we need either:
  - Option A: a `BYE_USER` singleton with `is_bye()` returning True, OR
  - Option B: a `_ByeUser` class with the AxiUser interface and `is_bye() = True`.
  - **Chosen: Option B.** Add a `_ByeUser` class to
    `axi/tournament_formats/single_elimination.py` (private to format
    modules). Has `.uid.id = -1 - i` (so IDs are unique negative values)
    and `is_bye()` returning True. AxiUser doesn't need modification.
- **Victory node linkage.** Source uses
  `self.victory_node.add_parent(match, 'W')` — port directly with
  `self.link_parent(self.victory_node, last_round_node, "W")`.

## Class signature

```python
import math
from axi.match_graph import MatchGraph


class _ByeUser:
    """Sentinel player for bracket padding. Has minimum AxiUser interface
    needed by MatchGraph (uid.id) and is_bye() returns True."""
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
    """Single-elimination bracket. Padded to 2^N with byes; standard
    1-vs-N seeding; matches escalate to BO5 once player count ≤ bo5_thresh.

    Constructor params:
      tournament : Tournament instance (owns players, rng, presets).
      players    : list of AxiUser. Padded to 2^N internally.
      stream     : False / True / int. True = stream with default threshold;
                   int = stream when temp_players <= threshold.
      bo5        : int. -1 = dynamic (switch to BO5 once temp_players <= 8);
                   N>0 = switch to BO5 once temp_players <= N.
    """

    def __init__(self, tournament, players, stream=False, bo5=8):
        super().__init__(tournament, players, stream)
        self.num_players = max(4, 2 ** math.ceil(math.log2(max(2, len(players)))))
        # Add byes to pad to 2^N.
        byes_needed = self.num_players - len(self.players)
        for i in range(byes_needed):
            self.players.append(_ByeUser(i))
        # bo5 parameter: -1 (dynamic) maps to threshold 8; else use given.
        self.bo5_threshold = 8 if bo5 == -1 else bo5
        # stream parameter: True maps to default threshold 6; int = explicit.
        if stream is True:
            self.stream_threshold = 6
        elif isinstance(stream, int):
            self.stream_threshold = stream
        else:
            self.stream_threshold = 0  # disabled

    def __repr__(self):
        return "SINGLE ELIMINATION"

    def generate_bracket(self):
        temp_players = self.num_players
        layer = {}
        wr = 1
        matches_to_call = []

        # Round 1
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

        # Subsequent rounds
        temp_players //= 2
        wr += 1
        last_match = None
        while temp_players > 1:
            round_matches = []
            for i in range(temp_players // 2):
                j = temp_players // 2 - 1 - i if temp_players // 2 > 1 else 0
                # Source uses (i, temp_players - 1 - i) at outer loop;
                # for the next layer we pair winners (layer[i], layer[N-1-i])
                # where N is the previous temp_players doubled.
                outer = temp_players * 2
                j_idx = outer - 1 - i
                node = self.add_node(
                    best_of=self._choose_best_of(temp_players),
                    loser_gets=temp_players,
                    label=self._label_for(temp_players, wr),
                    game=self._game_name(),
                )
                self._maybe_mark_streamed(node, temp_players, i)
                self.link_parent(node, layer[i], "W")
                self.link_parent(node, layer[j_idx], "W")
                layer[i] = node
                round_matches.append(node)
                last_match = node
            self.matches_by_round[round_matches[0].label] = round_matches
            temp_players //= 2
            wr += 1

        if last_match is not None:
            self.link_parent(self.victory_node, last_match, "W")
        else:
            # Two-player bracket: round-1 match IS the final.
            self.link_parent(self.victory_node, matches_to_call[0], "W")

        return matches_to_call

    def _choose_best_of(self, temp_players):
        return 5 if temp_players <= self.bo5_threshold else 3

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
        # Default game inherited from tournament preset config; subclasses or
        # presets may override. For now use a fixed default; presets set
        # node.game when needed.
        return getattr(self.tournament, "game", "rps")
```

## Preset registration

```python
# In axi/tournament_presets.py or a dedicated registration file in formats/
from axi.tournament_presets import register_preset
from axi.tournament_formats.single_elimination import SingleElimination


@register_preset("fast")
def _preset_fast(tournament):
    return [lambda t, players: SingleElimination(t, players, stream=False, bo5=8)], \
           "Single elimination."


@register_preset("se")
def _preset_se(tournament):
    return [lambda t, players: SingleElimination(t, players, stream=False, bo5=8)], \
           "Single elimination."
```

The `se` and `fast` source presets are byte-identical, so both register
the same factory.

## Files to add / modify

```
NEW  axi/tournament_formats/__init__.py    (empty, marks package)
NEW  axi/tournament_formats/single_elimination.py
MOD  axi/tournament_presets.py             (or new module that imports
                                            and registers; choose simpler)
```

No changes to Phase 1 modules.

## Test Plan

`tests/test_single_elimination.py`:

### Bracket construction (sizes 2, 4, 7, 8, 16)

1. **Size 2:** No padding. Single match labeled `WINNERS FINALS`.
   `victory_node` parent is that single match.
2. **Size 4:** No padding. 2 round-1 matches labeled `WINNERS SEMIS`,
   1 final labeled `WINNERS FINALS`. Bracket depth 2.
3. **Size 7:** Padded to 8. 1 bye in round 1. 4 round-1 matches
   `WINNERS QUARTERS`, 2 `SEMIS`, 1 `FINALS`. Bye player advances
   automatically.
4. **Size 8:** No padding. 4 quarters, 2 semis, 1 final.
5. **Size 16:** No padding. 8 round-1 `WINNERS ROUND 1`, 4 quarters,
   2 semis, 1 final.

### BO5 escalation

- `bo5=-1` (dynamic): rounds with temp_players ≤ 8 escalate to BO5.
  Verify rounds with > 8 players are BO3, rounds ≤ 8 are BO5.
- `bo5=4`: only rounds with ≤ 4 players escalate. Verify.
- `bo5=0`: every round is BO5 (since 0 < any temp_players means
  all rounds are ≤ 0 is false... wait, actually bo5_thresh = 0 means
  every match check `temp_players <= 0` is False so all BO3). Edge case
  worth testing.

### Stream marking

- `stream=False` (default): no node has `.streamed = True`.
- `stream=True`: matches with `temp_players ≤ 6` OR last of their round
  are flagged streamed.
- `stream=2`: only `temp_players ≤ 2` or last-of-round are streamed.

### Loser_gets placement tiers

- For a 16-player bracket: round-1 losers get tier 16, quarter losers get
  tier 8, semi losers get tier 4, finals loser gets tier 2.

### Bye handling

- Size 7 → 1 bye user added. Round 1 match containing the bye should
  auto-resolve via `MatchGraph.call_match`'s `is_bye()` check (already
  Phase 1 logic). Bye player advances to round 2 without launching a real
  match.

### Preset registration

- `apply_preset(tournament, "fast")` and `apply_preset(tournament, "se")`
  both work and set `phase_fns` to a SingleElimination factory.

## Resolved questions (no open items)

1. **__BYE__ user implementation:** `_ByeUser` class in
   `single_elimination.py` (Option B above). Keeps the format-specific
   sentinel out of `axi/axi_user.py`.
2. **Default game name:** Read from `tournament.game` if set, otherwise
   default to `"rps"`. Game configuration is a tournament-level concern,
   not format-level.
3. **`stream_thresh` default:** 6 when `stream=True`. Matches source
   `preset_classic` which uses `stream=6` literal.
4. **Subsequent-round pairing index:** Source uses
   `j = temp_players - 1 - i` at the OUTER loop but `temp_players` shifts.
   The correct pairing for layer-N → layer-(N+1) is: in the new round,
   pair `layer[i]` with `layer[outer - 1 - i]` where `outer` is the
   previous round's player count (which is `temp_players * 2` at the new
   loop level). This preserves standard single-elimination seeding.

## What's deferred

- Variations like "double seed split" or "snake seeding" — those are
  RoundRobin → DoubleElimination preset features in Phase 4.
- Match-thread creation / Discord rendering — Phase 14.
- Graphviz bracket image — Phase 15.
