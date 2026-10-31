# Formal evaluation readiness

This is a proposed acceptance checklist, not an approved experiment protocol.
The current handoff is ready for bounded integration checks, not a formal
long-game batch. Do not turn the four-ply smoke into a strength experiment
by increasing `max_plies` alone.

## Existing configurations

| Setting | Pawn smoke | Standard-start smoke |
|---|---|---|
| A | Sampled subgame, one-sided growth | Same |
| B | Fixed depth 1 PCFR reference | Same |
| A node / evaluator-call caps | 1024 / 48 | 5000 / 128 |
| B node cap | 1024 | 1024 |
| Leaf | SF19 D1, one thread, Hash 16 MB | Same |
| Histories returned / internal cap | 3 / 2000 | Same |
| Attempts / ply cap / seed | 2 / 4 / 17 | Same |
| Diagnostic action budget | 10000 ms | 30000 ms |
| Clock stopping | Disabled | Disabled |

These are compatibility controls, not equal-work or equal-time opponents.
In particular, fixed depth 1 is not ZS21. A ZS21 comparison requires the
partner's actual agent factory and a separately reviewed configuration.

## Acceptance sequence

| Gate | Required evidence | Owner / current state |
|---|---|---|
| Runtime dependencies | Review and merge actual heads in dependency order; rerun on resulting checkout | Pair A / pending upstream reviews |
| Short integration | Real engine, both colours, valid moves, no failures, reset and cleanup checks | Pair A / archived smoke passed |
| Actual resources | Saved config bytes/hash; actual loaded engine/model identity and device; commit/dirty state and documented hash convention | Pair C + evaluator owner / PR51 fixes pending author integration |
| Per-action recording | Preserve fallback flag, elapsed time, actual evaluator calls and work diagnostics; do not infer fallback from zero nodes | Pair C + Pair A / production diagnostic-copy change validated on its separate branch; pending review/integration |
| Tracker capacity | Longer observation sequences, consistent complete histories, recorded population/work/memory, explicit exhaustion handling | Tracker owner + Pair A / unresolved |
| Frozen match protocol | Agree opponents, seeds, colour pairs, resource controls, ply caps and failure policy before running | Pair C + team / pending agreement |
| Formal run | Fresh outputs, frozen source/config, no runtime edits during execution; retain failed and capped attempts | Evaluation operator / not started by this handoff |
| Report | Separate terminal outcomes, caps and failures; disclose approximation and engine-version differences | Pair A + Pair C / draft material available |

Upstream order for this handoff is #39 → #40 → #41 → #42 → #43 → #44 →
#46 → #48 → #57. Optional toy PRs #53–56 are not dependencies. An approval
of a downstream head does not approve upstream changes or authorize bypassing
an outstanding change request. Re-check live GitHub state before acting;
this list describes dependencies rather than a promise of current approvals.

## Tracker agreement needed before long games

The proposed minimum contract is history-preserving bounded inference, not
an assertion that an implementation already exists:

1. Every returned hypothesis has a replayable complete move path consistent
   with the player's observation/action history. Preserve repetition history
   and private-memory identity; matching only the current FEN is insufficient.
2. State separately whether returned weights are exact posterior weights,
   normalized retained mass, or approximate sampling weights. Search must not
   silently interpret truncated samples as the full posterior.
3. Bound internal population or inference work as well as output sample size.
   Record retained population, work and any resampling/truncation event.
4. Define exhaustion explicitly: reject the game or record a declared recovery
   method. Do not invent a hidden board or silently substitute uniform belief.
5. Validate across multiple seeds and longer observation sequences before a
   formal batch. The tracker owner and evaluation owner should agree the
   sequence lengths and limits; the current two four-ply tests are insufficient.

This agreement does not require implementing full Obscuro knowledge closure.
It does require reporting the approximation used. Projected-label root and
weight agreement remains a separate gate for training-data export.

## Proposed reporting policy

- Report requested, terminal/scored, capped and failed attempt counts, plus
  complete colour-pair counts. Keep the denominator next to every rate.
- Keep capped outcomes unavailable under this handoff's policy; do not import
  the capped-draw policy of a historical batch without an explicit decision.
- Report fallback frequency and timing together. A fast fallback is not a
  completed search. Record evaluator work rather than equating upper caps.
- For time comparisons, agree clock stopping, warm-up, engine reset policy,
  hardware and tracing overhead. The present smoke disables clock stopping.
- Keep historical Material/toy/clock evidence separate from new-source real
  engine results. Do not pool results across rule or engine revisions.
- Select sample size and uncertainty reporting with Pair C before inspecting
  a formal result; a convenient short run is not a justified strength estimate.

## Reproducible starting point

Use the [Stockfish handoff commands](stockfish_evaluation_handoff.md), then
inspect `handoff.json`, `agent-events.jsonl` and the normal runner outputs.
The [archived reference](../results/stockfish_handoff_reference.json) is the
baseline for integration checks, not a target win rate. Ready-to-adapt
[report paragraphs](stockfish_report_material.md) and
[presentation backup](../presentation/stockfish_integration_backup.md) preserve
the same scope and limitations.

The additive [per-action diagnostics change](per_action_diagnostics.md) preserves numeric decision diagnostics in successful production records. Partial records from failed attempts remain a separate limitation.
