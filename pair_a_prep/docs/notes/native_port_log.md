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

## A1. C++ kernel for the round (next)

Plan: export the tree once per growth step into arrays (node parent/children ranges, player, infoset id,
payoff, chance probabilities; per-infoset action counts and offsets), hold regrets, strategies, previous
utilities, sums in flat arrays, and implement in C++: the utilities walk (observe), the level-wise prepare
with memo, the average accumulation, and the PRM+ update. Interface via ctypes like `_belief_native.py`;
equivalence against `_prepare_fast` to 1e-12 on the same tests. Expected: the solver's share of the clock
falls to a few percent.
