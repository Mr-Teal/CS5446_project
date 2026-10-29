# Report material: real evaluator integration

These paragraphs are ready to adapt into the team report. They describe the
bounded integration evidence archived with PR57; they do not replace formal
evaluation results. No new experiment is introduced by this document.

## Methods

We implemented an Obscuro-inspired sampled subgame search agent and connected
it to the evaluation runner through per-player factories. The agent consumes
private observations and observation-consistent candidate histories; it does
not receive the referee's hidden board as its information state. During
search, hypothetical boards are evaluated using the existing Stockfish leaf
evaluator. The factory records the running UCI identity and executable SHA256,
includes evaluation options in the agent configuration identity, and owns
engine reset and cleanup. The smoke configuration uses Stockfish 19 at depth
1, with one thread, a 16 MB hash table and per-call resets. A two-second
engine-call watchdog does not impose a hard deadline on the complete action.
Actual history-dependent terminal outcomes are handled by the rules layer.

The implementation is an approximate reconstruction: it uses sampled
synchronous knowledge restriction, heuristic cross-turn reuse and audit-only
ancestor gift accounting. The paper specification instead identifies
Stockfish 14. Returned-history sampling limits search inputs but does not
bound the exact tracker's internally enumerated population. Consequently,
this integration does not establish readiness for arbitrary long games.

## Integration results

We ran the real evaluation pipeline on a pawn fixture and the standard
initial board. Each setting comprised two colour-swapped attempts, capped
after four plies, producing eight recorded actions. Neither setting recorded
an attempt failure, fallback action or diagnostic over-budget action. Each
run recorded four factory reset callbacks, and both owned engine processes
were closed at cleanup. A generated configuration pinning the validated
engine was also run successfully through the normal production factory.
All attempts reached their diagnostic ply cap: zero games were scored, and
win and score rates are unavailable. These checks establish short-sequence
compatibility between rules, tracker, search, evaluator and runner, rather
than playing strength or a latency advantage. Tracing adds overhead, so its
timings should not be used as a controlled speed comparison.

## Evidence map and remaining work

| Claim | Archived source |
|---|---|
| Binary identity, options and config IDs | `runs.<setting>.loaded` |
| Attempts and excluded caps | `runs.<setting>.summary` |
| Action/fallback/over-budget counts | `runs.<setting>.diagnostics` |
| Reset callbacks and engine cleanup | `factory_reset_events`, `engine_close_checks` |
| Runtime source identity | `source_hash_convention`, `source_sha256` |
| Untraced production check | `production_runner_repetition` |

The source is [`stockfish_handoff_reference.json`](../results/stockfish_handoff_reference.json).
Its local paths are sanitized; binary/source hashes are retained. The recorded
base commit predates uncommitted runtime changes at execution, so use the
source manifest, not the base commit alone, to identify measured code.
Focused automated validation separately passed 55 factory, clock and Pair C
regression tests; this count is not a game count or real-engine experiment.

Before formal strength evaluation, agree on a history-preserving bounded
tracker, resource budgets, seed/colour schedules, outcome handling and source
freeze with the tracker and evaluation owners. Record failures and caps
separately from terminal outcomes. Projected training labels remain disabled
pending the solver-root and weighting agreement; that agreement is a separate
data-export gate rather than evidence of an evaluation failure.
