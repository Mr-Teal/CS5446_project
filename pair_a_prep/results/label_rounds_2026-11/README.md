# Label rounds 2 and 3 and generation-0 self-play: per-game logs

One row per attempted game, as written by `pair_a_prep/label_run.py` when the game ended. They are here so that the
counts in sections 2.1 and 2.7 of `pair_a_prep/docs/handover_2026-11-12.md` can be recomputed (`python3 stats.py`).
The label records themselves (the positions with their search values) are not in git; they are on the VM under
`/home/dev/cs5446-review/labels/` and on Atlas under `/hpctmp/tommy.21.31/fow/`.

| File | Run | Protocol |
|---|---|---|
| `round2-progress.jsonl` | Label round 2, Atlas array 1038003, 20 tasks x 12 games, seeds 50001 + 1000 task + 2 game | Search agent (Python solver), SF-d8 leaf, 30 s a move |
| `round3-progress.jsonl` | Label round 3, Atlas array 1038307, seeds 80001 + 1000 task + 2 game | same |
| `gen0-vm-progress.jsonl` | Generation-0 self-play on the VM, seeds 100001 + 2 game; paused at 159 of 240 games | Search agent (native solver), value network v2 (480-set run 1) on the GPU, 2 s a move |
| `gen0-atlas-progress.jsonl` | Generation-0 self-play, Atlas array 1039088, seeds 300001 + 1000 task + 2 game; snapshot of 12 Nov 03:00 SGT with two tasks still running | same agent, leaf on one CPU thread, 12 s a move |

Rows are in task order, then game order. A row with `error` set is a failed game; the positions labelled before the
failure are kept in the label records. Atlas runs are acknowledged as NUSREC-HPC-00001.
