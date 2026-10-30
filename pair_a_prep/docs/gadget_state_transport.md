# Derived gadget coordinates and checked affine solver transport

This follow-up to the explicit-frame toys derives coordinates from actual finite gadget fields and validates one restricted solver-state conversion. It adds standalone APIs only. ChessSubgameAgent, rebase_solver, factories, labels and the gift ledger are unchanged.

## 1. Frames derived from a constructed gadget

For opponent group J, let `M[J] = sum(root.reach_mass)` over its sampled roots. The builder's conditional root probabilities are `reach_mass / M[J]`.

| Gadget continuation | Local group value | Declared raw reach-weighted sum |
|---|---|---|
| Resolve, after enter | conditional mean of u | M[J] * local |
| Maxmargin | conditional mean of u - alternate[J] | M[J] * local + M[J] * alternate[J] |

Thus the common-coordinate scale is M[J]; the offset is zero for Resolve and M[J]*alternate[J] for Maxmargin. This follows the constructed gadget's payoff convention; it does not certify that externally supplied reaches are the paper's correct CF reaches.

`certify_gadget_frames` verifies each stored gadget against its declared construction, then requires identical ordered raw root IDs, groups, masses and unshifted continuation trees. The common unit ID hashes that exact raw snapshot. Different histories, weights or continuations are rejected; the API does not infer a cross-turn correspondence. Numerical reconstruction of probabilities/payoffs uses 1e-12 tolerance to accommodate floating-point roundoff; root snapshot equality remains strict.

The test uses three hidden roots with group masses 4 and 2, unequal within-group weights and shared own information. Direct evaluation of the actual Maxmargin branches agrees with the derived frames for several policies. Mutated stored trees, changed root IDs, masses, groups, order or payoffs are rejected. This certifies continuation coordinates, **not** equivalence of Resolve and Maxmargin as entire games.

## 2. One safe solver-state conversion

`transport_affine_solver` accepts a target tree only if it has exactly the same players, infosets, ordered actions, topology, chance probabilities and cutoff flags. Every target terminal must satisfy the same global equation

`u_new = a * u_old + b`, with finite a > 0.

The map is inferred and checked at all leaves with 1e-12 numerical tolerance. A constant-payoff source uses scale 1 as an explicit choice. Negative scales, changed chance probabilities and per-group/non-affine terminal changes are rejected. Positive global affine equivalence of the normal-form matrix alone is insufficient if the extensive-form structure changed.

For either player and any infoset, the global offset adds an action-independent counterfactual baseline. It cancels in `utility - strategy @ utility` and predictive regret matching. The copied state therefore uses:

- regrets multiplied by a;
- previous utility vectors multiplied by a, in a baseline-free gauge;
- unchanged published strategy, pending-feedback flag, cached opponent profile and initial-action seed;
- unchanged own-reach average accumulators and round count.

The copied previous utility need not equal the target's raw utility vector; its action differences must agree. Tests compare centered vectors rather than incorrectly claiming raw equality. The source and target tree/state are detached, and the original solver is not mutated. Floating-point equality is numerical, not bit-for-bit identity.

## 3. Verified finite cases

```powershell
python -m pytest pair_a_prep/tests/test_gadget_frames.py pair_a_prep/tests/test_affine_solver.py pair_a_prep/tests/test_value_frames.py pair_a_prep/tests/test_subgame_boundaries.py pair_a_prep/tests/test_gift_accounting.py -q
python -m pair_a_prep.gadget_state_probe --output pair_a_prep/local_runs/gadget-state.json
```

The focused selection has 77 passing cases. It covers both schedules, predictive and nonpredictive matching, averaging powers 0 and 2, scaling up/down, offsets, partial chance reach, pending initial seeds, and actual multi-group Resolve/Maxmargin trees. Converted warm state after seven rounds is compared to a target solver trained from scratch, then both continue eight rounds. Separate actual-gadget cases start after five rounds. Regrets, averages, centered predictors and policies are checked, including source independence.

`results/gadget_state_transport_reference.json` records two reach/offset checks and four actual gadget/schedule continuation traces with full normalized source hashes. The largest policy error is about 6.7e-16. This is algebraic/implementation evidence, not convergence, exploitability or playing-strength evidence.

## 4. What this does not permit

Resolve-to-Maxmargin conversion changes enter/exit versus selector structure. A test explicitly verifies that a valid continuation-frame certificate still fails the solver-state certificate. Different per-group offsets also generally fail the single-global-map requirement. The APIs therefore do not replace the existing heuristic mode-switch warm start.

Real turns change the sampled roots, reach normalization, information sets and possibly unseen continuations. Deriving those correspondences, preserving the necessary original reach units, handling outside-sample branches and avoiding ancestor-payment double counting remain open. Numerical ancestor gifts are not added to the ledger or new boundaries. Future integration must first exhibit a valid transform for a real retained-root transition and justify the changed-game solver-state rule; it cannot rely only on matching hashes or these fixed-tree toys.
