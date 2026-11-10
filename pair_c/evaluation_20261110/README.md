# Network 1 vs Stockfish D1 evaluation

The GPU evaluation attempted all 50 colour-swapped pairs (100 games, seeds 1001–1050). Of those games, 93 reached a terminal result and 7 failed; none were capped, missing or unplayed. The failures affected 6 pairs, leaving 44 complete clean pairs for scoring.

On those 44 pairs, Network 1 scored **46.59%** (41 wins, 47 losses, 0 draws); the whole-pair bootstrap 95% interval was **36.36%–56.82%**. This score is conditional on clean completion and cannot be generalized to all planned seeds. The interval does not establish equivalence.

The excluded seeds were 1002, 1031, 1032, 1034, 1036 and 1043. Four games failed because bounded-history replay found no consistent full path; two exhausted the tracker update time allowance; and one exceeded the pruning time allowance. Failed games were not scored as draws or losses. The seed 17 opening check and seed 17/18 readiness checks passed and are excluded from batch statistics.

## Configuration and identities

- Source: PR 76 commit `aaa000a034ae5275afe981402891596e660312a4`, with clean recorded checkout. The handoff controller and settings were adapted from the original evaluation package to use the PR 76 configuration.
- Network 1 checkpoint: `pair_b/checkpoints/net1-v2/best.pt`, SHA-256 `ab470346acb5eb37947e3ab0eb43c005894ae72569ca016d7635fc2be6f9171f`.
- Stockfish 19 Windows universal, SHA-256 `45bc8e4969147db9c2eb533810637994619bff0eacc81ccfd9854394901bcbd0`, one thread and 16 MiB hash.
- Network device: `cuda:0`, NVIDIA GeForce RTX 5070 Ti Laptop GPU. Stockfish and native tracking ran on CPU. Python 3.13.13, PyTorch 2.12.0+cu130, CUDA 13.0.
- Both players used uniform-growth anytime search, initial depth 1 and maximum depth 2, 16 solver rounds, 4096 nodes, 128 evaluator calls and four sampled hypotheses. The cooperative search allowance was 5 seconds.
- Both used approximate native `bounded-history` tracking: at most 8192 retained paths, up to eight recovery attempts and a separate 60-second tracker allowance. These limits are not a hard process-memory or whole-turn deadline.
- The native library was built using the Pixi `darkchess` environment; its SHA-256 is `e8e738067e122f38b9f6faec6af7ee1cb5e6112121cdf322778e91d7d3494ed6`.

## Supporting records

[CS5446_evaluation_output-return.zip](CS5446_evaluation_output-return.zip) contains the generated configs, controller, logs, per-game and tracker records, provenance, build identity and analysis. Archive SHA-256: `e1716bada940d07d12de3bdc4f96a6f3bf83a4f12414ded0f720fb250a6cdce5`.
