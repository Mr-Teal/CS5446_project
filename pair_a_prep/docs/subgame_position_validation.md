# Richer-position integration evidence

This is bounded engineering validation of the optional sampled-I^2 gadget
prototype, not a representative chess strength study or timing benchmark.

## Reproduce

From the repository root:

```powershell
& .\pair_b\.venv\Scripts\python.exe -m pair_a_prep.subgame_validation
& .\pair_b\.venv\Scripts\python.exe -m pytest -q tests pair_a_prep/tests
```

Inputs: `data/subgame_positions.json`. Output:
`results/subgame_positions_reference.json`. The JSON records source hashes,
the base commit at execution (not a claim that later uncommitted corpus files
already belonged to that commit), Python/chess/NumPy versions, Material source
hash, leaf depth, configurations, seeds, tracker limits, raw/played policies,
actual evaluator work, node counts, timing, mode switches, retained/fresh roots,
fallbacks, resource failures and capped versus actual terminal outcomes.
Wall times vary; reruns need not reproduce the JSON bytes.

## Coverage

Eleven declared position/history cases cover:

- Standard public start for White and a Black-to-move public-start variant.
- Pawn capture, both colours' promotions and en passant.
- FoW castling through attack and exposing one's own king legally.
- Real king capture overriding heuristic estimates.
- Automatic fifty-move and third-repetition boundaries with retained stacks.

The repetition fixture supplies one declared consistent hypothetical history,
not a full posterior. Other single-root checks start at their public FEN. This
is distinct from the live runs, which use the actual shared private-observation
loop and independent exact trackers. The corpus does not settle #37's effective
EP repetition disagreement.

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
The complete shared and Pair A regression suite passed **478 tests** after
adding these corpus checks and the zero-opponent-reach regression.
Action timing excludes tracker updates in the shared runner. The exact tracker
population reached 1750 in one six-ply run against a cap of 2000; short-run success
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
