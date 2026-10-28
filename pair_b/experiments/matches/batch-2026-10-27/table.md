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
