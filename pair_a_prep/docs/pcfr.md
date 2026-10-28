# PCFR+ verification and incremental toy-tree expansion

Implementation: [pcfr.py](../pcfr.py). This is a solver for the existing finite
toy trees, not a complete Obscuro reproduction. It does not touch shared code.

## Algorithm and sources

Primary source: Farina, Kroer and Sandholm, [Faster Game Solving via Predictive
Blackwell Approachability](https://www.mit.edu/~gfarina/2021/predictive-approachability-aaai21/predictive-approachability.aaai21.pdf),
Algorithm 5 and Appendix F. Equations below use maximized utilities, not losses.

Each information set has its own projected regret vector `z`, previous local
strategy `x_previous`, and predicted action utility `m`:

```text
theta = max(0, z + m - dot(x_previous, m))
x = theta / sum(theta)                 # uniform if sum is zero
z = max(0, z + u - dot(x, u))           # after observing actual utility u
```

Predictions are built from the previous sequence-form utility, propagated
through the NEW own descendant strategies, in reverse own-decision order.
Simply caching old local counterfactual utilities misses that dependency.
Opponent and chance reach weight utilities; own reach does not. All occurrences
of an information set are summed before its regret update. The diagnostic
average uses own-reach weighting and round weights `t**2`.

Two explicit schedules are available. The default remains `simultaneous` for
compatibility with the original report: both players produce strategies before
either receives feedback. `alternating` initializes both held strategies, then
feeds back player 0's held strategy and publishes its successor, then feeds back
player 1 against that NEW player-0 strategy and publishes player 1's successor.
This implements alternating updates; exact growing-tree Obscuro integration is
still separate. Setting `predictive=False` supplies zero predictions as a CFR+
control with the chosen schedule and averaging.

One round contains one feedback update per player. In alternating mode the
returned last profile is the newly published profile, ready for the next
feedback. The initial uniform profile is not averaged: after each complete round
we average the two published policies with weight `t**2` and their own reaches.
In simultaneous mode the last profile remains the one used in that round.
Reports name their schedule, so iteration counts and policy timing are explicit.

## API

```python
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.toy_games import kuhn_poker

solver = PCFRPlus(kuhn_poker(), schedule="alternating")
solver.run(2000)                    # additional complete rounds
last = solver.policy()             # detached per-player infoset dictionaries
average = solver.policy(average=True)
print(solver.metrics())             # separate value and gap for each policy
```

Trees must be finite, acyclic, and have perfect recall. The constructor rejects
information sets whose nodes have different own action/information histories.
Do not mutate the tree after construction; use the expansion API below.
Zero-reach information sets still
receive counterfactual updates; an average with zero own reach falls back to
the current local strategy. Terminal utilities need not be restricted to [-1,1]
(Kuhn poker uses +/-2). Metrics use player 0's payoff perspective.

### Expanding cutoff leaves

`terminal(value)` is a true terminal and cannot be expanded. `frontier(estimate)`
is an explicit cutoff leaf: its finite estimate is used as player 0's payoff
until it is replaced by a nonterminal subtree. A cutoff is a search boundary,
not an additional player action or information set.

```python
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.toy_games import Node, frontier, matching_pennies

full = matching_pennies()
partial = Node(player=0, infoset="p0",
               children={"H": frontier(0), "T": frontier(0)})
solver = PCFRPlus(partial, schedule="alternating")
solver.run(10)
solver.expand({("H",): full.children["H"], ("T",): full.children["T"]})
solver.run(1000)
print(solver.metrics())  # rounds == 1010, now measured on the complete game
```

`expand({path: subtree, ...})` accepts tuples of root-relative action names;
`()` denotes the root. Call it between complete `step()`/`run()` calls.
Use one batch for related hidden histories. The caller is responsible for
choosing information-consistent expansion boundaries and correct information
set IDs; the solver cannot infer hidden information from a numeric estimate.

The complete candidate tree is validated before any solver state changes.
Existing information sets must keep their action labels and order, and all
occurrences must retain perfect recall. Missing paths, non-cutoff targets,
cycles, malformed chance distributions and inconsistent information sets raise
`ValueError` without changing the tree, policies, regret state or round count.
Empty batches do nothing. Expansion does not mutate the input tree or supplied
subtrees; use `solver.root` to access the resulting tree. Continue to treat all
nodes as immutable outside this API.

Existing minimizer objects, regrets, previous local utilities, held policies and
averaging sums are retained exactly. New information sets start with zero
regrets/utilities/sums and a uniform policy. An additional hidden occurrence of
an existing information set reuses its minimizer. Own-decision traversal order
is rebuilt. Cached opponent profiles retain existing entries and gain uniform
entries for new opponent information sets; future predictions are recomputed on
the expanded tree. Alternating mode also marks new uniform policies as awaiting
feedback when rounds have already run, without republishing existing policies.

The round counter and `t**averaging_power` weighting continue globally. New
information sets receive no retrospective average mass. Existing averages
retain earlier, approximate-game play; they are not reset or reweighted.
While cutoffs remain, values and Nash gaps describe only the current estimated
game, not the unknown complete game. These are warm-start semantics, not a
convergence theorem for changing games.

This reference implementation recomputes full-tree prediction traversals for
each own information set. It prioritizes readability over speed and is not
suited to chess-sized trees. The LP oracle and enumerated best responses are
also limited to small games. No seed is needed: there is no sampling.

## Reproduce the verification report

```powershell
python -m pytest -q pair_a_prep/tests/test_pcfr.py pair_a_prep/tests/test_pcfr_expansion.py
python -m pair_a_prep.pcfr --rounds 2000 --output pair_a_prep/results/pcfr_new.json
python -m pair_a_prep.pcfr --schedule alternating --rounds 2000 --output pair_a_prep/results/pcfr_alt_new.json
```

The report includes checkpoint metrics, final policies, LP reference values,
prediction and scheduling settings. Existing output files are not overwritten.
The Nash gap is the unhalved difference between the players' best-response
bounds. A value close to the oracle alone is insufficient evidence of a good
strategy; gap is measured independently. Last and average policies remain
separate; the measured last-iterate results are not a general convergence claim.

Tests independently check local arithmetic, predictive versus zero-prediction
behavior, chance-weighted hidden nodes, zero own reach, recall validation, a
nonuniform matrix equilibrium, deterministic continuation and Kuhn poker.
An alternating Kuhn replay also pins last/average values and Nash gaps at rounds
1, 10 and 100 against `pcfr_alternating_reference.json` with absolute tolerance
`1e-12`. These transient checkpoints detect stale-local-utility prediction and
ancestor-first preparation, which final equilibrium checks alone can miss.

Expansion tests additionally check atomic rejection, state retention, chance
and hidden-history aggregation, zero reach, initialization/averaging at birth,
both schedules, CFR+ control, and exact fixed-tree equivalence when growth
finishes before the first round. Progressive expansion tests compare average
strategies against the complete-game LP oracle and require Nash gap < 0.002
after 2000 further rounds on pennies, coin guessing (hidden/revealed) and Kuhn.
They check last-iterate gap separately for alternating mode; simultaneous
last-iterate convergence is not guaranteed by these tests.

See [the expansion handoff](incremental_tree_handoff.md) for measured results
and the deliberately bounded scope.

## Next integration steps

The API supplies incremental leaf expansion on toy trees. Before integrating
chess, separately implement/test an information-consistent one-sided expansion
policy, evaluator/budget integration, persistence across moves, and purification,
alongside the gadget and KLUSS components. This report does not validate a
complete Obscuro search.
