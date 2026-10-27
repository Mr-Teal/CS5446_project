# Small budget experiments

Prepared 25 October 2026. These are integration/cost probes of the uniform-growth
prototype, not win-rate estimates or a complete Obscuro evaluation. Exact
measurements, configuration IDs, source hashes and environment metadata are in
[the compact reference](../results/anytime_budget_reference.json). It records
a dirty working snapshot honestly; its hashes identify the executed source.

## Protocol

- Material evaluator; raw last iterate; alternating PCFR+; seed 17.
- Fixed depth 1, fixed depth 2 and uniform growth to at most depth 3.
- Twelve total solver rounds for each successful fixed-work probe. Growth uses
  three-round stages and reserves three final rounds.
- Caps `(nodes, evaluator calls)` are `(128, 4)` and `(512, 16)`.
- Three public-start fixtures: distant kings with White to move, Black with
  three hidden-history hypotheses after `a1b1`, and immediate rook king capture.
- Each configuration runs twice. All 18 semantic repeats matched, excluding
  elapsed time. Failed fixed-depth builds are reported, not silently replaced.
- Time stopping is disabled in these comparisons. Calls include discarded
  growth attempts. Caps are shared but actual work is not equal.

## Selected measurements

Times below are medians of only two samples on this Windows machine; they are
diagnostic observations, not precise performance estimates.

| Position | Call cap | Method | Final depth | Final nodes | Calls used | Median ms |
|---|---:|---|---:|---:|---:|---:|
| Kings / White | 4 | Fixed depth 2 | 2 | 14 | 3 | 6.71 |
| Kings / White | 4 | Growth | 2 | 14 | 4 | 7.50 |
| Kings / White | 16 | Growth | 3 | 68 | 13 | 26.96 |
| Hidden / Black | 4 | Fixed depth 2 | Failed | Not completed | 4 | 8.95 |
| Hidden / Black | 4 | Growth | 1 | 13 | 4 | 8.17 |
| Hidden / Black | 16 | Fixed depth 2 | 2 | 67 | 9 | 26.33 |
| Hidden / Black | 16 | Growth | 2 | 67 | 16 | 36.23 |
| King capture | 16 | Fixed depth 2 | 2 | 99 | 16 | 43.14 |
| King capture | 16 | Growth | 1 | 19 | 16 | 35.31 |

Growth preserves a valid shallow policy when deeper preparation fails. It does
not automatically use less computation. Shallow initialization, separate caches
for expanded contexts and discarded all-or-nothing subtrees consume extra calls.
In the king-capture fixture, fixed depth 2 fits the cap while growth does not
reach that depth under the same cap. The immediate win is already visible at
depth 1; final depth alone is not a strength measure.

The node cap bounds the retained tree, not cumulative node construction or
temporary memory. Elapsed time and total calls expose some discarded work;
these experiments do not measure total allocated nodes or peak memory.

## Short games and actual clock

Two six-ply games swap the growth agent's colour against fixed depth 1. Both
use the exact tracker with output sample size 4 and internal cap 2000. Both
complete all six plies with zero per-move 1000ms overruns and hit the diagnostic
ply cap; both outcomes are recorded as `null`, not draws. Their identical move
sequences in this tiny kings-only setup do not establish agent equivalence.

Separate clock-enabled kings probes returned:

| Nominal ms | Observed ms | Final depth | Rounds | Initial fallback |
|---:|---:|---:|---:|---|
| 1 | 0.82 | No tree | 0 | Yes |
| 10 | 10.05 | 2 | 24 | No |
| 50 | 32.70 | 3 | 24 | No |

The 10ms run slightly overruns. Evaluator calls, solver rounds and finalization
are not preemptible. Clock probes are single samples, and their stopping depths
and timings can change across machines or repeated runs.

## Interpretation and next steps

The evidence supports short-game interface compatibility, deterministic
fixed-work repetition, budget-limited continuation and initial action fallback.
It does not validate long games, tracker scalability, engine-backed latency,
neural labels, strength improvements or any original-paper reproduction claim.

Useful next experiments are persistent evaluation caches with history-aware
terminal overrides, preparation work accounting, and source-specific selective
expansion. Run these as separate changes against this baseline. Formal matches
should wait for agreed rules/source revisions and a stable tracker integration.

Reproduction command and API details: [anytime search](anytime_search.md).
