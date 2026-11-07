# BeliefTracker

`pair_a_prep.belief_tracker.BeliefTracker` implements the existing shared
`BeliefTracker` and `BeliefTrackerDraft` protocols. The input is one player's
private observation after **every ply**, plus that player's action when they
just moved. No referee board or hidden opponent action enters inference.

The 2026-10-31 implementation is based on main
`1db35d68638d52353381d13de20addfea58a4d99`. The previous exact implementation
is retained in `tests/reference_belief_tracker.py` as an independent regression
oracle. The ZS21 agent's separate position tracker and its DLL are unchanged.

## Windows runtime setup

The existing `zs21_runtime/pixi.toml` supplies the pinned Python packages and
optional C++ compiler. From the repository root in PowerShell:

```powershell
$trackerRepo = (Get-Location).Path
$env:PYTHONPATH = "$trackerRepo;$trackerRepo\pair_b\src"
Set-Location zs21_runtime
```

The shell commands below assume this working directory. The Pair B source path
is used by existing shared test fixtures; no neural training dependencies are
required. Projects with an existing `darkchess` Pixi environment can also run
the modules from a directory where the repository root is importable.

## Exact usage and compatibility

```python
from pair_a_prep.belief_tracker import BeliefTracker

tracker = BeliefTracker(sample_size=256)
tracker.reset(player="white", seed=17)
belief = tracker.update(initial_white_observation)
belief = tracker.update(after_white_move, own_move="e2e4")
belief = tracker.update(after_black_move)
```

`sample_size` limits **returned hypotheses only**. All consistent histories
remain available internally. Default time and memory budgets and the legacy
`max_candidates` are `None`; there is no implicit particle/state limit.
`sample_size=None` returns every history, which can itself be impractical even
when the internal compressed graph is small. Use a finite output sample in games.

The existing `fow_shared.evaluation.play_game` runner continues to work in exact
mode. It measures `agent.act`, not external tracker work; measure tracking
separately or explicitly include it in a match's overall turn deadline.

`initial_fen` must be a publicly agreed start, configured in both trackers and
the referee. A constructor FEN survives resets; a reset-time override applies
only to that game. Reset starts fresh repetition history, never hidden history
before a supplied midgame FEN. Wrong players, skipped/duplicate plies, wrong
own-action timing and updates after termination raise `ValueError`.

## What is compressed, and what is preserved

The tracker stores current boards once per piece placement, side, clean castling
rights, **raw** en-passant field, promoted-piece markers and move counters. Each
board points to a directed acyclic graph of hypothetical histories. An incoming
edge stores `(parent, move)` and represents every retained path of that parent.
Arbitrary-size integer counts preserve path multiplicity without enumerating
all paths. Different paths reaching the same board remain different hypotheses.

This is not ZS21's one-representative-per-position approximation. Full paths and
their probabilities can be recovered from the graph. Sampling a uniform integer
rank among all represented paths gives a uniform feasible-history sample without
replacement. FENs, full UCI paths and the original chained SHA-256 `history_id`
are materialized only for returned samples. The same seed/backend/private stream
is reproducible; samples need not match the old implementation's enumeration order.

Threefold repetition is checked **per path**, with the shared FoW-effective EP
position identity and the exact reversible-move window. A graph filter retains
the appropriate subset of paths when terminal or nonterminal feedback rules
histories in or out. A deterministic 1024-bit membership prefilter avoids graph
traversal when the target cannot occur. Hash collisions only cause extra exact
work; they never remove a feasible path or create a false repetition.

The fifty-move clock, king capture, no-legal-moves draw, visibility, capture
notifications, all legal moves and any explicitly revealed clock are checked.
Rule precedence and visibility agree with `RulesAdapter` and `fow_shared.values`.
Matching includes terminal observations, not just positions needing an action.

`Belief.population_size` counts histories, not distinct boards. `weighting="uniform"`
means equal weight per feasible history (or per member of its uniform sample),
not a Bayesian posterior under a uniform-move or learned opponent policy.
`tracker.state_count` separately counts stored current board/counter states.

## Optional native acceleration

```powershell
pixi run --locked -e darkchess python -m pair_a_prep.build_belief_kernel
```

The build uses the active C++ compiler and writes ignored files in
`pair_a_prep/_belief_build/`. Its manifest records the compiler, source hashes
and DLL hash. `backend="auto"` uses a matching build when available and otherwise
uses Python. `backend="native"` requires that build; `backend="python"` selects
the independent Python transition implementation. The default remains portable
without a compiler. The optional native build has been exercised on Windows.

`belief_kernel.cpp` reuses the existing ZS21 bitboard move/visibility primitives,
**not** its candidate-merging or draw approximation. Raw EP is restored for exact
FEN export. Terminal views and unsupported/promoted-board cases use the Python
path. The history graph, repetition filtering and output contract are shared
between the two backends. Native/Python/reference differential tests cover this
boundary; rebuilding the ZS21 DLL is not required.

## Time and memory budgets

Budget use is opt-in:

```python
tracker = BeliefTracker(sample_size=128, time_budget_ms=500, memory_budget_mb=256)
tracker.reset("white", 17)
result = tracker.update_budgeted(view, own_move=own_move)
if result.stopped_by is not None:
    # Optional: provide another budget for incomplete expansion OR output.
    result = tracker.resume(time_budget_ms=1000, memory_budget_mb=512)
if result.status == "complete":
    use_current_belief(result.belief)
else:
    # Caller policy: accept a labelled partial result, resume, or stop.
    handle_partial_or_empty(result)
```

Per-call non-`None` budgets override constructor settings. Zero is a valid
budget. `update()` still returns a shared `Belief`; its metadata is available in
`last_update`. If no current hypothesis is available, `update()` raises
`BeliefBudgetError` containing the same `TrackerUpdate` result. It never returns
a stale-ply belief or fabricates a hidden board.

| Result field | Meaning |
| --- | --- |
| `belief` | Valid current-ply hypotheses, or `None` |
| `status` | `complete`, `partial`, or `no_candidate` |
| `stopped_by` | `time`, `memory`, or `None` |
| `support_complete` | All histories consistent with the full private stream remain represented |
| `expansion_complete` | This update finished expanding its supplied parents |
| `generated_valid_count`, `retained_count` | Number of represented valid paths, not an extrapolated population |
| `state_count` | Stored current board/counter nodes |
| `attempted_transitions` | Cumulative processed board transitions, including rejected ones |
| `elapsed_ms` | This call's elapsed time, including output materialization |
| `accounted_bytes` | Retained-allocation estimate plus the latest returned output; not process RSS. A full base inventory exists only when `memory_inventory_count=1` |
| `memory_inventory_count` | Full inventories for this observation: zero without memory accounting, at most one across all resumes |
| `memory_inventory_ms` | Cumulative full-inventory time for this observation, already included in update/resume timing |
| `temporary_peak_bytes` | Largest estimated repetition-filter scratch allocation; released between filter calls, not added permanently to retained storage |

`resume()` continues the same pending observation. It does not duplicate already
processed branches. If every branch is eventually processed, completeness is
restored provided the incoming support was exact.

Expansion completion and output completion are separate. A finished graph can
report `support_complete=True` and `expansion_complete=True` while output hits a
time/memory limit: `status="partial"`, `stopped_by="time"` or `"memory"`, and
`weighting="uniform_over_returned_histories"`. The exact population remains
known, but the returned prefix is not a uniform sample of that full population.
Since the PR #59 output-continuation correction, this result remains resumable.
With more resources, `resume()` reuses the graph and re-materializes the requested
sample from the saved pre-update RNG state. Final histories, weights and later
sampling agree with an uninterrupted update. It does not cache partially built
output: repeated small slices can repeat the same prefix; one call needs enough
budget to produce the requested sample. The documented cooperative granularity
still applies. A completed output clears the continuation.

If a **new** observation follows an accepted partial Belief from a finished
graph, skipping unfinished output preserves exact support. If expansion itself
is unfinished, advancing discards unexpanded alternatives and `support_complete`
stays false on future turns. Every remaining path is still consistent with every
observation; finishing output never undoes earlier pruning or lost branches.

Output materialization can also be interrupted after graph expansion finishes.
In that case `support_complete` and `expansion_complete` can both be true while
`status` is `partial`. `resume()` regenerates the output from the saved RNG state,
so a completed sample and subsequent sampling agree with an uninterrupted update.
Advancing directly from an output-only interruption does not discard graph
support. Check `status == "complete"` before claiming a completed uniform sample.

For incomplete support, `Belief.population_size=None` and
`weighting="uniform_over_returned_histories"` avoid claiming a uniform posterior
over the unknown complete information set. Time-limited expansion can favor
earlier branches; its partial result is not an unbiased sample of unseen branches.

If no current-ply Belief has been returned, resume before advancing, even when
the graph already contains valid histories. The accepted observation is unchanged;
`TrackerUpdate` describes the pending graph. An
exhaustively inconsistent observation from exact support raises `ValueError`;
an empty successor set after earlier pruning is not proof of global inconsistency.
There is no automatic true-state injection or random-action fallback. Recovery
can reset at the public start and replay the caller's complete private stream
with larger budgets; it must not reset from a referee's current FEN.

These are **cooperative** budgets. Checks occur between transitions, during exact
repetition filtering and during output generation. One native parent expansion
and short result finalization can overshoot a wall-clock budget. Memory accounting
covers retained/pending graphs, temporary expansion and output reserves; Python
allocator fragmentation, interpreter memory and RSS are separate. A smaller
budget cannot retroactively free an already larger accepted state. Hard operating
system deadlines/process-memory limits require an external worker supervisor and
are not claimed here. `storage_stats()` measures reachable Python allocations
for diagnostics; do not confuse that with total process memory.

The first finite memory budget on an observation inventories its retained and
pending DAG once, counting boards and path nodes by identity and their fields
structurally, without revisiting every shared scalar. `storage_stats()` remains
a separate, slower object-by-object diagnostic for checking the estimates.
Later `resume()` calls reuse the ledger, including when
the limit changes. A new observation gets a fresh inventory so unreachable old
branches do not accumulate indefinitely. Reset and pruning discard the pending
ledger. Unbounded updates avoid the structural-accounting work; enabling a
finite limit on a later resume inventories everything built so far.

New boards, path nodes and incoming edges are charged from their Python object
structure, with allowances for dictionary/list growth and large counters. The
stack-free DAG does not allocate a separate ply-sized draw map per board.
Repetition-filter memo/recursion storage is temporary; newly retained filtered
path nodes are charged separately. The recursive visitor releases its memo and
closure on both completion and interruption, without waiting for cyclic garbage
collection. Retry work and regenerated output do not
accumulate as permanently retained objects. Both a previous partial output and
its replacement are covered while generating the replacement. These estimates
still overcount some shared scalars and are not byte-exact allocator bounds.
The budget's numeric meaning differs from the earlier cumulative per-visit
charges; comparisons must pin the implementation and report RSS separately.

For opt-in end-to-end diagnostics, `python -m
pair_a_prep.benchmark_tracker_matches --help` traces the actual Pair C runner.
It preserves private inputs, attempted decisions and applied referee actions
even on failure. `--whole-turn-ms` measures from referee handoff through agent
return, including both serial tracker updates and logging, and gives the agent
only the remaining allowance. It rejects late returns cooperatively; it does not
forcefully interrupt native code or change the shared runner's default clock.

The legacy `max_candidates` still raises `BeliefCapacityError` atomically; it is
not silently converted into truncation. Exact input/capacity failures preserve
the prior accepted state and RNG.

## Pair C evaluation policy

`HistoryTrackerFactory` preserves its historical `tracker_policy=exact` default
and 2,000-history capacity error. This differs from the standalone constructor's
uncapped default. `max_candidates=none` explicitly disables that count limit.

For cooperative, exact-or-fail evaluation, set these options in **both** player
sections, keeping their public initial FEN consistent with the referee:

```ini
tracker_factory = pair_a_prep.evaluation_factories:HistoryTrackerFactory
tracker_policy = budgeted-exact
sample_size = 3
max_candidates = none
tracker_backend = auto
tracker_slice_ms = 250
tracker_total_ms = 5000
tracker_memory_mb = 64
tracker_max_resumes = 16
```

Each private observation gets one total allowance, including expansion, output
and all resumes. At most 16 resumes follow the initial call. Time interruptions,
including output-only interruptions, may resume; memory exhaustion, incomplete
support, the total-time limit or exhausted retries fail the attempt explicitly.
No partial belief is submitted, no histories are pruned, and no hidden referee
state is used for recovery. A new attempt gets fresh trackers. Limits remain
cooperative, and logical memory is not process RSS. Zero slice/memory values are
valid explicit exhaustion probes; the total-time allowance must be positive.

The factory defaults for this opt-in policy are 100 ms slices, 2,000 ms total,
64 MiB logical memory and 16 resumes. Budget fields under `tracker_policy=exact`
raise an error instead of being silently ignored. `tracker_backend` selects
`auto`, `python` or `native` through the normal tracker backend contract.

The [Pair C pilot](../../pair_c/configs/budgeted_exact_pilot.ini) is a readiness
probe, not an agreed formal match protocol. It can fail if complete support
cannot be produced within these resources. Choose fresh outputs and configure
the actual Stockfish executable before running it.

Pair C records each update in `tracker_updates.jsonl` and embeds the same rows
in its game record, including failed updates. These records distinguish returned
sample size, known population, support completeness, tracker work, retry count,
elapsed time and exhaustion reason. Tracker timing includes all resumes and is
reported separately from `agent.act`; the runner's existing agent over-budget
flag is not a combined turn deadline. Failed attempts can still omit partial
agent records, so the aggregate recorded agent-plus-tracker total is not a
complete wall-clock measurement for a failed game.

## Explicit approximation

`tracker.prune(max_histories)` uniformly selects at most that many represented
full histories, preserves their valid paths and draw semantics, and discards the
others and any pending branches. It rebuilds shared prefixes from these selected
hypothetical paths and marks support incomplete. It is never called implicitly.
This bounds retained **histories**, not future expansion work. Its selection is
uniform over represented support only; pruning can remove the actual history.
No fixed sample size guarantees a small information loss in every position.
If the represented count is already at or below the requested limit, the call
leaves the tracker unchanged, including any pending update.

## Verification and full-game measurements

```powershell
pixi run --locked -e darkchess python -m pytest -q ../pair_a_prep/tests/test_belief_tracker.py ../pair_a_prep/tests/test_belief_graph.py
pixi run --locked -e darkchess python -m pair_a_prep.benchmark_belief_tracker --input PATH_TO_GAME_LOGS --output NEW_RESULT_DIRECTORY --games 0 1 2 3 4 5 6 7 8 9 --backend native --isolated
```

The benchmark replays complete existing games, regenerates both private streams
with the shared referee, and feeds each tracker only its stream and own moves.
The true path is used exclusively by an external oracle to verify it remains
in the exact graph. No time/memory/internal-state cap or pruning is used. A finite
output sample of 16 avoids enumerating all returned histories without dropping
internal support. Each game runs in a fresh process, sequentially.

Per-update JSONL records contain represented histories, stored states, graph
nodes/edges, update time, reachable Python bytes and process memory. `updating`
markers make interrupted runs visible. A run is complete only after both trackers
have accepted the actual terminal observation. Historical pilots and incomplete
runs must be kept separate from complete-game frequency tables. State-size
frequencies are empirical frequencies in this selected game corpus, not a
universal probability distribution for FoW chess.

Executed verification on 2026-10-31: **890 tests passed**, and all 10 preselected
complete games (633 plies, 1,286 private updates) finished with exact support and
the true-history membership audit passing at every step. Overall update median
was 5.78 ms, P95 1,658.30 ms, and maximum 117.59 s; 6 updates exceeded 16 s.
Thus unbounded completion is not a real-time guarantee. Three repeated paired
opening-prefix benchmarks gave a 28.08x aggregate update-time improvement over
the frozen reference, with identical history counts throughout those prefixes.
The [committed result bundle](../results/belief_tracker_2026-10-31/README.md)
contains the tables, raw measurements, source/data hashes and all ten replay
inputs, with commands to reproduce the complete run from this repository.

## Explicit unlimited logical-memory pilot

The evaluation factory accepts `tracker_memory_mb=none` only with `tracker_policy=budgeted-exact`. This passes `None` to the tracker, preserving the previous default of 64 MiB and numeric zero as a zero-memory budget. It disables logical accounting limits, not the per-update cooperative time budget. No partial belief or pruning is enabled. See [the 16-second pilot and its remaining failure](../results/unlimited_tracker_pilot_2026-11-03/README.md).
