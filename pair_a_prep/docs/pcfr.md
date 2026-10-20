# Fixed-tree PCFR+ verification

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

Trees must be finite, fixed, and have perfect recall. The constructor rejects
information sets whose nodes have different own action/information histories.
Do not mutate the tree after construction. Zero-reach information sets still
receive counterfactual updates; an average with zero own reach falls back to
the current local strategy. Terminal utilities need not be restricted to [-1,1]
(Kuhn poker uses +/-2). Metrics use player 0's payoff perspective.

This reference implementation recomputes full-tree prediction traversals for
each own information set. It prioritizes readability over speed and is not
suited to chess-sized trees. The LP oracle and enumerated best responses are
also limited to small games. No seed is needed: there is no sampling.

## Reproduce the verification report

```powershell
python -m pytest -q pair_a_prep/tests/test_pcfr.py
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

## Next integration steps

Before integrating chess, implement/test gadget values, KLUSS information sets,
one-sided tree expansion, persistence,
and purification separately. The report does not validate any of those parts.
