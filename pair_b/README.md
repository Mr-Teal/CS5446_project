# Pair B: leaf evaluators, Network 1 and its practice data

Pair B (Colin and Bryan) builds the judge that the search asks to score positions at the edge
of its tree. Everything here answers `fow_shared`'s `LeafEvaluator` calls, so a search or a match
swaps one evaluator for another by changing one argument.

## The evaluators

| Evaluator | `name` | What it is | ms per node* |
|---|---|---|---|
| `StockfishEvaluator(depth=1)` | `stockfish-19-d1` | Obscuro's own leaf ([1] App. C.5): Stockfish at depth 1, one MultiPV call per node | 1.5 |
| `StockfishEvaluator(depth=11)` | `stockfish-19-d11` | Careful Stockfish: our extra comparison, not used by the paper | about 230 |
| `NetworkEvaluator.from_checkpoint(...)` | `net1-v2+stockfish-19-d1` | Network 1: the same depth-1 call, then a learned correction | 4.6 on an Apple GPU, 15 on CPU |
| `MaterialEvaluator()` | `material-1-3-3-5-9` | Counts pieces: pawn 1, knight 3, bishop 3, rook 5, queen 9 | 0.7 |
| `BeliefNetworkEvaluator.from_checkpoint(...)` | `belief-v1-d1+stockfish-19-d1` | The belief network: scores every board of a belief together; see below | see below |

\* Median time of `evaluate_children` over 300 positions from real games (about 29 moves each) on
an M5 Pro Mac, with `new_game_each_call=False` as inside a search. Careful Stockfish's time is
from the practice-data runs.

All four:

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
decisions), measured against careful Stockfish by `scripts/eval_net1.py`
(`checkpoints/net1-v2/eval-d2-check-train.json`):

| Evaluator | Value error | Picks careful Stockfish's move | Average value lost by its pick |
|---|---|---|---|
| Piece values | 0.336 | 28% | 0.2108 |
| Quick Stockfish | 0.095 | 43% | 0.0355 |
| Network 1 | 0.076 | 42% | 0.0352 |

Network 1's values are 20% more accurate than quick Stockfish's, but it picks moves no better: a
tie (the paired difference in value lost is -0.0003, 95% CI -0.0017 to +0.0011, resampling the
959 games whole, since decisions from one game are correlated). It needs the
depth-1 call as input, so it is always slower than quick Stockfish. It is the warm-up; the
belief network that scores a whole belief at once is next.

## Use

```python
from pairb.network_evaluator import NetworkEvaluator

with NetworkEvaluator.from_checkpoint("pair_b/checkpoints/net1-v2/best.pt", new_game_each_call=False) as leaf:
    values = leaf.evaluate_children(fen)   # {uci: value for the player to move}
```

`new_game_each_call=True` (the default) clears Stockfish before every call, so no answer depends
on earlier ones; use it for labels. Inside a search, `False` is faster: 3 times for Stockfish
alone and 1.7 times for Network 1 here. The
network runs on CUDA or an Apple GPU when there is one (`device="cpu"` forces the CPU).

## The belief network (D6)

`BeliefNetworkEvaluator` scores every board of a belief knowing the whole belief. One shared board
reader turns each board into an embedding, the belief's weighted summary of all its boards sits
next to each board's own embedding, and a value comes out per board (`belief_net.py`). That is what
lets the same board be worth different amounts under different beliefs. `evaluate_beliefs` is its
real use; `evaluate_boards` and `evaluate_children` score each board as a belief of its own.

Until Pair A's player can label beliefs, it learns from practice data:

- **What each player sees:** `observe.py`, a stand-in that passes all 17 `pair_a_prep` rules
  fixtures and matches Pair A's `RulesAdapter.observe()` on 64,396 views, finished games included.
  Swap in Pair A's `observe()` once it is on `main`; a test compares the two until then.
- **Beliefs:** `standin_beliefs.py` keeps the true board and moves some of the opponent's unseen
  pieces to other unseen squares, keeping only boards the player cannot tell from the truth (same
  squares seen, same pieces on them, same legal moves): 8 boards for 99% of beliefs.
- **Labels:** careful Stockfish (depth 11) on each board. These are perfect-information values, so
  they cannot show what the fog changes; Pair A's solver labels can (`docs/label_definitions.md`).

Records are written in Teal's `TrainingRecord` format, so the training script reads Pair A's labels
unchanged. Trained on 9,585 practice beliefs and checked on 3,818 beliefs from fresh games, errors
against careful Stockfish (a position's value is the weighted mean of its boards' values):

| Network | Board error | Position error |
|---|---|---|
| Quick Stockfish alone | 0.080 | 0.055 |
| Belief network, board planes only | 0.178 | 0.141 |
| Belief network that also reads quick Stockfish's value | 0.074 | 0.047 |
| The same, ignoring the rest of the belief | 0.076 | 0.047 |

The network that reads quick Stockfish errs 15% less on positions than quick Stockfish alone
(paired difference -0.008, 95% CI -0.009 to -0.007, resampling the 959 games whole, since beliefs
from one game are correlated). The planes-only network needs far more data to
read chess from scratch. Reading the rest of the belief helps a little on these per-board labels,
but too little to call from one run each; Pair A's labels are the real test.

`checkpoints/belief-v1-d1/` is the kept network. A belief of 8 boards takes 3.7 ms on an Apple
GPU when 200 are scored in one call, and 6.8 ms one at a time; building the 32 planes in Python
is most of it. The `--use-d1` network also makes one quick Stockfish call per board.

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

The 157 tests run Stockfish itself where they need it; those are skipped when it is not on `PATH`.

## Rebuild Network 1, or retrain it on new labels

1. Practice data, about 30 minutes on 12 cores:
   `python scripts/make_d2.py --games 8000 --parents-per-game 4 --workers 12 --seed 2026 --out data/d2-v2`.
   Games use ordinary chess moves as a stand-in for real fog-of-war games; each record scores
   one move at depth 1 and depth 11 from a single MultiPV call at its parent, as Obscuro does.
2. Training, about 3 minutes on an Apple GPU: `python scripts/train_net1.py --data data/d2-v2 --out runs/net1-v2`.
   This is also the retrain command: point `--data` at any folder of records in the same format.
3. Evaluation: `python scripts/eval_net1.py --run runs/net1-v2 --data data/d2-check --split train`,
   which writes `eval-d2-check-train.json`. The test
   split needs `--final`, for the final report only.

Data is split by whole game (sha1 of `game_id` modulo 10: 0–7 train, 8 validation, 9 test), so
positions from one game never sit on both sides. `data/` and `runs/` stay out of git.

## Rebuild the belief network, or retrain it on Pair A's labels

1. Practice beliefs, about 3.5 minutes on 12 cores:
   `python scripts/make_beliefs.py --source data/d2-v2 --parents 12000 --out data/d6-v1`, and for
   the fresh check `--source data/d2-check --parents 100000 --seed 7 --out data/d6-check`.
2. Training, about 2 minutes on an Apple GPU:
   `python scripts/train_belief_net.py --data data/d6-v1 --out runs/belief-v1-d1 --use-d1`. Point
   `--data` at a folder of Pair A's labels to retrain on them. `--use-d1` needs quick Stockfish's
   values as `d1:<i>` diagnostics in the records; train without it otherwise.
3. Evaluation: `python scripts/eval_belief_net.py --run runs/belief-v1-d1 --data data/d6-check --split train`.

## Files

- `src/pairb/`: the evaluators (`stockfish.py`, `network_evaluator.py`, `material.py`,
  `belief_evaluator.py`), Network 1 (`net1.py`, with its 19-plane board encoding in `encode.py`),
  practice data (`d2.py`), and training and evaluation helpers (`data.py`, `evaluate.py`,
  `metrics.py`). The belief network: `belief_net.py`, `belief_data.py`, `belief_eval.py`, and the
  practice beliefs `observe.py` and `standin_beliefs.py`.
- `scripts/`: `make_d2.py`, `train_net1.py`, `eval_net1.py`, `make_beliefs.py`,
  `train_belief_net.py`, `eval_belief_net.py`.
- `checkpoints/net1-v2/`: the kept Network 1 (521k parameters, 2 MB), its training summary and its
  results on the fresh games. `checkpoints/belief-v1-d1/`: the kept belief network (562k
  parameters), the same three files.
- `tests/`: written before the code they test.
