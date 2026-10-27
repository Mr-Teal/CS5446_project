# Match protocol

Status: the decisions on #17 are recorded here. Colin proposed them on 24 October 2026, Teal and Bryan supported them, and objections stay open until 27 October 23:59 SGT. In short: `play_matches.py` is the runner of record; Bryan's runner is an independent sanity check, shown side by side and never pooled; every table uses `--rules standin`; a side with no fog-legal move and no rule result is a draw everywhere; the engine hash is kept within a game and cleared before every game; the batch is seven rows against quick Stockfish, 200 games each, seed 0. Nothing here is a strength claim; the 200-game runs have not been played.

## What the study measures

One planner, five leaves, plus two comparison sides. Every side is the one-ply belief bot (`pairb.bot.OnePlyBot`) on its own particle tracker (256 particles, 8 guesses), playing the move with the best weighted average value over its guesses. Only the leaf evaluator changes: piece values, quick Stockfish (depth 1, the paper's leaf), careful Stockfish (depth 11), Network 1 and the belief network; beside them the linear correction and `random` as a floor. So a difference between two rows is a difference between leaves with the rest of the bot held fixed: the same planner, the same number of guesses, the same tracker. It does not equalise total computation: the leaves themselves differ in internal work, most of all Stockfish at depth 1 and at depth 11.

It is not an equal-time comparison. The one-ply bot does not read the time budget and is not an anytime search, so "the same wall clock" has no meaning here; cost is reported beside strength instead: time per move per side (mean, median and 95th percentile of the bot's own call, which excludes its tracker), the plies over the time budget per side, the game's wall clock, and each tracker's state after every update (particles, capped, rebuilt). Equal-time comparisons belong inside an anytime search over beliefs, which is Pair A's player.

The bots are honest: through `fow_shared.evaluation.play_game` each one receives only its own observations and its own tracker's belief; the runner alone reads the true board, after the game, to measure the value lost by not knowing.

## Engine policy

Stockfish 19, one thread, 16 MB hash. Every scorer, and the second copy used for the value-lost measurement, starts each game with `ucinewgame`; within a game the hash is kept between calls, as inside a search. The run file records this under `settings.engine`, with the wall-clock limit on each Stockfish call (`call_timeout_s`). A Stockfish that dies (a crash) or stops answering (see Failures) is reopened after the game or measurement that found it dead, scorer and second copy, and the game records which side was reopened; a run stops after five failed games in a row.

Bryan's runner (`pairb.match_experiment`, PR #14) clears the engine before every call and opens fresh engines per game. The two policies give different values on the same position: with the hash kept from one earlier search, 9 of 30 depth-1 values change (by up to 0.02) and all 30 depth-11 values (by up to 0.10, and the best move changes), none with the hash cleared (`experiments/matches/engine-policy-probe.json`). Results from the two runners are therefore compared, not pooled.

The engine state matters. With identical openings and seeds, the pilot played before the per-game reset and the pilot played after it differ in the length of 8 of 10 games and in the winner of one (`experiments/matches/README.md`). No match number from before the reset (commit 44eec48) is cited anywhere.

## Openings, pairing and seeds

Opening i is k random legal plies, k drawn from 2 to 8 by `random.Random(seed * 1000 + i)`, never a move that ends the game, played through the runner so both trackers see every ply. Each opening is played twice with the colours swapped. `--opening-plies 0 0` plays every pair from the standard start, which is the setting the cross-check uses. Game n has match seed `seed * 1000 + n`; `play_game` seeds White with it and Black with it plus one.

## Rules

One table, one set of rules. A run of more than two games must pin `--rules standin` or `--rules teal`; the runner refuses `auto`, which picks Teal's adapter wherever the checkout has it (on `main` once #15 merges) and the stand-in elsewhere. The run file records the rules id and the SHA-256 of every source file that plays, including `pair_a_prep/*.py`, where Teal's adapter lives. #17 settled `--rules standin` for every table. If the rules of record change, every pairing of the table is rerun; a table never mixes the two.

A side with no fog-legal move and no rule result. Decided on #17: it is a draw everywhere. Once #28 reaches `main`, the referee's `terminal()`, Teal's adapter, `pairb/stockfish.py`, the bot and Fog Lab all agree. Teal's #28 puts the draw into the shared code (`fow_shared.values.terminal_score`, rule `no-moves`, which both sets of rules report as `no_legal_moves`) and into Teal's adapter. #28 targets the Pair A branch, so it reaches `main` only with #15.

`--rules standin` does not pin this rule; only the commit does. Games played before and after it can differ even when nothing fails, so all seven rows run on one commit and every table caption states its `no_move_rule`. Each run finds the rule out at the start, on a blocked position (`7k/8/8/8/1p6/pPp5/PRP5/KB6 w - - 0 1`, White to move), and records `no_move_rule` in its summary: `draw` once the rule is in the code, `unresolved` before. In a pre-rule run such a game fails with "ValueError: the observation has no legal move to choose from", the same text for a bot side and a random side. The summary counts these games in `errors_no_legal_move`, and a pre-rule table footnotes that count.

Before #28, Fog Lab already ends such a game as a draw (`pairb/lab/session.py`, reason `no_legal_moves`), but the evaluators do not score a move into such a position as a draw. In `7k/8/8/8/1pp5/pP6/PRP5/KB6 b - - 0 1`, c4c3 leaves White with no move; `StockfishEvaluator(depth=1).evaluate_children` gives it about -0.336 (depth 1 does not see the stalemate) and piece values give -0.870. Only Stockfish's `board_value` of the blocked board itself is 0.0; piece values score that board by material (0.870 for White). With #28's change applied to `main`, the rules decide that child, so no engine value is used for it, and both give 0.0.

## Score and intervals

The first-named side's score is wins plus half the draws over the complete colour pairs (openings whose two games both finished, one with each colour); a pair scores 0, 0.25, 0.5, 0.75 or 1 (a win and a draw is 0.75, a loss and a draw 0.25). Raw wins, draws and losses count every finished game and are reported beside it; incomplete pairs are counted and excluded.

Two intervals. Wilson's 95% score interval on the pair-level proportion (n = complete pairs) is always given; it is an approximation that treats a pair's score (which can be a quarter point) as a 0-or-1 outcome, and it stays informative at 0 and 1 (5 of 5 pairs: 0.57 to 1.00; 100 of 100: 0.96 to 1.00). A percentile bootstrap that resamples complete pairs (2,000 resamples, seed 0) is given only when there are at least 20 complete pairs that do not all score the same; otherwise it would collapse to a point and is withheld as degenerate, with the reason in the run file. For the 200-game rows the bootstrap is the headline interval where it exists and the Wilson interval covers the rows near 0 or 1.

## Failures

A game that raises (a tracker that loses the position, a scorer that fails, or, in a pre-rule run, a side with no fog-legal move) is recorded with its error, excluded from the score and from its pair, and the run goes on. A value-lost measurement that fails after a game finished keeps the game; the move records `diagnostic_error`. The run exits with status 1 if any game or measurement failed, so a batch wrapper notices; a table built from a run with errors states their count and cause (`errors`, and `errors_no_legal_move` for the no-move failures; each error's text is in `games.jsonl`). A run stopped with Ctrl-C still writes its summary, with `stopped_early` set to `interrupted` and `completed` false, and exits with a non-zero status. If the runner itself fails between games, `stopped_early` names the failure in the same way.

A Stockfish that stops answering is handled like one that crashes. Each Stockfish call has a wall-clock limit (`call_timeout_s`, 60 s by default; the search itself stays depth only, so no value changes). When it passes, the engine is closed and the call raises `TimeoutError`, so the game is recorded with that error, the side is reopened, and the run goes on. Without the limit, a depth-only call to a stuck engine would wait forever and the recovery would never be reached (Bryan's probe on #18).

## The runs for the report

Decided on #17 (objections open until 27 October 23:59 SGT). All seven rows run on one commit. From `pair_b/`:

```bash
for a in material stockfish-d1 stockfish-d11 network1 belief linear random; do
  .venv/bin/python scripts/play_matches.py --a $a --b stockfish-d1 --games 200 --seed 0 --rules standin --out runs/matches/$a-vs-d1
done
```

Time, from the pilot: about 40 minutes per quick pairing on an M5 Pro Mac; the careful-Stockfish pairing about 3 machine-hours at the measured 204 ms median per depth-11 call (`checkpoints/timing-stockfish-d11.json`; its 95th percentile of 667 ms would make it about 8), so a second machine or 100 games. The network sides need torch. Quick Stockfish against itself should score about 0.5 and `random` close to 0; those two rows check the runner.

## The cross-check against Bryan's runner

Two runners were built independently. #17 made `play_matches.py` the runner of record for the varied-opening tables above. `pairb.match_experiment` (merged in #14) stays unchanged as an independent sanity check, shown side by side, never pooled, with no claim that the two are equivalent. Both played quick Stockfish against piece values from the standard start, with 256 particles, 8 guesses, 2,000 rebuild tries, a 200-ply cap, the stand-in rules and ten colour pairs (settings aligned in `experiments/matches/crosscheck-config-for-match-experiment.json`).

| | Ours (`play_matches.py`) | Bryan's (`pairb.match_experiment`, #31) |
|---|---|---|
| Folder | `experiments/matches/crosscheck-d1-vs-material-standard-start/` | `experiments/matches/crosscheck-bryan-d1-vs-material-standard-start/` |
| Commit | `00639cb` | `3afc594` (main) |
| Engine policy | hash cleared before every game, kept within a game | engine reset before every call |
| Seeds | game n has match seed n (0 to 19) | seeds 0 to 9, one seed for both games of a pair |
| Machine | Colin's Mac (macOS, arm64, Python 3.14.6) | Bryan's Windows 11 PC (Python 3.12.10) |
| Stockfish 19 build (SHA-256) | `dc2f18c3` | `45bc8e49` |
| Quick Stockfish | 20 wins, 0 draws, 0 losses | 20 wins, 0 draws, 0 losses |
| Complete pairs | 10 | 10 |
| Score | 1.00 | 1.00 |
| Wilson 95% | 0.72 to 1.00 | 0.72 to 1.00 (from `play_matches.wilson95` on his 10 of 10 pairs; his summary gives no interval) |
| Plies a game | 40.5 | 36.7 (734 in all) |
| No-move rule | pre-rule | pre-rule |

Both runs are pre-rule: they were played before the no-move draw, and neither had a no-move failure. Both runs also predate the Stockfish time limit (#22). This is a sanity check, not a test of equivalence. There is no agreed margin. The two runners differ in engine policy on purpose, and also in seeds, machine and Stockfish build. A lopsided pairing like this one would pass almost any working runner. The report shows both estimates side by side, each with its own interval and number of complete pairs, names these differences, and does not say the runners agree. A score clearly outside our interval would be investigated before any table is used.

## Checks before a table is used

Compare these summary fields across all seven rows. A row that fails a check, or a mismatch between rows, holds the table back until it is explained.

- `git_commit`: one commit for every row, with `record.git_status` empty (a clean tree).
- `rules` and `no_move_rule`: the same in every row; the caption states `no_move_rule`.
- `record.stockfish.sha256`: the same Stockfish binary.
- `record.packages`: the same library versions.
- `sides.*.device`: the device each network ran on, the same across rows.
- `settings.engine`, `call_timeout_s` included: the same in every row.
- `completed` true and `stopped_early` null.
- `errors` and `errors_no_legal_move`: zero, or stated in the caption with their cause (a pre-rule table footnotes `errors_no_legal_move`).
- `sides.*.over_budget_plies`: reported beside the time per move.

## What the report may say from this

Strength with the planner, guesses and tracker held fixed (not at equal computation), with intervals; cost per move beside it; the value lost by not knowing per side as the value-of-information diagnostic; and the tracker's health (particles, capped and rebuilt updates). Not: equal-time strength, Obscuro-level play, or anything from a run with unexplained errors.
