# Linear correction to depth-1 Stockfish

This baseline tests how much a simple learned correction can contribute before using Network 1's
nonlinear board reader. It reuses D2 records, Network 1's 19-plane encoding and game split, and
the `LeafEvaluator` interface. It is board-only: beliefs are evaluated one hypothesis at a time.
It does not learn an imperfect-information strategy or replace Pair A's search.

## Model and fitting

Let `x` concatenate the flattened **float** planes and the side-to-move depth-1 value: 1,217
features. The prediction is `clip(d1 + x @ coef + intercept, -1, 1)`. The correction is affine;
the clipping is a bounded output transform. Unlike Network 1, it does not use tanh/atanh.

Ridge fitting minimizes `mean((x @ coef + intercept - (d11-d1))**2) + alpha * sum(coef**2)`.
The intercept is unpenalized. Inputs are centered on training rows only; no validation/test
statistics enter fitting. A single symmetric eigendecomposition fits the positive alpha grid.
Alpha is selected by **clipped validation MSE**, with the first alpha winning a tie. It is not
optimized on move-choice regret. Features are not standardized; this is an explicit baseline
choice, and alpha is defined for the mean-loss objective rather than the summed-loss objective.
Ridge statistics and predictions are computed in chunks of 4,096 rows, avoiding a full float64
design matrix. The existing D2 record/packed-array loader still holds the dataset in memory.

The split is the existing SHA1 of `game_id` modulo ten: buckets 0–7 train, 8 validation, 9 test.
All rows are read/encoded for bookkeeping, but test targets do not enter fitting or selection.
Changing only test targets is covered by a regression test. The checkpoint records training and
selection game IDs with a content key per game, file-content SHA256 hashes, encoding,
source-code hash and runtime versions.

Training/evaluation exclude rule-decided rows exactly as the existing Network 1 array loader
does. Move-choice metrics therefore compare **the remaining sibling candidates**, not all legal
moves in those cases. The live evaluators preserve exact rule scores and full fog-legal move
coverage. Values are converted from each child's side-to-move view when choosing a parent's move;
the existing `choice_metrics` implementation chooses the minimum-valued child.

## Run from the repository root

The baseline needs Python 3.12+, NumPy and python-chess; pytest for checks and Stockfish 19 for
data generation/live evaluation/timing. The existing `pair_b` package declares torch because it
also contains neural models. In an environment without torch, install the shared package and
the baseline dependencies, then expose the existing source directory:

```sh
python -m pip install -e . numpy pytest
export PYTHONPATH="pair_b/src:."

python pair_b/scripts/train_linear.py --data pair_b/data/d2-v2 --out pair_b/runs/linear-v1
python pair_b/scripts/eval_linear.py --run pair_b/runs/linear-v1 \
  --data pair_b/data/d2-v2 --split val --out pair_b/runs/linear-v1/eval-val.json
python pair_b/scripts/benchmark_linear.py --run pair_b/runs/linear-v1 \
  --data pair_b/data/d2-v2 --split val --out pair_b/runs/linear-v1/timing-val.json
```

If already using the project's uv environment, use `uv run python ...` from `pair_b/` and paths
relative to that directory. On PowerShell, the source-path setting from the root is
`$env:PYTHONPATH = "pair_b/src;."`.

Use Colin's original `d2-v2` dataset for fitting, and the same fresh evaluation records for all
models, to obtain the intended comparison. Neither dataset is in Git. Generate a **pilot** with
the existing `make_d2.py` if needed:

```sh
python pair_b/scripts/make_d2.py --games 120 --parents-per-game 3 --max-plies 120 \
  --workers 4 --seed 5446 --out pair_b/data/linear-pilot-120
```

The existing generator restarts IDs at `g-000000` for each run, so the same ID in two datasets
is usually two different games. Evaluation therefore compares games by ID only on the fitting
dataset itself (same dataset hash). On any other dataset it compares them by content: training
stores a content key per game next to the train and val game lists (the first 16 hex characters
of the sha1 of the game's sorted unique parent FENs), and the evaluated games' keys are checked
against them. A checkpoint without content keys is checked by ID. The report gives the overlaps
used (`fitting_game_overlap`, `selection_game_overlap`), their `overlap_basis` (`game_id` or
`content`) and the raw `game_id_overlap`. Evaluation rejects overlap with fitting games, and
rejects selection-game overlap from a different dataset. `--allow-seen-games` permits diagnostic
checks but reports the overlap explicitly. Validation on the original fitting dataset is allowed
and marked as selection data. The test split requires `--final`; reserve it until the protocol
is fixed.

With torch installed, add `--net1-run pair_b/checkpoints/net1-v2` to `eval_linear.py` to score
Network 1 on the **same rows** (CPU). Supply its original `splits.json` via `--net1-splits` if
it is not alongside the checkpoint. Without that evidence, Network 1's split status is
reported as unknown; the report's `independent_games` field refers to the linear model only.
The split file lists game IDs only: when its train and val games are the linear model's
(`same_games_as_linear`), the linear model's overlap holds for Network 1 too, by content on
another dataset; otherwise its IDs are compared with the evaluated games' IDs.
With evidence, overlaps require `--allow-seen-games`. Compare model quality only after checking
both models' fitting/selection games. Existing published README numbers came from another
dataset and machine and are not a direct comparison with this pilot.

Outputs refuse overwrites. `best.npz` stores numeric coefficients and JSON metadata, without
pickle. `summary.json` retains the alpha sweep and depth-1 validation metrics; `splits.json`
records the game split. Evaluation reports MAE/MSE, move-choice metrics and paired regret
differences with a fixed-seed, whole-game bootstrap. The bootstrap does not account for model
selection on the same validation games. Timing includes encoding, Stockfish and correction;
it uses separate warmed engines with one thread, 16 MB hash and `new_game_each_call=False`,
rotates evaluator order, and checks equal legal-move coverage. `--net1-run` also works for
timing. Dataset, source, engine binary and checkpoint hashes are retained for provenance.

## Use in the search

```python
from pairb.linear_evaluator import LinearEvaluator

with LinearEvaluator.from_checkpoint("pair_b/runs/linear-v1/best.npz",
                                      new_game_each_call=False) as leaf:
    children = leaf.evaluate_children(fen)
    boards = leaf.evaluate_boards(fens, player="white")
    beliefs = leaf.evaluate_beliefs(turns)
```

The adapter follows Network 1: children use one parent MultiPV depth-1 call plus fog-only
fallbacks, whereas standalone boards use their own depth-1 call. Those engine inputs are not
identical; D2 trains on the parent MultiPV distribution. Rule-decided values bypass the model.
Values at the interface are from the requested/acting player's view. A FEN does not carry
repetition history; these methods retain the existing shared interface's limitation.

## Pilot and remaining work

See [the pilot validation record](linear_baseline_validation.md). It exercises generation,
fitting, prediction, move-choice metrics and complete evaluator timing. Its validation results
are model-selection evidence, not an independent final result. The original dataset comparison,
Network 1 execution and full-game playing-strength experiments remain separate follow-ups.

Prepared with Codex assistance.
