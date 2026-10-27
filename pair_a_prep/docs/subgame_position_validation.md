# Richer-position integration evidence

This is bounded engineering validation of the optional sampled-I^2 gadget
prototype, not a representative chess strength study or timing benchmark.

## Reproduce

From the repository root:

```powershell
& .\pair_b\.venv\Scripts\python.exe -m pair_a_prep.subgame_validation --output pair_a_prep/local_runs/subgame-positions-review.json
& .\pair_b\.venv\Scripts\python.exe -m pytest -q tests pair_a_prep/tests
```

Inputs: `data/subgame_positions.json`. Output:
the fresh path supplied with `--output`. The original `results/subgame_positions_reference.json` is historical; the corrected evidence is `results/subgame_positions_review_reference.json`. The JSON records source hashes,
the base commit at execution (not a claim that later uncommitted corpus files
already belonged to that commit), Python/chess/NumPy versions, Material source
hash, leaf depth, configurations, seeds, tracker limits, raw/played policies,
actual evaluator work, node counts, timing, mode switches, retained/fresh roots,
fallbacks, resource failures and capped versus actual terminal outcomes.
Wall times vary; reruns need not reproduce the JSON bytes.

## Coverage

Twelve declared position/history cases cover:

- Standard public start for White and a Black-to-move public-start variant.
- Pawn capture, both colours' promotions and en passant.
- FoW castling through attack and exposing one's own king legally.
- Real king capture overriding heuristic estimates.
- Automatic fifty-move and third-repetition boundaries with retained stacks.
- A move into the shared no-fog-legal-move draw.

The repetition fixture supplies one declared consistent hypothetical history,
not a full posterior. Other single-root checks start at their public FEN. This
is distinct from the live runs, which use the actual shared private-observation
loop and independent exact trackers. A separate rule-history check includes #37's FoW-effective EP example and explicitly reports it blocked until the shared fix is integrated. It is not counted among the successful search roots.

## Recorded live runs

The Material-backed integrated agent plays both sides, with seeds 17 and 29.
All runs use 8 CFR rounds per turn, initial depth 1, maximum depth 2, 1024 chess
nodes, at most 48 evaluator calls, and a diagnostic 10000 ms action budget.
`stop_on_time=False` makes work scheduling reproducible; the second half of
solver rounds is used for support stability. This is **not** a hard-deadline
stress test or a claim about original Stockfish-based runtime.

| Public start | Seed | Plies | Result |
|---|---:|---:|---|
| Standard | 17 | 4 | capped, null outcome |
| Standard | 29 | 4 | capped, null outcome |
| Pawn endgame | 17 | 6 | capped, null outcome |
| Pawn endgame | 29 | 6 | capped, null outcome |
| Rook/pawn endgame | 17 | 6 | capped, null outcome |
| Rook/pawn endgame | 29 | 3 | actual White win |

Totals: 29 actions, no fallback, no action over 10000 ms, and no tracker capacity
failure. The slowest recorded action was approximately 967 ms on this machine.
The historical head had 478 shared/Pair A tests; this is not a test count for the review-fix head.
Action timing excludes tracker updates in the shared runner. The exact tracker
population peaked at **1819/2000 (91%)**, at ply 5 of rook_endgame seed 17; its final population was only 1750; short-run success
does not show that long games fit. No WDL rate or rating is inferred from these
tiny synthetic/capped games.

The action records demonstrate old-root reuse, fresh-root insertion and gadget
mode changes, including switching twice within a turn. A real observed
opponent move with zero blueprint reach exposed a division-by-zero in the
projected Resolve prior. Core PR #42 now applies and audits the explicit
all-zero-y uniform fallback; a separate visible-king regression exercises it.

## Next experiments

After tracker/weight/rule review: longer capped runs with explicit resource
failures, strict clock-enabled runs across move budgets, and matched compute
ablations for raw versus purified and uniform versus selective policies.
Original Stockfish 14 calibration, full-history inference, complete gift
bookkeeping and formal cross-agent evaluation remain separate work.

## Review-fix evidence and interpretation

The new reference has 12 root checks, six live games and 29 actions: five capped/null games, one actual White win, no uniform-move fallback and no observed 10000 ms overrun. These counts apply only to the explicitly recorded **1024 nodes / 48 evaluator calls**, not arbitrary smaller budgets. The factory now adopts these subgame defaults in #42.

Per-game peak populations (white / black): standard seed 17 421/343, standard seed 29 20/343, pawn seed 17 119/119, pawn seed 29 119/119, rook seed 17 119/1819, rook seed 29 2/9. Peaks include intermediate tracker updates, not merely the final turn. Capacity errors retain the completed action trace and mark unavailable completed-run plies as null; they are never counted as draws.

Actions export `zero_reach_uniform_prior` separately from uniform-move fallback. Under shallow Material search many raw policies are exact ties; purification then follows move order, not learned preferences. Projected training labels remain gated independently of these act()-based engineering runs.

All runtime Python source paths are repository relative and SHA-256 hashes normalize CRLF to LF, as declared by `source_hash_convention`. The manifest includes shared terminal scoring, Material/value code, expansion, gadgets and the runner; the corpus JSON is also hashed. Revision queries run from the repository root. Preserve historical artifacts rather than relabelling their hashes or numbers.
