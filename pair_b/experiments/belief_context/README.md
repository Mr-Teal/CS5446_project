# Belief context on practice labels: seed spread and sensitivity

Two checks of what the belief network's context (the pooled summary of the rest of the belief) does on practice beliefs, whose labels are depth-11 Stockfish values of each board taken alone, so the true value of a board does not depend on the belief it sits in. Neither is evidence about belief-dependent value; that needs Pair A's solver labels. They make the committed one-seed comparison honest.

## Five seeds per variant (`seeds.json`, `collect_seeds.py`)

The three variants of `scripts/train_belief_net.py` were trained on d6-v1 with seeds 1 to 4 (about a minute each on an Apple GPU) beside the committed seed-0 runs, and scored on d6-check's training bucket (3,818 beliefs, 30,406 boards) by `scripts/eval_belief_net.py`. The summaries and eval files of every run are under `seed_runs/` (home folders written as `~`); the checkpoints are not committed. Seed 0 is the committed run of 18 October; seeds 1 to 4 were trained on 22 October with the current training script (each eval names its commit).

| Variant | Flags | Board error, mean over 5 seeds | Range | Position error, mean |
|---|---|---|---|---|
| Reads quick Stockfish, with context | `--use-d1` | 0.0734 | 0.0725 to 0.0748 | 0.046 |
| The same, ignoring the rest of the belief | `--use-d1 --no-context` | 0.0762 | 0.0751 to 0.0776 | 0.048 |
| Board planes only | | 0.188 | 0.177 to 0.207 | 0.151 |
| Quick Stockfish alone | | 0.0798 | | 0.0548 |

Context minus no context on board error, seed by seed: -0.0019, -0.0049, -0.0011, -0.0026, -0.0034 (mean -0.0028). The gain is small and consistent, outside the seed spread, and it cannot be information about the belief, because the labels carry none: it is denoising, the network smoothing its estimate of a board over its company. The planes-only network's spread across seeds is fourteen times that of the two that read quick Stockfish (standard deviations 0.014 against 0.001; five times relative to its mean).

## Sensitivity to the company a board keeps (`sensitivity.json`, `sensitivity.py`)

For the first 300 check beliefs of the train bucket in file order, every board was placed in a second belief built around it by `standin_beliefs.make_turn` with another seed, and the kept network (`checkpoints/belief-v1-d1`) scored both; one rule-decided board was skipped. Over 2,385 boards the value of a board moved by 0.014 on average between the two beliefs (median 0.003, 95th percentile 0.054, 29% of boards by more than 0.01, 6% by more than 0.05), against the network's own error of 0.087 on the same boards: about a sixth of its error (a sixteenth by medians). The value in the second belief is no closer to the label (0.087 against 0.087; closer on 42% of boards, farther on 58%), which is what noise looks like. This subset is harder than the bucket as a whole: quick Stockfish errs by 0.093 on these boards against 0.080 overall, so the 0.087 is not comparable to the table's 0.074. The same measurement on solver-labelled beliefs is what would show the context carrying information.

Commands, from `pair_b/` with the data under `<Pair B>/code/data/`:

```sh
for s in 1 2 3 4; do
  .venv/bin/python scripts/train_belief_net.py --data <data>/d6-v1 --out runs/belief-seeds/ctx-s$s --use-d1 --seed $s
  .venv/bin/python scripts/train_belief_net.py --data <data>/d6-v1 --out runs/belief-seeds/noctx-s$s --use-d1 --no-context --seed $s
  .venv/bin/python scripts/train_belief_net.py --data <data>/d6-v1 --out runs/belief-seeds/pure-s$s --seed $s
  for v in ctx noctx pure; do .venv/bin/python scripts/eval_belief_net.py --run runs/belief-seeds/$v-s$s --data <data>/d6-check --split train; done
done
.venv/bin/python experiments/belief_context/collect_seeds.py --runs runs/belief-seeds --out experiments/belief_context/seeds.json   # also writes seed_runs/
.venv/bin/python experiments/belief_context/sensitivity.py --data <data>/d6-check --out experiments/belief_context/sensitivity.json
```
