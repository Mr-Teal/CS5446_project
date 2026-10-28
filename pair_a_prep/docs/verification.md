# Verification and handoff

## Main integration and review follow-ups: 27 October 2026

#15 merged at reviewed head `dfeea4c5067d0b2d3dd0eef52f2527c9653c240f`;
its tree matches the previously tested #30 integration head `a9e5b27`.
#26 then merged with #35's capped-outcome and evaluator-depth fixes. The
follow-up below is based on main `e875fbf`, not the separate #39-#44 stack.

- Final #15 shared/Pair A baseline: **430 passed**, using
  `python -m pytest -q tests pair_a_prep/tests`. Earlier recorded evidence;
  this count excludes `pair_b_prep` and the full Pair B suite.
- Colin's final-head review independently reports **441 tests and 2 subtests**
  with `pair_b_prep`, **17/17 fixtures**, and a full Pair B run of **1176 passed**
  on main plus #15, or **1188 passed** with #34. These are his scoped review
  counts, not new local reruns or evidence that #34 has merged.
- This review-follow-up tree: **433 passed** for `tests pair_a_prep/tests`,
  Python 3.12.15 in `pair_b/.venv`. It adds the blocked-child forced-draw FEN
  and mirror, plus rule-revision gadget-ID coverage. The overlapping focused
  values/gadget/archive-CLI run passed **71 tests**; do not add it to 433.
- An independent mutation probe ignoring no-move child outcomes changes
  forced-draw to None on both new FENs, so the new expected-result assertions
  detect the blind spot identified in review. Runtime scoring is unchanged.
- The unchanged #26 Pair C implementation passed **13 regression tests** with
  the integrated shared-rule package supplied as a dependency. A pytest cache
  permission warning did not affect results. No formal games or engines rerun.

The follow-up adds `rules`, `rules_id` and `no_move_rule` to hashed gadget
configuration and hashes `pair_b/src/pairb/values.py` in pilot provenance,
including failed setup reports. Historical artifacts keep their old IDs,
source hashes and rules; they are not regenerated or relabelled here.

#28's no-legal-move terminal draw is now on main through #15 and affects
Pair B stand-in/evaluator behavior too. The #34 time gate and #38's pre-rule
batch provenance remain separate. The newer 483-test experimental search stack
is pending review; it is not the implementation exercised by this entry.

## Historical chess integration validation: 24 October 2026

Using `pair_b/.venv/Scripts/python.exe` (Python 3.12.15), with the declared
Pair A requirements installed into that environment:

```powershell
.\pair_b\.venv\Scripts\python.exe -m pytest -q tests pair_a_prep/tests pair_b_prep
```

Result on the working tree based on merged branch `90a7908`, with the pilot-ID
fix: **405 tests and 2 subtests passed**,
including 18 chess bridge/pilot tests and the new alternating Kuhn checkpoint
regression. This command includes the belief tracker's 95 tests. The full
Pair B app/training suite was not part of this run.

This includes #21's 70 expansion tests and seven new pilot-identity tests.
The new tests distinguish tracker sample/cap, ply cap and D1 feature settings;
keep identical reruns stable; preserve existing game IDs when extending a batch;
and check canonical configuration hashing. Archive CLI tests additionally check
that manifest, report and records agree on the full pilot ID/configuration.
The agent's search-only ID remains separate from exported pilot protocol IDs.

A two-ply Material pilot with real Stockfish D1 input features passed its repeat
and round-trip checks. Pair B's CLI validator accepted both records with D1 and
played policies required, with zero errors and zero warnings. Its local output
is `pair_a_prep/local_runs/pilot-id-v2-20261024/` (ignored by Git).

The archive-portability follow-up adds six CLI/provenance cases: real source
copies without `.git`, execution without Git on PATH, invalid configuration and
engine-startup failures with retained reports, partially unavailable Git
metadata, and an archive enclosed by an unrelated Git repository. Archive CLI
successes retain source hashes without inventing a commit or clean status.

The chess gadget bridge adds 12 tests for opponent root grouping, shared and
distinct private-history strategies, Black/White perspectives, explicit external
parameters, root-order stability, independent LP objectives and continuation
labels excluding gadget priors, opt-outs and Maxmargin offsets. See
[chess_gadgets.md](chess_gadgets.md) for the analytic two-root example.

Four real-leaf fixture records (Material and Stockfish D1, each in Resolve and
Maxmargin) passed label acceptance with played policies required, repeated solves
and JSONL round trips. On the public Black king-capture fixture, all four chose
`e7e1`; continuation labels were 1.0 while the Maxmargin objective was 0.75.
These bridge records do not include optional D1 input features. The settings and
source hashes are in [chess_gadgets_reference.json](../results/chess_gadgets_reference.json).

The Kuhn regression compares last/average values and Nash gaps at rounds 1,
10 and 100 against the committed alternating reference at absolute tolerance
`1e-12`. Separate runtime mutation probes confirmed that stale-local-utility
prediction and ancestor-first preparation each fail at round 10 (largest metric
difference about 0.0687). The production solver algorithm was not changed.

After removing unnecessary move-stack copies, all 17 adapter fixtures passed.
The pre-change and optimized adapters also produced identical observations for
302 views through a synthetic 150-ply knight-cycle history, including terminal
views. This comparison is a semantic check, not a representative speed benchmark.
Existing sibling-isolation and repetition-history tests still pass.

The new tests check private-stream information sets (including hidden actions
that must share a key), same-FEN histories, complete path validation, retained
repetition history, Black/White payoff signs, shared-profile root labels,
explicit tree capacity and historical no-move failure handling (superseded by
the #28 terminal draw above), shared match integration, JSONL
round trips and a chess-tree value checked against the independent LP oracle.

Two small real-evaluator pilots passed: Material plus D1 features (12 records
from two capped games) and Stockfish D1 (one Black king-capture record). Both
passed Pair B's strict label checker with D1 and played policies required, with
zero errors/warnings, and repeated fixed-work runs identically. The Material
export also matched a separate-process run after excluding elapsed times and
over-budget flags. See [chess_search.md](chess_search.md) for settings and limits
and [the compact reference](../results/chess_search_reference.json) for hashes.

Raw pilot files are local and ignored under `pair_a_prep/local_runs/`. These
checks establish a small end-to-end pipeline, not production teacher quality,
long-game scalability, full KLUSS or a complete Obscuro reproduction.

## Earlier snapshots

The former 21 October entry described preparation before the exact tracker was
integrated and has been superseded by the current validation above. The tracker
integration baseline had 280 shared/Pair A tests, or 291 with `pair_b_prep`.
Commit `f297e37` then added 18 chess integration tests, and the review follow-up
adds the Kuhn checkpoint regression. Historical reports retain their original
source hashes and counts; they do not identify the current source snapshot.
The later CLI portability follow-up adds six tests to that 310-test snapshot.
The optional chess gadget bridge adds twelve more to the resulting 316 tests.

Environments, downloaded engines, caches and raw local pilot records remain
excluded from commits. See [pr_handoff.md](pr_handoff.md) for remaining work.

## Historical baseline: 17 October 2026

The sections below record the initial preparation before the rules adapter and
solver implementations. Their implementation gaps describe that date only.

## Executed checks

```powershell
python -m pytest -q -p no:cacheprovider pair_a_prep/tests tests
python -m pair_a_prep.toy_games --output pair_a_prep/results/toy_reference.json
python -m pair_a_prep.fixtures
```

The test command passed **19 tests**: 15 preparation checks and the 4 existing
shared-code checks. It covers hidden versus revealed information, chance
weighting, a nonuniform equilibrium, Kuhn poker's game value, best-response
gap, input size limits, benchmark corpus safety, raw score viewpoint, fixture
history, classical-rule counterexamples and observation matching assertions.

Reference outputs: [`toy_reference.json`](../results/toy_reference.json).

| Reference problem | Player 0 equilibrium value |
|---|---:|
| Hidden matching pennies | 0 |
| First action revealed to player 1 | -1 |
| Hidden coin, P(H)=0.75 | 0.5 |
| Coin revealed before guessing | 1 |
| Three-card Kuhn poker | -1/18 |
| Biased 2x2 payoff matrix | 0.5 |

Each solved reference has an unhalved best-response gap below `1e-8`.
The LP can choose among multiple equilibria, so exact policy probabilities
are not prescribed where only the value is unique. A known-value test does
not validate knowledge-limited gadget construction, tree expansion or PCFR+.

## What the fixtures verify now

All 17 definitions load; their FENs parse, the history case replays to its final
FEN, and the annotated orthodox checkmate/stalemate/illegal-move facts were
checked using python-chess. The castle counterexample's endpoint geometry is
also checked. Applying `Board.push` alone does not validate a fog move.

**No production FoW adapter has been run against the fixtures.** Expected fog
visibility and legality are hand-derived acceptance requirements, pending
review and an adapter implementation. An adapter that passes partial
expectations may still have untested errors elsewhere.

## Real engine execution

The official Stockfish 19 binary was downloaded to a temporary directory,
then run for 72 successful benchmark calls. The binary is not included in
this repository. See [benchmark.md](benchmark.md) for settings, results,
hashes and scope. There is no completed neural-network timing, full chess
match, replicated agent or solver-label run in this preparation.

The verification environment reused numpy/scipy/pytest already installed on
the machine and chess 1.11.2 in a temporary package directory. Teammates
should use the independent requirements file and environment instructions,
rather than depending on that temporary path.

## Initial integration gates (historical)

1. Review the proposed rule profile and the observation fields with Pair A.
2. Implement one rules adapter and run all fixture assertions against it.
3. Pick the agent ownership and implement a fixed-tree solver against the toy
   oracle, followed by gadget and tree-growth validation.
4. Settle belief-context evaluation and feature versioning with Pair B before
   producing teacher labels. Existing PR changes remain a separate decision.
