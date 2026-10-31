# Incremental chess tree growth

This optional API connects retained chess histories to `PCFRPlus.expand()`.

Its uniform complete-cut policy is an engineering baseline, not a requirement
to expand all indistinguishable histories. The paper selects history leaves
while shared information-set strategies remain shared; see the
[source audit](expansion_mechanism_audit.md).
It does not change the default fixed-depth agent, label protocol or shared
interfaces. It is an intermediate step towards Obscuro, not a complete agent.

## Usage

Given an existing `AgentInput`, evaluator and public initial FEN:

```python
from time import perf_counter
from pair_a_prep.chess_search import build_chess_tree, expand_chess_tree
from pair_a_prep.pcfr import PCFRPlus

tree = build_chess_tree(turn, evaluator, initial_fen=initial_fen, depth=1)
solver = PCFRPlus(tree.root, schedule="alternating")
solver.run(20)
tree = expand_chess_tree(
    tree, solver, evaluator,
    additional_depth=1,
    max_nodes=5000,
    max_evaluator_calls=100,
    deadline=perf_counter() + 2.0,
)
solver.run(20)
policy = solver.policy()  # Raw last iterate; 40 total rounds.
```

Assign the returned tree after each successful expansion. The old `ChessTree`
remains a snapshot; it must not be reused with the updated solver.
`tree.continuations` and `tree.root_infoset` still support per-hypothesis value
and current-policy extraction. New information sets begin with fresh solver
state; existing regrets, predictive state and accumulated averages survive.

## Retained state and consistent expansion

- True outcomes use ordinary terminal leaves. Evaluated nonterminal leaves use
  `cutoff=True` and are eligible for later expansion.
- `tree.frontiers` maps root-relative action tuples to `HistoryRoot` contexts.
  A context retains the full repetition stack and both private memory chains.
  It is internal hypothetical state, never an extra agent observation.
- All current frontiers expand together by the same additional ply depth.
  This preserves the common cut across hidden histories; individual path
  selection and heuristic selective expansion are deliberately unsupported.
- New observations extend the original private memories. Full FENs and root
  indices do not become information-set identifiers.
- Only the new subtrees are built. Already expanded branches are not rebuilt
  or re-evaluated. Evaluation caches are local to each expanded context.

## Budgets and failures

`max_nodes` bounds the resulting sampled-root tree, including its chance root.
`max_evaluator_calls` bounds invocations of `evaluate_children` during this
attempt, not the evaluator's internal engine calls. `tree.evaluator_calls`
counts successful construction and expansion work cumulatively.

Subtrees are prepared before the atomic solver graft. A capacity error,
deadline error, evaluator exception or solver validation failure leaves the
original tree and solver unchanged. Already performed evaluator work and its
external side effects cannot be undone. The deadline is cooperative: a running
evaluator call and the solver's final validation cannot be interrupted. Budget
failures are exceptions; callers decide whether to continue solving the old tree.

## Limits and verification

Gadget cloning retains cutoff flags, including Maxmargin's shifted estimates.
`expand_chess_tree` accepts only the original sampled-root solver. For gadget
solvers, use [ChessGadget.expand](chess_gadgets.md#incremental-gadget-growth),
which translates paths, opponent keys and shifted replacement payoffs. Do not
graft raw chess continuations directly into a gadget solver.

This API does not implement paper-specific expansion selection, gifts,
alternates, knowledge closure, root replenishment, between-turn persistence,
purification or a production anytime agent. The integrated #28 rule reports
no-fog-legal-move positions as terminal draws before frontier evaluation.

Run focused checks from the repository root:

```powershell
.\pair_b\.venv\Scripts\python.exe -m pytest -q pair_a_prep/tests/test_chess_expansion.py pair_a_prep/tests/test_chess_search.py pair_a_prep/tests/test_chess_gadgets.py pair_a_prep/tests/test_pcfr_expansion.py
```

Tests compare two consecutive expansions with independently built deeper
trees, including Black as player 0 and multiple hidden roots. They check full
history stacks, private memories, old minimizer identity and regrets, resumed
solver rounds, failed-attempt atomicity, and gadget cutoff/offset preservation.
