# Phase 1: Tournament Core — Detailed Design (rev 2)

Plan card: `mpe7khwpau7bnqkjxs8` in deck `mm5jyprhi9vnbeqt9bf`.

This phase introduces tournament orchestration as a layer above the existing
single-match `match_handler`. It is pure Python (no Discord imports) and
returns effect dataclasses that the Discord adapter executes.

**Revisions in rev 2:**
1. UUID-based identity (`node_id: str`, `tournament_id: str`, `graph_id: str`) instead of `id()` — survives serialization, immune to GC reuse.
2. Removed `MatchNode.match` field — the pure layer never holds a reference to a concrete `Match` object. The mapping lives only in `TournamentState.nodes_to_matches[node_id]`.
3. Added explicit completion-callback contract: `match_handler.launch_match(..., completion_callback=None)`. Tournament registers a callback when launching.
4. Replaced object cycles with ID-only references. `MatchNode` and `MatchGraph` hold `tournament_id`, not `tournament`. Lookup via `TournamentState`.
5. Added a Test Plan section.
6. Default-answered the 4 open questions inline.

## Scope

Phase 1 ships the **foundation only** — abstractions, data structures, and
integration glue. Concrete tournament formats (Single Elim, Double Elim,
Round Robin, Ladder Elim, Friendlies) follow in Phases 2–6 and depend on
this layer.

## Resolutions to the 4 prior open questions

1. **`MatchNode.match` field type** → REMOVED. Mapping lives in `TournamentState.nodes_to_matches[node_id]`. MatchNode stays pure data.
2. **`Tournament.scope` representation** → string for Phase 1; promoted to a richer type by Phase 12 (scope/role system).
3. **`first_ban` determinism** → keep `tournament.rng.randrange(2)` (reproducible from seed). Seed is set per Tournament via `setrng` command later.
4. **Effect granularity for bracket announcements** → `AnnounceBracket` (adapter decides format). Phase 1 emits the semantic event; rendering decisions live in the adapter / Phase 15 viz.

## Components

### 1. `axi/util.py` (add constants)

```python
# Match lifecycle
MATCH_STATUS_ASLEEP    = 0  # bracket slot exists; players may be unresolved
MATCH_STATUS_CALLED    = 1  # players resolved + match launched; checkin window
MATCH_STATUS_ACTIVE    = 2  # both players checked in / game underway
MATCH_STATUS_COMPLETED = 3  # score finalized
```

(`MATCH_STATUS_CALLED` already exists. Add the other three.)

### 2. `axi/match_node.py` (new)

A bracket slot. Pure data + transition methods that return effect lists.
Holds NO reference to the underlying `Match` object — that mapping lives
in `TournamentState`.

```python
import uuid
from dataclasses import dataclass, field

@dataclass
class MatchNode:
    tournament_id: str        # ID-only reference; look up via TournamentState
    graph_id: str             # ID of containing MatchGraph
    players: list = field(default_factory=list)  # list[AxiUser]; may be empty
    label: str = ""           # "WINNERS QUARTERS", "GRAND FINALS", etc.
    game: str = "rps"         # name from registry
    mode: str = "versus"
    best_of: int = 3          # -1 = dynamic
    loser_gets: int = None    # placement tier for loser
    checkin_timer: int = 360  # seconds

    # State
    score: list = field(default_factory=lambda: [0, 0])
    checkins: set = field(default_factory=set)
    reports: dict = field(default_factory=dict)  # {player: score_str}
    status: int = MATCH_STATUS_ASLEEP
    streamed: bool = False
    round_number: int = 0
    first_ban: int = 0        # set by Tournament constructor via rng
    checkin_deadline: float = None

    # Graph (uses node_id refs to avoid object cycles when serializing)
    node_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    parents: dict = field(default_factory=dict)   # {parent_node_id: "W" | "L"}
    children: dict = field(default_factory=dict)  # {child_node_id: "W" | "L"}

    # Helpers — pure
    def asleep(self):    return self.status == MATCH_STATUS_ASLEEP
    def awake(self):     return self.status in (MATCH_STATUS_CALLED, MATCH_STATUS_ACTIVE)
    def completed(self): return self.status == MATCH_STATUS_COMPLETED
    def first_to(self):  return (self.best_of + 1) // 2
    def winner(self):    return self.players[0] if self.score[0] > self.score[1] else self.players[1]
    def loser(self):     return self.players[1] if self.score[0] > self.score[1] else self.players[0]
    def is_sweep(self):  return self.completed() and min(self.score) == 0
    def is_bye(self):    return any(p.is_bye() for p in self.players)

# Functions operate on MatchNodes via the MatchGraph that owns them.
# Transitions live in MatchGraph methods (call_match, advance, report_score,
# undo_match) — keeps MatchNode purely data, easier to serialize/test.
```

### 3. `axi/match_graph.py` (new)

Abstract base for all bracket formats. Subclasses (SingleElimination, etc.)
implement `generate_bracket()`. The graph owns its nodes by `node_id`.

```python
from abc import ABC, abstractmethod
import uuid

class MatchGraph(ABC):
    def __init__(self, tournament_id, players, stream=False):
        self.tournament_id = tournament_id
        self.graph_id = uuid.uuid4().hex
        self.players = players
        self.stream = stream
        # Bookkeeping (populated in create_data_structures)
        self.nodes_by_id = {}  # node_id -> MatchNode
        # ...

    @abstractmethod
    def generate_bracket(self) -> list:
        """Return the initial set of MatchNodes to call."""

    def begin(self) -> list:
        """Build bracket, call initial matches. Returns effects."""
        self.create_data_structures()
        initial = self.generate_bracket()
        effects = []
        stream_candidates = []
        if self.stream:
            self.schedule_stream()
        for n in initial:
            (stream_candidates if n.streamed else effects).extend(self.call_match(n))
        if not self.stream_match and stream_candidates:
            effects += self.call_match_for_stream(stream_candidates)
        return effects

    def create_data_structures(self):
        self.seed_by_player = {p: i for i, p in enumerate(self.players)}
        self.matches_by_round = {}
        self.matches_by_pair = {p: {q: [] for q in self.players} for p in self.players}
        self.matches_by_player = {p: [] for p in self.players}
        self.current_match_by_player = {p: None for p in self.players}
        self.placements_dict = {p: -1 for p in self.players}
        self.active_matches = []
        self.called_matches = []
        self.non_matches = {}        # node_id -> (player, reason)
        self.stream_history = []
        self.stream_planned = []
        self.stream_candidates = []
        self.stream_match = None     # node_id or None
        self.victory_node = self.add_node(label="VICTORY")

    def add_node(self, **kwargs) -> 'MatchNode':
        node = MatchNode(tournament_id=self.tournament_id, graph_id=self.graph_id, **kwargs)
        self.nodes_by_id[node.node_id] = node
        return node

    def link_parent(self, child, parent, flag):
        """Set parent→child W/L edge."""
        child.parents[parent.node_id] = flag
        parent.children[child.node_id] = flag

    def ancestors(self, node, include_completed=False) -> set:
        """Recursive set of parent nodes."""
        result = set()
        for parent_id in node.parents:
            parent = self.nodes_by_id[parent_id]
            if parent.completed() and not include_completed:
                continue
            result.add(parent)
            result |= self.ancestors(parent, include_completed)
        return result

    # Lifecycle transitions (all pure — return effect lists)
    def call_match(self, node) -> list:
        """ASLEEP → CALLED. Handle bye/drop/dq auto-resolution.
        Real matches emit LaunchTournamentMatch effect."""
        if node.is_bye():
            return self.auto_resolve_non_match(node, reason="bye")
        # check drop/dq via Tournament lookup
        node.status = MATCH_STATUS_CALLED
        node.checkin_deadline = time.time() + node.checkin_timer
        self.called_matches.append(node)
        return [LaunchTournamentMatch(
            node_id=node.node_id,
            tournament_id=self.tournament_id,
            graph_id=self.graph_id,
            players=[p.uid.id for p in node.players],
            game=node.game,
            mode=node.mode,
            best_of=node.best_of,
            label=node.label,
            stream=node.streamed,
        )]

    def receive_checkin(self, node, user) -> list:
        """Add to checkins; if both checked in → ACTIVE."""

    def report_score(self, node, reporter, score_str) -> list:
        """Validate, store in reports, confirm if dual-report or admin."""

    def complete_match(self, node) -> list:
        """ACTIVE → COMPLETED. Compute winner, propagate to children.
        Returns effects including recursive call_match for newly-ready children."""

    def undo_match(self, node) -> list:
        """COMPLETED → ASLEEP, cascade through children."""

    def undo_drop_user(self, user) -> list: ...
    def undo_dq_user(self, user) -> list: ...

    # Stream
    def schedule_stream(self) -> list: ...
    def score_stream_match(self, node) -> tuple: ...
    def call_match_for_stream(self, candidates) -> list: ...

    # Placements
    def get_placements(self) -> list: ...

    # Helpers
    def auto_resolve_non_match(self, node, reason) -> list: ...
```

### 4. `axi/tournament.py` (new)

Top-level orchestrator. Holds a sequence of phases (each a `MatchGraph`
instance), drop/dq state, RNG, player colors, and the preset registry.

```python
import uuid
from collections import defaultdict

class Tournament:
    def __init__(self, title, scope, series=None, seed=None):
        self.tournament_id = uuid.uuid4().hex
        self.title = title
        self.scope = scope           # str for Phase 1; richer type by Phase 12
        self.series = series
        self.rng = random.Random(seed)
        self.players = []
        self.placements = []                # list[(rank, AxiUser)]
        self.phase_fns = []                  # list[Callable[[tournament, players], MatchGraph]]
        self.phases = []                     # list[MatchGraph]
        self.phase_id = -1
        self.started = False
        self.frozen = False
        self.manual_phases = False
        self.drop_dict = defaultdict(list)
        self.dq_dict = defaultdict(list)
        self.onedrop_dict = defaultdict(list)
        self.streamer = None
        self.format = ""                     # human-readable preset description
        self.player_colors = {}              # HSV color per player

    # Roster
    def add_players(self, players): ...
    def remove_players(self, players): ...

    # Lifecycle — all return effect lists
    def begin(self) -> list: ...
    def advance_phase(self) -> list: ...
    def initialize_phase(self) -> list: ...
    def check_end_of_phase(self) -> list: ...
    def completed(self) -> bool: ...
    def winner(self): ...

    # Drops / DQs
    def drop_user(self, user) -> list: ...
    def dq_user(self, user) -> list: ...
    def is_dropped(self, user) -> bool: ...
    def is_dq(self, user) -> bool: ...

    # Undo
    def undo_match(self, p0, p1) -> list: ...
    def undo_drop_user(self, user) -> list: ...
    def undo_dq_user(self, user) -> list: ...
    def undo_phase(self) -> list: ...

    # Score reporting (delegates to current phase)
    def report_score(self, reporter, p0, p1, score) -> list: ...

    # Match completion callback (called by adapter when a launched match closes)
    def report_match_complete(self, node_id, winner_user_id, score) -> list:
        """Wired in from match_handler via completion_callback."""

    # Stream
    def set_streamer(self, user): ...

    # Color assignment (HSV space)
    def assign_player_colors(self): ...

    # Presets
    def preset(self, name) -> list:
        """Apply a preset; sets self.phase_fns + self.format."""

    # Visualization (Phase 15 hook)
    def visualize(self) -> str: ...
```

### 5. `axi/tournament_presets.py` (new, registry)

```python
PRESETS = {}  # name -> (phase_fns_factory, format_description)

def register_preset(name):
    def decorator(fn):
        PRESETS[name] = fn
        return fn
    return decorator
```

Phases 2–6 register their presets here.

### 6. `axi/tournament_state.py` (new, service object)

```python
class TournamentState:
    def __init__(self):
        # (guild_id, scope) -> tournament_id
        self.scope_to_tournament = {}
        # tournament_id -> Tournament instance
        self.tournaments = {}
        # node_id -> id(Match) [from match_handler]; reverse: id(Match) -> node_id
        self.nodes_to_matches = {}
        self.matches_to_nodes = {}

    def get_tournament(self, tournament_id):
        return self.tournaments[tournament_id]

    def reset(self):
        """Test-only — clears all state."""

state = TournamentState()
```

The `nodes_to_matches` map is the integration glue. Match identity uses
the existing `id(match)` key from `match_handler.state.matches_by_id` for
Phase 1 (consistent with current pattern). Phase 10 may swap to UUID
match IDs.

### 7. `axi/effects.py` (add 5 dataclasses)

```python
@dataclass
class LaunchTournamentMatch:
    """Tournament asks the adapter to launch a match for a bracket node.
    The adapter calls match_handler.launch_match(...,
    completion_callback=on_match_complete) and stores the resulting Match in
    TournamentState.nodes_to_matches[node_id]."""
    node_id: str
    tournament_id: str
    graph_id: str
    players: list             # list[user_id: int]
    game: str
    mode: str
    best_of: int
    label: str
    stream: bool

@dataclass
class AnnounceBracket:
    """Emit a bracket announcement (text + optional image) to a channel.
    Adapter decides formatting (text-only vs Graphviz PNG)."""
    guild_id: int
    channel_name: str
    text: str
    image_path: str = None

@dataclass
class CallMatchForStream:
    """Designate a specific match as the next streamed match."""
    node_id: str

@dataclass
class ArchiveTournamentMatch:
    """Tournament asks the adapter to archive the match's thread/DM artifacts."""
    node_id: str

@dataclass
class UpdateTournamentUI:
    """Refresh the tournament's status / placements display."""
    tournament_id: str
```

## Integration with `match_handler`

### Change required: optional completion callback

Modify `match_handler.launch_match` to accept an optional callback:

```python
def launch_match(
    name, players, mode="versus", ladder=None, best_of=1,
    checkin_timer=None, label="UNRANKED",
    completion_callback=None,  # NEW: Callable[[match, winner, score], list[Effect]]
):
    ...
    if match:
        state.matches_by_id[id(match)] = match
        if completion_callback is not None:
            state.completion_callbacks[id(match)] = completion_callback
    return match
```

And in `close_match`:

```python
def close_match(match):
    effects = []
    # ...existing close logic...
    callback = state.completion_callbacks.pop(id(match), None)
    if callback is not None:
        effects += callback(match, match.winner(), match.score)
    return effects
```

This is a small, additive change to `match_handler` — no breaking changes to
existing call sites that don't pass a callback.

### Adapter flow

The Discord adapter executes `LaunchTournamentMatch`:

```python
def _execute_launch_tournament_match(effect):
    players = [user_handler.get_user_by_id(uid) for uid in effect.players]
    tournament = tournament_state.state.tournaments[effect.tournament_id]
    graph = next(g for g in tournament.phases if g.graph_id == effect.graph_id)
    node = graph.nodes_by_id[effect.node_id]

    def on_complete(match, winner, score):
        # Map winner user to AxiUser, dispatch to tournament
        return tournament.report_match_complete(
            node_id=effect.node_id,
            winner_user_id=winner.uid.id,
            score=score,
        )

    match = match_handler.launch_match(
        effect.game, players, mode=effect.mode,
        best_of=effect.best_of, checkin_timer=node.checkin_timer,
        label=effect.label, completion_callback=on_complete,
    )
    tournament_state.state.nodes_to_matches[effect.node_id] = id(match)
    tournament_state.state.matches_to_nodes[id(match)] = effect.node_id

    # Execute standard match-launch UX effects
    return match_handler.prepare_match_ux(match, effect.game, ...)
```

The callback is a closure that captures `effect.node_id`. When
`match_handler.close_match` runs, it invokes the callback, which routes
the result back to the tournament's `report_match_complete` method.

This avoids the leaky abstraction of MatchNode holding a Match reference —
the only object held by Tournament state is the `node_id → match_id`
mapping, which is pure data.

## Files to add / modify

```
NEW  axi/match_node.py
NEW  axi/match_graph.py
NEW  axi/tournament.py
NEW  axi/tournament_presets.py
NEW  axi/tournament_state.py
MOD  axi/util.py             # add MATCH_STATUS_ASLEEP/ACTIVE/COMPLETED
MOD  axi/effects.py          # add 5 dataclasses
MOD  axi/handlers/match_handler.py  # add optional completion_callback parameter
```

Three small additions to `match_handler` are the only changes outside
the new tournament files; no other existing files modified in Phase 1.

## Test Plan

Phase 1 tests live in `tests/test_tournament_core.py` (new) and reuse the
existing `conftest.py` mock infrastructure.

### Unit tests (per class)

**MatchNode (purely-data tests):**
- Default field values
- `asleep/awake/completed/is_sweep/is_bye` predicates per status
- `first_to(bo3/5/7)`, `winner/loser` from score
- Parent/child dicts hold node_id strings (not object refs)

**MatchGraph (transition tests with stub generate_bracket):**
- `create_data_structures` initializes all bookkeeping dicts correctly
- `add_node` adds to `nodes_by_id` and returns the node
- `link_parent` sets both sides of the edge
- `ancestors` returns correct recursive set (including the include_completed flag behavior)
- `call_match`:
  - Returns `LaunchTournamentMatch` effect for a real match
  - Returns auto-resolution effects for a bye match
  - Auto-resolves a drop/dq player without launching
- `complete_match`: status transition, child node propagation, recursive call for newly-ready children
- `undo_match`: cascades through children, restores prior state
- `report_score`: validates X-Y format, BO5 limits, dual-report confirmation
- `auto_resolve_non_match`: handles bye/drop/dq with placement updates

**Tournament:**
- `add_players` / `remove_players` updates roster
- `assign_player_colors` distributes HSV colors
- `drop_user` / `dq_user` updates dicts + propagates to current phase
- `is_dropped` / `is_dq` true after action
- `preset` (with a registered stub preset) sets phase_fns + format
- `begin` initializes first phase (effects returned correctly)
- `advance_phase` increments phase_id and initializes next phase
- `report_match_complete` (callback path) updates the correct node
- `undo_match` / `undo_phase` revert state

**TournamentState:**
- `nodes_to_matches` / `matches_to_nodes` round-trip lookups
- `reset()` clears all dicts (test-only helper)

### Bracket-format tests (per-phase, not Phase 1)

Phases 2–6 each add their format-specific tests building on this base.

### Integration tests

`tests/test_tournament_integration.py` (new):
- Build a Tournament with a 4-player single-bracket stub.
- Simulate `LaunchTournamentMatch` effect → call `match_handler.launch_match`
  with completion callback → mock match completion → verify callback fires
  → verify Tournament state updates correctly → verify next match
  launched.
- Run a full mini-tournament through completion. Assert final placements
  match expected.

### Undo tests

`tests/test_tournament_undo.py` (new):
- Build a 4-player bracket, simulate through 2 rounds.
- `undo_match` last match → verify status reverts, children clear, players returned.
- `undo_phase` → verify phase rolls back fully.
- Replayability: after undo, re-applying same results should reach same state.

### Test infrastructure additions

Extend `tests/conftest.py`:
- `make_tournament(player_count=4, seed=42)` fixture — pre-built Tournament with N FakeUsers, fixed seed.
- `simulate_effect_loop(effects)` — executes effects against TournamentState + a fake match_handler, returns further effects (allows multi-step simulations).
- `tournament_state_clean()` autouse fixture — calls `tournament_state.state.reset()` between tests.

### Coverage targets

- All public methods on MatchNode/MatchGraph/Tournament have at least one positive + one negative test.
- All 5 new effect dataclasses appear in at least one assertion.
- Integration test covers the LaunchTournamentMatch → callback → report_match_complete loop end-to-end.

### Tests deferred to later phases

- Bracket format correctness (Phases 2–6 own their format tests).
- Persistence/restoration (Phase 10 owns checkpoint tests).
- Discord adapter execution (Phase 14 owns adapter tests).
- Visualization output (Phase 15 owns viz tests).

## What's deferred

- Concrete bracket generation algorithms — Phases 2–6.
- `save_checkpoint` / restoration — Phase 10 (stubs in Phase 1 are no-op).
- Preset implementations — Phases 2–6 register their presets via `tournament_presets.register_preset(name)`.
- Discord wiring of effects — Phase 14.
- Graphviz `visualize()` — Phase 15 (stub here).

## Open questions

(None remaining — the 4 prior open questions are resolved above.)
