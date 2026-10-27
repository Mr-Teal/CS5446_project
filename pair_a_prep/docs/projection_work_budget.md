# Projection preparation work and budgets

This follow-up is stacked on #44, independent of tracker population/weight
changes. It preserves the existing sampled-tree I^2 definition and resource
caps. It does not promise hard deadlines or stronger play.

## Preparation versus growth

The initial project/build stage previously used the expansion cutoff (60% in
the clock matrix). A valid shallow search could therefore fall back even when
the action still had preparation/solving time available. Preparation now uses
the solve cutoff (90% with the default 10% submission reserve). Subsequent
growth still stops at 60%; spending longer preparing does not renew its window.
The changed convention is included in configuration identity.

## Replay and evaluation reuse

The first projection replays input candidate histories once, then builds from
the validated HistoryRoot objects. It no longer replays the same candidates a
second time through build_chess_tree. Input validation and capacity checks are
retained at the projection entry point.

Fresh/cutoff-root builds in one projection share an attempt-local FEN evaluation
cache. Only evaluator answers are cached; state transitions, legal actions,
terminal outcomes, repetition stacks and private memories remain per history.
Actual evaluator calls, including failed work, are counted. The cache is not
persisted across turns or used to merge roots. A regression with identical FENs
checks that a threefold-draw child remains terminal in one history and an
estimated child in another even when its evaluator answer is reused.

## Recorded first-stage evidence

Reproduce in the documented Pair B environment:

```powershell
& .\pair_b\.venv\Scripts\python.exe -m pair_a_prep.clock_ablation --output pair_a_prep/results/projection_budget_reference.json
```

The initial optimization run recorded 1 fallback / 48 single-turn checks and
9 / 48 live actions, compared with #44's recorded 8 and 11. No action overran
in this run. Four fixed-work raw/purified pairs still had matching raw policies.
These are sequential machine measurements, not a statistical speedup claim.
The old #44 records are retained. Of the 9 live fallbacks, 5 reached the
evaluator-call limit and 4 exhausted construction time; they are not tracker
failures or fabricated terminal outcomes.

The full shared/Pair A suite passed 486 tests for this first-stage snapshot.
The overlapping focused preparation/clock/integration run passed 17 tests.

## Lazy outside-I knowledge neighbours

An old estimated cut root outside the current own information set can remain
an estimated leaf. Preparing it eagerly is unnecessary in a growing tree and
can exhaust the evaluator budget before solving the current move. The projector
now keeps such roots, their reach masses and old boundary evidence unchanged,
records them as explicit root frontiers, and expands them only when sampled.
Current-I roots still need a legal-move decision node. Already expanded
neighbours retain their continuations. No root, observation class or belief
candidate is dropped, and both gadget modes can expand the deferred root later.

The analytic kings cut retains all 9 histories, expands its 3 current-I roots
with 3 evaluator calls, and leaves 6 outside-I roots estimated. Tests grow one
of those roots through Resolve and Maxmargin while preserving the old solver.

`results/projection_lazy_reference.json` records the same clock matrix after
this change: **0/48 single-turn fallbacks and 0/48 live-action fallbacks**, with
0 and 1 observed overruns respectively. All 12 live games remain capped/null.
The overrun is retained in the raw record, not hidden by a rerun. This changes
when heuristic leaves are expanded and may change policies; it is not a claim
of equal work, stronger play or guaranteed deadlines. The earlier two snapshots
remain committed for comparison. Reproduce using the same clock_ablation
command with `--output pair_a_prep/results/projection_lazy_reference.json`.
