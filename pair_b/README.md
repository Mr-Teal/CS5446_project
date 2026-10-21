# Pair B: leaf evaluators, Network 1 and its practice data

Pair B (Colin and Bryan) builds the judge that the search asks to score positions at the edge
of its tree. Everything here answers `fow_shared`'s `LeafEvaluator` calls, so a search or a match
swaps one evaluator for another by changing one argument.

## The evaluators

| Evaluator | `name` | What it is | ms per node* |
|---|---|---|---|
| `StockfishEvaluator(depth=1)` | `stockfish-19-d1` | Obscuro's own leaf ([1] App. C.5): Stockfish at depth 1, one MultiPV call per node | 1.4 |
| `StockfishEvaluator(depth=11)` | `stockfish-19-d11` | Careful Stockfish: our extra comparison, not used by the paper | 204 |
| `NetworkEvaluator.from_checkpoint(...)` | `net1-v2+stockfish-19-d1` | Network 1: the same depth-1 call, then a learned correction | 12.2 on CPU, 4.4 on an Apple GPU |
| `MaterialEvaluator()` | `material-1-3-3-5-9` | Counts pieces: pawn 1, knight 3, bishop 3, rook 5, queen 9 | 0.6 |
| `LinearEvaluator.from_checkpoint(...)` | `linear-v1+stockfish-d1-linear` | The [linear correction](docs/linear_baseline.md): a comparison, not one of the five | 1.7 |
| `BeliefNetworkEvaluator.from_checkpoint(...)` | `belief-v1-d1+stockfish-19-d1` | The belief network: scores every board of a belief together in `evaluate_beliefs`; in play it is called board by board, see below | see below |

\* Median time of `evaluate_children` on an M5 Pro Mac, with `new_game_each_call=False` as inside a
search, over the 300 positions of d2-check's training bucket that `scripts/benchmark_linear.py`
picks (the first 300 sorted parent positions; about 30 moves each), 4 calls each:
`checkpoints/linear-v1/timing-d2-check-train.json` (CPU) and, for Network 1 on the Apple GPU,
`checkpoints/linear-v1/timing-d2-check-train-mps.json` (`--net1-device mps`). Careful Stockfish:
one call on every 10th of those 300 (mean 239 ms), `checkpoints/timing-stockfish-d11.json`.

All six:

- answer `evaluate_children(fen)`, `evaluate_boards(fens, player)` and `evaluate_beliefs(turns)`;
- return values in [-1, 1] from the acting player's view, with Stockfish scores converted by
  `fow_shared.values` (tanh(cp / 600); a forced mate is exactly +1 or -1);
- generate moves with `fow_shared.values.fog_legal_moves`, so moves into check and castling into,
  out of or through check are included;
- score positions the fog rules decide (`rule_score`) exactly, before any engine or network call;
- where they use Stockfish, run it with 1 thread and 16 MB of hash, and close it when used in a
  `with` block.

The Stockfish and piece-value evaluators also take a `chess.Board` directly (`board_value`,
`children_values`, values from White's view). Children keep that board's move history for the
rule checks, so a threefold-repetition draw is seen; Stockfish always gets the position alone.

## How good they are

On fresh games (`d2-check`: the 959 games of its training bucket, 94,963 positions after 3,818
decisions; a position here is a child row the fog rules do not decide), measured against careful
Stockfish by `scripts/eval_net1.py` (`checkpoints/net1-v2/eval-d2-check-train.json`), and the
linear correction on the same rows by `scripts/eval_linear.py`
(`checkpoints/linear-v1/eval-d2-check-train.json`). The check set is a separate generation of
1,200 games (seed 7, against d2-v2's seed 2026). Only its hash buckets 0 to 7, the 959 games
here, are used. That bucket also compared three candidate Network 1 runs on 16 October, and the
kept run was the best on validation too (`experiments/net1_candidates/`). Bucket 9, the test
bucket, stays sealed behind `--final` for the final report.

| Evaluator | Value error | Picks careful Stockfish's move\* | Average value lost by its pick |
|---|---|---|---|
| Piece values | 0.336 | 27.7% | 0.2108 |
| Quick Stockfish | 0.095 | 42.9% | 0.0355 |
| Network 1 | 0.076 | 42.4% | 0.0352 |
| [Linear correction](docs/linear_baseline.md) | 0.084 | 41.5% | 0.0346 |

\* Move choice is measured among the siblings of each parent that the rules do not decide. "Picks
careful Stockfish's move" means the chosen child's depth-11 value equals the best sibling's. A
tie in a scorer's values goes to the first child in UCI order.

Network 1's values are 20% more accurate than quick Stockfish's (paired difference in value error
-0.019, 95% CI -0.021 to -0.018), but it picks moves no better: a tie (the paired difference in
value lost is -0.0003, 95% CI -0.0017 to +0.0011). Both intervals resample the 959 games whole,
since decisions from one game are correlated. It needs the
depth-1 call as input, so it is always slower than quick Stockfish. It is the warm-up; the
belief network that scores a whole belief at once is next.

The linear correction is a comparison, not a scorer for the search: on the same inputs it gets a
bit over half of Network 1's value-error gain over quick Stockfish (0.084 vs 0.076 vs 0.095);
neither picks moves better, and both are worse than quick Stockfish on close positions (careful
Stockfish's value between -0.3 and 0.3).

## Use

```python
from pairb.network_evaluator import NetworkEvaluator

with NetworkEvaluator.from_checkpoint("pair_b/checkpoints/net1-v2/best.pt", new_game_each_call=False) as leaf:
    values = leaf.evaluate_children(fen)   # {uci: value for the player to move}
```

`new_game_each_call=True` (the default) clears Stockfish before every call, so no answer depends
on earlier ones; use it for labels. Inside a search, `False` is faster: 3.4 times for Stockfish
alone and 1.8 times for Network 1 on an Apple GPU (`checkpoints/timing-new-game-each-call.json`). The
network runs on CUDA or an Apple GPU when there is one (`device="cpu"` forces the CPU).

## The belief network (D6)

`BeliefNetworkEvaluator` scores every board of a belief knowing the whole belief. One shared board
reader turns each board into an embedding, the belief's weighted summary of all its boards sits
next to each board's own embedding, and a value comes out per board (`belief_net.py`). That is what
lets the same board be worth different amounts under different beliefs. `evaluate_beliefs` is the
whole-belief pass; `evaluate_boards` and `evaluate_children` score each board as a belief of its own.
In play, in Fog Lab and in the match runner, the one-ply bot scores each guess's children with one
`evaluate_children` call, so there the belief network is used board by board, and the whole-belief
pass is exercised in offline evaluation only; a search over beliefs (Pair A's player) is where a
successor belief would reach it. The Fog Lab guide's scorer table predates this clarification.

Until Pair A's player can label beliefs, it learns from practice data:

- **What each player sees:** `observe.py`, a stand-in that passes all 17 `pair_a_prep` rules
  fixtures and matches Pair A's `RulesAdapter.observe()` on all 118,208 views of 500 seeded random
  games, 968 of them game-ending views (`checkpoints/observe-agreement.json`, run against Teal's
  branch at 8e914ef, whose adapter is unchanged since 219eb6a).
  Swap in Pair A's `observe()` once it is on `main`; a test compares the two until then.
- **Beliefs:** `standin_beliefs.py` keeps the true board and moves some of the opponent's unseen
  pieces to other unseen squares, keeping only boards the player cannot tell from the truth (same
  squares seen, same pieces on them, same legal moves): 8 boards for 99% of beliefs
  (`experiments/data_manifests/d6-v1.json`).
- **Labels:** careful Stockfish (depth 11) on each board. These are perfect-information values, so
  they cannot show what the fog changes; Pair A's solver labels can (`docs/label_definitions.md`).

Records are written in Teal's `TrainingRecord` format, so the training script reads Pair A's labels
unchanged. Trained on 9,585 practice beliefs and checked on 3,818 beliefs from fresh games, errors
against careful Stockfish (a position's value is the weighted mean of its boards' values), from
each run's `eval-d6-check-train.json`:

| Network | Board error | Position error | File |
|---|---|---|---|
| Quick Stockfish alone | 0.080 | 0.055 | `checkpoints/belief-v1-d1/` (`baseline`) |
| Belief network, board planes only | 0.178 | 0.141 | `checkpoints/belief-v1-pure/` |
| Belief network that also reads quick Stockfish's value | 0.074 | 0.047 | `checkpoints/belief-v1-d1/` |
| The same, ignoring the rest of the belief | 0.076 | 0.047 | `checkpoints/belief-v1-d1-noctx/` |

The network that reads quick Stockfish errs 15% less on positions than quick Stockfish alone
(paired difference -0.008, 95% CI -0.009 to -0.007, resampling the 959 games whole, since beliefs
from one game are correlated). The planes-only network needs far more data to
read chess from scratch; it was also still improving when it reached the 30-epoch cap (best epoch
29, `checkpoints/belief-v1-pure/summary.json`). Reading the rest of the belief helps a little on these per-board labels,
but too little to call from one run each; Pair A's labels are the real test.

`checkpoints/belief-v1-d1/` is the kept network. A belief of 8 boards takes 3.4 ms on an Apple
GPU when 200 are scored in one call, and 6.5 ms one at a time
(`checkpoints/belief-v1-d1/timing-beliefs.json`); building the 32 planes takes about a quarter of
that, and the quick Stockfish call on each board most of the rest. The `--use-d1` network also makes one quick Stockfish call per board, a node's
children included: it trained on each board's own depth-1 value, and a parent's MultiPV score of a
child differs from that by 0.066 on average (median 0.032; 7,529 children of the 300 timed
parents, `checkpoints/belief-v1-d1/d1-parent-vs-own.json`). A rule-decided board with no recorded quick-Stockfish
value takes its rule value, in training as in the evaluator.

```python
from pairb.belief_evaluator import BeliefNetworkEvaluator

with BeliefNetworkEvaluator.from_checkpoint("pair_b/checkpoints/belief-v1-d1/best.pt") as leaf:
    answers = leaf.evaluate_beliefs(turns)   # one LeafValues per fow_shared AgentInput
```

## Set up

Needs Python 3.12+ and Stockfish 19 on `PATH`.

With uv, from `pair_b/`:

```bash
uv sync
uv run pytest -q
```

With pip (Windows PowerShell), from the project root:

```powershell
python -m venv pair_b/.venv
pair_b/.venv/Scripts/Activate.ps1
pip install -e . -e pair_b pytest
cd pair_b; python -m pytest -q
```

The tests run Stockfish itself where they need it; those are skipped when it is not on `PATH`, and
so are the ones that need torch where torch is not installed (Intel Macs).

## Rebuild Network 1, or retrain it on new labels

1. Practice data, about 30 minutes on 12 cores (`experiments/data_manifests/d2-v2.json`):
   `python scripts/make_d2.py --games 8000 --parents-per-game 4 --workers 12 --seed 2026 --out data/d2-v2`.
   Games use ordinary chess moves as a stand-in for real fog-of-war games; each record scores
   one move at depth 1 and depth 11 from a single MultiPV call at its parent, as Obscuro does.
2. Training, about 3 minutes on an Apple GPU: `python scripts/train_net1.py --data data/d2-v2 --out runs/net1-v2`.
   This is also the retrain command: point `--data` at any folder of records in the same format.
   The kept checkpoint is the epoch-1 model: validation error stopped improving after one pass
   while training error kept falling (`best_epoch` 1, `epochs_run` 6, patience 5, in
   `checkpoints/net1-v2/summary.json`; per epoch in its `metrics.jsonl`). The two other candidate
   runs scored 0.0792 and 0.0787 on the check set against its 0.0757 (`experiments/net1_candidates/`).
3. Evaluation: `python scripts/eval_net1.py --run runs/net1-v2 --data data/d2-check --split train`,
   which writes `eval-d2-check-train.json`. The test
   split needs `--final`, for the final report only.

The evaluation rows are in git: `data/d2-check-train/` holds the 95,104 records of d2-check's
training bucket (2.8 MB, written by `scripts/freeze_split.py`; its `manifest.json` names the source
and its SHA-256). `python scripts/eval_net1.py --run checkpoints/net1-v2 --data data/d2-check-train
--split train` reruns the committed evaluation without Stockfish and gives the same digits.

Data is split by whole game (sha1 of `game_id` modulo 10: 0–7 train, 8 validation, 9 test), so
positions from one game never sit on both sides. `data/` (except `data/d2-check-train/`) and
`runs/` stay out of git.
Fresh games can still reach positions the training games reached: 5 of the 3,818 d2-check
evaluation parents are also d2-v2 training or validation parents, and 168 of its 94,963 rows (0.18%)
share a position with a d2-v2 training or validation row
(`experiments/overlap/position-overlap-d2-check-train-vs-d2-v2.json`).

The check set was made with `python scripts/make_d2.py --games 1200 --parents-per-game 4 --workers 12
--seed 7 --out data/d2-check` (`experiments/data_manifests/d2-check.json`). Both datasets were made
on 16 October, before the rule changes of 17 and 18 October renamed the rule results (`checkmate`,
`stalemate` and `fifty-move` became `forced-loss`, `forced-draw`, `repetition` and
`king-captured`). Made again with today's code, they would leave out a slightly different set of
rule-decided rows, and the digits would shift a little.

## Rebuild the belief network, or retrain it on Pair A's labels

1. Practice beliefs, about 3.5 minutes on 12 cores (`experiments/data_manifests/d6-v1.json`):
   `python scripts/make_beliefs.py --source data/d2-v2 --parents 12000 --out data/d6-v1`, and for
   the fresh check `--source data/d2-check --parents 100000 --seed 7 --out data/d6-check`.
2. Training, about a minute on an Apple GPU (54 s, `checkpoints/belief-v1-d1/summary.json`):
   `python scripts/train_belief_net.py --data data/d6-v1 --out runs/belief-v1-d1 --use-d1`. Point
   `--data` at a folder of Pair A's labels to retrain on them, after checking that folder with
   `python scripts/validate_labels.py <folder>` (add `--require-played-policy` for a full label run;
   [docs/label_validation.md](docs/label_validation.md) lists the checks). `--use-d1` needs quick
   Stockfish's values as `d1:<i>` diagnostics in the records; train without it otherwise.
3. Evaluation: `python scripts/eval_belief_net.py --run runs/belief-v1-d1 --data data/d6-check --split train`.

A label folder holds JSONL files written with `fow_shared.recording.write_records` (`part-*.jsonl` by
default; `--pattern` reads others) and, optionally, `manifest.json`. Empty files are skipped. Every
run writes `splits.json`, the games it trained and selected on. A step holds whole beliefs, at most
`--batch` of them and `--max-boards` boards (4,096 by default), and `--planes-on host` keeps the
encoded planes in main memory. One limit remains for Pair A's planned scale: every board is
encoded once and cached, about 10 GiB for 10,000 beliefs of 256 boards (32 planes of 64 squares
in float16 is 4 KiB a board), so such a run will need
fewer boards per belief per epoch or encoding on the fly.

## Fog Lab: test and demo app

Fog Lab runs on your own laptop and opens in your browser. It has two tabs:

- **Play:** play fog-of-war chess against our bot. You see only what the fog rules let you see, and
  the bot's reasoning sits beside the board. Testing mode adds the true board, the bot's own view
  and the values it weighed.
- **Tests:** one page that shows whether everything still works: the open pull requests merged one
  by one, Pair A's 17 rules positions drawn as boards, Bryan's checks on every scorer, and how
  accurate each scorer is.

A step-by-step guide with screenshots, from starting it to a five-minute demo, is in
[docs/fog_lab_guide.pdf](docs/fog_lab_guide.pdf).

After a human move, the Play tab shows the observation immediately after that move for one second
before displaying the bot's reply. Both observations come from the server and respect fair-game
visibility. The server computes the reply before sending the two snapshots; this is a display pause,
not extra thinking time or a change to the bot's decisions.

The bot is honest. It gets only the `AgentInput` of its own turn (its observation, its belief and
its history), never the true board or anything from your side. `tracker.py` keeps its belief as a
set of possible true boards (at most 256) from its own observations and moves alone. `bot.py` asks
the scorer you pick, one of the five evaluators above, for the value of every legal move on each of
its guesses at your hidden pieces (8 by default), and plays the move with the best average.

### Start it

From the project root, on macOS and Linux:

```bash
cd pair_b && uv run python -m pairb.lab --open
```

On Windows PowerShell, give the path of your own Stockfish. With uv:

```powershell
cd pair_b; uv run python -m pairb.lab --open --stockfish "C:\path\to\stockfish.exe"
```

or with the `pair_b/.venv` that the pip set-up above makes:

```powershell
cd pair_b; .\.venv\Scripts\python -m pairb.lab --open --stockfish "C:\path\to\stockfish.exe"
```

If uv stops with a certificate error, as it does on Colin's Mac, add `--system-certs` after
`uv run`. The app prints `Fog Lab: http://127.0.0.1:8765  (Ctrl+C to stop)`; open that address in a
browser, or add `--open` and it opens the page itself. It listens on 127.0.0.1 only, so nobody else
on your network can reach it, and it needs no internet except the optional fetch on the Tests tab.
It takes these flags:

| Flag | What it does | Default |
|---|---|---|
| `--port` | the port to listen on; 0 takes any free one | 8765 |
| `--stockfish` | the Stockfish command on the `PATH`, or the path of the engine | `stockfish` |
| `--device` | where the two networks run: `cpu`, `mps` or `cuda` | the best one torch finds |
| `--rules` | `auto` is Teal's `RulesAdapter` when this checkout has it, otherwise Pair B's stand-in; `teal` and `standin` force one | `auto` |
| `--open` | opens the page in your default browser once Fog Lab is listening | off |

The top right of the page says which rules, scorer and device are in use.

**Intel Macs.** torch has no build for them, so `uv sync` leaves it out. The belief network and
Network 1 are greyed out in the scorer list with the reason, quick Stockfish becomes the default
scorer, and the tests that need torch skip: in grey on the Tests tab, never red. Everything else
works.

### Pair A's environment, for the Tests tab

Pair A's tests need scipy, which Pair B's environment lacks, so the Tests tab runs them in Pair A's
own environment, `pair_a_prep/.venv`. Set it up once, from the project root, as
`pair_a_prep/README.md` does. On macOS and Linux:

```bash
python3 -m venv pair_a_prep/.venv
pair_a_prep/.venv/bin/python -m pip install -r pair_a_prep/requirements.txt
```

On Windows PowerShell:

```powershell
python -m venv pair_a_prep/.venv
pair_a_prep/.venv/Scripts/python -m pip install -r pair_a_prep/requirements.txt
```

Without it, Pair A's lines are grey ("Pair A's environment not set up here", with these commands)
and never count as failures.

### What a test run does

Press Run again; the cards fill in stage by stage as the run goes, and each shows how long its
stage took.

1. It fetches from GitHub first (a read-only `git fetch origin`; untick the box to work offline).
2. In a temporary git worktree outside your checkout, it builds the stages of
   `pair_b/fog_lab_stages.json`: the first stage is checked out, each later one is merged on top,
   and every stage runs the checks it has.
3. The last stage is always "+ this checkout", the committed `HEAD` of the checkout the app runs
   from ("contained" when an earlier stage already has it). Uncommitted changes are never part of a
   run.
4. The worktree is removed. A run never touches your checkout, branches or stash, and never pushes.

The fog-rules, scorer and accuracy sections show the last stage that built. The accuracy numbers
are read from saved evaluation files, and Run again never recomputes them.

The stages file lists one git ref per stage, in merge order. Edit it as pull requests open and
merge: add a line for a new pull request, such as

```json
{"label": "+ PR #9", "ref": "origin/pair-b/branch", "title": "What it adds"},
```

and delete the line of one that is in `origin/main`: it has nothing new to check, and its card
only says "contained".

Runs and saved games live in `pair_b/.fog_lab/` (git-ignored): `runs/` holds each run's summary and
logs, and the last 10 runs are kept; `games/` holds saved games.

### How fast the tracker is

Measured on Colin's Mac with 256 particles, over 5 seeded random games of up to 40 plies (410
updates; `uv run python scripts/bench_tracker.py --games 5 --plies 40 --particles 256 --out
checkpoints/tracker-bench.json`): one tracker update took a median of 24 ms and 718 ms at the 95th
percentile, and the slowest took 5.1 s. 18 of the 410 updates had to rebuild the belief. The slow ones follow a move you made that
the bot could not see, because then every particle is expanded by every move. The scorer's time
comes on top.

### A demo in six steps

1. **New game in Testing mode.** On the Play tab choose your colour and the bot's scorer (the
   belief network is the default), tick "Testing mode" and press New game.
2. **A few moves.** Click one of your pieces and its legal destinations light up; click one to
   move. Hatched squares are hidden from you, and the fog rules let you move into check. The bot
   replies after each move.
3. **The panel.** Beside the board, "Bot (Black) played ..." lists its top 6 moves with their
   average value over its guesses, a bar and the range over the guesses. The small boards are its
   guesses at your hidden pieces. These are the numbers it chose by.
4. **The true board and "lost by not knowing".** The Testing strip shows your view, the true board
   (held only by the referee) and the bot's view, and a heatmap of the top moves on each guess with
   a "True board" column that the app scores itself. "Lost by not knowing" is the best value on the
   true board minus the true-board value of the move played; the belief-health line says how many
   boards the tracker still thinks possible and whether the true one is among them.
5. **A fair game.** Tick "Fair game" and press New game. Until the game ends the page gets only
   your own view, your own moves, whose turn it is and whether the game is over: the bot's moves
   show as "?", and its panel and the Testing strip stay hidden. When the game ends, the bot's
   moves and its panel appear, and the "Testing mode" switch brings up the Testing strip.
6. **Step through a saved game.** "Save this game" writes the record to `pair_b/.fog_lab/games/`
   and downloads a copy. Pick it under "Saved games" and press Open (or "Open a file..." for one a
   teammate sent). First, Back, Forward and Last, or the Home, arrow and End keys, step through it
   ply by ply, with the bot's panel at every ply (and the Testing strip when Testing mode is on).
   For a demo, save a good game in advance.

## Matches

`scripts/play_matches.py` plays bot against bot with Fog Lab's honest pieces: each side is the
one-ply belief bot on one of the five scorers or the linear correction (`linear`), or `random`, a
uniform random legal move, on its own particle tracker, and through `fow_shared`'s `play_game` it
sees only its own observations. The protocol of record for the report's runs, what the study
measures, the engine policy, the interval rules, failures, and the cross-check against Bryan's
runner are in [docs/match_protocol.md](docs/match_protocol.md); the script's docstring lists every
flag. Three rules it enforces: a run of more than two games must pin `--rules standin` or `teal`,
one table is played by one set of rules, and a score gets a bootstrap interval only from 20 or more
complete colour pairs that do not all score the same (Wilson's interval is always given).

The pilot (`experiments/matches/pilot-d1-vs-material/`: 10 games, 200-ply cap, seed 0, stand-in
rules, on Colin's Mac): quick Stockfish won all 10 games against piece values, a score of 1.00 over
5 complete colour pairs. Five identical pairs give no bootstrap interval; Wilson's interval on 5 of 5
is 0.57 to 1.00, so the pilot says the quick leaf is the stronger one and not by how much. Every
game ended by a king capture, 49.7 plies on average; the 10 games took 128 s, 12.7 s a game. A move
took 14.2 ms for quick Stockfish and 4.0 ms for piece values (95th percentiles 20.6 and 7.4 ms), so
most of a game's time is the two trackers (1,014 updates, 153 of them capped and 39 rebuilt). The
same 10 games played before the per-game engine reset (`pilot-d1-vs-material-shared-engine-state/`)
differ in the length of 7 games and the winner of one: engine state carried across games changes
results, which is why no number from before the reset is cited.

The runs for the report, for ZW, once the runner decision with Bryan is recorded (proposed, pending
that decision): every scorer, the linear correction and `random` against quick Stockfish, 200 games
each, with the same seed so that every pairing plays the same openings, and one rules id for the
whole table (`standin` today; if Teal's adapter becomes the rules of record, every pairing is rerun
under `teal`; a table never mixes the two).

```bash
for a in material stockfish-d1 stockfish-d11 network1 belief linear random; do
  .venv/bin/python scripts/play_matches.py --a $a --b stockfish-d1 --games 200 --seed 0 --rules standin --out runs/matches/$a-vs-d1
done
```

At the pilot's rate a pairing of quick scorers takes about 40 minutes (200 games of about 12 s). A
slower scorer adds 9 calls per move (8 guesses and the true-board measurement) at its time per
node in the table at the top: about 1.8 s a move for careful Stockfish, so about 9 machine-hours
for its 200 games; run it on a second machine or at 100 games. Quick Stockfish against itself
should score about 0.5 and `random` close to 0: those two check the runner. The network sides need
torch. `experiments/matches/` holds the pilot, the superseded shared-engine-state pilot and the
standard-start cross-check, each described in its README.

## Files

- `src/pairb/`: the evaluators (`stockfish.py`, `network_evaluator.py`, `material.py`,
  `belief_evaluator.py`), Network 1 (`net1.py`, with its 19-plane board encoding in `encode.py`),
  practice data (`d2.py`), and training and evaluation helpers (`data.py`, `evaluate.py`,
  `metrics.py`). The belief network: `belief_net.py`, `belief_data.py`, `belief_eval.py`, the
  practice beliefs `observe.py` and `standin_beliefs.py`, and `label_validation.py` (the checks
  behind `scripts/validate_labels.py`, for Pair A's label folders). The linear comparison:
  `linear.py`, `linear_evaluator.py` and `linear_workflow.py`, which need only NumPy. Fog Lab:
  `tracker.py` (the honest belief tracker), `bot.py` (the one-ply belief bot), `rules.py` (Teal's
  adapter or our stand-in, behind one interface), `harness_adapter.py` (the belief network as a
  scorer for Bryan's harness) and `lab/` (the server, the test runner and the page in `lab/static/`).
  `provenance.py` records which data files, checkpoint and code a result came from.
- `scripts/`: `make_d2.py`, `train_net1.py`, `eval_net1.py`, `make_beliefs.py`,
  `train_belief_net.py`, `eval_belief_net.py`, `eval_children.py`, `bench_tracker.py`,
  `validate_labels.py`, `play_matches.py` (see Matches), `write_provenance.py` (provenance for runs
  trained before their summaries recorded it), `freeze_split.py` (one split of a dataset as one
  gzipped part), and the linear comparison's `train_linear.py`, `eval_linear.py` and
  `benchmark_linear.py`.
  `eval_children.py` measures per-move accuracy against depth-16 Stockfish and writes only the
  JSON file named by `--out`; the Tests tab reads `checkpoints/belief-v1-d1/eval-children-d16.json`.
  `bench_tracker.py` times the belief tracker and, with `--out`, writes the timings as JSON.
- `checkpoints/net1-v2/`: the kept Network 1 (521k parameters, 2 MB), its training summary and
  log, its results on the fresh games and `provenance.json` (the data and checkpoint hashes,
  written after training). `checkpoints/belief-v1-d1/`: the kept belief network (562k
  parameters), the same files, `eval-children-d16.json`, which `eval_children.py` wrote, and
  `d1-parent-vs-own.json`. `checkpoints/belief-v1-pure/` and `checkpoints/belief-v1-d1-noctx/`: the
  two ablations in the belief table. `checkpoints/linear-v1/`: the linear correction fitted on d2-v2
  (`best.npz`, no pickle), its summary, its comparison on the fresh games and its timings (CPU, and
  Network 1 on the Apple GPU). `checkpoints/timing-stockfish-d11.json`, `tracker-bench.json` and
  `observe-agreement.json`, `timing-new-game-each-call.json` and
  `belief-v1-d1/timing-beliefs.json` back the timings and the observe comparison above.
- `data/d2-check-train/`: the evaluation rows, so the evaluation reruns without Stockfish.
- `experiments/`: studies and checks behind the report, each with a README: `tanh_linear/` (the
  linear correction inside tanh, and Figure 1), `mc_td/` (learning the leaf from outcomes by MC and
  TD against distillation), `overlap/` (positions shared by the check set and the training data),
  `matches/` (the match pilot and the standard-start cross-check), `net1_candidates/` (the other two Network 1 runs),
  `data_manifests/` (how the four datasets were made) and `readme_checks/` (the scripts behind
  five of the README's measurements).
- `tests/`: written before the code they test. `tests/js/` holds the page's JavaScript helper
  tests, run from `pair_b/` with `node --test tests/js/`, which needs Node 20.19, or 22.7 or later.
  The app itself needs no Node.
