# Blueprint boundaries on an explicit finite cut

`subgame_boundaries.py` implements the arithmetic in Obscuro Appendix B.1,
C.1-C.3 (supplied arXiv:2506.01242v2, pp. 14-17). Its input is a finite tree,
a valid raw blueprint profile and explicit cut paths with opponent observation
classes. The caller must supply complete selected classes. It does not infer
asynchronous knowledge closure or silently treat a sampled belief as that closure.

## Computation and utility signs

All values are player-0 maximizing utility, as required by `build_gadget`:

- Root mass is chance reach times player-0 reach, p(h)x(h), excluding opponent
  reach. Current-profile conditional value at J is computed from joint reach.
- Opponent ancestor action CFVs aggregate p(h)x(h) times continuation value.
  A gift is the positive part of action CFV minus profile CFV, summed along
  the remembered opponent sequence. These are current-profile CFVs, not best
  responses or ordinary conditional action values. Gift estimates are added
  literally as in C.2; no extra division or clipping to [-1,1] is performed.
- Alternate is conditional player-0 continuation value plus that gift.
- Resolve alpha is half uniform over J and half normalized opponent sequence
  reach y(J). Each observation class contributes once, not once per history.
  This differs from belief weights and p(h)x(h) root masses.
- Zero joint reach uses the class's counterfactual conditional value; all-zero
  y gives a uniform alpha. Both engineering fallbacks are exposed in audit.
  Zero counterfactual class mass is rejected. Forgotten opponent action
  sequences, invalid policies and overlapping cut paths are rejected.

## Gadget switching and warm state

`BoundarySession` builds both finite gadget trees, performs a serial CFR step,
then selects Maxmargin when the minimum current continuation margin is at least
-1e-10, otherwise Resolve. It records transitions and copies compatible local
minimizers via `rebase_solver`; opponent gadget controls absent from the old game
start fresh. Round count, raw policies, regret predictors, averages and cached
opponent profiles are retained for matching keys with identical action order.

Both modes use equivalent cloned continuations, not the original paper's shared
mutable continuation tree/concurrent solver. Tree rebasing is a warm-start
heuristic: previous equilibrium certificates no longer apply, and this code
does not claim exploitability safety. The same helper supports cross-turn chess
private-infoset warm starts; changing utility perspective is unsupported.

## Independent checks

`test_subgame_boundaries.py` checks hand-calculated gifts, nonuniform chance,
zero-reach behavior, fully mixed prior, LP-solvable derived gadgets, mode changes,
and independent warm state under both CFR schedules. The two-action fixture has
blueprint root value -.5, mistake gift 1.5, alternates (2.5,-1), and Resolve alpha
(.375,.625). Alternates exceeding 1 are intentional gift-adjusted boundaries.

This is a finite-cut building block. Chess KLUSS closure, boundary projection
when only part of a previous tree survives, sampled-root replenishment boundaries
and automatic use inside the live chess agent remain separate work. In
particular, no fresh chess root is assigned a fabricated previous boundary.
