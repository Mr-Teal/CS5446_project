# Matches: the pilot, the superseded pilot and the cross-check

Runs of `scripts/play_matches.py` and the independent `pairb.match_experiment` cross-check under the protocol in `docs/match_protocol.md`. None of them is a strength claim; the 200-game runs come later.

| Folder | What | Result |
|---|---|---|
| `pilot-d1-vs-material/` | 10 games, random openings of 2 to 8 plies, 200-ply cap, seed 0, stand-in rules, played on the committed runner (commit 00639cb, clean tree) | Quick Stockfish 10 of 10 against piece values; 5 complete pairs, score 1.00, no bootstrap interval (fewer than 20 pairs), Wilson 0.57 to 1.00; 49.7 plies and 12.7 s a game; 14.2 ms a move for quick Stockfish, 4.0 for piece values |
| `pilot-d1-vs-material-shared-engine-state/` | The same 10 games as first played (commit d900296), before every scorer started each game with a clean engine. Kept for the record, never to be cited | 9 of 10 (0.90). With identical openings and seeds, 8 of the 10 games differ in length from the clean-engine run (only game ids 0 and 5 match, the 1st and 6th games) and game id 7, the 8th game, has the other winner: engine state carried across games changes results |
| `crosscheck-d1-vs-material-standard-start/` | 20 games from the standard start (`--opening-plies 0 0`), the pairing Bryan's runner plays, same tracker (256 particles, 8 guesses), cap and rules | Quick Stockfish 20 of 20; 10 complete pairs, score 1.00, Wilson 0.72 to 1.00; 40.5 plies and 7.8 s a game |
| [crosscheck-bryan-d1-vs-material-standard-start/](crosscheck-bryan-d1-vs-material-standard-start/) | Bryan's `pairb.match_experiment` run from main `3afc594`, audited 22 October 2026; standard start, ten seeds, both colours, stand-in rules, engine reset before every call | Quick Stockfish 20 wins, 0 draws, 0 losses; 10 complete pairs, score 1.00, Wilson 0.72 to 1.00; 36.7 plies a game (734 total), no failed games or act-budget overruns. Original config, manifest, games, summary and audit retained; compare with Colin's run, do not pool |
| `engine-policy-probe.json` (`engine_policy_probe.py`) | A rerun on Colin's Mac of the probe Bryan described in his #16 review, on his position: scored fresh and after an earlier search, with the hash kept (this runner within a game) and cleared (his runner). Bryan's own run changed 18 depth-1 values and all 30 depth-11 values, and he did not claim a change of move | Hash kept: 9 of 30 depth-1 values change (up to 0.02), all 30 depth-11 values (up to 0.10), and in this rerun the depth-11 best move changes (e2e3 to c2h7); cleared: none |
| `crosscheck-config-for-match-experiment.json` | The same pairing for `pairb.match_experiment` (Bryan's runner, PR #14): ten seeds, both colours, 256 particles, 8 hypotheses, 2,000 rebuild tries, 200-ply cap, `standin` | Completed at `3afc594`; see Bryan's artifact folder above. A sanity check, not an equivalence test: compare the runs separately and do not infer equivalence from their matching aggregate scores |

For a new run, use the repository root on `main` (#14 is merged), so both runners use the same `pairb.stockfish` (his branch carried an older copy without the blocked-position draw and `new_game()`). Record the source revision; reproducing Bryan's historical run instead requires the pinned revision and configuration described in its artifact folder:

```sh
PYTHONPATH=pair_b/src:. python -m pairb.match_experiment --config pair_b/experiments/matches/crosscheck-config-for-match-experiment.json --out <new folder>
```

The two runners share the game machinery (`fow_shared.evaluation.play_game`, the one-ply bot, the particle tracker, the referee) and differ in engine policy: his clears the engine before every call, ours before every game with the hash kept within a game. The same position gets different values under the two policies (`engine-policy-probe.json`), so the runs are compared, not pooled.
