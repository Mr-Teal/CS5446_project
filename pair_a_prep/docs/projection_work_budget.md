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
