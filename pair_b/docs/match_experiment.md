# Fixed-planner evaluator experiment

This is an exploratory experiment connecting leaf-value approximation to full-game decisions.
It holds `OnePlyBot`, tracker settings, explicit rules, public starts and a fixed opponent constant
while swapping material, depth-1 Stockfish, linear correction and Network 1. It is not an
Obscuro reproduction, a whole-belief-network experiment or an equal-time comparison.

## Run

From the repository root, with the existing Pair B dependencies installed and Stockfish 19 on PATH:

```sh
PYTHONPATH=pair_b/src:. python -m pairb.match_experiment \
  --config pair_b/experiments/pilot.json --out /tmp/fow-pilot-001
```

PowerShell, from the repository root:

```powershell
$env:PYTHONPATH = "pair_b/src;."
python -m pairb.match_experiment --config pair_b/experiments/pilot.json --out "$env:TEMP/fow-pilot-001"
```

Use a new output directory every time. Edit a copy of the JSON to set an absolute `stockfish_path`
if necessary. Checkpoint paths are relative to the repository root (absolute paths also work).
The existing checkpoints are used unchanged; there is no training or final-test-set selection.
The config includes two seeds, four candidates against depth-1 Stockfish, and both candidate
colours: 16 games, capped at 80 plies each. This is a development pilot, not a powered study.
CPU Network 1 uses one PyTorch thread and deterministic algorithms. No automatic model skipping
or rule-adapter fallback occurs. Use `rules: "teal"` explicitly once that adapter is available.

Each seed/start/candidate combination produces two games with the candidate changing colour.
The public starting position stays the same. The shared loop seeds each colour with seed + colour
index, keeping the colour-specific random streams consistent across candidates. Opponent engines
and trackers are fresh for every game; engines use one thread, 16 MiB hash and clear search state
on each evaluator call. Hardware, package versions, engine binary hash and checkpoint hashes are
recorded. Exact numerical reproducibility across hardware/engine builds is not guaranteed.

All initial FENs are **public starts** known to both trackers, not secret midgame boards. `null`
means the standard start. A FEN cannot carry earlier repetition or observation history; do not
use private midgame test positions as starts while claiming the original information structure.

## Outputs

- `manifest.json`: full configuration, Git revision/status, Python source hashes, checkpoint and
  engine hashes, environment, planner and seed conventions. An uncommitted implementation is
  identified by its source hashes; retain the checkout/diff with the results. Source hash keys
  are repository-relative paths with forward slashes on every platform, including Windows.
- `games.jsonl`: flushed after each attempt; candidate colour, pair ID, winner, candidate score,
  termination, move records, search-node counts, act timing and budget flags, tracker timing,
  rebuild/capping/exactness diagnostics, and errors with partial event logs.
- `summary.json`: refreshed after every game; W/D/L over completed games, failures, ply-limit
  draws and complete/incomplete pairs. `paired_score` averages the two colour scores in each
  complete pair, then averages pairs. It is null if none complete. Failures are never draws;
  if a game fails, its pair is excluded from paired score, while completed-game W/D/L remains
  visible. Excluding failed pairs can bias results: resolve failures before making strength claims.

The command exits nonzero if any game fails. A killed process can leave its final game unrecorded;
completed games already flushed remain available. There is no resume/append mode. The saved
schedule can be reconstructed from the manifest; compare expected vs recorded games after an
external interruption.

## Interpretation and next gate

The budget is diagnostic only: `OnePlyBot` ignores it, and the shared loop records overruns without
interrupting agents. Act timing excludes belief maintenance; tracker events and whole-game wall
time are recorded separately. Initialization and process startup are included only in wall time.
This does not establish equal-time performance. Priority 2 requires a defined enforceable budget.

All candidates use one-ply weighted-hypothesis action selection and the same hypothesis cap.
Their actual positions, particle counts and evaluator costs can differ as games diverge, so this
is a fixed-planner protocol, not exact equality of nodes or CPU work. Same-position action-quality
experiments are a separate control. Depth-1 versus itself is a symmetry/sanity comparator.

Before expanding: inspect failures, tracker rebuilds, termination reasons, cap-draw rate and timing.
Choose the final game/seed budget after this throughput pilot, reserve untouched evaluation seeds,
and freeze configurations before final evaluation. Report paired uncertainty at the game-pair level
for the final study. Do not interpret an eight-ply smoke test or a few completed pairs as playing
strength. Belief-context learning requires a separate successor-belief integration and target study.

## Rules integration regression

The runner tests exercise both `standin` and `teal` explicitly, including colour pairing,
candidate score perspective, repeatability, rule draws versus ply caps, failure accounting
and portable manifest paths. The `teal` cases are explicitly skipped when Pair A's adapter
is absent; a combined-checkout validation should run them without skips.

```powershell
python -m pytest pair_b\tests\test_match_experiment.py pair_b\tests\test_rules.py `
  pair_b\tests\test_bot.py pair_b\tests\test_tracker.py tests\test_match_loop.py `
  pair_a_prep\tests\test_rules_adapter.py pair_a_prep\tests\test_observations.py -q
```
