# Warm and cold initialization on identical frozen target games

This offline experiment follows the actual transition audit. It changes no live agent, factory, label schema, warm-start rule or default policy.

## Controlled comparison

The existing Material/heuristic-warm agent supplies private-turn snapshots. For each snapshot, one target projection is prepared before any new CFR round or growth. Preparation retains the source node and evaluator-call caps. Resolve and Maxmargin are then examined separately, with a fixed mode, boundary, prior, root set and payoff tree.

Three independently cloned solvers receive exactly the same target-tree fingerprint and checkpoints at 0, 1, 4 and 8 additional full rounds:

| Method | Initial state |
|---|---|
| heuristic_warm | Production rebase_solver plus seed_new; retains compatible regrets, predictors, strategies and historical averages |
| seeded_cold | Empty state, heuristic initial actions, round counter 0 |
| round_aligned_seeded_cold | Empty state and heuristic initial actions, with the counter aligned to the warm history for future averaging weights |

The round-aligned alternating control publishes its seeded pending strategy before stepping. All methods share schedule, predictive setting and averaging power. Warm source rounds are history on an older game, not extra training on the new target. Round alignment does not isolate every state component: warm retains historical average sums and policies, while cold does not.

No evaluator calls, tree growth, purification or mode switching occur during the comparison. Preparation is excluded and recorded separately. Utility traversal counts are recorded; equal added rounds are **not** an equal-arithmetic, equal-time or equal-total-training claim. Snapshots and frozen targets are not mutated. A paired control verifies snapshot collection preserves source moves and raw policies in fixed-work mode.

## Finite-game metric

Each last and average profile receives a value, lower bound, upper bound and gap. The upper bound is the player-0 best response against the current opponent; the lower bound is the opponent's best response against the current player-0 policy. The gap is upper minus lower.

The dynamic best-response calculation aggregates all occurrences of an infoset with opponent/chance reach and resolves actions in reverse own-history order. It keeps one action per infoset and avoids exponential pure-policy enumeration. It is checked against independent exhaustive responses on matching pennies, hidden coin, Kuhn poker and both gadget types, including zero-reach branches.

These bounds apply only to the sampled, estimated finite gadget. They are not full FoW exploitability or playing strength. Resolve and Maxmargin have different objectives/offsets; their gap magnitudes must not be pooled. Input-belief continuation values are exported separately from gadget objectives and do not become TrainingRecords. Projected labels remain disabled.

## Recorded sample

`results/frozen_warm_cold_reference.json` uses the same three public starts and seeds 17/29 as the transition audit. Six source games produce 12 private target snapshots. Each is evaluated in both modes: 24 fixed-game comparisons, with no preparation failure. Source games are four-ply capped/null fixtures, not warm-versus-cold matches. The targets come from the existing warm agent's trajectory, so they are not a representative sample of states a cold agent would visit.

The JSON summary uses the **last-policy finite gap after eight added rounds**, with tie tolerance 1e-10. Counts compare methods within the same target; these are descriptive counts, not independent match outcomes or statistical superiority tests.

| Mode | Control | Warm lower gap | Tied | Warm higher gap |
|---|---|---:|---:|---:|
| Resolve | seeded cold | 1 | 11 | 0 |
| Resolve | round-aligned seeded cold | 1 | 11 | 0 |
| Maxmargin | seeded cold | 1 | 11 | 0 |
| Maxmargin | round-aligned seeded cold | 1 | 11 | 0 |

Average policies show a different pattern, and are retained rather than hidden:

| Mode | Control | Warm lower average gap | Tied | Warm higher average gap |
|---|---|---:|---:|---:|
| Resolve | seeded cold | 4 | 6 | 2 |
| Resolve | round-aligned seeded cold | 5 | 7 | 0 |
| Maxmargin | seeded cold | 5 | 6 | 1 |
| Maxmargin | round-aligned seeded cold | 5 | 7 | 0 |

The single last-policy difference in each mode is rook_pawn seed 17, Black at ply 3. Resolve gaps are about 0.005872 warm versus 0.014793 seeded cold; Maxmargin gaps are about 0.089990 versus 0.102017. Do not compare those magnitudes across modes. The many shallow Material ties and changing average-policy conclusions preclude a general warm-start benefit claim.

## Reproduce and verification

```powershell
python -m pytest pair_a_prep/tests/test_frozen_search.py pair_a_prep/tests/test_finite_security.py pair_a_prep/tests/test_transition_audit.py pair_a_prep/tests/test_gadget_frames.py pair_a_prep/tests/test_affine_solver.py -q
python -m pair_a_prep.frozen_search_probe --output pair_a_prep/local_runs/frozen-warm-cold.json
```

The focused selection has 80 passing tests. It checks the pure-policy metric oracle, actual copying versus zeroed cold state, matched added-round accounting under both schedules/modes, source immutability, repeatability, nonconstant report metrics, preparation caps and source trajectory preservation. The reference includes Python/chess/NumPy versions, source/rule/config identities, input hypotheses, all checkpoints, per-method initialization hashes, target fingerprints, raw policies, both profile metrics and separate preparation failures.

## Next decision

The current experiment is evidence about an initialization bundle on a small frozen target sample. It neither proves exact cross-turn transport nor supports changing the live default. Next use richer target positions and explicit controls for retained regret versus held policy and historical average sums. Define any causal attribution carefully; resetting a stored utility vector alone does not necessarily remove PCFR's recomputed opponent-profile predictor. Numerical ancestor-payment lifting, bounded inference and the projected-label contract remain separate work.
