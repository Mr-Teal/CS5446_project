# Network 1 vs Stockfish D1: readiness diagnostic

## Outcome

The runner stopped at the first readiness pair (seed 17): both colour-swapped games failed with `TreeCapacityError: requested tree exceeds max_nodes=4096`. The batch was not launched, so no playing-strength score is available. There was no machine failure or power interruption.

| Stage | Planned | Attempted | Terminal | Capped | Failed | Unplayed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Opening check (seed 17) | 2 games | 2 | 0 | 2 | 0 | 0 |
| Readiness (seeds 17 and 18) | 4 games | 2 | 0 | 0 | 2 | 2 |
| Batch (50 colour-swapped pairs) | 100 games | 0 | 0 | 0 | 0 | 100 |

The opening caps are expected, unscored four-ply checks. Failed games are not scored as draws or losses. The batch counts in `analysis.json` exclude opening and readiness games.

## Identities and configuration

- Source commit: `10352fe54ec5c11acbad8671f165642b812eae78`; recorded Git status was clean.
- Network 1 checkpoint: `pair_b/checkpoints/net1-v2/best.pt`; SHA-256 `ab470346acb5eb37947e3ab0eb43c005894ae72569ca016d7635fc2be6f9171f`.
- Engine: Stockfish 19 Windows x86-64 universal; SHA-256 `45bc8e4969147db9c2eb533810637994619bff0eacc81ccfd9854394901bcbd0`.
- Network device: `cuda:0`, NVIDIA GeForce RTX 5070 Ti Laptop GPU; Stockfish player device: CPU. Python 3.13.13, PyTorch 2.12.0+cu130, CUDA 13.0.
- Fixed depth 2, 16 solver rounds, 4096 nodes, four sampled hypotheses, Teal rules, 5-second cooperative search allowance. Python exact-or-fail tracker: 16-second / 512-MiB logical-memory allowance per update, no pruning or resume. Stockfish: one thread, 16 MiB hash. See the recorded INI files for the complete settings.
- Declared limits: four hours total, 20 minutes per pair. The readiness failure was not a pair timeout.

## Reproduction

With the original handoff package, pinned clean checkout, checkpoint and Stockfish 19, run from outside the checkout with a new output path:

```powershell
python run.py --repo C:/Projects/PycharmProjects/CS5446_evaluation --stockfish C:/Projects/PycharmProjects/CS5446_project/pair_c/stockfish/stockfish-windows-x86-64-universal.exe --out C:/Projects/PycharmProjects/CS5446_evaluation_trial --device auto
```

Adapt the paths for the host and use a nonexistent output directory.

## Supporting records

`CS5446_evaluation_trial-return.zip` contains the original configs, logs, game records, provenance and analysis. SHA-256: `87fbb231acbd4b0b5d21db1236e0e834c6bbe6841229951425c982d469172323`.
