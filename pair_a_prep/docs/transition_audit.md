# Actual cross-turn projection audit

This offline diagnostic follows the fixed-game transport work. It reads saved raw trees, their current solver profiles and the next private projection. It does not change a decision, the live warm-start rule, a boundary, or the audit-only gift ledger. No true referee board is accepted by audit_transition().

## Inputs and checks

Each projected root is identified by its full candidate path and FEN-derived history ID, never by FEN alone. A retained root must have exactly one old full-path ancestor. Its hypothetical state is replayed from that old sampled root, and its declared mass is checked independently against the old player-1 CF reach. Fresh perfect-information roots are marked separately and receive no invented source correspondence.

The audit records old counterfactual reach for both players, old joint reach, new raw chance weight, compatible/new/removed infoset counts, local subtree certificates and the strict full-game affine certificate. It checks the root-path/ID and normalized-mass metadata and leaves the source solver/tree unchanged.

## Why the two players see different ratios

Here player 0 is the acting agent's utility perspective, not necessarily White. Along a retained cut path let c denote chance reach, x our prefix behavior reach and y the opponent's prefix behavior reach. The old CF reaches at that cut are:

- player 0: c*y;
- player 1: c*x.

The projection uses declared root mass c*x, normalized by T over its selected and fresh masses. Thus retained roots have new raw chance q=c*x/T. Where old reaches are positive, the root-level ratios are:

- player 0: q/(c*y)=x/(T*y);
- player 1: q/(c*x)=1/T.

The first ratio can vary by root, or become undefined when y=0 but q>0. New positive support cannot be recovered by multiplying an old zero contribution. Fresh roots have no old ratio. These are **current-profile root ratios**, not conversion factors for an entire infoset's cumulative regret. Subtree changes and aggregation across histories still matter.

For example, at x=0.5 and T=3, opponent reaches (1/6, 1/3, 1/2) give own ratios (1, 1/2, 1/3), while opponent ratios remain 1/3. Even uniform instantaneous ratios do not certify unchanged game structure or historical reach weights.

## Recorded private-turn runs

`results/transition_audit_reference.json` records seeds 17 and 29 for public king, pawn and rook/pawn starts, four plies each. The fixed-work Material agents use initial/max depth 3, six solver rounds, 10000 nodes and 512 evaluator calls. Trackers sample three histories and fail explicitly above 2000 retained histories.

| Item | Observed |
|---|---:|
| Games / actions / transitions | 6 / 24 / 12 |
| Capped/null games | 6 |
| Uniform-move fallback / tracker-capacity failure | 0 / 0 |
| Full-game affine certificates | 0 / 12 |
| Transitions with nonuniform positive own root ratios | 5 |
| Transitions with no positive own scale rows | 3 |
| Transitions introducing positive own CF support from zero | 4 |
| Such root rows (not games) | 112 |
| Fresh roots | 3 |
| Locally affine or unchanged cutoff/subtree roots | 310 |

The ratio categories can overlap; do not add them as disjoint outcomes. Local certificates include unchanged estimates and neighbours outside the current own infoset. They do not mean that 310 cumulative minimizers can be transferred. All 12 whole-game tests reject exact affine copying, even though many local roots match.

This is neither a strength study nor timing evidence. The audit adds work after act() and is tested in fixed-work mode. A paired control checks that moves and raw policies remain identical with and without auditing; wall times are not claimed identical.

## Aggregated-state counterexample

The report also records two hidden-history feedback assignments. With old weights (0.5,0.5), both yield the same PRM+ regrets (0.5,0) and the same previous utility (1,0). With new weights (0.9,0.1), their reconstructed regrets differ: (0.9,0) versus (0.1,0). The same subsequent feedback then produces different policies.

Consequently the aggregated minimizer plus new root weights alone does not identify the reweighted state. This is not an impossibility theorem for offline replay; it demonstrates why additional history-specific training data or proven restrictions are needed. Current reach ratios alone do not supply that missing information, and regret clipping makes arbitrary retrospective reweighting more complicated.

## Reproduce

```powershell
python -m pytest pair_a_prep/tests/test_transition_audit.py pair_a_prep/tests/test_gadget_frames.py pair_a_prep/tests/test_affine_solver.py -q
python -m pair_a_prep.transition_probe --output pair_a_prep/local_runs/transition-audit.json
```

The focused selection has 59 passing cases. Tests include independent nonuniform-root arithmetic, fresh versus rebuilt cutoffs, malformed metadata, source immutability, a same-moves/raw-policies control, capped/null output and the aggregated-state counterexample. The report declares source/rule/config identities and normalized source hashes.

## Next integration decision

The existing cross-turn rebase remains a heuristic warm start, not an exact transport justified by this audit. Next, compare heuristic warm versus cold solving on the same frozen target tree and track any per-history data needed for a justified reweighting. Do not infer numerical ancestor-payment lifting, add old gifts to new boundaries or enable projected labels from these diagnostic results.

## Frozen-target follow-up

The first controlled warm/cold target-tree comparison is documented in [frozen_warm_cold.md](frozen_warm_cold.md). It measures an initialization bundle with explicit round and average-policy caveats, not exact changed-game transport or comparative playing strength.
