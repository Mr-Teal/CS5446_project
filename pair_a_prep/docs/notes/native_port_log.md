# Native port log (branch `pair-a/native-port`, started 2026-11-10)

Decision (user, 2026-11-10): port the search to native code before any self-play work. Order from the move
profile in `handover_2026-11-10.md` section 2.9: A) the PCFR+ round, B) fog-chess rules and move generation,
C) construction across cores, D) the rest of the search loop. Every step keeps the Python path as the reference
and ships with an exact-equivalence test on toy games and on recorded chess positions.

Terms as in the handover: *PCFR+ round* = one `PCFRPlus.step()`; *walk* = one traversal of the subgame tree;
*own-history depth* of an information set = the number of the player's own decisions before it.

## A0. Level-wise prediction walk, pure Python (2026-11-10 06:40)

Finding: `PCFRPlus._prepare` built each information set's prediction with a full-tree walk of its own
(`_utilities(player, previous)[key]` inside the loop over sets), so one round cost about 20 walks on a chess
tree; this was 31-51 % of a 5 s move (4.5-7.7 million `visit` calls).

Change (`pair_a_prep/pcfr.py`): `_prepare_fast` walks the tree once per own-history depth, deepest first,
publishes every set of that depth after the walk, and memoises the value of own nodes whose set is already
final, so later walks stop there. Same floating-point operation order; `_prepare_reference` keeps the old loop;
`FOW_PCFR_FAST=0` or `PCFRPlus(..., fast_prepare=False)` selects it. Why it is exact: a set's prediction depends
on the previous opponent strategy and on its own descendants' strategies only (own reach is 1 in the
counterfactual; same-depth sets live in disjoint subtrees).

Tests: `pair_a_prep/tests/test_pcfr_fast.py`, 14 cases: matching pennies, hidden coin, Kuhn poker x both
schedules x predictive on/off, every round for 60 rounds, policies (last and average) and regrets equal to
1e-12; recorded chess positions with the material leaf, 12 rounds with one-sided growth every third round,
equal throughout. The existing `test_pcfr.py`, `test_pcfr_expansion.py`, `test_anytime_agent.py` pass (108).

Effect (`profile_move.py`, three recorded positions, network v2 leaf, 5 s, no tracker):

| Position | rounds, reference | rounds, level-wise | PCFR+ own time | nodes |
|---|---|---|---|---|
| ply 5 | 384 | 1,024 (the cap, reached in 3.95 s) | 2.22 s -> 1.57 s | 929 -> 929 |
| ply 28 | 177 | 611 | 1.38 s -> 1.30 s | 1,365 -> 1,440 |
| ply 68 | 216 | 537 | 1.99 s -> 1.40 s | 1,129 -> 1,449 |

Rounds per move 2.5-3.5x; growth steps rise with them (every 2 rounds), so trees get a little bigger. Not yet
merged into the handover branch: the strength arms run from that worktree and must keep the code they started
with until they finish.

## A1. C++ kernel for the round (2026-11-10)

Result: the whole `PCFRPlus.step()` runs in C++ with results equal bit for bit to the Python solver on this
VM; the solver's share of a profiled 5 s move falls from 27-40 % to 3.5-7 %, and all three profiled positions
reach the 1,024-round cap.

### Design as built

Python keeps the `Node` tree, `expand()` grafting, `information_sets`, `_check_recall` and the infoset-key <->
id mapping (`pair_a_prep/_pcfr_native.py`, class `NativeState`). After `__init__` and after every `expand()`
the tree is compiled again and the state moved into fresh arrays, carried by key (`_native_compile`).

* Tree, nodes in DFS order, root = 0: `kind` (int8: 0 terminal, 1 chance, 2 decision), `player` (int8),
  `infoset` (int32, per-player id), `payoff` (float64, player 0's); `child_begin[n+1]` / `child` (children in
  dict order, which for decision nodes is checked to equal the infoset's action list); `chance_begin[n+1]` /
  `chance_child` / `chance_prob` (the `probabilities` dict order, which `_utilities` iterates; it may differ
  from the children order that `_accumulate_average` uses).
* Per player: `offset[sets+1]` (the actions of set s are `[offset[s], offset[s+1])` in every state array),
  `depth` (own-history depth, `_depth`), `level_sets` (`_order`, deepest first) with `level_begin` /
  `level_depth` (the levels of `_prepare_fast`).
* State per player, float64 over that player's actions: `regrets`, `strategy` (the published strategy, which is
  also `PredictiveRMPlus.strategy`: the two are equal at every point of the Python reference, and loading
  checks it), `previous_utility`, `sums`, `previous_opponent` (over the opponent's actions, with one
  `has_previous` flag per player); per set: `pending` (int8) and `initial_action` (int32, -1 = none).
* The solver's Python containers become views of these arrays: `minimizers[p][key]` is a `FlatMinimizer`
  (a `PredictiveRMPlus` whose `regrets` / `strategy` / `previous_utility` / `_pending` are properties on the
  slices), `_strategy` and `_sums` are dicts of views whose item assignment copies into the array,
  `_previous_opponent` is a two-item list of such dicts. So every existing reader and writer keeps working
  (`policy()`, `metrics()`, `warm_start.rebase_solver`, `search_policies.seed_new`, affine transport,
  `frozen_search.state_digest`, the Python `_prepare` / `_utilities` / `_accumulate_average`), expand keeps the
  minimizer objects of existing sets, and `deepcopy` of a native solver gives an independent native solver.
  `_initial_actions` stays a plain dict, written into `initial_action` before each kernel call and popped when
  the kernel consumed the entry (the first publish), as `_publish` does.
* Kernel `pair_a_prep/pcfr_kernel.cpp`, one ctypes structure `PcfrSolver` with pointers to all of the above;
  extern "C": `pcfr_utilities(s, player, opponent|NULL, values)` (`_utilities`), `pcfr_prepare(s, player)`
  (`_prepare`: zero predictions before the first snapshot or when not predictive, else the level-wise walk with
  memo over final own nodes, then PRM+ `next_strategy` per set and the initial-action override),
  `pcfr_observe(s, player)` (utilities walk, PRM+ `observe`, opponent snapshot),
  `pcfr_accumulate_average(s, player, weight)` (first visit per set), `pcfr_step(s, rounds)` (both schedules,
  including the alternating round-0 prepare; weight = (rounds+1) ** averaging_power). Pending-flag violations
  return -1 / -2 and become the same `ValueError`s.
* Floating-point order. Elementwise updates are single IEEE operations (built with `-ffp-contract=off`). Three
  reductions are not plain loops in the reference, and the kernel copies each: chance nodes sum like CPython
  3.12's `sum()` over floats (Neumaier compensation, starting from the int 0); `theta.sum()` is numpy's
  pairwise sum; `strategy @ values` is OpenBLAS `ddot`, and on this Zen 5 host OpenBLAS 0.3.34 picks the AVX-512
  kernel: fused multiply-adds in 32-wide blocks into four 8-lane accumulators, folded to 4 lanes, 16-wide blocks,
  a fixed reduction, then a sequential fused tail (sequential FMA alone matches only below 16 actions). Measured
  against numpy before writing the kernel; `std::fma` keeps it portable.
* Selection: `PCFRPlus(..., backend="auto"|"python"|"native")`, default `PCFRPlus.BACKEND` =
  `FOW_PCFR_BACKEND` or "auto". auto = native when the library loads and `fast_prepare` is on; native without
  the library is an error, native with `fast_prepare=False` too (when chosen per call; from the environment such a
  solver stays on Python, so the reference side of test_pcfr_fast.py remains Python). A solver whose
  `_utilities` or a minimizer's `observe` / `next_strategy` was replaced on the instance (frozen_search counts
  traversals that way, test_one_sided spies on observe) runs its rounds in Python on the same views.
* Build: `python -m pair_a_prep.build_pcfr_kernel` (`g++ -std=c++17 -O3 -DNDEBUG -ffp-contract=off -shared
  -static-libgcc -static-libstdc++ -fPIC`), output `pair_a_prep/_pcfr_build/` (ignored) with `manifest.json`
  (sha256 of `pcfr_kernel.cpp` and `_pcfr_native.py`, and of the library); `_pcfr_native.library()` returns
  None for a missing or stale build. The host build (Ubuntu g++ 11.4) loads in the `fow-portability` container.

### Tests

* `pair_a_prep/tests/test_pcfr_native.py`, 20 cases: toy games (matching pennies, hidden coin, Kuhn) x both
  schedules x predictive on/off, 60 rounds, the whole state compared every round (last and average policies,
  regrets, published strategies, previous utilities, pending flags, sums, opponent snapshots, unconsumed
  initial actions); initial actions with averaging powers 0, 1, 2; write-through views across in-place and
  assigned writes, deepcopy and expand; the kernel's utilities (current and given opponent) and average walks
  against the Python methods; backend selection; recorded chess positions (material leaf, three per schedule)
  with one-sided growth through `expand_chess_tree` every third round, both schedules. Tolerance 1e-9; run
  with tolerance 0 (exact equality) all 19 equivalence cases also pass.
* Python reference suites (test_pcfr, test_pcfr_expansion, test_pcfr_fast, test_anytime_agent): 109 passed
  before the change, 109 with `FOW_PCFR_BACKEND=native`. Fifteen further suites that build solvers (chess
  search, subgame agent, frozen search, gadgets, affine, cross-turn, one-sided, ...) plus the above: 339 passed
  under native, auto and python. The whole `pair_a_prep/tests`: the same 53 failures under auto and python, all
  in `test_zs21_*` (they fail without the kernel too).

### Effect

`profile_move.py --pcfr-backend {python,native}` (three recorded positions, network v2 leaf, 5 s budget, 1,024-round
cap, no tracker), in the container, one run each. PCFR+ share = own time in `pcfr.py` plus `_pcfr_native.py`
(the kernel runs inside the ctypes call there, together with the Python tree compilation after each expansion),
of the profiled time.

| Position | rounds, Python | rounds, native | PCFR+ share, Python | PCFR+ share, native | nodes | wall |
|---|---|---|---|---|---|---|
| ply 5 | 1,024 (cap) | 1,024 (cap) | 40.2 % (1.60 s) | 3.7 % (0.09 s) | 929 -> 929 | 4.03 -> 2.42 s |
| ply 28 | 519 | 1,024 (cap) | 26.7 % (1.18 s) | 3.5 % (0.12 s) | 1,440 -> 1,440 | 4.51 -> 3.54 s |
| ply 68 | 529 | 1,024 (cap) | 31.0 % (1.38 s) | 6.9 % (0.24 s) | 1,437 -> 1,659 | 4.51 -> 3.56 s |

The round cap, not the clock, now ends every profiled move; the remaining time is tree construction and
growth (python-chess 25-36 %, rules, one-sided growth). At ply 68 (111 expansions) the Python recompilation of the
tree after each `expand()` is most of the 0.16 s in `_pcfr_native.py`; an incremental compile is the obvious
follow-up if it grows. Python rounds at ply 28 / 68 are lower than in A0 (611 / 537): other jobs share the
VM, so compare within a table, not across.

### Exactness

No deviation measured: every compared quantity is equal bit for bit on this VM (19 cases, every round). The
match depends on the OpenBLAS kernel numpy uses here; on a host whose BLAS picks another ddot kernel the dot
products can differ in the last bits, which is what the 1e-9 test tolerance allows for.

## A2. Rounds and depth caps with the native solver (2026-11-10 07:50)

`profile_move.py --pcfr-backend native --rounds R --max-depth D`, three recorded positions, 5 s budget, no tracker.
Rounds 1,024 -> 4,096 cost 0.3 s more; 16,384 requested gives 11.9k-13.2k rounds before the clock stops the move
(~3,000 rounds/s on a 1.6k-node tree). Depth cap 2 -> 4 -> 6 changes nodes by at most 1,440 -> 1,556 (ply 28) and
929 -> 1,685 (ply 5), with 26-114 expansions per move: growth stops at the 70 % growth deadline because each
expansion costs about 40 ms in python-chess and the rules adapter (`rules_adapter.py observe` 0.82-0.86 s per move
over 3.8k-5.7k calls, `chess/` 0.9-1.4 s). Conclusion: phase B (native rules, move generation, observation) is the
binding constraint now; revisit depth caps after it. profile_move.py gained --rounds, --max-depth, --max-nodes and
prints the stop reason.
