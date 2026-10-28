# Regression tests

This folder holds focused checks for individual review issues. Add each future
issue under its own heading with the original feedback, response, and test command.

## Review issue 1: Reset engine state between games (see #17)

**Original feedback** (copied from `pair_c/TODO`):

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

**Original feedback** (copied from `pair_c/TODO`):

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

**Original feedback** (copied from `pair_c/TODO`):

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
