# Budgeted uniform-growth PCFR+ agent

`AnytimePCFRAgent` connects the existing original sampled-root chess tree,
PCFR+ and complete-cut growth into the shared `reset/act` agent interface.
It is a runnable engineering baseline, not a complete Obscuro reproduction.
See [the mechanism/status map](obscuro_status.md) for missing paper mechanisms.

## Run an agent

From an environment with the Pair A and Pair B dependencies installed:

```python
from pairb.material import MaterialEvaluator
from pair_a_prep.anytime_agent import AnytimeConfig, AnytimePCFRAgent

agent = AnytimePCFRAgent(MaterialEvaluator(), AnytimeConfig(), initial_fen=None)
agent.reset("white", seed=17)
decision = agent.act(turn)
```

`turn` is a shared `AgentInput`: complete private observation history and
hypotheses with full `candidate_moves` paths from the public starting FEN.
Use Pair A's history-preserving tracker. A FEN-only particle tracker is not
compatible. A custom initial FEN must be configured identically in both
trackers, the referee and the agents.

The default is a depth-1 start, a maximum depth of 3, 24 total solver rounds,
growth after each 4-round stage, at least 4 reserved final rounds, 5000 nodes
and 128 evaluator invocations. It uses the alternating solver schedule.

## Budget and failure semantics

1. Replay roots and build the complete shallow tree.
2. Solve a stage, then attempt to grow every frontier together by one ply.
3. Retain solver state after a successful graft. Once a growth budget is hit,
   stop growing and continue solving the original tree until the round/time cap.
4. Sample the raw last iterate. Evaluate every hypothesis under that same
   profile to support the shared continuation-label convention.

With `stop_on_time=True`, preparation/growth stops at `expansion_fraction`
(default 0.7) of `turn.time_budget_ms`. Remaining time is available for final
solving. `final_rounds` also reserves solver rounds before the last permitted
growth. With `stop_on_time=False`, only work caps apply and seeded runs are
repeatable; the supplied time budget is still reported diagnostically.

`max_nodes` bounds the current committed raw tree, not total temporary memory
or discarded preparation work. `max_evaluator_calls` counts all invocations
across initial construction and every growth attempt, including discarded
attempts. It does not count internal engine operations. Expansions currently
use separate context caches, so growth can consume more evaluator calls than
building the same final depth directly.

The clock is cooperative. Evaluator calls, solver rounds, validation and final
value extraction cannot be interrupted; an action can exceed its nominal
deadline. This agent does not promise a hard real-time limit.

If the initial tree does not fit a budget, `act()` samples uniformly from the
observation's legal moves and marks `fallback=1`. It does not inspect a true
board. `solve()` and `label()` raise on that condition rather than fabricate
values. Bad evaluator output, evaluator exceptions and malformed histories
propagate; they are not relabelled as ordinary budget fallback.

## Diagnostics and export

Diagnostics include depth, nodes, expansions, total evaluator calls, rounds,
terminal/frontier counts, elapsed/over-budget flags, stage times and one-hot
`stop:*` / `growth_stop:*` reasons. `last_stop_reason` gives a readable final
reason. `last_tree` and `last_solver` are local inspection tools; they are
replaced on the next turn and must not be passed to another player.

`agent.label(turn, game_id)` exports the current actor's raw policy and
unshifted per-hypothesis values, with their belief-weighted mean. Agent config
IDs include search/evaluator settings, initial FEN and simplified rule/growth
conventions. They do not identify a full dataset: callers still need tracker
settings, actual time budget, source hashes and unique game IDs. Clock-stopped
records can differ even with the same seed and configuration.

## Reproduce the budget probes

Run from the repository root; choose fresh output paths:

```powershell
.\pair_b\.venv\Scripts\python.exe -m pair_a_prep.budget_experiments --out pair_a_prep/local_runs/my-budget-probes.json --summary pair_a_prep/local_runs/my-budget-summary.json
```

The script uses Material, three small positions (including a hidden-history
Black turn and immediate king capture), two node/call caps and three methods:
fixed depth 1, fixed depth 2 and uniform growth. Each of the 18 cases is run
twice with the same seed. Semantic repeats exclude elapsed time. Fixed-depth
cases can explicitly fail if their complete requested tree exceeds a cap.

Two colour-swapped six-ply games with the exact tracker exercise shared-runner
integration; reaching the ply cap is recorded as no observed outcome. Three
additional 1/10/50ms probes exercise the real cooperative clock. These small
tests do not estimate win rate or demonstrate superiority.

Committed measurements: [budget experiment notes](budget_experiments.md) and
[compact JSON reference](../results/anytime_budget_reference.json). Raw local
records remain ignored. Outputs record source hashes and optional Git metadata;
a dirty source snapshot is identified honestly rather than presented as a clean
commit. Historical references are not rewritten when code changes later.

## Scope

This branch now incorporates #28: a no-fog-legal-move position is a terminal
draw after other outcomes are checked. New agent configuration IDs and budget
probe metadata identify `terminal_draw_v1`. The committed historical budget
reference retains its original pre-rule source hashes/configuration and is
not rewritten to imply a post-rule run.
Gadget growth remains available separately through `ChessGadget.expand()`;
the agent does not invent paper-specific alternate values or gadget priors.
There is no selective one-sided expansion, cross-turn persistence,
root replenishment, purification or production teacher-data pipeline.
