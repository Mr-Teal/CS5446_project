# Stockfish evaluation handoff

`SearchFactory` now supports `leaf_evaluator=stockfish` using Pair B's existing
`StockfishEvaluator`. Material remains the default with `leaf_depth=0`.
This is a bounded integration of the Obscuro-inspired sampled subgame agent,
not a complete reproduction or a strength result.

## Run from the repository root

Use an installed engine; do not commit its executable. Choose fresh output
directories for each run. In PowerShell:

```powershell
$enginePath = 'C:\path\to\stockfish.exe'
.\pair_b\.venv\Scripts\python.exe -m pair_a_prep.stockfish_handoff --stockfish-path $enginePath --output pair_a_prep/local_runs/sf-handoff-01
.\pair_b\.venv\Scripts\python.exe pair_c/run_evaluation.py pair_a_prep/local_runs/sf-handoff-01/pinned-config.ini
```

The first command runs the real Pair C runner with lifecycle tracing and
creates `handoff.json`, `agent-events.jsonl`, and a production `pinned-config.ini`.
The second runs the normal factory without the trace wrapper. For the
standard initial board, add
`--config pair_a_prep/data/pair_c_stockfish_standard_smoke.ini` to the first
command and choose another output directory. The default uses the pawn fixture.
Both configurations play two colour-swapped four-ply attempts.

## Identity and lifecycle

The templates require UCI name `Stockfish 19`. To test another version, edit
that explicit expectation in a local config and report the version difference.
The generated production config pins the actual executable SHA256, UCI name
and local absolute path. A different machine must supply its own path and
validate its own binary. The public reference omits machine-specific paths.

Supported settings are `stockfish_path`, `stockfish_expected_name`,
`stockfish_sha256`, `leaf_depth`, `stockfish_hash_mb`,
`stockfish_new_game_each_call`, and `stockfish_call_timeout_s`. The examples
use depth 1, one thread, Hash 16 MB, per-call resets and a two-second call
watchdog. Depth is distinct from the agent's search depth. The watchdog is
not a hard whole-action deadline; the smoke clocks are diagnostic.

Factories own one evaluator, reject a second load, reset it between games,
and close it at cleanup, including initialization failures. Pair C supplies
the per-game callbacks. Direct callers must call `factory.reset_game()`.
The agent's config identity includes the engine hash and evaluation options;
moving the same binary does not change that identity. Material identities
retain their existing format. Engine failures are recorded rather than
silently replaced with fabricated leaf values.

The evaluator is available as `agent.evaluator`, with
`provenance_executable_path` and `handoff_identity`. This factory loads no
neural checkpoint. A provenance exporter should inspect the actual evaluator
and avoid treating unrelated checkpoint settings as loaded model identity.

## Evidence and limits

`results/stockfish_handoff_reference.json` records two real-engine smoke
runs, each with eight actions, no failures, no fallbacks, four per-game
factory reset callbacks, and both engines closed. A separate production
runner repetition also completed. All attempts hit their diagnostic ply cap:
there are zero scored games and win/score rates are unavailable.
The trace wrapper adds overhead, so its timing is not a latency benchmark.

The paper specification uses Stockfish 14 depth 1 MultiPV; these runs use
Stockfish 19. Ordinary legal children use MultiPV, while FoW-only actions
can need additional child-board evaluations. True history-dependent terminal
outcomes remain the responsibility of Pair A's rules layer.

Formal long-game readiness is still false: the exact tracker can exceed its
population cap, sampled synchronous knowledge restriction and cross-turn
reuse are approximations, and ancestor gifts are audit-only. Projected
training labels remain disabled pending the root/weight agreement. This
handoff enables evaluation integration; it does not resolve those gates.

Before planning a formal batch, use the [acceptance gates and proposed protocol](formal_evaluation_readiness.md). The smoke caps and opponents are not a formal strength configuration.
