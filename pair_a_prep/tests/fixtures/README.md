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
