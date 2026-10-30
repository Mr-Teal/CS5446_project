# Backup: from search prototype to evaluation

This is optional slide content for the existing Pair A section, not a new
agreed slide number or speaking assignment. It follows slides 4–5: after
explaining hidden histories and search growth, explain what now runs in the
evaluation pipeline.

## Slide content

**Real engine integration works; long-game strength remains unmeasured.**

`Private observation → consistent sampled histories → subgame PCFR+ search`

`→ Stockfish leaf evaluation → legal move → Pair C referee`

| Integration check | Pawn fixture | Standard initial board |
|---|---:|---:|
| Colour-swapped attempts | 2 | 2 |
| Recorded actions | 8 | 8 |
| Failed attempts / fallback actions | 0 / 0 | 0 / 0 |
| Factory reset callbacks | 4 | 4 |
| Engines closed after run | 2 / 2 | 2 / 2 |
| Terminal games scored | 0 | 0 |

Footer: Stockfish 19, depth 1, one thread, Hash 16 MB. Four-ply diagnostic
caps; no win-rate or strength conclusion. The paper specifies Stockfish 14.

## Speaker script (about 45 seconds)

We have connected the search prototype to the actual evaluation runner using
Pair B's Stockfish evaluator. The configuration records the running engine's
version, executable hash and options, and the factory resets and closes the
engine between games and at cleanup. We tested both a pawn fixture and the
standard initial board, with two colour-swapped attempts in each setting.
There were no failed attempts or fallback moves in these short checks.
However, every attempt stopped at the four-ply diagnostic cap, so there are
no terminal results from which to estimate win rates. The next integration
constraint is the exact belief tracker's growth over longer observation
sequences. Our current implementation remains a sampled, approximate
reconstruction of Obscuro, using Stockfish 19 rather than the paper's version 14.

## Backup answers

- **Why not show a win rate?** All attempts are capped; capped attempts are
  excluded from outcome rates and are not draws.
- **Does this reproduce the original agent?** No. Knowledge restriction uses
  sampled synchronous histories, reuse is heuristic, and ancestor gifts are
  audit-only. These differences remain explicit in the report.
- **Does sampling solve tracker growth?** No. It bounds the hypotheses
  returned to search; the exact internal population can still exceed its cap.
- **Is this a speed comparison?** No. The trace wrapper adds overhead, and
  the smoke settings use diagnostic clocks. Formal latency comparisons need
  an agreed protocol and actual completed work/fallback counts.
- **Can Pair B use these outputs as training labels?** This delivery enables
  evaluation. Projected labels remain gated by the solver-root/weight contract.

## Evidence

All table values come from `runs.pawn` and `runs.standard` in
[`stockfish_handoff_reference.json`](../results/stockfish_handoff_reference.json).
Counts must remain separate from earlier Material, toy and clock experiments.
`production_runner_repetition` is an additional untraced pawn-config run,
not a third independent strength experiment or part of the table above.
See the [run instructions](../docs/stockfish_evaluation_handoff.md) and
[report-ready methods/results](../docs/stockfish_report_material.md).
