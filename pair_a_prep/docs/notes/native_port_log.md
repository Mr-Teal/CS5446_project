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
