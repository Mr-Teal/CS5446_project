# Match protocol

Status: proposed on 22 October 2026, pending the runner decision with Bryan on 26 October. Nothing here is a strength claim; the 200-game runs have not been played.

## What the study measures

One planner, five leaves. Every side is the one-ply belief bot (`pairb.bot.OnePlyBot`) on its own particle tracker (256 particles, 8 guesses), playing the move with the best weighted average value over its guesses. Only the leaf evaluator changes: piece values, quick Stockfish (depth 1, the paper's leaf), careful Stockfish (depth 11), Network 1, the belief network, the linear correction, and `random` as a floor. So a difference between two rows is a difference between leaves at equal search work: the same planner, the same number of guesses, the same tracker.

It is not an equal-time comparison. The one-ply bot does not read the time budget and is not an anytime search, so "the same wall clock" has no meaning here; cost is reported beside strength instead (time per move per side, and the tracker's time separately). Equal-time comparisons belong inside an anytime search over beliefs, which is Pair A's player.

The bots are honest: through `fow_shared.evaluation.play_game` each one receives only its own observations and its own tracker's belief; the runner alone reads the true board, after the game, to measure the value lost by not knowing.

## Engine policy

Stockfish 19, one thread, 16 MB hash. Every scorer, and the second copy used for the value-lost measurement, starts each game with `ucinewgame`; within a game the hash is kept between calls, as inside a search. The run file records this under `settings.engine`. A Stockfish that dies (a crash) is reopened after the game or measurement that found it dead, scorer and second copy, and the game records which side was reopened; a run stops after five failed games in a row.

Bryan's runner (`pairb.match_experiment`, PR #14) clears the engine before every call and opens fresh engines per game. The two policies give different depth-1 values on the same position (9 of 30 moves in one probe, up to 0.08 in value), so results from the two runners are compared, not pooled.

The engine state matters. With identical openings and seeds, the pilot played before the per-game reset and the pilot played after it differ in the length of 7 of 10 games and in the winner of one (`experiments/matches/README.md`). No match number from before the reset (commit 44eec48) is cited anywhere.

## Openings, pairing and seeds

Opening i is k random legal plies, k drawn from 2 to 8 by `random.Random(seed * 1000 + i)`, never a move that ends the game, played through the runner so both trackers see every ply. Each opening is played twice with the colours swapped. `--opening-plies 0 0` plays every pair from the standard start, which is the setting the cross-check uses. Game n has match seed `seed * 1000 + n`; `play_game` seeds White with it and Black with it plus one.

## Rules

One table, one set of rules. A run of more than two games must pin `--rules standin` or `--rules teal`; the runner refuses `auto`, which becomes Teal's adapter the moment his branch merges. The run file records the rules id and the SHA-256 of Pair A's rules files. If the rules of record change, every pairing of the table is rerun; a table never mixes the two.

Open question for 26 October: a position where a side has no fog-legal move and no rule result. Pair B's stand-in rules and Teal's adapter both leave it undecided; in play the bot raises and the game is recorded as an error with the text "no legal move"; inside the Stockfish evaluator such a child scores as a draw. Options: a draw, a loss for the blocked side, or a pass. Until it is decided, a table footnote states the count of games that failed for this reason, and the referee's `terminal()` and `pairb/stockfish.py` must agree afterwards.

## Score and intervals

The first-named side's score is wins plus half the draws over the complete colour pairs (openings whose two games both finished, one with each colour); a pair scores 0, 0.5 or 1. Raw wins, draws and losses count every finished game and are reported beside it; incomplete pairs are counted and excluded.

Two intervals. Wilson's 95% score interval on the pair-level proportion (n = complete pairs) is always given; it is an approximation that treats a pair's score as a proportion, and it stays informative at 0 and 1 (5 of 5 pairs: 0.57 to 1.00; 100 of 100: 0.96 to 1.00). A percentile bootstrap that resamples complete pairs (2,000 resamples, seed 0) is given only when there are at least 20 complete pairs that do not all score the same; otherwise it would collapse to a point and is withheld as degenerate, with the reason in the run file. For the 200-game rows the bootstrap is the headline interval where it exists and the Wilson interval covers the rows near 0 or 1.

## Failures

A game that raises (a tracker that loses the position, a scorer that fails, a side with no legal move) is recorded with its error, excluded from the score and from its pair, and the run goes on. A value-lost measurement that fails after a game finished keeps the game; the move records `diagnostic_error`. The run exits with status 1 if any game or measurement failed, so a batch wrapper notices; a table built from a run with errors states their count and cause.

## The runs for the report

Proposed, pending the decision with Bryan. From `pair_b/`:

```bash
for a in material stockfish-d1 stockfish-d11 network1 belief linear random; do
  .venv/bin/python scripts/play_matches.py --a $a --b stockfish-d1 --games 200 --seed 0 --rules standin --out runs/matches/$a-vs-d1
done
```

Time, from the pilot: about 40 minutes per quick pairing on an M5 Pro Mac; the careful-Stockfish pairing about 9 machine-hours at about 700 ms per depth-11 call, so a second machine or 100 games. The network sides need torch. Quick Stockfish against itself should score about 0.5 and `random` close to 0; those two rows check the runner.

## The cross-check against Bryan's runner

Two runners were built independently. `play_matches.py` is proposed as the runner of record for the varied-opening tables above; `pairb.match_experiment` (PR #14) stays unchanged as the independent second implementation, run once on one pairing from the standard start. The settings are aligned in `experiments/matches/crosscheck-config-for-match-experiment.json` (quick Stockfish against piece values, standard start, 256 particles, 8 guesses, 2,000 rebuild tries, 200-ply cap, `standin`, ten seeds with both colours) and the same pairing was played by `play_matches.py --opening-plies 0 0 --games 20` into `experiments/matches/crosscheck-d1-vs-material-standard-start/`: quick Stockfish won all 20, 10 complete pairs, Wilson 0.72 to 1.00. The rule: Bryan's paired score must fall inside that Wilson interval. The report then says that the two implementations agree on that pairing, and names the one policy difference (engine reset per call versus per game).

## What the report may say from this

Strength at equal work, with intervals; cost per move beside it; the value lost by not knowing per side as the value-of-information diagnostic; and the tracker's health (particles, capped and rebuilt updates). Not: equal-time strength, Obscuro-level play, or anything from a run with unexplained errors.
