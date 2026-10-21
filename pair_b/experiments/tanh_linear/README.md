# Linear correction inside tanh

Bryan's question on PR #8: how much of the value-error gap between the linear correction and
Network 1 comes from Network 1's output transform, and how much from its board reader?

This run fits the same linear correction, on the same 1,217 inputs (19 planes of 64 squares, plus
the depth-1 value d1), inside Network 1's output: v = tanh(atanh(clip(d1, 0.999)) + X w + b). The
loss is mean squared error in value space plus alpha times the squared length of w (b is not
penalised), as for the plain linear fit. Alpha was picked on d2-v2's validation games from 1e-5,
1e-4 and 1e-3 (1e-5 won, validation MSE 0.0210). All scorers are then scored on d2-check's train
bucket, the same rows as the committed linear and Network 1 evaluations.

## Files

| File | What it is |
|---|---|
| `linear_tanh.py` | The script as it ran on 20 October (before PR #8 merged, hence its PYTHONPATH note) |
| `tanh-linear-d2-check-train.json` | Its report: fit, scores, paired differences, the three bands |
| `tanh-linear.npz` | The fitted weights w, b and alpha |
| `run.log` | Its console output |
| `make_band_figure.py` | Draws Figure 1 of the D8 draft from the JSON, as plain SVG (no third-party package) |
| `value-error-by-band.svg` | Its output, byte-identical to the draft's figure |
| `value-error-by-band.png` | The same figure rendered for the Word draft |

## Command

From `pair_b/`, with the two D2 data folders (they are not in the repo):

```
.venv/bin/python experiments/tanh_linear/linear_tanh.py <d2-v2> <d2-check> \
  checkpoints/linear-v1/best.npz checkpoints/net1-v2 <out folder>
python3 experiments/tanh_linear/make_band_figure.py
python3 experiments/tanh_linear/make_band_figure.py --check
```

The run took 130 seconds. The data it read, by the SHA-256 the JSON records (the hash of each
`part-*.jsonl` and `manifest.json`, combined as in `pairb.provenance.data_files`):

- fit: d2-v2, `b6f05233a5c2f9737a84410f382a3cbc9fa67d4e8b5f8f25b7289f3f281bd758`, 638,451 training
  and 76,765 validation positions (the same hash as `checkpoints/net1-v2/provenance.json`);
- evaluation: d2-check, train bucket, `5475455ca72909b1481058b96d80a1f62aec890f25d1aafe8e2af5eff2983903`,
  94,963 positions at 3,818 decisions from 959 games (the same hash as
  `checkpoints/linear-v1/eval-d2-check-train.json`).

## Results

Value error is the mean of |v - v_d11| over the 94,963 positions; top-1 and regret are move choice
at the 3,818 decisions. Intervals are 95%, from 2,000 resamples of whole games with seed 0.

| Scorer | Value error | Top-1 move | Regret |
|---|---|---|---|
| Quick Stockfish (depth 1, the paper's leaf) | 0.0949 | 42.9% | 0.0355 |
| Linear correction | 0.0841 | 41.5% | 0.0346 |
| Linear correction inside tanh | 0.0790 | 43.5% | 0.0348 |
| Network 1 | 0.0757 | 42.4% | 0.0352 |

| Paired difference in value error | Mean | 95% interval |
|---|---|---|
| Inside tanh minus linear | -0.0051 | -0.0060 to -0.0042 |
| Inside tanh minus Network 1 | +0.0033 | +0.0025 to +0.0041 |
| Inside tanh minus quick Stockfish | -0.0159 | -0.0175 to -0.0143 |
| Network 1 minus linear | -0.0084 | -0.0094 to -0.0075 |

The answer: moving the linear correction inside tanh closes 0.0051 of the 0.0084 gap between the
linear correction and Network 1, about 61%; the remaining 0.0033 is Network 1's board reader. On
move choice no pair differs: every paired regret interval in the JSON includes zero (inside tanh
minus linear +0.0001, -0.0012 to +0.0015; inside tanh minus Network 1 -0.0005, -0.0022 to +0.0014).

By band (Figure 1), mean value error per scorer:

| Band (share of positions) | Quick Stockfish | Linear | Inside tanh | Network 1 |
|---|---|---|---|---|
| Close, \|v\| < 0.3 (16%) | 0.091 | 0.095 | 0.111 | 0.107 |
| Leaning, 0.3 to 0.9 (49%) | 0.109 | 0.103 | 0.094 | 0.093 |
| Decided, \|v\| > 0.9 (35%) | 0.076 | 0.052 | 0.043 | 0.037 |

In close positions every correction is worse than quick Stockfish alone; the gains come from
leaning and decided positions.
