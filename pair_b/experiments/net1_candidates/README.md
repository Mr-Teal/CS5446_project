# The two other Network 1 candidates

On 16 October three Network 1 runs were trained on d2-v2 and scored on d2-check's training bucket
(the check set): the kept run, `checkpoints/net1-v2`, and the two here. Each folder has the run's
`summary.json` (its `cache_dir`, `data` and `out` written relative to the folder the runs used),
its training log `metrics.jsonl` and its check-set result `eval-d2-check-train.json`. The weights
are not committed.

| Run | Blocks x channels | Learning rate, weight decay | Best epoch | Validation error | Check-set error |
|---|---|---|---|---|---|
| net1-v2 (kept) | 6 x 64 | 0.002, 0.0001 | 1 of 6 | 0.0778 | 0.0757 |
| v2-big | 10 x 128 | 0.001, 0.0001 | 2 of 6 | 0.0816 | 0.0792 |
| v2-slow | 6 x 64 | 0.0005, 0.001 | 2 of 6 | 0.0816 | 0.0787 |

The kept run was the best on validation as well as on the check set, so choosing it by the check
set did not pick a different run from the one validation picks. All three were scored on the
check set's training bucket only.
