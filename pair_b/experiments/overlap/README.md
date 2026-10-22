# Position overlap between the evaluation rows and the training data

Game IDs restart at `g-000000` in every generated dataset, so 955 of the 959 evaluated d2-check
games share an ID string with a d2-v2 training game although the games differ. This checks what
matters for leakage: the same positions in both. A position is the FEN without its move number,
which is everything the 19-plane encoding sees.

From `pair_b/`, with the two data folders:

```
.venv/bin/python experiments/overlap/overlap.py data/d2-v2 data/d2-check <out.json>
```

Result (`position-overlap-d2-check-train-vs-d2-v2.json`): of d2-check's train bucket (94,963
rows at 3,818 parents from 959 games), 168 rows (0.18%) have a position that is also a d2-v2
training or validation row, and 5 parents, in 5 games, are also d2-v2 training or validation
parents. The JSON lists those five.
