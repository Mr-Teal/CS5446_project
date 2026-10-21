# Matches: the pilot, the superseded pilot and the cross-check

Runs of `scripts/play_matches.py` under the protocol in `docs/match_protocol.md`. None of them is a strength claim; the 200-game runs come later.

| Folder | What | Result |
|---|---|---|
| `pilot-d1-vs-material/` | 10 games, random openings of 2 to 8 plies, 200-ply cap, seed 0, stand-in rules, played on the committed runner (commit 00639cb, clean tree) | Quick Stockfish 10 of 10 against piece values; 5 complete pairs, score 1.00, no bootstrap interval (fewer than 20 pairs), Wilson 0.57 to 1.00; 49.7 plies and 12.7 s a game; 14.2 ms a move for quick Stockfish, 4.0 for piece values |
| `pilot-d1-vs-material-shared-engine-state/` | The same 10 games as first played (commit d900296), before every scorer started each game with a clean engine. Kept for the record, never to be cited | 9 of 10 (0.90). With identical openings and seeds, 8 of the 10 games differ in length from the clean-engine run (only games 1 and 6 match) and game 7 has the other winner: engine state carried across games changes results |
| `crosscheck-d1-vs-material-standard-start/` | 20 games from the standard start (`--opening-plies 0 0`), the pairing Bryan's runner plays, same tracker (256 particles, 8 guesses), cap and rules | Quick Stockfish 20 of 20; 10 complete pairs, score 1.00, Wilson 0.72 to 1.00; 40.5 plies and 7.8 s a game |
| `engine-policy-probe.json` (`engine_policy_probe.py`) | Bryan's probe from his #16 review, committed: one position scored fresh and after an earlier search, with the hash kept (this runner within a game) and cleared (his runner) | Hash kept: 9 of 30 depth-1 values change (up to 0.02), all 30 depth-11 values (up to 0.10, and the best move changes); cleared: none |
| `crosscheck-config-for-match-experiment.json` | The same pairing for `pairb.match_experiment` (Bryan's runner, PR #14): ten seeds, both colours, 256 particles, 8 hypotheses, 2,000 rebuild tries, 200-ply cap, `standin` | To be run by Bryan; the rule is that his paired score falls inside the Wilson interval above |

Run Bryan's side from the repository root once #14 is merged onto `main`, so both runners use the same `pairb.stockfish` (his branch carries an older copy without the blocked-position draw and `new_game()`):

```sh
PYTHONPATH=pair_b/src:. python -m pairb.match_experiment --config pair_b/experiments/matches/crosscheck-config-for-match-experiment.json --out <new folder>
```

The two runners share the game machinery (`fow_shared.evaluation.play_game`, the one-ply bot, the particle tracker, the referee) and differ in engine policy: his clears the engine before every call, ours before every game with the hash kept within a game. The same position gets different values under the two policies (`engine-policy-probe.json`), so the runs are compared, not pooled.
