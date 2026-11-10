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

## B1. Native rules for tree construction and growth (2026-11-10)

Result: tree construction and growth no longer go through python-chess. With the native rules backend the
rules work of one expansion (all of `_build_roots` except the leaf evaluator) falls from 12-52 ms to
0.75-2.1 ms (about 17-25x), every result is identical to the Python adapter, and in the same 5 s move the
agent makes 1.8-2.4x the expansions and grows a tree with 1.6-1.9x the nodes. All three positions now stop at
the 4,096-round cap, not the growth deadline. The python-chess time left in a move is inside the belief-network
leaf (`pairb.observe`, `fow_shared.features`, `forced_score`), not in the search.

### Profile attribution before the change

`pair_a_prep/experiments/network_leaf_2026-11/pipeline/profile_construction.py` (the agent and records of
profile_move.py, cProfile with callers). Python rules, native solver, 4,096 rounds, depth cap 4, three
positions (ply 5 / 28 / 68), cumulative seconds per move:

| operation | ply 5 | ply 28 | ply 68 |
|---|---|---|---|
| `_build_roots` (with the leaf) / leaf `evaluate_children` | 3.22 / 1.85 | 2.98 / 1.53 | 2.09 / 0.76 |
| `reconstruct_roots` (replay of 16 paths) | 0.08 | 0.37 | 0.87 |
| `RulesAdapter.observe` (calls) | 0.77 (3,456) | 0.92 (4,044) | 0.83 (5,720) |
| of it `visible_squares` | 0.27 | 0.33 | 0.28 |
| `legal_moves` (all callers; `fog_legal_moves` 0.3-0.6) | 0.44 | 0.49 | 0.33 |
| `apply_move` (of it the RuleState stack copy) | 0.21 (0.04) | 0.39 (0.15) | 0.80 (0.62) |
| `_extend` / `observation_key` (of it `asdict`) | 0.23 / 0.21 (0.16) | 0.27 / 0.28 (0.22) | 0.30 / 0.37 (0.29) |
| `terminal` | 0.06 | 0.06 | 0.07 |

The planes encoder (`fow_shared.features`, 0.33-0.91 s) and `pairb.observe` belong to the leaf evaluator and
were left alone. Targets chosen from this: observe (visibility, legal moves, terminal), apply_move without the
copy of the move stack (quadratic in the game length: 0.62 s at ply 68), and the observation key without
building and `asdict`-copying an Observation.

### Design as built

* `RulesAdapter(backend="auto"|"python"|"native")`, default `RulesAdapter.BACKEND` = `FOW_RULES_BACKEND` or
  "auto"; auto = native when the library loads. Subclasses (zs21 `SearchRules`, `RefereeRules`, `FastRules`)
  override single rules that the base `observe` calls, so they stay on Python under auto. Native without the
  library is a `RuntimeError`. The kernel module is bound on the class, not the instance (belief_tracker's
  memory accounting walks instance attributes).
* State: a native-made `RuleState` has no `_board`. It carries `_native` (`_rules_native.Native`): the packed
  board as 80 bytes (`zs21.native_tracker.Packed`: six piece bitboards, White, castling rights, turn, EP square),
  halfmove and fullmove counters, the parent state and the move, and the repetition window: the FoW position
  keys of the previous min(len(move_stack), halfmove_clock) positions, extended per ply and emptied by a zeroing
  move, exactly the positions `_is_fog_threefold_repetition` walks back over. Analysis, terminal result and FEN
  are cached on it. `state.fen` comes from the kernel; `state._board` / `board_copy()` are built on first use
  (`RuleState.__getattr__`) by replaying the moves from the nearest ancestor that has a board, so the move stack
  is the full one; nothing in construction or growth asks for it (0 calls in the profiles below). A Python-made
  state used by the native backend is packed once, with its window from popping a copy of its stack.
* Kernel `pair_a_prep/rules_kernel.cpp` includes `zs21/native/inference.cpp` and adds two calls:
  `rk_analyze(board)` returns, as ASCII lines, king presence, the fog-legal move count, the FoW position key, the
  fog-legal moves in sorted UCI (text and JSON), and per player the visible squares (sorted by name), their piece
  letters and the `visible_pieces` / `visible_squares` JSON. `rk_play(board, move)` applies a move. Python
  (`pair_a_prep/_rules_native.py`) turns these into the adapter's answers: terminal in `terminal_score`'s order
  (king captured, fifty-move, repetition by counting the current key in the window, no fog-legal move),
  `legal_moves`, `observe` (an `Observation` with every field) and `observation_key`, which formats the same
  JSON string as `chess_search.observation_key(observe(...))` without building the Observation.
* `chess_search`: `_extend(memory, observation, move)` is now `_extend_key(memory, observation_key(observation),
  move)`; `_build_roots` and `reconstruct_roots` ask `rules.observation_key(state, player)`, which on the Python
  backend is `observation_key(self.observe(...))`. Public APIs of the adapter and of `_build_roots` unchanged.
* Build: `python -m pair_a_prep.build_rules_kernel` (`g++ -std=c++17 -O3 -DNDEBUG -shared -static-libgcc
  -static-libstdc++ -fPIC`), output `pair_a_prep/_rules_build/` (ignored) with `manifest.json` (sha256 of
  `rules_kernel.cpp`, `zs21/native/inference.cpp`, `_rules_native.py` and of the library);
  `_rules_native.library()` returns None for a missing or stale build. The host build (Ubuntu g++ 11.4) loads in
  the `fow-portability` container.

### Reused from the tracker kernel, and the semantic bridges

Reused unchanged from `zs21/native/inference.cpp`: the `Board` layout (and `native_tracker.Packed` / `pack` /
`encode` on the Python side), the attack masks, `moves()` for the fog-legal move set, `play()` for the successor,
and `zs_fen()`. Where its semantics differ from `RulesAdapter`, the bridge:

* Castling rights. python-chess uses `clean_castling_rights()`, which cleans the FEN's rights only while the
  move stack is empty and otherwise returns the raw rights; `push` cleans before every move. So after any move
  the raw rights equal their cleaned form, and the kernel cleans (rooks on a/h corners of their colour, king on
  e1/e8) before generating moves, keys or successors. `play()` additionally canonicalizes rights by rook
  presence and king square; on cleaned rights this removes exactly what `push` removes (moves from or to a
  corner, king moves, a king captured on its back rank).
* En passant. `play()` drops an EP square nobody can use; the FEN boundary keeps it after every double step
  (`standard_fen`), so `rk_play` restores it, as `belief_kernel.cpp` does. Move generation and visibility use the
  square only for the real side to move, as python-chess's pseudo-legal EP does.
* Move order. `moves()` sorts by its integer code; the adapter sorts UCI strings, so the kernel sorts the UCI
  strings. The fog-legal set is python-chess's pseudo-legal moves plus castling into, out of or through attacks;
  `moves()` generates castling without attack checks, which is that union because python-chess's attack-checked
  castling is a subset of it.
* Visibility. `visible()` in the tracker returns nothing when a king is missing (inference never advances a
  terminal view), but `RulesAdapter.visible_squares` is defined after a king capture and the tree observes
  terminal children; it also follows python-chess's castling (attack-checked). The kernel therefore has its own
  `visible_squares`: own pieces, all pseudo-legal destinations for that colour as if it were to move, EP
  square and captured pawn for the side to move only. Castling destinations need no separate case: a castling
  right means the own rook on its corner with empty squares to the king, so the rook's own move reaches c1/g1.
* Repetition key: `fog_position_key` (pieces, colours, turn, cleaned rights, EP square only when a pseudo-legal
  EP capture exists) is computed by the kernel; the window is kept in Python.
* Unreachable differences, not bridged: python-chess would let a pawn standing on its first rank double-step,
  and generates pawn pushes past the last rank as squares beyond 63; neither position arises from play.
  Promoted kings (crazyhouse) do not exist in standard chess, so `promoted` is ignored.

### Tests

`pair_a_prep/tests/test_rules_native.py` (25 tests, 56 s on the host; skipped without the library). Each check
runs both backends side by side: FEN, ply, capture notice, side to move, `terminal()`, `legal_moves()` (set and
order), `observe()` for both players (every field, `visible_pieces` in order), `visible_squares`, the
observation key from both adapters, rejection of an unavailable move, and the replayed python-chess board with
its move stack. Positions: the 17 rule fixtures (`pair_a_prep.fixtures` suite, with all children), 20 hand-made
corners (repetition, EP both ways and a fog-only EP, castling into/through attacks and lost rights, FEN rights
that the position does not support, promotions with and without capture, king captures including on a back rank
with rights, fifty-move boundary, no fog-legal move reached by a move and from a FEN, a missing king), a mixed
Python/native history reaching threefold repetition, and the recorded games: 139 records of
`solver-v2-sf8-g237` (every 10th part file), every state on four hypotheses' paths from ply zero, every child of
465 path ends and the grandchildren of every fourth: 60,816 states compared, with 18,194 castling moves, 724
promotions, 10 EP captures and 15 king captures among them. Subgame trees: 6 recorded turns built (depth 1 and
2) and grown three times through `expand_chess_tree` with selected frontiers, under each backend with the
material leaf; node structure, infoset strings, children order, payoffs, chance probabilities, counters,
frontier paths, memories and states identical (43,280 nodes). All equal; nothing needed a tolerance.

Existing suites with `FOW_RULES_BACKEND=native`: `test_rules_adapter`, `test_chess_search`,
`test_anytime_agent`, `test_pcfr_native`, `test_pcfr_fast` 88 passed (2.1 s; 5.2 s on Python). The whole
`pair_a_prep/tests` directory: 855 passed, 53 failed under native, the same 53 under Python; they are the
`test_zs21_*` tests that load `zs21/native/inference.so`, which is not built on this host (pre-existing). The
native run first showed two more failures (`test_belief_graph` memory resume, `test_evaluation_tracking`
memory limit): the adapter instance held the kernel module and the tracker's memory accounting counted it;
fixed by binding it on the class.

### Before / after (profile_move.py, native solver, 4,096 rounds, depth cap 4, 5 s budget)

"python" = this code with the rules build hidden (auto falls back to Python); the run before the change gave the
same numbers within noise (ply 5: 1,649 nodes, 44 expansions; ply 28: 1,635 / 28; ply 68: 1,804 / 108).
Rules per expansion = (`_build_roots` cumulative - leaf `evaluate_children` cumulative) / `_build_roots` calls,
and the `_rules_native` own time, come from profile_construction.py runs (python rows: the run before the
change); the other columns from profile_move.py.

| ply | rules | nodes | evaluator calls | expansions | wall s | stop | `chess/` own | `pair_a_prep.rules` + `_rules_native` own | rules per expansion |
|---|---|---|---|---|---|---|---|---|---|
| 5 | python | 1,622 | 56 | 43 | 3.85 | round_limit | 1.34 s (35.9 %) | 0.16 s (4.2 %) | 30 ms |
| 5 | native | 2,635 | 92 | 79 | 4.08 | round_limit | 1.22 s (30.5 %) | 0.06 s (1.4 %) | 1.5 ms |
| 28 | python | 1,556 | 43 | 26 | 3.82 | round_limit | 1.40 s (37.5 %) | 0.20 s (5.3 %) | 52 ms |
| 28 | native | 2,921 | 79 | 62 | 4.20 | round_limit | 1.30 s (31.5 %) | 0.07 s (1.7 %) | 2.1 ms |
| 68 | python | 1,728 | 105 | 103 | 3.85 | round_limit | 0.91 s (24.1 %) | 0.20 s (5.2 %) | 12 ms |
| 68 | native | 3,395 | 213 | 211 | 4.08 | round_limit | 0.68 s (16.9 %) | 0.10 s (2.5 %) | 0.75 ms |

Native-run attribution: `legal_moves` + `apply_move` + `terminal` + `observation_key` together 0.06-0.10 s per
move (1.2-2.1 s before at half the expansions), `reconstruct_roots` 0.01-0.11 s (0.08-0.87 s), no `observe`
calls left in construction, no board materialized. The remaining `chess/` time is the leaf: `pairb.observe`
visibility and `fow_shared.values.forced_score` per child, and `chess.Board` construction in
`fow_shared.features.encode_belief`, which now run about twice as often because there are twice the expansions.
The move chosen is the same at ply 5 and 28; at ply 68 it already varied between Python runs (growth is
timing-dependent).

Next: the leaf's own python-chess work (pairb.observe, forced_score, the planes) is now the largest
non-network cost per expansion; and with expansions cheap, the depth-cap and growth-fraction settings of A2
are worth measuring again.

## B2: the leaf data path (belief-network `evaluate_children`)

Before B2, every expansion called `BeliefNetworkEvaluator.evaluate_children(fen)`, which made each child with
python-chess, decided it with `rule_value`, built its one-board belief (`_alone`: `observe` + `standard_fen` +
`Hypothesis`) and encoded it with `encode_belief`, then ran one network pass. Under the profiler that was
~30 ms per call (2.7 s per move at plies 5 and 28); the GPU pass is a small part of it.

### Design as built

* Kernel `pair_a_prep/leaf_kernel.cpp` includes `rules_kernel.cpp` (hence `zs21/native/inference.cpp`) and exports
  one call, `lk_children(parent, halfmove, fullmove, all_planes, ...)`. For the packed parent it returns 0 when
  `terminal_score(parent)` is set (the evaluator's `{}`), else for every fog-legal move in `fog_legal_moves` order:
  the encoded action and its UCI name, the rule flag and White-view rule value (`rule_value`), the 32x8x8 float32
  planes (for the undecided children only, packed in order, or for all with `all_planes`), and optionally the
  packed child boards and their standard FENs (tests only).
* Loader `pair_a_prep/_leaf_native.py` (`library()`, `children(fen, all_planes=False, details=False)`), build
  `python -m pair_a_prep.build_leaf_kernel` into `pair_a_prep/_leaf_build/` (ignored) with `manifest.json`
  (sha256 of `leaf_kernel.cpp`, `rules_kernel.cpp`, `zs21/native/inference.cpp`, `_leaf_native.py` and the
  library); `library()` returns None for a missing or stale build. Same compiler flags as B1. The host build
  (g++ 11.4) loads in the `fow-portability` GPU container.
* `pairb/belief_evaluator.py`: `BeliefNetworkEvaluator(leaf_backend="auto"|"python"|"native")`, default
  `LEAF_BACKEND` = `FOW_LEAF_BACKEND` or "auto"; auto = native when the library loads; native without it is a
  `RuntimeError`; a `use_d1` network always stays on Python (it needs Stockfish per child). `self.leaf_backend`
  is the effective choice. The native branch (`_native_children`) feeds the kernel's planes straight to the
  network with weight 1 and one belief per child, and applies the same signs and `+ 0.0` as the Python path.
  The network pass is factored out of `_score` into `_forward`, used by both paths, unchanged.
  `evaluate_boards` / `evaluate_beliefs` stay on Python.

### Reused, and what was added

Reused from B1 / the tracker kernel: the `Board` layout (`native_tracker.Packed` / `pack`), attack masks, `play()`
with B1's `rk_play` bridge (exact EP square after a double step, cleaned rights), `rk::clean_rights`,
`rk::ep_effective` (python-chess `has_pseudo_legal_en_passant`), `rk::visible_squares` (the
`RulesAdapter.visible_squares` rule, which `pairb.observe.visible_squares` follows), `rk::uci` and `zs_fen`.

Added:

* `fog_moves`: `fog_legal_moves` in its exact order, which B1's sorted `moves()` does not give: python-chess
  `generate_pseudo_legal_moves` (non-pawn pieces by square high to low, targets high to low; then castling
  that python-chess allows, i.e. with `_attacked_for_king` checks, rights scanned high to low; pawn captures by
  square high to low with promotions Q, R, B, N; single pushes by target high to low; double pushes; EP), then
  `_available_fog_moves`'s fog-only castling (kingside, then queenside) when not already listed. The order
  matters: the dict `evaluate_children` returns and the network batch are in it.
* `attackers` (python-chess `attackers_mask` with an explicit occupancy), `was_into_check`, `terminal`
  (`terminal_score` without history: king captured, fifty-move, no fog-legal move) and `rule_value`
  (`terminal_score` or `forced_score`, then White's view and `+ 0.0`). Repetition is not checked: the parent is a
  FEN with no history, so the child has one move on its stack and the grandchildren two, below the four plies
  `_is_fog_threefold_repetition` needs.
* `encode`: the planes, below.

### Plane-by-plane source of truth

The belief `_alone(child)`: player = child's side to move, one hypothesis `standard_fen(child)` of weight 1,
`Belief.ply` 0, `population_size` None, observation `observe(child, player)` with ply 0; `encode_belief` with
`opponent_visible`, search depth 0, no capture recency. Mirroring is `_index`: White row = 7 - rank, Black
row = rank, column = file.

| planes | Python source | native |
|---|---|---|
| 0-5, 6-11 | hypothesis board pieces, own / enemy by `player_white` | child board, same split |
| 12 | `obs.visible_squares` = `pairb.observe.visible_squares(child, player)` | `rk::visible_squares(child, player)` |
| 13 | of those, squares whose `visible_pieces` letter is the enemy's | same squares with an enemy piece |
| 14-19 | `+= weights[i]` for each enemy piece: 1.0 | 1.0 |
| 20 | `min(log2(population_size or 1) / 15, 1)` = 0 | 0 |
| 21 | `opponent_visible(board)` = the other colour's `visible_squares` on the re-parsed hypothesis | `rk::visible_squares(child, !player)` |
| 22 | of those, squares holding the player's pieces | same |
| 23 | capture recency: none | 0 |
| 24, 25 | `min(ply / 200, 1)` with ply 0; `min(search_depth / 4, 1)` with 0 | 0 |
| 26-29 | `has_kingside/queenside_castling_rights` on `chess.Board(standard_fen)` (own, then enemy) | cleaned rights bits h/a corner of each back rank |
| 30 | EP square, only when `has_pseudo_legal_en_passant()` | `rk::ep_effective` |
| 31 | `min(halfmove_clock / 100, 1.0)` of the hypothesis (float64, cast to float32) | `float(min(double(h) / 100, 1.0))` |

Planes that needed careful reading: 21-22 are computed on the hypothesis board re-parsed from its FEN, not on the
child board object, so the castling rights and EP square are the FEN's (cleaned on parse; equal to the pushed
child's, as B1 established); 26-29 use python-chess's `has_*_castling_rights`, which on a freshly parsed board
are exactly the cleaned corner bits; 30 is marked only when an EP capture is pseudo-legal although the standard
FEN names the square after every double step; 31 is the child's own clock (0 after a pawn move or capture, else
the parent's + 1), not hidden as in the observation; 20, 23, 24 and 25 are constant 0 here.

### Tests

`pair_b/tests/test_leaf_native.py` (5 tests; skipped without the library; needs torch). Per parent, against
the Python path: move list and order, child standard FENs, packed child boards, rule flags, rule values (by
`repr`, so a -0.0 would show), all children's planes with `np.array_equal` on float32, and the evaluator's
compact planes (undecided children only). Parents: 24 corner sequences (37 positions: EP used / unused / fog-only
/ unusable FEN square, castling allowed, into and through attacks, lost and impossible rights, promotions,
king captures, a king left en prise, a missing king, fifty-move at the child, one move ahead and at the parent,
no fog-legal move), the rule fixtures (`pair_a_prep.fixtures`, 25 positions), and 4,000 recorded parents (hypotheses of every 10th
part file of `solver-v2-sf8-g237`, both sides to move: 2,006 Black, plus two random children of each):
122,490 children, 4,468 rule-decided, 998 castling moves, 112 promotions, 1,115 with an EP plane. End to end
with `belief-solver-v2-sf8-g237/best.pt` on CPU: Python and native evaluators on 337 parents (695 s on CPU; the
committed test uses 97 parents, 89 network passes, 183 s, also exact): same move order, largest value difference 0.0, and all 329 planes arrays fed to
the network identical. Everything was bit-exact on the first run; nothing needed a tolerance.

Existing suites with `FOW_LEAF_BACKEND=native`: `pair_b/tests/test_belief_evaluator.py`, `test_belief_net.py`,
`pair_a_prep/tests/test_chess_search.py`, `test_anytime_agent.py`: 40 passed.

### Before / after (profile_move.py, native solver and native rules, 16,384 rounds, depth cap 4, 5 s budget)

"before" = the branch before B2; "python" = B2 with the leaf build hidden (auto falls back to Python); "native"
= B2 with the kernel. Module times are own time under cProfile; `evaluate_children` cumulative is not in the
native run's top 12 any more, so it is bounded by the 12th entry's cumulative time.

| ply | leaf | nodes | expansions | evaluator calls | rounds | wall s | stop | `chess/` | features + observe + values | `evaluate_children` cum. | ms / call (profiled) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5 | before | 2,545 | 76 | 89 | 7,443 | 4.52 | submission_reserve | 1.25 s (28.0 %) | 0.62 s | 2.78 s | 31 |
| 5 | python | 2,607 | 78 | 90 | 7,322 | 4.52 | submission_reserve | 1.22 s (27.5 %) | 0.61 s | 2.73 s | 30 |
| 5 | native | 3,061 | 94 | 106 | 7,408 | 4.52 | submission_reserve | 0.03 s (0.6 %) | 0 | < 0.54 s | < 5.1 |
| 28 | before | 2,887 | 61 | 77 | 6,243 | 4.52 | submission_reserve | 1.28 s (28.7 %) | 0.64 s | 2.74 s | 36 |
| 28 | python | 2,921 | 62 | 79 | 5,959 | 4.52 | submission_reserve | 1.35 s (30.3 %) | 0.64 s | 2.81 s | 36 |
| 28 | native | 6,943 | 167 | 183 | 3,041 | 4.54 | submission_reserve | 0.06 s (1.3 %) | 0 | < 0.64 s | < 3.5 |
| 68 | before | 3,330 | 208 | 209 | 7,323 | 4.52 | submission_reserve | 0.70 s (15.6 %) | 0.32 s | 1.56 s | 7.5 |
| 68 | python | 3,330 | 208 | 210 | 7,243 | 4.52 | submission_reserve | 0.69 s (15.3 %) | 0.31 s | 1.54 s | 7.3 |
| 68 | native | 4,567 | 278 | 279 | 5,970 | 4.53 | submission_reserve | 0.07 s (1.5 %) | 0 | < 0.66 s | < 2.4 |

Without the profiler (GPU container, 400 recorded parents, 32.2 children each, two alternating runs per
backend): Python 10.1 / 10.6 ms per `evaluate_children`, native 0.75 / 0.64 ms, network pass included.

With the leaf off the critical path the move's time is now the solver: `one_sided.select` / `utilities`
(2.1 s cumulative, 1.5 s own, at ply 5), `pcfr.policy`, and at plies 28 and 68 the per-expansion
`pcfr._native_compile` (0.96-1.13 s cumulative, of which `toy_games.information_sets` 0.64-0.68 s), which
recompiles the whole tree after every expansion.
Expansions rose 1.2-2.7x; at ply 28 the solver now reaches fewer rounds (3,041) because the tree is 2.4x larger,
and the move differed (d1f1 vs d4e5), as growth is timing-dependent.

## A3/A4/D1: the Python glue around the solver (2026-11-10)

Result: with all three kernels on, the Python work around the solver during a move is gone: no per-round dispatch
or `policy()` dictionaries, no recompilation after an expansion, no Python tree walk per growth attempt. In the
arms' configuration (1,024 rounds, depth cap 2) a move does the identical search in 0.30-0.67 s instead of
0.82-2.31 s. In the 5 s configuration (16,384 rounds, depth cap 4) the move at ply 5 reaches the round cap
(16,384 rounds, 7,680 before), and at plies 28 and 68 the agent grows 2.3-3.2x the tree in the same time. Every
result stays equal bit for bit to the Python path. One pre-existing A1 bug was found and fixed on the way (below).

### Bug fixed first: stale chance probabilities in gadget mode (A1)

`BlendedGadgetControl.apply` rewrites the gadget root's `probabilities` dict in place after every round. The
native solver compiled `chance_prob` once and never re-read it, so from the subgame agent's second move on (a
saved blueprint, hence a blended gadget) the native solver solved a stale gadget. On the branch as found: a toy
tree with a reweighted root gives strategy differences up to 0.80 between the backends, and a four-ply
`ConstantLeaf` game with the subgame agent plays a different move at ply 2 (a2a3 native vs a2b2 Python). Fix
(commit 829227e): the compiled tree keeps its chance nodes' dicts, and every kernel call re-reads them first (one
`np.fromiter`; the grown chess trees measured have one chance node, the root, with 16 entries). Test:
`test_pcfr_native.py::test_chance_probabilities_rewritten_in_place_reach_the_kernel`, and the end-to-end game
comparison below.

### Design as built

* A3, rounds in batches. Kernel `pcfr_run(s, rounds, n, *done, trace_player, trace_set, trace)` calls `pcfr_step`
  n times from the completed count (so the alternating schedule's round-0 prepare and the weight
  `(rounds+1) ** averaging_power` are per round, as in `step()`), reports the rounds completed (a pending-flag
  error mid-batch leaves `solver.rounds` correct), and optionally writes one set's published strategy after
  every round. `PCFRPlus.run(n, record=None)` uses it on the native backend; `record=(player, key)` returns the
  rows (`policy()[player][key]` after each round). It goes through `step()` when `step` was replaced on the
  class or instance (tests patch it to inject failures or advance a fake clock) or the solver is instrumented.
* A3, the agent loops. Both agents run the rounds up to the next growth check (or the round target) with one
  `run()`; with a clock a batch has at most `ROUND_BATCH = 32` rounds (class attribute, not in `AnytimeConfig`, so
  config ids are unchanged). The clock is read between batches exactly where the per-round loop read it between
  rounds, so a move stops at the same round count up to one batch: the batch is the granularity of the
  anytime agent's deadline and of the subgame agent's half-budget mark. The subgame agent keeps its
  submission-reserve rule (stop when `now + predicted >= solve_deadline`), with `predicted` = the last batch's
  time per round, one round per batch until a round has been timed, and a batch cut to the rounds that end
  before the solve deadline at that pace. Its stable-support observation takes the root policy of every round
  from `run(..., record=(0, root_infoset))` instead of `solver.policy()` per round. With a blended gadget the
  controller needs the full profile after every round and rewrites the root, so batches are one round there.
  Without a clock (round budgets) the rounds, growth checks and results are those of the per-round loop.
* A4, incremental index. `GraftIndex` (`_pcfr_native.py`, native backend only) keeps, per set, the child-index
  path of its first node (`information_sets` lists a player's sets in DFS order of first occurrence, which is the
  lexicographic order of these paths) and its own history (`_check_recall`). `expand()` grafts as before, then
  indexes only the grafted subtrees: the action-order check against existing and new sets (same message as
  `information_sets`), then perfect recall from the graft point's histories (same message), new sets inserted
  into the sorted (path, key) lists with `bisect` (a set that reappears earlier in DFS order moves, as the
  full walk would move it), `_order` by depth buckets (= the stable reverse sort). So `sets` (including its
  order), `_order` and `_depth` are what `_index_tree` returns for the whole tree; the Python backend still uses
  `_index_tree` (it stays the reference). `information_sets(subtree)` still validates each replacement, as
  before.
* A4, incremental compile. `NativeState.extend` appends the grafted subtrees' nodes (DFS within each graft) and
  points the replaced leaf's slot in its parent (and the parent's chance slot) at the new subtree; the leaf stays
  as an unreachable node. New sets get the next ids (after the existing ones) and their offsets; the state
  arrays are allocated with spare room (`_room(n) = 2n + 64`), so the new sets' state is written in place and the
  existing views (`FlatMinimizer`, `FlatDict`, the opponent snapshots) stay valid; only when the room runs out do
  the arrays move and every view is rebound. The containers gain the new sets in the order the Python path adds
  them. Levels are rebuilt from `_order` (same keys in the same order as a full compile). Grafting at the root
  (a solver whose whole tree was one cutoff) still recompiles.
* Deviation from "ids identical to a full recompile": a full compile numbers sets in `solver.sets` order (DFS
  first occurrence), so new sets are interleaved with old ones there, not appended; appending is what keeps the
  existing views valid. The two numberings differ only by a permutation of ids (and of node ids, since grafted
  nodes are appended); the kernel's results do not depend on it (a level's sets are published independently,
  walks follow child pointers), and the test compares the incremental state with a fresh compile through the
  keys and a parallel walk from the root.
* D1. Kernel `pcfr_growth_utilities(s, conditional0, conditional1)` is `OneSidedExpansion.utilities` under the
  published strategies (= `solver.policy()`, the raw last iterate) on the flat tree, in the Python walk's
  floating-point order: reach times `strategy[i]` for both players, signed values `v * 1` / `v * -1`,
  reach-weighted totals and masses accumulated in DFS order, CPython `sum()` (Neumaier, from the int 0) for
  chance nodes, node values and the zero-reach fallback mean. `OneSidedExpansion.flat_utilities(solver)` returns
  a `FlatUtilities` mapping ((player, infoset) -> {action: value} built on access from the arrays, with the
  sets and slots of the walk's time). `select()` uses it when the solver is native and the sampled tree is the
  solver's, and builds `{action: probability}` from `solver._strategy` only for the nodes on the sampled path;
  `distribution`, the `Random` draws and `commit` are unchanged. The deadline is checked before and after the
  walk instead of at every node: the walk takes about 0.012 ms on a grown 2.3k-node chess tree (the Python walk
  1.0 ms), measured outside the profiler. Python solvers keep the Python walk with `policy()`.
* Build unchanged (`python -m pair_a_prep.build_pcfr_kernel`); the manifest covers the edited kernel and loader.

### Tests

`pair_a_prep/tests/test_native_loop.py` (25 tests, 4 s on the host) plus the chance test in
`test_pcfr_native.py`:

* `run(n)` vs n x `step()` on two native solvers, bit for bit (every state array, both policies, initial
  actions): matching pennies, hidden coin, Kuhn x both schedules x averaging power 0/1/2, with initial actions,
  batches of 1, 2, 5, 0, 13, 32 starting at round 0; the recorded rows equal `policy()[0][key]` after each step.
  `run()` goes through a patched `step()`.
* Incremental compile: Kuhn poker grown layer by layer from one cutoff (the first graft replaces the root),
  both schedules, two rounds between expansions, with the spare room shrunk so the arrays move several times;
  after every expansion: `sets` (as ordered item lists), `_order`, `_depth` equal `_index_tree` of the whole
  tree; a parallel walk of the incremental and a freshly compiled `NativeState` from the root (kind, player,
  payoff, infoset key, children, chance children and probabilities; every node of the fresh compile reached);
  the same chance dicts; per key the action widths, regrets, strategies, previous utilities, sums, pending,
  depth, initial action, opponent snapshots; levels as (depth, keys). Solver state against the Python solver.
* `flat_utilities` equals `utilities(root, solver.policy())` with `==` on toy games, including pure initial
  strategies that leave sets without reach (the fallback mean).
* Recorded chess positions (3 per schedule, material leaf): a Python solver + sampler against a native solver +
  sampler with the same seed, 30 batches of 2 rounds with a growth attempt after each, as the agents do: state
  equal after every batch, flat utilities equal to the Python walk, proposals equal (path, visited sets,
  utilities, RNG state) with `policy` disabled on the native solver during `select`, samplers equal after each
  commit, and the incremental-vs-fresh compile check after every expansion.
* End to end: `ChessSubgameAgent` and `AnytimePCFRAgent` play the same four-ply `ConstantLeaf` game on both
  backends with round budgets (40 rounds, growth every 2, depth 2-4): same moves and all non-timing diagnostics
  equal (policies, values, nodes, expansions, mode switches, margins, Nash gap); the subgame agent runs its
  blended gadget from its second move. This comparison fails on the branch as found (the chance bug).

Everything compared equal with `==` / `np.array_equal`; nothing needed a tolerance (the A1 tests keep their
1e-9).

Whole suites (`pair_a_prep/tests` + `pair_b/tests/test_belief_evaluator.py`, all three backends switched
together): before 862 passed, 53 failed, 33 skipped under native and the same under python; after 888 passed
(+26 new), 53 failed, 33 skipped under native and under python. The 53 are the `test_zs21_*` tests that need
`zs21/native/inference.so` (not built on this host). One existing test needed the "one round until timed" rule:
`test_clock_ablation::test_clock_guard_cannot_interrupt_an_inflight_round`.

### Before / after (profile_move.py, all three kernels, three recorded positions, 5 s budget)

"before" = the branch as found (40227c1), "after" = be2ffcc. Module shares are own time under cProfile; the
kernel runs inside `_pcfr_native.py`'s ctypes calls, so its share now is mostly the PCFR+ rounds themselves.

16,384-round cap, depth cap 4:

| ply | run | nodes | expansions | rounds | wall s | stop | `_pcfr_native` | `pcfr` | `one_sided` | `chess_search` | move |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5 | before | 3,061 | 94 | 7,680 | 4.52 | submission_reserve | 0.70 s (15.4 %) | 0.79 s (17.5 %) | 1.55 s (34.2 %) | 0.07 s (1.6 %) | g8h6 |
| 5 | after | 3,061 | 94 | 16,384 | 4.04 | round_limit | 1.38 s (34.3 %) | 0.01 s (0.3 %) | 1.07 s (26.5 %) | 0.04 s (0.9 %) | g8h6 |
| 28 | before | 7,058 | 170 | 2,917 | 4.55 | submission_reserve | 1.13 s (24.9 %) | 0.80 s (17.6 %) | 0.54 s (11.8 %) | 0.10 s (2.2 %) | d1f1 |
| 28 | after | 16,367 | 410 | 5,328 | 4.59 | submission_reserve | 2.05 s (44.8 %) | 0.02 s (0.5 %) | 0.14 s (3.1 %) | 0.40 s (8.7 %) | d1f1 |
| 68 | before | 4,545 | 277 | 6,126 | 4.53 | submission_reserve | 1.25 s (27.7 %) | 0.67 s (14.8 %) | 0.54 s (11.8 %) | 0.08 s (1.8 %) | c5b4 |
| 68 | after | 14,499 | 842 | 4,564 | 4.59 | submission_reserve | 1.55 s (33.9 %) | 0.03 s (0.6 %) | 0.17 s (3.8 %) | 0.44 s (9.7 %) | c5b4 |

Per operation (cumulative): `PCFRPlus.expand` 11.9 ms -> 1.4 ms per expansion at ply 28 (2.02 s for 170 ->
0.57 s for 410), with no `_native_compile` or `_index_tree` after the first (`information_sets` only on each
grafted subtree); every expansion leaves one unreachable leaf in the compiled arrays; `pcfr.policy`
8,471 calls (0.73 s) at ply 5 -> one per move; `one_sided.select` 2.8 ms -> 0.43 ms per attempt at ply 5
(789 -> 4,670 attempts), the Python `utilities` walk (1.85 s) replaced by the kernel walk.

1,024-round cap, depth cap 2 (the arms' configuration): the same search before and after (same nodes,
expansions, rounds and moves; every move ends at the round cap), only faster:

| ply | run | nodes | expansions | rounds | wall s | stop | `_pcfr_native` | `pcfr` | `one_sided` | move |
|---|---|---|---|---|---|---|---|---|---|---|
| 5 | before | 929 | 19 | 1,024 | 0.82 | round_limit | 0.04 s (4.4 %) | 0.05 s (5.9 %) | 0.29 s (35.5 %) | g8h6 |
| 5 | after | 929 | 19 | 1,024 | 0.41 | round_limit | 0.03 s (6.6 %) | < 0.01 s | 0.02 s (5.9 %) | g8h6 |
| 28 | before | 1,440 | 23 | 1,024 | 1.00 | round_limit | 0.05 s (5.4 %) | 0.08 s (8.2 %) | 0.46 s (45.5 %) | d4e5 |
| 28 | after | 1,440 | 23 | 1,024 | 0.30 | round_limit | 0.04 s (12.9 %) | < 0.01 s | 0.03 s (10.6 %) | d4e5 |
| 68 | before | 2,439 | 177 | 1,024 | 2.31 | round_limit | 0.31 s (13.6 %) | 0.15 s (6.5 %) | 0.68 s (29.3 %) | c5b4 |
| 68 | after | 2,439 | 177 | 1,024 | 0.67 | round_limit | 0.07 s (10.8 %) | < 0.01 s | 0.04 s (6.1 %) | c5b4 |

### What a 5 s move spends its time on now

* The PCFR+ rounds themselves (the kernel inside `_pcfr_native._run`): 1.2-1.9 s, on trees now up to 3x larger.
* Tree construction for the expansions: `expand_chess_tree` 2.2-2.6 s cumulative at plies 28/68, of it
  `_build_roots` 1.4-1.7 s (the leaf evaluator about 0.5-1.0 s, the network pass included) and 0.26-0.30 s own
  time in `expand_chess_tree` (not attributed further; from reading the code, the per-expansion work there that
  grows with the tree is the `next_frontiers` comprehension over all frontiers).
* At ply 5, where the tree stops growing (most of 4,670 attempts sample a terminal or depth-capped path):
  `OneSidedExpansion.distribution` (1.56 s cumulative), i.e. the variance bonus recomputed with `sum()` over each
  action's whole sample list at every explorer node of every attempt. Making it incremental would change the
  floating-point order of the variance, so it needs its own exactness decision.
* Not covered by the profile (first moves only): in gadget mode `ChessGadget.expand` still builds a temporary
  `PCFRPlus` on the raw chess tree per expansion (a full native compile and `GraftIndex` walk each time), and
  batches are one round there because the controller needs the profile every round.

## D2: the cross-turn gadget path (2026-11-10)

Result: from a game's second move on, the subgame agent projects the saved tree and solves through the blended
Resolve/Maxmargin gadget; that path ran in Python and took the whole 5 s clock for trees a fresh turn builds in
0.3 s. After D2, in the arms' configuration (1,024 rounds, depth cap 2) a gadget turn takes 0.25-0.55 s instead
of 2.7-4.5 s and every one reaches the round cap (three of six stopped at the submission reserve before); in the
5 s configuration (16,384 rounds, depth cap 4) gadget turns run 4.4k-16.4k rounds instead of 304-683, and two
reach the cap. Every number stays equal bit for bit to the Python reference (tests below).

### Profile attribution before the change

`profile_move.py --game-turns 8 --rounds 1024 --max-depth 2` (all kernels, network leaf, GPU container), turns
2..8 profiled, 24.6 s:

* `BlendedGadgetControl.update` 19.1 s cumulative (5,523 calls, one per solver round), of it
  `Gadget.continuation_values` 17.6 s: per round and continuation `information_sets` twice (in
  `continuation_values` and again in `behavioral_value`, 268,661 calls, 12.4 million `visit`s, 11.7 s) and
  `_distribution` per set (174,155 calls, numpy `isclose` 2.2 s); the value walk itself 1.6 s; plus `solver.policy()`
  dictionaries every round.
* `project_chess` 2.5 s (0.32 s per turn): its saved-tree `visit` built an `Observation` per node and player
  (`rules.observe` + `asdict` + json in `_extend`, 1.8 s).
* `ChessGadget.expand` 1.57 s for 110 calls (14 ms each): a temporary `PCFRPlus` on the whole raw chess tree per
  expansion (full index and native compile), then the whole gadget again (`roots.build` -> `build_gadget`:
  namespace check and clone of every continuation and a second `PCFRPlus` on the gadget tree for validation).
* Batches of one round in gadget mode (the controller needs the profile after every round).

### Design as built

Switch: `Gadget.FAST` = `FOW_GADGET_FAST` != "0" (default on). Off, every piece below takes the code path as it
was before D2 (and gadget batches stay one round); that is the reference side of the tests.

* Values, validated once (`gadgets.py`). `toy_games.value_walk` is `behavioral_value`'s walk factored out (same
  expression, same order). `Gadget.round_values(profile)` validates each part of the continuations once, exactly
  as `continuation_values` validates a continuation (information sets, profile restricted to them,
  `behavioral_value`'s checks and errors): on a new gadget every whole continuation in order (so its first call
  raises what `continuation_values` raises), on a gadget regrown by an expansion only the grafted subtrees; then
  it only walks. The parts still to validate are `Gadget._unchecked` (absent = all continuations).
  `BlendedGadgetControl.update` uses `round_values`. Why skipping is safe: a continuation never changes once
  built (an expansion returns a new `Gadget`, path-copied), and the per-round profile is the solver's, whose
  strategies are distributions over exactly its sets by construction.
* Native value walk. Kernel `pcfr_behavioral_values(s, n, nodes, values)`: `value_walk` of the subtrees at flat
  node ids under the published strategies (= `policy()`), CPython's compensated `sum()` over children in children
  order (a chance node's probability looked up per child, since `chance_prob` follows the probabilities dict's
  order). `Gadget.native_nodes(solver)` (blended gadget whose tree is the solver's root) validates the pending
  parts with the solver's profile restricted to their sets and returns the continuations' node ids from the
  root's child slots (`tree.children[root_id]` is the continuation: the same object until the first expansion,
  after it the solver's graft of the same structure, which the tests check). `Gadget.solver_values(solver)` =
  `round_values(solver.policy())` without the dictionaries.
* Controller in the kernel. `BlendedGadgetControl.run(gadget, solver, rounds, record)` = `rounds` x
  (`solver.run(1, record)` + `update_from_solver`); returns the recorded root rows and the mode after each round.
  Native path (FAST, native solver on this gadget's tree, none of `step` / `run` / `_utilities` / `_advance` /
  `update_from_solver` / `solver_values` / the controller's PRM+ methods replaced): one call to
  `pcfr_run_gadget` = per round `pcfr_step`, the root trace, then `control_advance`: the continuations' value walk;
  group means `fsum(reach * value) / fsum(reach)` with a port of CPython 3.12's `math.fsum` (exact partials and
  the half-even correction; the denominators are Python's `fsum`, passed in); `margins = entering - alternate`;
  per group R_J's PRM+ `observe([-entering, -alternate])` and `next_strategy()`, then the selector's on the
  negated margins, with numpy's operation order (`(regrets + u) - dot(strategy, u)` with the A1 BLAS `dot`, the
  pairwise sum for `theta.sum()`, `1.0 / n` when it is not positive); `p_max` = the first largest; `apply()`'s
  probabilities `(p_max * alpha * pi_resolve + (1 - p_max) * pi_maxmargin) * reach / mass` and
  `p_max * alpha * (1 - pi_resolve)` written into the root's `chance_prob` slots. The controller's PRM+ arrays,
  blend, `p_max`, margins and the root's probabilities dict are written back after the call (same keys, same
  order). Kernel codes -3 / -4 map to PredictiveRMPlus's finiteness errors. `BlendedGadgetControl.history`
  (class attribute, default None) is a list that receives every round's numbers on both paths (tests).
  `ChessSubgameAgent.solve` calls `control.run` and counts switches from the per-round modes; gadget batches follow
  the ordinary batch rule (to the next growth check, at most `ROUND_BATCH` with a clock).
* Expansion (`chess_gadgets.py`). A blended bridge keeps the raw structural solver it grew (`ChessGadget.raw_solver`,
  `compare=False`), reused while its root is the bridge's raw root, so its `expand()` indexes only the graft
  (GraftIndex); otherwise one is built as before. `gadgets.regrow_blended(gadget, roots, grafts, prior, tree)`
  replaces `roots.build`: namespace check on the grafted raw subtrees, `_clone` of only those, path-copied into the
  previous clone (`_graft_clone`; equal to cloning the grown continuation whole), untouched continuations
  shared, `root_prior` computed as `build_gadget` does, grafted clones queued for validation. The whole-gadget
  `PCFRPlus` validation of `build_gadget` is not repeated: the raw graft was validated on the whole raw tree
  (action order, perfect recall), which implies both for the gadget tree (player 0's keys and histories are the
  raw ones; player 1's are the raw ones refined by group), and the trained solver's `expand()` validates the
  gadget graft again. Replacements are read from the regrown continuations.
* Projection (`chess_projection.py`, not FAST-gated). The saved-tree walk extends memories with
  `_extend_key(memory, rules.observation_key(state, p), move)`: the adapter's `observation_key` is
  `observation_key(observe(...))` by definition on Python and equal to it on the native rules (B1).
* Agent (not FAST-gated). The gadget-path view of the chess frontiers (a map over all frontiers) was rebuilt on
  every growth attempt; it is now rebuilt only when `projection.tree` or `solver.root` changes. In the 16k-round
  profile this was 6.1 s of `solve`'s own time over seven turns.
* Build unchanged (`python -m pair_a_prep.build_pcfr_kernel`; the manifest covers the edited kernel and loader).

Cached vs native: the profile validation and the per-continuation structure walks are cached (validated once
per part); the value walk, the controller and the round loop between growth checks are native; the expansion's
raw solver is kept and the gadget rebuilt incrementally in Python; the projection walk stays Python with the
cheaper observation keys.

### Tests

`pair_a_prep/tests/test_gadget_native.py` (11 tests, ~9 s native, ~21 s under the python setting):

* `round_values` and `solver_values` equal `continuation_values` (by `repr`) every round for 40 rounds of a toy
  blended gadget (three roots in two groups, a continuation with a chance node whose probabilities dict is ordered
  unlike its children, a cutoff continuation), both schedules; controls on a Python and a native solver agree.
* Validation: the first call raises the `continuation_values` errors (bad distribution, missing set), a gadget
  rebuilt by `replace` validates again, with FAST off every call validates; a regrown toy gadget (grafts at a
  continuation's root and below a player-1 node) equals a fresh `build_gadget` (continuations by `Node ==`, order,
  roots, alternates, `root_prior` by `repr`), shares untouched clones, queues exactly the grafts, and rejects a
  profile without the grafted sets or with an invalid distribution there.
* `BlendedGadgetControl.run` in the kernel against the per-round loop on the Python solver with FAST off: both
  schedules x predictive on/off, batches 1, 3, 7, 0, 5: recorded rows, modes, PRM+ state, blend, margins, root
  probabilities, solver policies (last and average) and the per-round history, all by `repr`; an instrumented
  `_advance` falls back to the loop.
* End to end: three recorded games of `solver-v2-sf8-g237`, seven consecutive own turns each, through one
  `ChessSubgameAgent` (material leaf, 48 rounds, growth every 2, depth 1/2, no clock): the reference (Python
  solver, FAST off, observation keys through `observation_key(observe(...))`) against the native path. Per turn:
  move, raw root policy, all non-timing diagnostics, the final profile, the projection (root ids, groups, current
  ids, aliases, audit, paths, frontiers, memories, boundaries with alternates, gifts, prior, audit and reach
  masses) and the final tree (`Node ==`), and per round the controller's values, margins, `pi_resolve`,
  `pi_maxmargin`, `p_max`, mode and root distribution. On every fast expansion the bridge equals what `roots.build`
  makes from the same grown chess tree, the solver's grafted continuations equal the gadget's, the kept raw
  solver's sets equal a fresh index, and every queued validation part is a subtree of its continuation. 15 of
  the 21 turns solve through the gadget (all 720 of their rounds in the kernel), with mode switches on 11. The
  comparison detects a one-ulp change of the native values (checked by perturbing them with `nextafter`).

Everything compared equal with `repr` / `==`; nothing needed a tolerance.

Whole suites (`pair_a_prep/tests` + `pair_b/tests/test_belief_evaluator.py`, the three backends switched
together): before 888 passed, 53 failed, 33 skipped under native and under python; after 899 passed (+11),
53 failed, 33 skipped under both. The 53 are the pre-existing `test_zs21_*` failures (library not built here).

### Before / after (profile_move.py, all kernels, network leaf, GPU container, 5 s budget)

"before" = 45a36db, "after" = bb6dd05. One recorded game (`...51001` as Black), eight consecutive own turns;
turn 1 is fresh. The harness restarts a turn fresh when the label agent's recorded move had zero probability
under this agent ("refused", a harness artifact). Module shares are own time over turns 2..8.

1,024 rounds, depth cap 2 (the arms' configuration):

| turn (ply) | run | wall s | nodes | rounds | expansions | switches | stop | move |
|---|---|---|---|---|---|---|---|---|
| 1 (5) fresh | before / after | 0.33 / 0.32 | 929 / 929 | 1,024 / 1,024 | 19 / 19 | 0 / 0 | round_limit | g8h6 / g8h6 |
| 2 (9) | before / after | 4.33 / 0.36 | 1,145 / 1,197 | 1,024 / 1,024 | 25 / 27 | 0 / 0 | round_limit / round_limit | b8c6 / b8c6 |
| 3 (11) | before / after | 4.52 / 0.55 | 1,775 / 2,169 | 639 / 1,024 | 25 / 40 | 0 / 0 | submission_reserve / round_limit | g7c3 / g7c3 |
| 4 (13) | before / after | 4.52 / 0.51 | 1,495 / 1,496 | 809 / 1,024 | 29 / 29 | 0 / 0 | submission_reserve / round_limit | b5b4 / b5b4 |
| 5 (17) | before / after | 2.72 / 0.25 | 613 / 613 | 1,024 / 1,024 | 1 / 1 | 0 / 0 | round_limit | c6b5 / c6b5 |
| 6 (21) | before / after | 4.51 / 0.37 | 1,207 / 1,207 | 1,003 / 1,024 | 23 / 23 | 0 / 0 | submission_reserve / round_limit | h6g4 / h6g4 |
| 7 (25) | before / after | 3.37 / 0.31 | 885 / 885 | 1,024 / 1,024 | 7 / 7 | 0 / 0 | round_limit | g4f6 / g4f6 |
| 8 (27) refused, fresh | before / after | 0.44 / 0.47 | 2,342 / 2,342 | 1,024 / 1,024 | 49 / 49 | 0 / 0 | round_limit | d6e5 / d6e5 |

Where the clock did not cut the move before (turns 5, 7) the search is identical; elsewhere the old path stopped
growing at the growth deadline or the reserve. Same moves on every turn. Turns 2..8 profiled: 24.6 s -> 2.9 s;
`toy_games` 12.51 s (50.9 %) -> 0.13 s (4.4 %), `chess/` 2.32 s -> 0.08 s, `pcfr` 0.93 s -> 0.02 s,
`_pcfr_native` 0.68 s -> 0.36 s (12.5 %), `_rules_native` 0.49 s -> 0.41 s (14.3 %, now the largest). Per step
(same profile, turns 2..8): 24.6 s; values cached + kernel walk (183e20c) 8.4 s; expansion and projection
(e1a534b) 5.3 s; per-continuation validation and the controller in the kernel (b52c0f7, 3e1e6ee) 3.4 s; frontier view (7c26fc3) 3.0 s; grafts only (bb6dd05)
2.9 s. Per operation: `ChessGadget.expand` 14 ms -> 4.8 ms per call (of which the leaf and rules in
`expand_chess_tree` most), `project_chess` 0.32 s -> 0.12 s per turn (mostly `_build_roots` for fresh roots and
the leaf), the controller 3.5 ms per round (Python, one-round batches) -> `BlendedGadgetControl.run` 0.20 ms per
two-round batch, both PCFR+ rounds included.

16,384 rounds, depth cap 4 (searches differ after turn 1: the clock ends most turns, and a larger tree gives
other moves):

| turn (ply) | run | wall s | nodes | rounds | expansions | switches | stop | move |
|---|---|---|---|---|---|---|---|---|
| 1 (5) fresh | before / after | 3.31 / 3.13 | 3,061 / 3,061 | 16,384 / 16,384 | 94 / 94 | 0 / 0 | round_limit | g8h6 / g8h6 |
| 2 (9) | before / after | 4.52 / 4.56 | 1,798 / 5,930 | 683 / 15,279 | 47 / 191 | 11 / 18 | submission_reserve | b8c6 / f8g7 |
| 3 (11) | before / after | 4.52 / 4.59 | 2,174 / 7,961 | 488 / 10,432 | 32 / 136 | 0 / 0 | submission_reserve | g7c3 / g7c3 |
| 4 (13) | before / after | 4.53 / 3.71 | 2,630 / 2,989 | 371 / 16,384 | 64 / 76 | 0 / 0 | submission_reserve / round_limit | b5b4 / b5b4 |
| 5 (17) | before / after | 4.53 / 3.62 | 2,232 / 3,058 | 592 / 16,384 | 47 / 70 | 10 / 8 | submission_reserve / round_limit | c6b5 / c6b5 |
| 6 (21) | before / after | 4.54 / 4.64 | 2,956 / 12,627 | 304 / 4,386 | 74 / 357 | 0 / 0 | submission_reserve | h6g4 / h6g4 |
| 7 (25) | before / after | 4.53 / 4.61 refused, fresh | 1,961 / 16,373 | 666 / 5,829 | 36 / 424 | 0 / 0 | submission_reserve | g4f6 / d8c7 |
| 8 (27) | before / after | 4.60 refused, fresh / 4.65 | 16,379 / 10,888 | 5,921 / 6,403 | 427 / 270 | 0 / 0 | submission_reserve | c8b7 / c8b7 |

Own time, turns 2..8 (31.5 s / 30.7 s profiled): `toy_games` 12.10 s (38.4 %) -> 0.73 s (2.4 %); `_pcfr_native`
4.03 s (12.8 %) -> 12.67 s (41.2 %, the kernel's rounds now); `chess/` 1.95 -> 0.52 s; `_rules_native` 1.08 ->
1.76 s (more expansions); `pcfr` 0.92 -> 0.19 s; `chess_search` 0.61 -> 1.07 s; `one_sided` 0.15 -> 0.82 s.

Single positions (`--moves 3 --rounds 1024 --max-depth 2`, fresh turns only), before -> after: ply 5 0.39 ->
0.40 s, 929 nodes, 19 expansions, g8h6; ply 28 0.32 -> 0.32 s, 1,440 nodes, 23 expansions, d4e5; ply 68 0.67 ->
0.64 s, 2,439 nodes, 177 expansions, c5b4. Unchanged.

### What is not exact, and where

No deviation measured: every compared quantity is bit-equal (repr). Differences by construction, none
reachable by the agent's inputs:

* Validation timing. Per-round profiles and unchanged continuation parts are not re-validated; a malformed
  profile passed to `round_values` after its first validation is evaluated (or raises KeyError) instead of being
  rejected. On the expansion fast path the gadget-tree validation is left to the trained solver's `expand()`, so
  an invalid graft would raise there, after the deadline check, instead of in `build_gadget` before it (the raw
  graft, validated first, makes this unreachable).
* Clock granularity. With a clock, gadget batches now hold up to `ROUND_BATCH` rounds (one before), as for fresh
  turns since A3: the half-budget mark and the deadline are read between batches. Without a clock the rounds,
  growth checks and results are those of the per-round loop (FAST off keeps one-round batches).
* Kernel arithmetic reproduces numpy and CPython for finite values: `np.maximum(x, 0)` is `x >= 0 ? x : 0`
  (they differ only for -0.0 and NaN, which the regret updates cannot produce: regrets start at +0 and `a + b`
  is -0.0 only if both are), and the `math.fsum` port has no special-value handling (inf / NaN / overflow; the
  values come from finite payoffs). The BLAS `dot` caveat of A1 applies.

### What a gadget-mode move spends its time on now

16,384-round profile, turns 2..8 (30.7 s): the kernel's PCFR+ rounds and controller 10.9 s own in
`_pcfr_native._run`; tree growth `expand_chess_tree` 6.7 s cumulative (`_build_roots` with the leaf 4.5 s);
`PCFRPlus.expand` 3.5 s cumulative over 2,624 calls (the trained gadget solver and the raw structural solver),
of which `deepcopy` of the grafted subtree 2.4 s; `one_sided.select` 2.6 s (24.6k growth attempts); per-batch
setup of the native controller (`_run_native` own 1.8 s: 24.8k batches of two rounds, arrays and the ctypes
structure built each time); `solve`'s own loop 1.7 s; `project_chess` 2.2 s (0.31 s per turn, mostly fresh roots'
`_build_roots`). Obvious next steps: keep the controller's arrays across batches, graft without `deepcopy` in the
raw structural solver, and the A3 note on `next_frontiers` in `expand_chess_tree`.

## D3/C: the last glue, and the round kernel on several threads (2026-11-10)

Result: the per-batch and per-expansion Python glue named at the end of D2 is gone (D3), and the PCFR+ kernel can
walk the tree on several threads (C). Everything stays bit-equal: D3 changes no number, and the multi-threaded
kernel gives the single-thread results bit for bit for every thread count (no tolerance was needed; see
"Exactness"). In the arms' configuration (1,024 rounds, depth cap 2) the gadget turns are 25 % faster than after D2
with the identical search; in the 5 s configuration the kernel's throughput on the profiled game rises 1.2x / 1.6x
/ 1.8x with 2 / 4 / 6 threads (rounds x nodes per second of kernel time), and on fixed chess trees 2.7x (8.7k nodes)
and 3.0x (24.9k nodes) with 6 threads. One thread is as fast as before C. Threads are opt-in: `FOW_PCFR_THREADS`
(default 1).

### D3 design (all exact)

1. Controller arrays kept across batches (`subgame_boundaries.BlendedGadgetControl._session`). The fixed numbers of
   `pcfr_run_gadget` (reach masses, groups, alternates, alpha, group masses, chance slots, the `Control` structure)
   are built once per (gadget, compiled solver state, root distribution dict and its keys, history on/off) and
   kept; the continuations' node ids are rewritten before every call. The R_J and selector minimizers hold views
   of the kernel's state arrays, so after a call their state is the kernel's without copies; before a call a
   minimizer whose array was replaced in Python (`PredictiveRMPlus.observe` / `next_strategy` assign new arrays,
   e.g. a Python `update_from_solver` round in between) is copied in, and in-place writes go through the views.
   Pending flags, `pi_resolve`, `pi_maxmargin`, `p_max`, margins and the root's probabilities dict are written back
   after every call as before (`.tolist()` instead of per-element `float()`, same values). Semantic change: a
   reference to `control.entry[J].regrets` kept across a kernel call now sees the new values (before, the call
   replaced the array); nothing in the code keeps one.
2. Grafts without `deepcopy` (`PCFRPlus.expand(copy=False)`; default `copy=True`). Aliasing, as verified in the
   code: `expand_chess_tree` builds each replacement with `_build_roots` in the same call (`Node`, `terminal()`,
   `frontier()` all create new objects; the evaluation cache holds value dicts, not nodes), and the only other
   references are the local `ChessTree` of the temporary builder (discarded) and `initialize_best`'s read-only
   walk; so the grafted subtree is referenced by the solver's tree alone, as the copy was. `ChessGadget.expand`'s
   fast path grafts `regrow_blended`'s fresh clones (`_clone` creates every node and copies every probabilities
   dict); they are also reachable from the regrown gadget's `continuations` and its pending validation parts. That
   sharing is the one a blended gadget has from its construction (`tree.children[root_id] is continuations[root_id]`
   until the first expansion), and no code mutates a `Node` in place (expansions path-copy; the only in-place write
   is the controller's rewrite of the gadget root's probabilities dict, which is not inside any graft). The
   reference path (`roots.build`) and all other callers still copy.
3. Frontier map. `expand_chess_tree` copies the frontier dict and deletes the selected paths instead of filtering
   every frontier through a comprehension (same keys, values and order; the given tree stays as it was). The
   subgame agent's gadget-path view of the frontiers (`chess_subgame_agent.GadgetFrontiers`) is built once per turn
   and then updated per expansion by the selected and the appended frontiers (`expand_chess_tree`'s frontiers are
   the previous ones without the selected, then the new ones), instead of a rebuild over all frontiers;
   `GadgetFrontiers.CHECK` (on in the recorded-game replay test) compares it with a rebuilt view after every update.
4. Projection. The saved-tree walk is now `chess_projection.saved_cut`; it computes a node's private memories (two
   `_extend_key` chains) only where they are used, at the cut and on the way to it, not for terminal children and
   incomplete leaves (55 % of the visited nodes on the profiled game). `_extend_key` encodes with one module-level
   `json.JSONEncoder(separators=(",", ":"))`: `json.dumps` with separators builds that encoder on every call (same
   payload; 1.77 -> 1.32 us per key unprofiled).
5. Larger batches: nothing to do without changing results. A batch already runs up to the next growth check
   (`rounds_per_stage` = 2 rounds in the agents' configuration) and up to `ROUND_BATCH` once growth has stopped. A
   growth check cannot be skipped: `OneSidedExpansion.select` draws from the sampler's RNG and reads the solver's
   strategies at that round. The only check that is always a no-op is inside the final-rounds window, which is one
   batch (`final_rounds` = 2). Raising `ROUND_BATCH` would change the clock granularity, so it was left.

### C design

* Root-parallel walks (`pcfr_kernel.cpp`, OpenMP). With more than one thread and a tree of at least
  `FOW_PCFR_PARALLEL_NODES` nodes (default 1,024), the utilities walk (observe, `pcfr_utilities`), each level of
  the prediction walk, the average walk and the growth-utilities walk visit the root's children as parallel tasks
  (`schedule(dynamic, 1)`; 16 hypotheses on a fresh chess tree, roots plus exits on a gadget). A task does not add
  into the shared per-action arrays: it appends each addition it would make (a set's offset and the products
  `reach * action_values[i]`; for the growth walk the set, reach and signed values; for the average the first
  visit of each set and its own reach) to a log of its own, in DFS order. After the tasks the logs are applied in
  root order, then the root's own operations (its contribution to its set, the memo of the prediction walk), as the
  sequential `visit(0)` does after its children. Memo entries of the prediction walk are per node and written by
  the task that owns the node.
* The per-set loops (observe's regret update, the publishes of a prediction level) run in parallel chunks of 32
  sets when the walk does and there are at least 64 sets; they are independent per set. The controller's
  continuation values and `pcfr_behavioral_values` walk their subtrees in parallel (pure functions).
* Threads: `FOW_PCFR_THREADS` read when the library is loaded, `_pcfr_native.set_threads(n, min_nodes)` at run
  time (`pcfr_set_threads`), default 1. With one thread, or a smaller tree, the sequential code runs.
  `pcfr_parallel_walks()` counts root-parallel walks (tests and profiles check that the path ran). The profiles
  set the variable inside the container's Python before the library loads (`torch_port.sh` passes no `-e`; the
  container sees all 12 host cores); the count of parallel walks is printed with each run.
* Build: `-fopenmp` added (`build_pcfr_kernel.py`); libgomp stays a shared library (`libgomp.so.1` exists on the
  host and in `fow-portability:probe`). The walks are templates on `kLog`; the sequential instantiation is the code
  as before C. With the parallel code in the unit, g++ 11's `inline-unit-growth` limit stopped inlining `dot()` into
  the sequential prediction walk and one thread ran 10-15 % slower than the D3 kernel (8.7k-node tree 6.3k vs 7.9k
  rounds/s); the build passes `--param inline-unit-growth=100`, which restores it (7,674 vs 7,675 and 2,102 vs
  2,015 rounds/s on the 8.7k / 24.9k-node trees, same host run, D3 kernel built separately; `-fopenmp` alone made
  no measurable difference). Commit 6987d79.
* Memory: no per-thread infoset buffers. Per root child one log (cache-line aligned, reused across calls; its
  capacity is the largest subtree contribution seen) and per thread the walk stack. On a 25,574-node chess tree:
  utility logs 0.14 MB (player 0: 707 nodes, 16,569 actions at them) and 0.07 MB (player 1), growth log 0.22 MB in
  total over all tasks, stack 0.20 MB per thread, `seen` flags one byte per set per thread.

### Exactness

* D3: bit-equal by construction (identical arithmetic; only object identity, copying and where a pure function is
  evaluated change). Tests: `test_gadget_native.py::test_control_session_follows_python_writes_between_kernel_calls`
  (kernel batches interleaved with a Python controller round, in-place writes and a new gadget object, against the
  all-Python reference, both schedules; skipping the copy-in of replaced arrays fails it);
  `test_native_loop.py::test_chess_grafts_without_copy_equal_copied_grafts` (copy-free vs copying growth on
  recorded positions: trees, frontiers in order, counters, solver state and compiled state equal; the previous
  tree unchanged; grafted nodes are new objects; the frontier order is the comprehension's);
  `GadgetFrontiers.CHECK` in the recorded-game replay (appending the new frontiers in reverse order fails it);
  `test_chess_search.py::test_extend_key_matches_json_dumps`; `test_gadget_native.py::test_saved_cut_equals_an_eager_walk`
  (the pre-D3 eager walk against `saved_cut` on two recorded games' saved blueprints: paths, node identities,
  states, memories, moves and incomplete counts).
* C: bit-equal for every thread count. Why: every floating-point operation of the parallel walk is the one the
  sequential walk performs on the same operands; only the additions into shared per-action (and per-set) arrays
  could change order, and the logs replay them in the sequential order (root children in visit order, DFS within
  each); the root's own operations follow, as in the sequential walk. Sums over a node's children (dot products,
  compensated sums) stay inside one task. So the requested 1e-12 tolerance and the drift question do not arise:
  the measured deviation is 0 in every compared quantity and round. Tests: `test_pcfr_threads.py` (9 tests: toy
  games x both schedules, 40 rounds; the toy blended gadget through `BlendedGadgetControl.run` with history; two
  recorded positions x both schedules grown by one-sided growth for 25 batches of 2 rounds (to 400+ nodes) with
  the parallel path forced on every tree size: 1 thread against 2, 4 and 6, with `==` on every state array, the
  policies, the recorded root rows, the flat growth utilities and the behavioral values, every batch). Mutation
  checks: replaying the logs in reverse root order (utilities, prediction or growth walk) or ignoring the global
  first-visit flag of the average fails them. The whole suite with `FOW_PCFR_THREADS=6 FOW_PCFR_PARALLEL_NODES=0`
  (every native solver on 6 threads, every tree parallel) gives the same counts as with 1 thread. The A1 caveat
  stays: the sequential kernel reproduces this host's OpenBLAS `ddot`; that is unchanged by threads.

### Tests

Whole suites (`pair_a_prep/tests` + `pair_b/tests/test_belief_evaluator.py`, the three backends switched together):
before 899 passed, 53 failed, 33 skipped under native and under python; after D3 904 passed (+5), 53 failed, 33
skipped under both; after C 913 passed (+9), 53 failed, 33 skipped under native, under python, and under native with
6 threads forced on every tree. The 53 are the pre-existing `test_zs21_*` failures (library not built here).

### Before / after (profile_move.py, all kernels, network leaf, GPU container, 5 s budget)

"before" = b805764 (end of D2), "D3" = 44caad8, "C" = 6987d79 with `FOW_PCFR_THREADS` = 1, 2, 4, 6. Cells are nodes /
rounds of the turn ("cap" = stopped at the round cap, else at the submission reserve; "f" = the projection was
refused and the turn started fresh), then wall. After turn 1 the searches differ between runs (the clock decides
growth and rounds), so compare totals and like-sized turns.

16,384 rounds, depth cap 4, one game (`...51001` as Black), turns 2..8 profiled:

| run | turn 1 (ply 5) | 2 (9) | 3 (11) | 4 (13) | 5 (17) | 6 (21) | 7 (25) | 8 (27) | profiled s | `_pcfr_native` own | `chess_search` | `one_sided` | `chess_projection` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| before (b805764) | 3,061 / 16,384 cap, 3.19 s | 5,930 / 15,730, 4.56 s | 7,871 / 10,630, 4.59 s | 2,989 / 16,384 cap, 3.73 s | 3,058 / 16,384 cap, 3.59 s | 12,558 / 4,310, 4.63 s | 16,373 / 5,645 f, 4.61 s | 10,738 / 6,306, 4.66 s | 30.74 | 12.91 | 0.97 | 0.82 | 0.16 |
| D3 (44caad8) | 3,061 / 16,384 cap, 3.24 s | 6,131 / 16,384 cap, 4.35 s | 9,330 / 11,731, 4.60 s | 16,280 / 5,369 f, 4.60 s | 3,103 / 16,384 cap, 4.09 s | 16,345 / 4,896, 4.67 s | 16,373 / 7,297 f, 4.62 s | 14,223 / 6,865, 4.68 s | 32.08 | 15.68 | 1.05 | 1.96 | 0.45 |
| C, 1 thread | 3,061 / 16,384 cap, 3.35 s | 6,159 / 16,384 cap, 4.30 s | 11,018 / 9,978, 4.62 s | 4,696 / 16,384 cap, 4.05 s | 3,155 / 16,384 cap, 2.87 s | 16,345 / 4,800, 4.68 s | 16,373 / 7,618 f, 4.62 s | 14,027 / 6,855, 4.66 s | 29.96 | 15.83 | 1.09 | 0.95 | 0.16 |
| C, 2 threads | 3,061 / 16,384 cap, 2.98 s | 6,798 / 16,384 cap, 4.11 s | 7,650 / 14,731, 4.59 s | 16,374 / 6,371 f, 4.61 s | 3,103 / 16,384 cap, 4.36 s | 16,345 / 6,275, 4.69 s | 16,373 / 9,539 f, 4.62 s | 14,658 / 7,948, 4.67 s | 32.20 | 15.24 | 1.22 | 2.01 | 0.40 |
| C, 4 threads | 3,061 / 16,384 cap, 2.91 s | 6,188 / 16,384 cap, 4.26 s | 10,687 / 13,534, 4.62 s | 6,608 / 16,384 cap, 4.11 s | 3,573 / 16,384 cap, 3.31 s | 16,359 / 9,356, 4.68 s | 16,373 / 14,173 f, 4.62 s | 15,174 / 9,461, 4.69 s | 30.64 | 14.41 | 0.93 | 1.26 | 0.35 |
| C, 6 threads | 3,061 / 16,384 cap, 2.66 s | 6,245 / 16,384 cap, 4.29 s | 12,042 / 14,101, 4.64 s | 5,477 / 16,384 cap, 3.74 s | 4,713 / 16,384 cap, 3.79 s | 16,359 / 10,177, 4.69 s | 16,373 / 16,384 cap f, 4.50 s | 15,174 / 10,109, 4.68 s | 30.27 | 14.20 | 1.14 | 1.22 | 0.26 |

Per operation, before -> D3 (cumulative over turns 2..8 of one profiled run each; the D3 numbers from a second run
of 44caad8 dumped with pstats): controller work outside the kernel call 130 us -> 44 us per batch
(`_run_native` cumulative minus `run_gadget`: 3.25 s over 24,964 batches -> 1.13 s over 25,740); `PCFRPlus.expand`
1.41 -> 0.44 ms per call (3.67 s / 2,604 -> 1.48 s / 3,366), `deepcopy` 2.42 -> 0.07 s (left: retained subtrees in
the projection, `rebase_solver`); `expand_chess_tree` own 0.32 -> 0.11 ms per call; `solve` own 1.43 -> 0.43 s;
saved-tree walk 36 -> 27 us per visited node under the profiler, memories for 45 % of the visited nodes;
`project_chess` stays about 0.26 s per turn under the profiler (the saved-tree walk 0.17 s, of which the native
terminal check per node, which now pays the board analysis that the parent's observation key paid before; fresh
roots' `_build_roots` with the leaf; `reconstruct_roots`). Like-sized turns: turn 6 (16,345 nodes in every run from
D3 on) 4,896 rounds (D3), 4,800 / 6,275 / 9,356 / 10,177 with 1 / 2 / 4 / 6 threads; turn 7 (fresh, 16,373 nodes,
424 expansions in every run) 5,645 / 7,297 / 7,618 / 9,539 / 14,173 / 16,384 (the cap, in 4.50 s) for
before / D3 / C x 1, 2, 4, 6.

1,024 rounds, depth cap 2 (the arms' configuration): the identical search in every run (same nodes, expansions,
rounds and moves on all eight turns, every turn at the round cap), only faster:

| run | turn 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 (f) | profiled s (turns 2..8) |
|---|---|---|---|---|---|---|---|---|---|
| before (b805764) | 0.33 s | 0.36 s | 0.60 s | 0.53 s | 0.26 s | 0.41 s | 0.32 s | 0.49 s | 3.04 |
| D3 (44caad8) | 0.30 s | 0.26 s | 0.45 s | 0.41 s | 0.19 s | 0.31 s | 0.24 s | 0.37 s | 2.29 |
| C, 1 thread | 0.33 s | 0.28 s | 0.45 s | 0.42 s | 0.18 s | 0.31 s | 0.23 s | 0.36 s | 2.27 |
| C, 6 threads | 0.33 s | 0.27 s | 0.45 s | 0.41 s | 0.18 s | 0.30 s | 0.23 s | 0.45 s | 2.28 |

(nodes / expansions per turn: 929 / 19, 1,197 / 27, 2,169 / 40, 1,496 / 29, 613 / 1, 1,207 / 23, 885 / 7,
2,342 / 49; moves g8h6, b8c6, g7c3, b5b4, c6b5, h6g4, g4f6, d6e5 in every run.) These trees are at most 2.3k nodes
and spend little time in rounds, so threads do not help here; the 6-thread run is the same search, end to end.

Single positions, `--moves 3 --rounds 16384 --max-depth 4` (nodes / rounds / stop / move):

| ply | before | D3 | C, 1 thread | C, 6 threads |
|---|---|---|---|---|
| 5 | 3,061 / 16,384 cap, 4.02 s, g8h6 | 3,061 / 16,384 cap, 3.94 s, g8h6 | 3,061 / 16,384 cap, 3.95 s, g8h6 | 3,061 / 16,384 cap, 3.75 s, g8h6 |
| 28 | 16,367 / 6,026, c3d5 | 16,367 / 7,078, c3d5 | 16,367 / 7,299, c3d5 | 16,367 / 16,327, c3d5 |
| 68 | 14,730 / 4,647, c5b4 | 16,377 / 4,951, c5b4 | 16,377 / 4,542, c5b4 | 16,377 / 9,980, c5b4 |

### Thread scaling

Kernel only, outside the profiler (`/home/dev/d3c-work/bench.py`, not committed): native solver on recorded chess
trees (material leaf, 16 hypotheses), alternating schedule, best of three runs of 300 rounds, host Python, other
jobs using 2-3 of the 12 cores. "equal" = the state arrays after the runs compared bit-equal across thread counts.

| tree | nodes | 1 thread | 2 threads | 4 threads | 6 threads |
|---|---|---|---|---|---|
| depth 1 | 369 | 337k rounds/s | sequential (below 1,024 nodes) | | |
| depth 1, a quarter of the frontiers grown | 2,450 | 26.6k | 30.1k (1.13x) | 39.5k (1.49x) | 44.6k (1.68x) |
| depth 2 | 8,666 | 7.52k | 10.8k (1.44x) | 16.7k (2.23x) | 20.1k (2.68x) |
| depth 2, a twelfth of the frontiers grown | 24,883 | 1.99k | 2.91k (1.46x) | 4.59k (2.30x) | 6.01k (3.01x) |

In the profiled game (16k-round profile above, kernel time = `_pcfr_native._run` own time, which holds the kernel
calls), rounds x nodes per second of kernel time: 46.2M (1 thread), 56.0M (2, 1.21x), 76.0M (4, 1.65x), 84.6M (6,
1.83x); rounds over turns 2..8: 78.4k, 77.6k, 95.7k, 99.9k. Parallel walks counted in the container: 0, 836k,
1.01M, 1.04M (the variable reached the kernel). Same tree, same clock: ply 28 of the single positions 7,299 rounds
(1 thread) vs 16,327 (6 threads); ply 68 4,542 vs 9,980.

Why not more: a walk on these trees takes 30-100 us, so a task (one hypothesis subtree) is a few microseconds; the
replay of the logs and the root's own operations are sequential (the replay alone 3.5 of 57 ms per 300 rounds, 6 %,
of a 6-thread run on the 25k-node tree in an instrumented build); the root has 16 children, unevenly sized (397-877 nodes on the depth-2 tree); prediction levels are
sequential by construction. The hardware is not the limit (a compute-bound OpenMP loop scales 5.9x on 6 threads
here) and an OpenMP region costs 0.4-0.7 us.

### What remains

* Kernel scaling: write directly (no log) for information sets confined to one root subtree (most opponent sets);
  apply the logs in parallel over disjoint action ranges; one parallel region per `pcfr_run` with barriers
  between phases instead of a region per walk. Each keeps the results exact if the addition order is kept.
* `project_chess` about 0.26 s per profiled turn (saved-tree walk with a board analysis per node, fresh roots'
  `_build_roots` with the leaf): the next step would be the saved-tree walk in the rules kernel.
* `OneSidedExpansion.distribution` (variance bonus, 1.2-2.7 s cumulative per profiled game): its
  incremental form changes the floating-point order (A3/A4 note), so it needs an exactness decision first.
* The anytime agent's per-growth scans over all frontiers (`anytime_agent.py`, lines 166 and 186) were not
  touched (not on the profiled path).
* Threads and torch: the kernel's libgomp is the system's, torch brings its own; they coexist in the profiles. With
  threads on, the kernel's idle workers spin briefly after each region (libgomp's default wait policy).
