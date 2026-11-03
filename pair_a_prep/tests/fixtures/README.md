# Sequence-form numerical regression

`zs21_lp_v5_ply80.npz` is the full A/B/C and flow-constraint model from
`results/formal-100-v5/game-004.jsonl.gz`, seed 210606072, ply 80. Both agents'
80 committed decisions were recreated with their logged completed iteration
counts: every sampled move and every root-policy entry matched exactly. The
original 1e-8 solve again failed the independent full-tree certificate with
gap 1.242005452852398e-8. This fixture is independent of live Stockfish and
native tracker objects; infoset identifiers are replaced by row numbers while
variable, row and action order are retained.

SHA-256: `9a8c30fb0f949c9c1eb865e5b158e9657bd843941706176700fc6b108a8ab145`.
Full matrix shape: 5766 by 2513; forced-action reduction: 2357 by 628.
With 1e-9 feasibility, the same full certificate gap is
1.5363714488262586e-10. The acceptance threshold remains 1e-8.

See project decision D-25 and `results/integration/lp-precision-v1.json`.

## Historical HiGHS Not Set failures

`zs21_lp_not_set_game001_ply61.npz` and
`zs21_lp_not_set_game006_ply68.npz` contain the unchanged full A/B/C and flow
models reconstructed from games 2 and 7 of the frozen 34-game evaluation.
Each `_raw.npz` companion contains the exact first failing SciPy LP input:
objective, CSR inequality/equality matrices, right-hand sides, bounds and
options. Numeric coefficients and sequence order are retained; live game
objects and engine processes are not required.

The replay matched all 64 preceding own decisions and both failure-turn
fallback policies, moves, completed rounds and node counts. The captured LPs
reproduce the failures in the locked Windows runtime (SciPy 1.18.1 / HiGHS
1.12.0). Independent rational certificates verified feasibility and finite
optimal values. See [the recovery record](../../docs/zs21_highs_recovery.md).

| Fixture | SHA-256 |
|---|---|
| `zs21_lp_not_set_game001_ply61.npz` | `ab0ab6f6980ef5ec19f99ab82c56836d49bab05096ed6613a0014266427e39e8` |
| `zs21_lp_not_set_game001_ply61_raw.npz` | `eea8a16185aef9fa6317b76f2c846d7906165654237cb7db014765505d2efcfc` |
| `zs21_lp_not_set_game006_ply68.npz` | `5dc442fdc2c2fb169d86ee8a5ec590c250464d2bdd647031859093b4d321cb84` |
| `zs21_lp_not_set_game006_ply68_raw.npz` | `21bfbf3cc61a4f0404c875623e753bff2ad1ee5d021eae0c1abc5ba45f69aaf6` |
