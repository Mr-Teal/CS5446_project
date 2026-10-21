# Measurements behind numbers in pair_b/README.md

Each script writes one JSON file that the README names; each refuses to overwrite. Run from
`pair_b/` with the venv's Python and `PYTHONDONTWRITEBYTECODE=1`; `<d2-check>` is the D2 check-set
folder (`data/d2-check`).

| Script | Writes | What it measures |
|---|---|---|
| `time_stockfish_d11.py <d2-check> <out>` | `checkpoints/timing-stockfish-d11.json` | careful Stockfish's time per node, on 30 of the 300 parents the other timings use |
| `d1_parent_vs_own.py <d2-check> <out>` | `checkpoints/belief-v1-d1/d1-parent-vs-own.json` | how far a parent's MultiPV depth-1 score of a child is from the child's own depth-1 value |
| `time_new_game_each_call.py <d2-check> <out>` | `checkpoints/timing-new-game-each-call.json` | how much faster quick Stockfish and Network 1 are inside a search (`new_game_each_call=False`) |
| `time_belief_evaluator.py <d6-check> <out>` | `checkpoints/belief-v1-d1/timing-beliefs.json` | the belief evaluator's time per belief, in one call and one at a time, and the share spent building planes |
| `observe_agreement.py --games 500 --out <out>` | `checkpoints/observe-agreement.json` | the stand-in views against Teal's `RulesAdapter.observe()` on every view of 500 random games |

`observe_agreement.py` needs Teal's adapter, which is on `pair-a/rules-interface`, not on main. It
was run with a temporary worktree of `origin/main` merged with that branch (head 8e914ef, whose
`pair_a_prep/` is unchanged since 219eb6a) first on `PYTHONPATH`:
`PYTHONPATH=<worktree>:<worktree>/pair_b/src .venv/bin/python experiments/readme_checks/observe_agreement.py --games 500 --out checkpoints/observe-agreement.json`.

The other timings come from the scripts themselves: `scripts/benchmark_linear.py` (CPU, and
`--net1-device mps` for the Apple GPU) and `scripts/bench_tracker.py --out`.
