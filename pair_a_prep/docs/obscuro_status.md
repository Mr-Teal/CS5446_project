# Obscuro implementation status

Further optional follow-ups: [projection work budgets](projection_work_budget.md)
separate preparation/growth windows and defer outside-I estimates without
dropping roots. [Gift accounting](gift_accounting_audit.md) explicitly partitions
local retained/discarded CF contributions and preserves cross-turn audit
lineage. It does not numerically transfer ancestor gadget payments.

Latest optional integration: [sampled-tree chess subgame agent](chess_subgame_integration.md)
connects saved-tree I^2 projection, finite-cut boundaries, fresh-root caps,
serial gadget switching, selective growth, initial best policies and C.8-style
purification. Earlier tables below are the historical uniform baseline. The
new integration has explicit sampling, gift-scope and heuristic approximations;
it is not complete full-history KLUSS or a full reproduction.

This is a repository implementation map, not a claim of exact reproduction.
The latest incremental implementation is described in
[Serial one-sided search](one_sided_search.md): selected-history growth,
support/variance-PUCT sampling and growth-node best-child initialization are
implemented. The historical baseline checklist below describes the uniform
prototype; it must not be read as the status of the new optional growth mode.
Follow-up building blocks are now documented in
[finite-cut blueprint boundaries](subgame_boundaries.md) and
[opt-in cross-turn retention](cross_turn_retention.md). These are connected in the sampled subgame prototype; full-history knowledge closure, tracker population and new-root boundary semantics remain limited.
The source anchors below follow the existing [paper specification map](paper_specs.md)
for Zhang and Sandholm, *General search techniques without common knowledge
for imperfect-information games*, arXiv:2506.01242v2. The authors' original
implementation and evaluation setup are unavailable. Engineering choices below
are explicitly separated from the source-mapped mechanisms.

## Current delivery checklist

| Mechanism | Implemented evidence | Remaining limit |
|---|---|---|
| Rules and observations | Shared FoW rules, adapter and effective en-passant checks are integrated | Freeze actual rule revision with each batch |
| Histories | Exact observation-consistent tracker and sampled returned paths | Output sampling does not bound internal population; long-game capacity remains a blocker |
| PCFR+ and growth | Fixed-tree solver, selected-history one-sided growth, best-child initialization | Sampled finite trees; no whole-game exploitability guarantee |
| Knowledge and gadgets | Sampled synchronous I^2 projection, finite-cut boundaries, serial mode switching | No full asynchronous knowledge closure; ancestor gifts are audit-only |
| Retention and output policy | Heuristic cross-turn reuse, raw/played policy separation and purification | These are explicitly bounded approximations |
| Leaf evaluator | Material default; pinned real Stockfish factory and Pair C smoke | Actual SF19 differs from paper SF14; bounded smoke is not strength evaluation |
| Labels | Cold labels supported; projected labels gated | Complete solver-root and weight agreement still required |

## Ownership and immediate sequence

The [expansion audit](expansion_mechanism_audit.md) now checks the local paper's
exact support/PUCT mixture and initialization. It also clarifies that our
complete-cut requirement is an engineering restriction; the paper can expand
one history leaf without expanding every member of its information set.

1. Deliver the pinned real-evaluator configurations and source identities to Pair C.
2. Agree with the tracker owner on bounded history-preserving inference before long-game batches.
3. Freeze evaluation settings with Pair C and report capped, failed and terminal attempts separately.
4. Finalize report/slides with measured results and the explicit approximation list.
5. Treat further regret/policy toy ablations as optional; they do not block this delivery.

## Reporting requirements

- Identify the selected mode and actual config ID; describe subgame mode as an Obscuro-inspired sampled prototype. Reserve `uniform-growth-pcfr-prototype-v1` for historical uniform runs.
- Preserve source hashes, configuration, seeds, tracker limits and rule revision.
- Distinguish final tree size from total preparation/failed-expansion work.
- Compare actual evaluator calls and elapsed time, not only identical upper caps.
- Report interrupted initial builds and fallback counts. Fallback policies have
  no invented continuation values and cannot produce training labels.
- Do not count a diagnostic ply limit as a draw or infer ratings from toy/short
  games. Per-subgame Nash gaps do not establish whole-game exploitability.
- Stockfish version changes, simplified scheduling, approximate knowledge restriction and
  unresolved knowledge/gadget inputs must remain visible in the final report.
