# Explicit payoff-frame transport toys

This isolated mathematical prototype establishes what must remain invariant when old gadget payments are re-expressed. It is **not** integrated into ChessSubgameAgent, warm_start or the gift ledger. The live ledger remains audit-only.

## Declared frames and assumptions

All utilities use the player-0 sign convention. A frame declares

`common_value = scale * local_value + offset`, with finite `scale > 0`.

Two frames may be related only after the caller proves they refer to the same common unit. Matching unit strings assert that proof; a FEN, source hash, belief weight or ledger parent does not establish it. The toy API refuses different unit IDs and invalid scales. Offsets must be constant across actions within each group, including exit. Trees must retain the same information and action structure.

Scalar transport uses `(source.scale * old_value + source.offset - target.offset) / target.scale`. A delta or gift increment uses only `source.scale / target.scale`; offsets cancel. Carrying a payment in the right unit does not prove it should be added: ancestor identity, retention and double counting still need separate treatment.

## Resolve prior transport

Write the old group payoff as `old_v[J] = a[J] * new_v[J] + b[J]`, where

- `a[J] = target.scale[J] / source.scale[J]`;
- `b[J] = (target.offset[J] - source.offset[J]) / source.scale[J]`.

For a fixed original prior p, set `Z = sum(p[J] * a[J])` and `q[J] = p[J] * a[J] / Z`. Then every pure-strategy pair satisfies

`old_payoff = Z * new_payoff + sum(p[J] * b[J])`.

Since Z is positive, this preserves the finite game's strategic ordering. Merely converting values while keeping p can change the game when group scales differ. The oracle fixture uses p=(0.7, 0.3), target scales (2, 0.25), target offsets (0.3, -0.1): Z=1.475 and shift=0.18. Every normal-form matrix entry agrees to about 1.1e-16; the source LP value is 0.17.

## Maxmargin counterexample

A free opponent selector cannot be repaired by changing a chance prior. Margins must be compared in their original common units.

| Group | Original margin | Target scale | Unweighted local margin | Corrected source-unit margin |
|---|---:|---:|---:|---:|
| A | 0.2 | 0.1 | 2.0 | 0.2 |
| B | 0.3 | 1.0 | 0.3 | 0.3 |

The minimizing group flips from A to B if local margins are compared directly. A separate Maxmargin normal-form LP reproduces the value change from 0.2 to 0.3; scaling the rows back recovers 0.2. Transferring only alternate payoffs is insufficient.

## Reproduce and scope

```powershell
python -m pytest pair_a_prep/tests/test_value_frames.py pair_a_prep/tests/test_gift_accounting.py pair_a_prep/tests/test_subgame_boundaries.py -q
python -m pair_a_prep.value_frame_probe --output pair_a_prep/local_runs/value-frames.json
```

The focused selection has 25 passing tests; `results/value_frame_toy_reference.json` records the matrix, oracle values, frames and complete normalized source manifest. Toy transformed utilities can lie outside [-1,1]; they must not be clamped or exported as ordinary training values.

Remaining work: derive proven frames from actual CF reaches and gadget offsets; transport compatible solver regret/predictor/average state; handle outside-sample branches; verify real multi-turn decisions. The Resolve algebra alone does not implement Obscuro's payment lifting, full knowledge closure, tracker replenishment or a strength improvement.
