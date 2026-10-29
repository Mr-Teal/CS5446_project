# Regression tests

This folder holds focused checks for individual review issues. Add each future
issue under its own heading with the original feedback, response, and test command.

## Review issue 1: Reset engine state between games (see #17)

**Original feedback**:

> The agents/scorers are reused across games with new_game_each_call=False, but OnePlyBot.reset() does not clear Stockfish state. In a two-game probe, neither scorer's new_game() was called.
>
> Please clear every scorer's engine before each game, including Stockfish inside network evaluators, while retaining the hash within a game. This matches the proposed policy in #17.

**Rebuttal / response:**

1. Added `reset_game()` to the factory interface and updated the runner to call each player's factory hook before every game.
2. Users can clear Stockfish or other game-specific state in `reset_game()`. The example in `pair_c/agent_factories.py` demonstrates resetting both direct Stockfish scorers and Stockfish inside network evaluators.
3. Users remain responsible for managing any other state across games, such as hashes and caches.

`test_reset_game.py` runs two short games through the real runner and game loop.
It checks that both factories' `reset_game()` callbacks run before each
game, including between the first game's end and the second game's start.

Run from the repository root: `python -m pytest pair_c/regression_tests/test_reset_game.py -v`.

## Review issue 2: Return a failure exit status

**Original feedback**:

> With an agent that raises, both games were recorded as failed, but the CLI still exited with status 0.
>
> Please retain the logs and summary, then return a nonzero exit status when any game fails so batch runs can detect it.

**Rebuttal / response:**

1. The CLI now checks `games_failed` after the runner saves its results and the CLI prints the complete summary and output directory. Any failed game causes exit status `1`; a run with all games completed retains exit status `0`.
2. Per-game exceptions still allow later games to run. `games.jsonl`, `summary.json`, and the configuration copy are retained, and calling `run()` directly still returns the summary.
3. The terminal summary now includes the failed-game count. When games fail, stderr explains the failure and where the logs and summary were saved.

`test_failure_exit_status.py` launches the real CLI in a subprocess with lightweight
agents and the real two-game loop. It covers two cases: both games succeed, or
the first game fails and the second succeeds. Each case checks the process exit
status, both game records, saved summary counts, and terminal summary. The failure
case also checks the agent's recorded error, confirming that the second game still
runs after the first fails. No Stockfish process, checkpoint, or torch is required.

Run from the repository root:

```powershell
python -m pytest pair_c/regression_tests/test_failure_exit_status.py -v
```

## Review issue 3: Allow each player to supply its tracker

**Original feedback**:

> The runner always constructs ParticleTracker, whose hypotheses lack the complete candidate_moves paths required by Pair A's search. Using our current agent reproduced:
>
> ValueError: hypothesis needs a complete candidate_moves path
>
> Could we support a tracker factory or explicit tracker choice per player? Pair A's exact tracker can support bounded integration tests; a scalable history-preserving tracker remains separate work.

**Rebuttal / response:**

1. Each player can select its own `tracker_factory`; trackers are created per game and follow the player when colors alternate.
2. `tracker_factories.py` provides a Pair B example. Each factory handles its own tracker settings.
3. Pair A can supply its exact tracker. A scalable history-preserving tracker remains separate work.

`test_tracker_factory.py` contains one normal-flow test: two players use ParticleTracker and a test path tracker for two games with alternating colors. It checks tracker outputs, complete candidate paths and fresh instances. Actual Pair A integration is not verified.

Run from the repository root:

```powershell
python -m pytest pair_c/regression_tests/test_tracker_factory.py -v
```

## Follow-up: outcome accounting and depth metadata

`test_outcome_accounting.py` checks terminal-only W/D/L denominators while
retaining successful capped attempts in timing. It also runs the real CLI
with two one-ply caps: zero scored games, zero terminal draws, unavailable
outcome rates and successful exit after writing both records.

`test_leaf_depth_metadata.py` checks all five built-in scorer IDs reject
inconsistent depth metadata before loading resources, and that a valid D11
setting reaches the constructor unchanged. No real engine/checkpoint is used.

Run all focused regression checks from the repository root:

```powershell
python -m pytest -q pair_c/regression_tests
```

## Review issue 4: Save evaluation provenance

**Original feedback** (copied from `pair_c/TODO`):

> Source/checkpoint/engine provenance remains necessary before using this runner for broader experiments. #17's formal Pair B runner and #34's merge gates are unchanged.

**Rebuttal / response:**

Added `provenance.json` to each evaluation's output directory. It records:

1. Runtime environment: Python, PyTorch and PyTorch-build CUDA versions, automatically detected CPU model, and evaluation start time in UTC.
2. Each player's effective inference device, backend and corresponding GPU model. CPU players have no GPU model; macOS MPS is recorded separately from CUDA. Unknown hardware is accompanied by a detection note.
3. The original configuration's absolute path and each player's checkpoint path.
4. Each player's Stockfish executable path and the running engine's UCI name and author, including engines nested inside network scorers. Players without an engine have `null` entries.
5. A grouped `sha256` section containing the configuration hash, separate checkpoint and Stockfish executable hashes for both players, and a nested `source_files` mapping. The latter dynamically discovers all Git-tracked files across the repository at runtime and hashes their current working-tree bytes, without file-type filtering or an aggregate hash. Untracked files are excluded; tracked files deleted locally but not yet staged are recorded as `null`.

`test_provenance.py` constructs an INI with Player A on CPU and Player B on GPU.
It covers CUDA and macOS MPS configurations using simulated torch/hardware
responses, lightweight legal-move agents and nested engine metadata. Temporary
checkpoint and engine files are hashed without loading models or starting an
engine. The real runner, game loop and provenance writer generate the output.

The test checks the saved field structure and actual values: exact INI bytes,
configuration/checkpoint/engine hashes, declared checkpoint paths, UCI identity,
CPU/CUDA/MPS device metadata and software versions. The factory double explicitly
declares checkpoint metadata to simulate a loader. Source discovery is stubbed
in this output test; actual GPU inference, checkpoint loading and engine execution
are not exercised.

Run from the repository root:

```powershell
python -m pytest pair_c/regression_tests/test_provenance.py -v
```

## PR51 follow-up: actual loaded resources

`test_provenance_resources.py` covers unused/missing configured checkpoints,
explicit loaded-checkpoint declarations, direct/scorer/evaluator engine discovery,
CPU evaluator subclasses, relative PATH resolution, and dynamic tracked-file
hash changes/deletions. Checkpoint declarations are supplied by loaders, never
inferred from an INI or a hard-coded factory name. Unknown declarations produce
an explicit detection note. Git-index requirements and raw working-tree hash
semantics are unchanged.

Run with `python -m pytest pair_c/regression_tests -q`.
