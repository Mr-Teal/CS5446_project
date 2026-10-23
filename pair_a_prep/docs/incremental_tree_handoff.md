# Incremental toy-tree expansion: Pair A handoff

Prepared for Pair A review as Bryan's incremental toy-tree contribution,
23 October 2026. The code and results below are scoped to leaf expansion;
integration into the eventual Obscuro search remains separate.

## Baseline and scope

The pre-edit [solver](../pcfr.py) and [toy-game definitions](../toy_games.py)
were checked against Pair A's PR #15 browser source at its current
`cb610196f1df3a28ec6ccb9715569274295f225d` head. Their normalized SHA-256 hashes
matched the local files before editing:

| File | Pre-edit SHA-256 (LF, trailing whitespace trimmed at EOF) |
|---|---|
| `pcfr.py` | `11a1fbe6054fae41ac870d1897f2d856057425cb3fecc71a0c3eecafb6210189` |
| `toy_games.py` | `fc347dbd5153d9791cf44000631068dc3593558f86102a9f7a936b815745f860` |

Validation below applies to this local workspace and the changed core solver,
not to all newer chess-search work in PR #15. Main was still `cdbdba7`; PR #15
was the only open PR when work began.

This is a bounded prerequisite for growing-tree search, **not a complete
Obscuro implementation**. It expands explicit cutoff leaves while keeping
actions at existing information sets fixed.

## What changed

- [toy_games.py](../toy_games.py): `Node.cutoff` and `frontier(estimate)`
  distinguish estimated search leaves from genuine terminals. Tree validation
  rejects cycles, non-node children and malformed cutoff leaves.
- [pcfr.py](../pcfr.py): `PCFRPlus.expand({path: subtree, ...})` validates and
  installs a batch without resetting existing state. Paths are action tuples
  from the root; `()` expands a cutoff root.
- [Expansion tests](../tests/test_pcfr_expansion.py): 70 parametrized test cases.
- [Algorithm/API notes](pcfr.md), [Pair A README](../README.md) and the
  [repository README](../../README.md): updated scope and usage.

Use the runnable example in [the API notes](pcfr.md#expanding-cutoff-leaves).
It was executed successfully: 10 pre-expansion plus 1000 post-expansion rounds,
with both matching-pennies Nash gaps zero.

## State-migration contract

1. Existing minimizer objects, regrets, previous local utilities, published
   policies, average accumulators and total round count survive unchanged.
2. Only genuinely new information sets get uniform strategies and zero
   regrets/utilities/average sums. New hidden occurrences of an old information
   set share its existing minimizer.
3. Descendant-first prediction ordering is rebuilt. Cached opponent snapshots
   retain old entries and get uniform policies for new opponent information
   sets. Predictions are subsequently recomputed on the expanded tree.
4. Alternating mode preserves existing pending strategies and gives newly born
   minimizers a pending uniform strategy when training has already begun.
   Expansion before round zero leaves initialization to the usual first step.
5. Average weighting continues with global round number `t**averaging_power`.
   New information sets receive no historical mass. Old approximate-game
   contributions remain in existing averages.
6. A rejected batch changes nothing. Expansion never mutates the supplied
   tree/subtrees. Obtain the current tree through `solver.root`.

Call expansion between complete solver calls. Nodes remain externally
immutable by contract; this is not a thread-safe or in-place mutation API.
Batch related hidden histories together. Perfect recall and action consistency
are checked, but choosing information-consistent boundaries/IDs remains the
caller's responsibility.

## Verified results

Run from the repository root using an environment with the existing Pair A
dependencies installed:

```powershell
python -m pytest -q pair_a_prep/tests/test_pcfr_expansion.py pair_a_prep/tests/test_pcfr.py
python -m pytest -q pair_a_prep/tests/test_toy_games.py pair_a_prep/tests/test_gadgets.py pair_a_prep/tests/test_knowledge.py pair_a_prep/tests/test_toy_visualizer.py
```

Results: **86 passed** in the solver/expansion suite, **27 passed** in directly
dependent regressions, **113 total**, no skips. The VS Code test tool did not
discover these tests, so they were run through pytest in the workspace's
existing validation virtual environment.

Coverage includes both schedules, predictive/non-predictive controls, all
averaging powers, repeated growth, root/chance expansion, zero-reach histories,
shared information sets, aliased input nodes, exact continuation, pre-first-round
fixed-tree equivalence, and failure atomicity. Existing fixed-tree tests were
not changed.

Progressively exposing one level at a time, with five training rounds before
each expansion, then 2000 additional rounds on the complete tree:

- Hidden/revealed matching pennies, hidden/revealed coin guessing, and Kuhn
  poker passed average Nash gap **< 0.002** under both schedules.
- Their average values were within **0.001** of the complete-game LP oracle.
- Alternating mode also passed last-iterate Nash gap **< 0.002** on every case.

### Important simultaneous-mode limitation

The initial test also required simultaneous last-iterate convergence. It failed
on warm-started Kuhn poker, despite the average passing. A separate longer run
confirmed that this was not simply fixed by increasing the round count:

| Schedule | Additional complete-game rounds | Average value | Average Nash gap | Last Nash gap |
|---|---:|---:|---:|---:|
| simultaneous | 2000 | -0.0555550412 | 0.0003693434 | 0.0890200843 |
| simultaneous | 5000 | -0.0555554235 | 0.0001926990 | 0.0802739120 |
| simultaneous | 10000 | -0.0555555267 | 0.0001134961 | 0.1946354312 |
| alternating | 2000 | -0.0555555304 | 0.0000002755 | 2.15e-16 |
| alternating | 5000 | -0.0555555539 | 0.0000000180 | 2.15e-16 |
| alternating | 10000 | -0.0555555553 | 0.0000000023 | 2.15e-16 |

Kuhn's reference value is `-1/18`. These runs had 20 rounds of staged-tree
training before the additional complete-game rounds. The final tests require
average convergence for both schedules and check last-iterate convergence
separately for alternating mode; they do not claim simultaneous last-iterate
convergence. No existing update equations or fixed-tree scheduling behavior
were changed to hide this result.

## Remaining work for Pair A

- No new actions at old information sets, pruning, rerooting, leaf-value-only
  refresh, or replacement of genuine terminals.
- No automatic frontier selection, one-sided Obscuro expansion rule, evaluator
  calls, time/node budget, or information-set closure discovery.
- No persistence across moves/processes, serialization, or purification.
- Metrics on partially expanded trees describe the **estimated current game**,
  not a full-game exploitability bound.
- No growing-game convergence theorem, performance claim, or end-to-end chess
  validation follows from these toy results.

Suggested next integration step: have Pair A supply an information-consistent,
budgeted expansion policy and evaluator-produced cutoff values on top of this
API, retaining separate last/average diagnostics and the alternating schedule
when evaluating its Obscuro path.
