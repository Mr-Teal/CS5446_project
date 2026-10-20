# Linear baseline validation

Validated against main at `6d743a4aa2ff1467d8265a87c5fd0b2eea171db8` on 19 October 2026.
All base files were verified against GitHub blob hashes before editing. Only `pair_b/README.md`
changes among existing files; the implementation, commands, tests and reports are additions.

## Checks

145 selected tests passed, including 26 new baseline tests, with real Stockfish 19 on PATH:

```sh
export PYTHONPATH="pair_b/src:."
python -m pytest tests \
  pair_b/tests/test_linear.py pair_b/tests/test_linear_evaluator.py \
  pair_b/tests/test_linear_workflow.py pair_b/tests/test_data.py \
  pair_b/tests/test_encode.py pair_b/tests/test_metrics.py \
  pair_b/tests/test_material.py pair_b/tests/test_stockfish.py \
  --import-mode=importlib -q -p no:cacheprovider
```

Coverage includes an independent augmented-least-squares reference, chunk-size invariance,
unpenalized intercept, packed/live feature agreement, clipping and checkpoint round trips,
colour/perspective conversion, fog-only castling/move coverage, exact rule bypasses, batches
and belief ordering, split isolation, test-target perturbation invariance, overlap rejection
and final-test opt-in. Fresh-process training, evaluation and complete timing also passed with
an import hook that rejects torch imports. Checkpoint loading uses no pickle.

This is a selected regression suite, not the full neural or Pair A suite. Torch is unavailable
in the local Python 3.14 x86_64 environment; the optional Network 1 comparison paths were not
executed. A broader Pair A collection attempt also requires unavailable SciPy. Existing
python-chess asyncio deprecation warnings were emitted by the passing selected tests.

## Pilot

Generated 120 ordinary-chess stand-in games with Stockfish 19, depth-11 labels, seed 5446,
three sampled parents per game, maximum 120 plies, four workers. The dataset has 9,487 records;
four rule-decided rows are excluded by the existing Network 1 loader. It yielded 7,981 training
rows from 100 games, 841 validation rows from ten games, and nine held-out test games. One
generated game contributed no non-rule rows. Test
games were not evaluated. Alpha 0.1 won the default validation sweep. The pilot's labels,
caches and checkpoint stay outside Git.

| Evaluator | Validation MAE | Mean move-choice regret | Median complete children call |
|---|---:|---:|---:|
| Material | 0.336663 | 0.321849 | 3.188 ms |
| Depth-1 Stockfish | 0.100150 | 0.014255 | 6.044 ms |
| Linear correction | 0.095154 | 0.013347 | 8.064 ms |

Validation contains 30 parent decisions from ten games. The linear-minus-depth-1 regret
difference is -0.000908, with a 95% whole-game bootstrap interval of [-0.011621, +0.008440]
(2,000 resamples, seed zero). This does not establish better move choice. These same validation
games selected alpha; the interval does not account for that selection. The roughly 5% lower
MAE is exploratory validation evidence, not a final held-out improvement claim.

Timing ran after training/tests on this macOS x86_64 machine, Python 3.14.0, NumPy 2.5.4,
python-chess 1.11.2, with 30 unique validation parents, three passes (90 calls per evaluator),
30.57 children per parent on average. It includes rules, encoding, Stockfish and correction.
All engines used one thread, 16 MB hash and retained search state between calls; evaluator
order rotated. Separate parent ordering/machines/load can change timings. The linear adapter
was slower than depth-1 Stockfish here. No comparison with the README's Apple GPU timings is
implied.

To reproduce after generating the pilot as documented in `linear_baseline.md`:

```sh
python pair_b/scripts/train_linear.py --data pair_b/data/linear-pilot-120 \
  --out pair_b/runs/linear-pilot-120-v1
python pair_b/scripts/eval_linear.py --run pair_b/runs/linear-pilot-120-v1 \
  --data pair_b/data/linear-pilot-120 --split val \
  --out pair_b/runs/linear-pilot-120-v1/eval-val.json
python pair_b/scripts/benchmark_linear.py --run pair_b/runs/linear-pilot-120-v1 \
  --data pair_b/data/linear-pilot-120 --limit 30 --repeats 3 \
  --out pair_b/runs/linear-pilot-120-v1/timing-val.json
```

Reproduction can vary with Stockfish build/architecture; hashes identify this particular run.
The same-record Network 1 comparison, fitted on Colin's original data, is in
`checkpoints/linear-v1/` (see `linear_baseline.md`); full-game experiments remain to be run.
No playing-strength or belief-conditioning claim is made by this pilot.
