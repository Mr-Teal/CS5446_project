# Clock and purification engineering ablation

This small serial experiment measures the sampled-I^2 Material prototype.
It does not establish strength, statistical speedup or a hard real-time limit.

## Reproduction

From the repository root:

```powershell
& .\pair_b\.venv\Scripts\python.exe -m pair_a_prep.clock_ablation --submission-reserve-fraction 0 --output pair_a_prep/results/clock_ablation_baseline.json
& .\pair_b\.venv\Scripts\python.exe -m pair_a_prep.clock_ablation
& .\pair_b\.venv\Scripts\python.exe -m pair_a_prep.presentation_materials
& .\pair_b\.venv\Scripts\python.exe -m pytest -q tests pair_a_prep/tests
```

The first two commands run sequentially. Do not run other experiment/test suites
at the same time if comparing these caller timings. JSON artifacts include raw
measurements, hashes of the code used, versions, configuration IDs, seeds and
budget settings. Wall-clock stopping is inherently nondeterministic: neither
output bytes, work counts nor trajectories must match on another run/machine.

## Matrix and controls

- Budgets: 20, 100, 500 ms; seeds: 17 and 29; two repeats per condition.
- Conditions: purification off/on, cold standard start and a warm kings fixture.
  Each clock matrix has 48 action measurements, four samples per table cell.
- Warm preparation uses an explicitly declared candidate history and an already
  computed saved blueprint. Preparation/restoring that input is outside the
  measured action. No real hidden referee state is supplied to search.
- Each matrix also plays 12 four-ply pawn-endgame matches (48 actions) with
  independent exact trackers, sample_size=3, max_candidates=2000.
- Material only; 64 possible CFR rounds, depth 1 to at most 3, node cap 512,
  evaluator cap 32. Growth gets at most 60% of the action budget.
- Condition order alternates across repeats. The no-reserve and reserve
  matrices are sequential small samples, not randomized benchmark blocks.
- Fixed-work controls use 12 rounds, clock stopping disabled, and the same
  saved inputs/seeds for each purification pair. Raw root policies must match;
  regression tests also verify identical raw continuation labels. This isolates
  the output transform; clock-stopped trajectories need not match.

Caller timing surrounds the whole act() call, including diagnostics, raw snapshot
conversion and output preparation. Internal elapsed diagnostics are retained
separately. Tracker updates remain outside both action timings. A fallback is
a legal uniform action with no label, not a successful completed search.

## Submission guard and explicit limits

The initial experiment exposed 1-3 ms overruns in warm 20/100 ms turns. The
integrated agent now defaults to a 10% action-budget reserve for finalization.
Before starting another CFR round it checks the remaining solve window against
the previous completed round (including gadget switching). A zero reserve
disables this additional prediction and reproduces the original loop policy.
Both choices are included in config_id. The optional evaluation factory accepts
`purify=true/false` and `submission_reserve_fraction=0/0.1` for subgame mode.

This is an estimate, not preemption. A first or unexpectedly slow CFR round,
an in-flight evaluator call, validation/cloning, OS scheduling or finalization
can still exceed the budget. Tests deliberately demonstrate such an overrun,
as well as a reserve preventing another known expensive round. No hard-time
guarantee is inferred even if the recorded reserved run has no overruns.

Fallback diagnostics now include actual attempted evaluator calls and a typed
stop marker; report rows preserve the human-readable budget/capacity reason.
Resource-limited preparation must not look like zero work or invent labels.

## Reading the evidence

The recorded controlled runs produced:

| Guard | Turn overruns / 48 | Turn fallbacks / 48 | Live overruns / 48 | Live fallbacks / 48 |
|---|---:|---:|---:|---:|
| No reserve or round prediction | 16 | 8 | 13 | 14 |
| 10% reserve and previous-round estimate | 0 | 8 | 0 | 11 |

All 12 live games in each condition were capped with null outcomes; no tracker
capacity failure occurred. The reserved live fallbacks comprised six tree-build
clock failures, three evaluator-call-limit failures and two growth-deadline
failures. All cold-standard 20 ms turns fell back after one evaluator call:
their short return time is not successful search latency. Four fixed-work
purification pairs had identical raw policies. The complete shared/Pair A suite
passed 483 tests. These results are a small run on one machine, not a probability
bound on future overruns or a strength comparison.

Use `summary` for per-fixture/budget/condition sample counts, median/max caller
times, overrun counts, fallbacks, rounds, actual evaluator calls and L1 distance
between raw and played policies. `fixed_work_pairs` records the controlled
policy comparison. `live_summary` counts actual action overruns/fallbacks and
keeps capped outcomes null. `slide5-clock-backup.svg` renders the current table
and the no-reserve/reserve totals directly from the two JSON files.

These are implementation observations: time savings can trade against solver
work, and purification changes the played distribution rather than proving it
is stronger. Live fallbacks include evaluator-call limits as well as clock
failures. The tracker/weighting discussion and #37's rule
decision are unresolved. Longer games and engine-based strength comparisons
need those agreements and separately frozen configurations.
