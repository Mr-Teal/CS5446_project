# The #17 batch, 27 October 2026

Colin ran the #17 batch on his M5 Pro Mac (macOS 26.5.1, torch 2.14.1 on mps, Stockfish 19). Each side plays in the one-ply bot against quick Stockfish: 200 games, 100 colour pairs, random 2 to 8 ply openings, seed 0, stand-in rules. Rows ran one at a time from a clean worktree at a5c5fb6 (main 2af8f1f plus #34): material, stockfish-d1, linear, random, network1, belief, stockfish-d11. The batch ran 26 Oct 22:47 to 27 Oct 08:09 SGT; stockfish-d11 took about 6 hours. It is pre-rule (`no_move_rule` `unresolved`, #28 not on main), with no no-move games.

Row folders hold `summary.json` (only `settings.out` changed, to the relative `runs/matches/<row>` from `command`) and `games.jsonl.gz`; logs and `batch-status.tsv` sit beside them, unchanged. `checksums.json` has every copied file's sha256 (and the original's, for `summary.json`), and what each `.gz` unpacks to.

## Results

Each side inside the one-ply bot against quick Stockfish, 200 games (100 colour pairs), seed 0, rules pairb-standin, no-move rule unresolved (0 no-move failures), commit a5c5fb6, Stockfish sha256 dc2f18c34ae9. Score = the side's paired score; equal work per move with the rest of the bot held fixed, not equal computation. Failed games are excluded with their pair and counted by cause (match_protocol.md, Failures).

| Side (vs quick Stockfish) | Score | Wilson 95% | Bootstrap 95% | W-D-L | Pairs | Plies | ms/move median (p95) | Value lost | Failed games | Other endings |
|---|---|---|---|---|---|---|---|---|---|---|
| random | 0.00 | 0.00 to 0.04 | none | 0-0-199 | 99 | 31.0 | 0.0 (0.0) | n/a | 1 TrackerLost | none |
| material | 0.05 | 0.02 to 0.11 | 0.02 to 0.08 | 9-1-190 | 100 | 44.6 | 4.3 (7.3) | 0.012 | none | threefold_repetition 1 |
| linear | 0.51 | 0.42 to 0.61 | 0.46 to 0.57 | 98-9-93 | 100 | 55.5 | 14.2 (30.0) | 0.060 | none | threefold_repetition 7, ply_limit 2 |
| stockfish-d1 | 0.52 | 0.42 to 0.62 | 0.46 to 0.59 | 103-2-95 | 100 | 50.2 | 11.1 (23.9) | 0.069 | none | threefold_repetition 2 |
| network1 | 0.52 | 0.42 to 0.61 | 0.45 to 0.59 | 100-6-94 | 100 | 49.3 | 36.1 (52.7) | 0.067 | none | threefold_repetition 6 |
| belief | 0.56 | 0.46 to 0.66 | 0.49 to 0.63 | 111-3-86 | 100 | 52.0 | 149.8 (257.4) | 0.059 | none | threefold_repetition 3 |
| stockfish-d11 | 0.58 | 0.49 to 0.68 | 0.51 to 0.66 | 114-6-80 | 100 | 55.0 | 2452.2 (9054.7) | 0.063 | none | threefold_repetition 2, ply_limit 4 |

Checks: all passed

Exact values: linear 0.5125, network1 0.515, belief 0.5625, stockfish-d11 0.585; bootstrap ends material 0.0225 to 0.0775, belief's low end 0.495, stockfish-d11's low end 0.5125. The prose rounds these half up to 3 decimals; the run logs round the stored floats with ties to even, so they print 0.512, 0.562, 0.022 to 0.077 and 0.512. Value lost uses each side's own scorer, so rows differ in scale.

## One failure

random-vs-d1 game 36 (opening 18; `game 37/200` in the log) hit `TrackerLost` at ply 18 in quick Stockfish's tracker. The 256-particle cap dropped the true position at ply 7, so no kept position fitted a bishop seen at ply 17, and the rebuild found none. A replay reproduces it. It is the tracker limit under Failures in `match_protocol.md`: the game and its pair are excluded, and the row exited 1. A random win there would give 0.005.

## What it shows

Equal work per move, not equal time:

- Sanity rows pass: stockfish-d1 against itself scores 0.520 (both intervals include 0.5); random and material are far below.
- linear (0.513) and network1 (0.515) score close to 0.5: both intervals include 0.5, so neither differs from quick Stockfish here.
- belief (0.563) and stockfish-d11 (0.585) are above 0.5 by point estimate. Both belief intervals include 0.5. stockfish-d11's Wilson includes 0.5, but its bootstrap (0.513 to 0.660) does not. Weak evidence: a correction for seven rows removes it.
- Rows are not head-to-head. A gap needs about 0.10 to show; the top five span 0.513 to 0.585 (belief minus network1: +0.048; resampling the 100 shared openings gives about -0.05 to +0.15).
- Median time per move: network1 about 3 times quick Stockfish, belief 13 times, stockfish-d11 220 times. No move passed the 60 s budget.

## What it does not show

No equal-time claim, no strength claim beyond these pairings. No evidence that the belief network learns the value of hidden information: its labels are board-level (#24). Pre-rule, so never pooled with runs after #28. Bryan's runner stays a separate check.

## Provenance after #34

From the repository root on main, this checks each `record.source_sha256` against the files. Every row should print `all match` (before #34, `play_matches.py` and `bot.py` differ).

```sh
python3 - <<'EOF'
import hashlib, json, pathlib
for f in sorted(pathlib.Path("pair_b/experiments/matches/batch-2026-10-27").glob("*/summary.json")):
    src = json.loads(f.read_text())["record"]["source_sha256"]
    bad = [p for p, h in src.items() if hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() != h]
    print(f.parent.name, f"{len(src)} files,", "all match" if not bad else f"differ: {bad}")
EOF
```

## Rebuilding the table

From this folder (standard library; exits 1 if a check fails):

```sh
python3 make_batch_table.py --runs . --out table.md --json table.json
```
