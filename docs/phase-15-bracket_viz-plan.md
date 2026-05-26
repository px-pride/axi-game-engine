# Phase 15: Bracket visualization

Plan card: deck `mm5jyprhi9vnbeqt9bf`, Phase 15.

Adds Graphviz-based bracket visualization — emits DOT source from a
`MatchGraph` DAG, renders to PNG via the `graphviz` Python package
(which shells out to the `dot` binary), and posts the PNG as a
Discord embed image. Wires to `/bracket` and `/current` slash
commands (added as stubs in Phase 14).

Source implementation: `match_graph.py:353-545` (200-line `visualize`
method). Target uses the same HSV → RGB player-color assignment
(already implemented in `axi/tournament.py:assign_player_colors`).

## Scope

- Add `visualize(tournament)` function to a new
  `axi/handlers/bracket_viz.py` module (pure-layer, no Discord
  imports). Returns DOT source (str) + an optional rendered PNG
  path.
- Add `MatchGraph.visualize(tournament)` method that delegates to
  the bracket_viz module — keeps the API on the graph for callsite
  convenience.
- Add `DotRenderUpload` effect dataclass — adapter accepts DOT
  source, calls `graphviz.Source(dot_str).render(...)` to produce a
  PNG, then uploads to the target channel as a Discord embed.
- Wire `/bracket` and `/current` slash commands (Phase 14 stubs) to
  emit `DotRenderUpload` effects.
- Add `graphviz` Python package to `pyproject.toml` runtime
  dependencies.

## Files

| File | Change |
|---|---|
| `axi/handlers/bracket_viz.py` (NEW) | `dot_source(graph, tournament)` builder. |
| `axi/match_graph.py` | Implement `visualize(tournament)` → delegates to bracket_viz. |
| `axi/tournament.py` | Update `visualize()` → walks current_phase → delegates to bracket_viz. |
| `axi/effects.py` | Add `DotRenderUpload` dataclass. |
| `axi/handlers/discord_handler.py` | `/bracket` + `/current` emit `DotRenderUpload`. Adapter renders + uploads. |
| `pyproject.toml` | Add `graphviz` to dependencies. |
| `tests/test_bracket_viz.py` (NEW) | DOT structure tests across formats (SE/DE/RR/LadderElim). |

## `axi/handlers/bracket_viz.py` API

```python
"""Bracket visualization handler (Phase 15).

Pure-layer module — emits Graphviz DOT source from a MatchGraph DAG.
The Discord adapter consumes the DOT via DotRenderUpload effect and
renders it to PNG via the `graphviz` Python package.
"""


def id2dot(idx):
    """Encode an int id as an alphabetic node name (A, B, …, Z, AA,
    AB, …). Source uses this to avoid Graphviz reserved tokens."""


def dot_source(graph, tournament):
    """Build a DOT-format string for `graph` (a MatchGraph instance).

    Walks `graph.victory_node.ancestors(include_completed=True)`,
    projects winners/losers for unfinished matches via
    seed_by_player + W/L parent flags, groups nodes by label cluster
    (LOSERS / INVISIBLE / WINNERS / GRAND / DEADASS), ranks them
    same-rank in the source DAG, and writes per-node HTML-table
    labels with player-color fills (from `tournament.player_colors`).

    Returns the DOT source string. Does NOT render to PNG (that's
    the adapter's job).
    """
```

## DotRenderUpload effect

```python
@dataclass
class DotRenderUpload:
    """Render a Graphviz DOT source to PNG and post to Discord.

    The adapter writes the DOT to a temp file, runs
    graphviz.Source(dot_str).render(format='png'), then uploads the
    resulting PNG to the target channel.
    """
    guild_id: int
    channel_name: str
    dot_source: str            # the DOT source string
    title: str = None          # optional message text above the image
```

## Adapter dispatch (in `execute_effects`)

```python
elif isinstance(effect, DotRenderUpload):
    guild = bot.get_guild(effect.guild_id)
    if not guild:
        continue
    channel = get(guild.channels, name=effect.channel_name)
    if not channel:
        continue
    import graphviz, tempfile, os
    try:
        with tempfile.NamedTemporaryFile(suffix='.gv', delete=False) as f:
            f.write(effect.dot_source.encode('utf-8'))
            dot_path = f.name
        src = graphviz.Source(effect.dot_source)
        src.format = 'png'
        out_path = src.render(filename=dot_path, cleanup=True)
        await send_long(channel, effect.title or "", file=out_path)
        try:
            os.unlink(out_path)
        except Exception:
            pass
    except Exception as e:
        await send_long(channel, f"Couldn't render bracket: {e}")
```

## Slash command wiring (Phase 14 stubs → real)

`/bracket` and `/current` in `discord_handler.py` currently respond
with a "see #tourney-pinned" text-only placeholder. Phase 15
replaces them with effect-emitting versions:

```python
@bot.tree.command(name="bracket",
                  description="Show the current bracket as a Graphviz PNG.")
async def bracket(ctx):
    scope = _scope_from_ctx(ctx)
    t = tournament_handler._get_tournament(scope)
    if t is None:
        await ctx.response.send_message("No active tournament here.")
        return
    phase = t.current_phase()
    if phase is None:
        await ctx.response.send_message("No phase started yet.")
        return
    from axi.handlers import bracket_viz
    dot = bracket_viz.dot_source(phase, t)
    effects = [DotRenderUpload(
        guild_id=ctx.guild.id,
        channel_name=ctx.channel.name,
        dot_source=dot,
        title=f"**{t.title}** — bracket",
    )]
    await ctx.response.send_message("Rendering bracket…")
    await execute_effects(effects)


@bot.tree.command(name="current",
                  description="Alias for /bracket.")
async def current(ctx):
    await bracket.callback(ctx)
```

(The existing `/current` text-status handler from Phase 14 is renamed
`/currenttext` or merged — see Decision G.)

## DOT structure (key invariants)

The DOT structure matches source `match_graph.visualize`:

1. `digraph bracket { rankdir="LR" bgcolor="#222222" … }` header.
2. **Clusters** by node-label prefix: `cluster_LOSERS`, `cluster_INVISIBLE`,
   `cluster_WINNERS`, `cluster_GRAND`, `cluster_DEADASS`. Source order
   matters for left-to-right visual layout.
3. **Nodes** are HTML-table labels (`shape=plaintext`) with:
   - Header row: `<b>{node_id}: {node.label}</b>`
   - Per-player rows: name + score, with `bgcolor` = the player's
     RGB hex from `tournament.player_colors`.
   - Score color: gold for winner, silver for loser, white if active,
     pink/red if asleep.
4. **Edges**: `parent -> child` with `penwidth=4 color="lightgray"`
   for "W" links. "L" links are commented out in source — we
   follow.
5. **Rank groups**: nodes at the same `rank()` (= depth from
   victory) are pinned to the same `rank=same` subgraph for vertical
   alignment.

Source's `id2pydot` encoding (A, B, … Z, AA, AB, …) is kept for
visual consistency.

## Test plan

`tests/test_bracket_viz.py`:

1. **`TestDotIdEncoding`** — `id2dot(0) == "A"`, `id2dot(25) == "Z"`,
   `id2dot(26) == "AA"`, `id2dot(51) == "AZ"`, `id2dot(52) == "BA"`.

2. **`TestDotSourceMinimal`** — 2-player single-elim → DOT contains
   "digraph bracket", 1 node header for FINALS, both player names
   in the table, edges from FINALS to victory_node.

3. **`TestDotSourceFourPlayerSE`** — 4-player SE → DOT has 3 nodes
   (2 semis + 1 finals), 3 edges to victory_node downstream, both
   semi players colored.

4. **`TestDotSourceClusterLabels`** — DoubleElim with WINNERS/LOSERS
   labels → DOT contains `cluster_WINNERS` and `cluster_LOSERS`
   subgraphs.

5. **`TestDotSourceRoundRobin`** — RoundRobin phase → DOT renders
   each pool's matches without crashing (pools are just labels;
   DAG has no parents).

6. **`TestDotSourceLadderElim`** — LadderElim → DOT handles the
   victory_node + danger labels.

7. **`TestDotSourceColoringByPlayer`** — verify each player's row
   `bgcolor` in the DOT matches `tournament.player_colors[player]`.

8. **`TestDotSourceCompletedMatchShowsScore`** — completed match
   with score [2, 1] shows "2" and "1" cells in the table.

9. **`TestDotSourceUnknownPlayer`** — DOT generation handles missing
   `player_colors[user]` gracefully (defaults to gray).

10. **`TestDotRenderUploadEffect`** — instantiate `DotRenderUpload`
    with fields, verify shape.

11. **`TestVisualizeIntegration`** — `tournament.visualize()` returns
    a DOT string (or DotRenderUpload effect) when phase is active.

12. **`TestVisualizeNoPhase`** — `tournament.visualize()` before
    `begin()` returns None / empty.

PNG rendering itself is NOT tested in unit tests — that depends on
the `dot` binary being installed, which is a runtime concern. Adapter
integration is exercised via static analysis (effect dataclass
fields) only.

## Major decisions

### A. Dependency: `graphviz` Python package

Source uses both `graphviz` and `pydot`. `pydot` is only used for the
`id2pydot` naming convention — we inline that logic and avoid the
pydot dep. `graphviz` package is added to runtime dependencies.

Note: `graphviz` (Python package) is just a thin wrapper over the
`dot` command-line binary. Production deployments need `dot`
installed (`apt install graphviz`). For tests, the conftest mock
shouldn't be needed since we only invoke the rendering in the
adapter, not the pure layer.

### B. Pure-layer DOT generation, adapter-layer render

Source mixes DOT generation + render + filesystem I/O in one
`visualize()` method. Target splits: pure layer
(`bracket_viz.dot_source(graph, tournament)`) returns the string,
adapter handles `graphviz.Source(...).render(...)` + tempfile +
upload.

This enables testing the DOT structure without requiring `dot` to be
installed, and decouples the bracket-data layout (deterministic)
from the rendering (which may fail for environment reasons).

### C. HSV color reuse — already implemented in target

`Tournament.assign_player_colors` (axi/tournament.py:217) already
produces an HSV-based RGB tuple per player. Phase 15 just reads
`tournament.player_colors[player]` as the per-row bgcolor.

The target's HSV uses a simpler 1D hue scan (one full color rotation
across N players); source uses a 2D saturation+hue scan
(`num_saturations = sqrt(N/4)`). We KEEP target's simpler approach
— still produces distinguishable colors for up to ~16 players,
which covers typical bracket sizes.

### D. `seed_by_player` lookup — needed for projected winners

Source's projection logic uses `self.seed_by_player[player]` to
order projected players. Target's MatchGraph doesn't have a
`seed_by_player` field. We add it as an optional dict, populated by
`Tournament.begin()` if available; if missing, projection falls
back to `tournament.players.index(player)` (the player's index in
the roster).

### E. Skip the "ad_overlay" PIL composite

Source has commented-out code to overlay the bracket on a branded
background image using PIL. Not portable, not needed — skip
entirely.

### F. `cluster_INVISIBLE` for layout-only nodes

Source uses `INVISIBLE` cluster for spacer nodes that don't render
but keep layout stable. We KEEP this — it's important for DE finals
alignment.

### G. `/current` aliases `/bracket`

Phase 14 added `/current` as a text-status command listing active +
called matches. Phase 15 changes its semantics: `/current` is now
the alias for `/bracket` (image), matching source semantics. The
text-status flow is moved to a new `/active` command (or merged
with `/matches`).

### H. No automatic re-render on phase advance

The current bracket is on-demand via `/bracket`; we don't
auto-emit a PNG when the phase advances (which would spam the
channel). Admins can `/bracket` whenever they want a fresh image.

### I. PNG output size

Graphviz default. No custom DPI or size — let the layout breathe.
If brackets grow too large, that's a deferred concern.

## Resolved questions

1. **`include_completed` flag on `ancestors()`?** Yes — source uses
   `include_completed=True` so completed matches are shown with
   scores. Target's `ancestors()` already supports this kwarg
   (axi/match_graph.py:114).

2. **What if no phase exists yet?** `/bracket` responds with "No
   phase started yet" — no DOT emitted.

3. **What if the graph has no nodes (e.g. empty Ladder)?** DOT
   generates an empty `digraph bracket { }` block — graphviz
   renders an empty image. Tolerable; user sees "no matches yet".

4. **Where does `seed_by_player` come from?** Tournament sets it
   from the roster order at `begin()` time. MatchGraph reads via
   `self.tournament.seed_by_player`.

5. **What about LadderElim's dynamic node creation?** Each call to
   `visualize` walks the current victory_node ancestors; if new
   matches are added between calls, the next `/bracket` shows them.

6. **What about node "score color" semantics in source?** Gold for
   winner row, silver for loser row, white for active match,
   pink/red for asleep. We follow.

7. **How are byes/DQs handled?** Source's `visualize` skips
   `is_bye()` / `is_dq()` nodes entirely. We follow.

## What's deferred

- **Image branding overlay** (logo, custom backgrounds, watermarks)
  — source has commented-out PIL composite. Deferred to a future
  "media polish" pass.
- **SVG output** — Graphviz supports it. Discord embeds prefer PNG.
  Defer SVG until needed.
- **Auto-render on phase advance** — admins can `/bracket` manually.
- **Bracket caching** — re-rendering on every `/bracket` is cheap
  enough for typical bracket sizes (<32 players).
- **Per-game customization** (e.g. wand emoji decorations on player
  rows) — defer to game-specific overrides if needed.
- **Streamer / observer highlighting** — source has special
  `streamed` styling (purple fill). We KEEP this from source.
