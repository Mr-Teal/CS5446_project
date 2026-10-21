# Small games: the Kuhn-poker convergence figure

Inputs for Section 3's half page on Pair A's small-game verification, produced from Pair A's code without changing it. `run_kuhn_control.py` imports Pair A's `pcfr.py` and `toy_games.py` (on their branch `pair-a/rules-interface`, or on `main` once #15 merges) and runs Kuhn poker with the alternating schedule twice, PCFR+ and the same solver with `predictive=False`, recording the last and average iterate's value and Nash gap at 14 log-spaced checkpoints up to 2,000 rounds. `make_gap_figure.py` draws `kuhn-gap-vs-rounds.svg` from that JSON with no third-party library, and `--check` compares the PCFR+ curve with Pair A's committed `pcfr_alternating_reference.json` at the five checkpoints they share (it matched to 1e-9 on 22 October).

The control is "PCFR+ with zero predictions", not the published CFR+: `pcfr.py` keeps its quadratic averaging and the schedule when predictions are off. Cite Farina, Kroer and Sandholm (2021) for the predictive step only.

What the figure shows: PCFR+'s last iterate reaches a gap of exactly zero by round 100 and its average by round 1,000; with zero predictions the last iterate stalls between 0.03 and 0.1 and the average is still at 2e-4 after 2,000 rounds. The four other toy games (matching pennies, the two coin games, the KLSS and KLUSS cuts) are solved exactly at the first update, so they are a sentence and an appendix table, not a figure.

Commands, from the repository root with Pair A's environment (NumPy and SciPy) and their files on the path:

```sh
PYTHONPATH=. pair_a_prep/.venv/bin/python pair_b/experiments/small_games/run_kuhn_control.py --out pair_b/experiments/small_games/kuhn-gap-vs-rounds.json --reference pair_a_prep/results/pcfr_alternating_reference.json
python3 pair_b/experiments/small_games/make_gap_figure.py --curves pair_b/experiments/small_games/kuhn-gap-vs-rounds.json --out pair_b/experiments/small_games/kuhn-gap-vs-rounds.svg --reference pair_a_prep/results/pcfr_alternating_reference.json --check
```
