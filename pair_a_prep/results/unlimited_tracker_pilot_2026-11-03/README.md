# Native 16-second tracker pilot without a logical memory cap

Runtime `0426f73` adds only explicit `tracker_memory_mb=none` parsing and its
regression, based on main `1492781`. The previous default remains 64 MiB;
zero still means a zero-memory budget. Time, exact-support and failure rules
are unchanged. DLL built with locked Windows Pixi/x86_64 GCC. No main or
teammate branch was modified. **The candidate still fails a complete pair.**

## Fixed input and prefix checks

Two 12-ply prefix attempts (seeds 17/18, alternating colours) completed with
no failures. The seed18 Black private prefix through ply9 matches the prior
committed difficult-input fixture exactly. The newly captured ply11 input is
from that same seeded trajectory, after the earlier memory-budget failure.
Actual full-history support, not a truncated posterior, is retained.

| Target update | Fresh-process trials | Wall time range | Histories after completion |
|---|---:|---|---:|
| Black ply9 | 3 | 1.046?1.139 s | 197,428 |
| Black ply11 | 3 | 7.590?7.656 s | 4,270,301 |

Each trial reconstructs the exact prefix outside the target timer, then uses
the actual HistoryTrackerFactory/BudgetedExactTracker. All six updates finish
with exact support and uniform returned weights; each target's three serialized
belief signatures agree. Ply9 also matches the old reference signature.
The prefix match process peaks at about 687.27 MiB RSS. This is a new
configuration's evidence, not a retrospective correction of the old pilots.

## 200-ply-cap real-engine pilot

The same search settings are retained: SF19 depth1, sample size3, subgame
node/call caps 5000/128, eight solver rounds, one-sided growth and purification;
the opponent is fixed-depth-1 PCFR, not ZS21 or a neural evaluator. Search
clock stopping is disabled. Both sides use native exact tracking, no history
population cap, one 16-second call per private update, no logical memory cap
and zero resumes. No pruning or partial-support substitution is used.

- Seed17: A as White wins by king capture at ply39.
- Seed18: Black tracking fails explicitly at ply13 on total time, after about
  16.072 seconds in one cooperative call. The graph is incomplete; full
  population is unknown. Its partial graph records 25,594,846 represented
  histories and 364,174 states; those are not a complete posterior count.
- Requested two attempts: one terminal game, one failed attempt, zero capped
  games. All **108 tracker update records**, including the failure, survive.
- Runner process peak RSS: **1066.85 MiB**; OS-reported peak private commit:
  **1051.28 MiB**. Stockfish child processes are excluded. Samples are taken
  every 100 ms; Windows peak counters provide the process high-water marks.
- Capture/monitoring adds overhead. Private observations are logged before the
  tracker call; no referee state is injected. These are readiness measurements,
  not an isolated speed benchmark. The 200-ply cap was never reached.

The seed17 terminal game repeats an earlier pilot seed and is not independent
strength evidence. There is no complete colour pair. The runner's conditional
100% score must not be reported as playing strength. Failed attempts still
omit partial agent-action records; tracker and captured observation logs are
preserved. The API-based reproduction driver writes a summary even for failed
attempts; inspect `games_failed`, rather than relying on its exit status.

The 16-second setting is **per tracker update**, not a whole-action deadline.
Both trackers are updated and agent search is timed separately. The measured
16.072-second failure also illustrates cooperative overshoot. Conceptual
`accounted_bytes` still records allocation charges when no cap is enforced;
it is not retained memory or measured RSS. Unlimited logical memory is not a
promise of bounded process memory.

## Validation and reproduction

58 focused budget, factory, native resume and runner tests pass, zero skipped.
The new test verifies that `none` really passes Python None, the default stays
64, and a real exact update completes. No full test-suite rerun is claimed.

From the checkout containing this change, with Pixi and the pinned SF19 on PATH:

```powershell
$env:PYTHONPATH = (Get-Location).Path + ';' + (Join-Path (Get-Location) 'pair_b/src')
pixi run --locked --manifest-path zs21_runtime/pixi.toml -e darkchess python -m pair_a_prep.build_belief_kernel
New-Item -ItemType Directory -Force pair_a_prep/local_runs/unlimited-20261103
Copy-Item pair_a_prep/results/unlimited_tracker_pilot_2026-11-03/prefix.ini pair_a_prep/local_runs/unlimited-20261103/prefix.ini
Copy-Item pair_a_prep/results/unlimited_tracker_pilot_2026-11-03/pilot.ini pair_a_prep/local_runs/unlimited-20261103/pilot.ini
pixi run --locked --manifest-path zs21_runtime/pixi.toml -e darkchess python pair_a_prep/results/unlimited_tracker_pilot_2026-11-03/run_match.py prefix
foreach ($targetPly in 9,11) { foreach ($trialIndex in 0,1,2) { pixi run --locked --manifest-path zs21_runtime/pixi.toml -e darkchess python pair_a_prep/results/unlimited_tracker_pilot_2026-11-03/replay_fixed.py $targetPly $trialIndex } }
pixi run --locked --manifest-path zs21_runtime/pixi.toml -e darkchess python pair_a_prep/results/unlimited_tracker_pilot_2026-11-03/run_match.py pilot
```

Edit the copied local configs for the actual engine path; retain or explicitly
update the binary hash/name. Use fresh output directories. The raw driver
scripts are preserved from execution; they do not overwrite the runner output.
Their own capture files should likewise be used only in a fresh local folder.
`summary.json` holds measurements, fixed trials, source hashes and native build
identity. `evidence.zip` holds sanitized observations, provenance, game/update
logs, memory samples and test XML. Paths are sanitized; the archive is not a
byte-identical copy of local outputs. `artifact-sha256.json` hashes committed
published bytes. Measurement source hashes use their stated LF convention;
later evidence-only additions are not measured runtime changes.

## Decision needed

Removing the cap fixes the two measured resource failures but merely moves the
next failure to ply13. Do not declare 16 seconds sufficient for standard-start
exact full games. Owners must choose a reviewed optimization/approximation,
a restricted experiment protocol, or a larger independently justified budget.
No automatic 30/60-second escalation or formal batch was run here.
