# Tournament Integration: Conventions

Cross-cutting conventions for the 16-phase tournament integration work in
deck `mm5jyprhi9vnbeqt9bf`. All phase cards reference this document.

## Branch + commit

- **Branch:** `discord-refactor` (already checked out; do NOT switch).
- **Commit messages:** Imperative summary line, then optional bullet list:
  ```
  Add SingleElimination tournament format

  - axi/tournament_formats/single_elimination.py: SE bracket generation
  - tests/test_single_elimination.py: 12 tests across sizes 2/4/7/8/16
  ```
- **Push:** `git push origin discord-refactor`.
- **Do not commit:** caches (`__pycache__/`, `.pytest_cache/`), DB files
  (`axi.db`), env files (`.env`, `.bashrc`, etc.), IDE config (`.idea/`,
  `.vscode/`), bare-repo artifacts (`HEAD`, `objects/`, `refs/`, `hooks/`,
  `config`). Always stage explicitly by filename — do NOT use `git add -A`.
- **Pre-commit gate:** `uv run pytest` must pass. If any tests fail, fix
  before committing.

## Architecture

- **Pure layer:** All tournament code is pure Python — NO `discord` imports
  in `axi/match_node.py`, `axi/match_graph.py`, `axi/tournament.py`,
  `axi/tournament_formats/`, `axi/tournament_state.py`, `axi/tournament_presets.py`.
- **Effects pattern:** Pure functions return `list[Effect]` dataclasses
  (defined in `axi/effects.py`). The Discord adapter (`axi/handlers/discord_handler.py`)
  executes them via `execute_effects()`. Do not call Discord APIs directly
  from the pure layer.
- **Identity:** Use UUID strings (`uuid.uuid4().hex`) for `node_id`,
  `tournament_id`, `graph_id`. Do not use `id(obj)` for new identifiers.
- **Service objects:** Module-level singletons follow the
  `MatchState` / `LadderState` / `TournamentState` pattern. Each exposes a
  `reset()` method for test cleanup.
- **No cycles:** MatchNode holds `tournament_id` (str), not `tournament`
  (object). Lookups go through `tournament_state.state.tournaments`.

## Test setup

- **Location:** `tests/test_<feature>.py`. One file per significant
  feature area (e.g., `tests/test_tournament_core.py`,
  `tests/test_single_elimination.py`).
- **Reuse `tests/conftest.py`:** It mocks Discord, numpy, openskill,
  dotenv, pytimeparse at the `sys.modules` level. Adds `FakeUser`,
  `FakeLadder` doubles. Auto-resets module state between tests.
- **Run:** `uv run pytest tests/test_<feature>.py -v` for a single file;
  `uv run pytest` for the full suite.
- **Coverage targets per phase:**
  - Each public method has at least one positive + one negative test.
  - All effect dataclasses appear in at least one assertion.
  - Integration tests for cross-component flows (e.g., LaunchTournamentMatch
    → match_handler.launch_match → completion_callback → report_match_complete).
- **Test isolation:** Add `tournament_state.state.reset()` to autouse
  fixtures where new modules are touched.
- **Regressions:** After any change, run the full suite to confirm no
  regression. Current baseline: **183 passing tests** (as of Phase 1).

## Plan card protocol

Each `Plan Phase N` card:
1. Write a detailed design doc to `docs/phase-<N>-<name>-plan.md`.
2. Follow the structure of `docs/tournament-core-plan.md` (rev 2):
   - Scope
   - Components (with class signatures / method stubs)
   - Integration points
   - Files to add / modify
   - Test Plan section
   - Resolved + open questions
3. Resolve any open questions inline (don't leave them dangling).
4. Present the doc for explicit user approval BEFORE marking the card
   done. Plan/design cards require explicit approval per MinFlow conventions.

## Implement card protocol

Each `Implement Phase N` card:
1. Implement per the approved design doc.
2. Maintain the architectural conventions above (pure layer, effects,
   UUIDs, service objects).
3. Add minimal smoke test inline (`uv run python -c "from axi.X import Y"`)
   to confirm imports resolve.
4. Run full existing test suite to confirm no regressions.

## Test card protocol

Each `Test Phase N` card:
1. Add `tests/test_<feature>.py`.
2. Cover the items listed in the design doc's Test Plan section.
3. Use `conftest.py` fixtures.
4. Run via `uv run pytest tests/test_<feature>.py -v` — all pass.
5. Run full suite to verify no regressions.

## Commit card protocol

Each `Commit/push Phase N` card:
1. Verify `uv run pytest` passes (gate).
2. Stage only the files added/modified for the phase (no cache/db/env).
3. Commit with the message format above.
4. Push to `origin/discord-refactor`.
5. Verify the push succeeded.

## Source-of-truth references

- **Source (old tourney bot):** `/tmp/claude-1001/tourney-inspect/`
  (cloned from `git@github.com:px-pride/axi-tourney-old.git`).
- **Target (current engine):** `/home/pride/coding-projects/axi-game-engine/`.
- **Per-phase audit notes:** see the `notes` field of deck
  `mm5jyprhi9vnbeqt9bf` (full per-phase target status, dropped features,
  bugs found).
