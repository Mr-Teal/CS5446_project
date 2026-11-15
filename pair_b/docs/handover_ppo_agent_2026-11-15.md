# Handover: PPO self-play agent and its matches (15 Nov 2026)

This handover covers a PPO agent for fog-of-war chess, its matches against three opponents, and all
that is needed to play it in the team's runner. Everything is in `pair_b/experiments/ppo_selfplay/`
(`$PKG` below); file paths in this document are relative to that folder. Contact: Colin.

**The job left to do:** decide which of these results go into the report, and use the PPO agent as
one more player in your own matches if you need more games. Section 5 shows how to run it.

## 1. What the PPO agent is

One network call per move. No belief, no search, no engine.

1. **Input: its own view only.** 25 planes of 8 x 8, from the mover's side (Black is mirrored): its
   own pieces (6), the enemy pieces it sees now (6), the squares it sees (1), the enemy pieces it last
   saw on squares it no longer sees (6), the age of that memory (1), its own piece that was just
   captured (1), its castling rights (2), the ply (1) and its colour (1). It keeps this memory itself
   from its observations (`player/fowppo/agent.py`, `ObservationMemory`). It does not read the belief.
2. **Network:** 4 residual blocks of 64 channels, 380,386 weights (`player/fowppo/model.py`).
3. **Output:** 64 move types for each from-square (56 queen-like moves and 8 knight jumps), 4,096
   slots, illegal moves masked before the softmax; and one value. It always promotes to a queen.
4. **Move choice:** a move drawn from the policy, as in training (`move_choice = sample`). The
   most likely move (`move_choice = best`) is supported and was not measured. About 2 ms a move on a CPU.
5. **Training:** PPO self-play from random weights for 12.2 hours on one laptop (Apple M5 Pro):
   389.5 million moves, 13,488 updates. 512 games at a time, 64 plies between updates, 2 passes,
   minibatch 2,048, learning rate 3e-4 falling to 3e-5, gamma 0.995, lambda 0.95, clip 0.2, entropy
   bonus 0.01. Reward: +1 for taking the king, -1 for losing it, 0 for a draw, plus potential-based
   shaping on the piece balance (0.02 a pawn). Opponents in training: itself 70 %, earlier copies of
   itself 15 %, a scripted "always capture" player 10 %, a random player 5 %. Random openings of 0 to
   8 plies. No team player, no engine and no label was used. Rules: `fow_shared.values`.

## 2. Results against the three opponents

Scores are from the PPO agent's side: (wins + draws / 2) / scored games, 95 % Wilson interval.

| # | Opponent | Scored games | PPO wins-draws-losses | Score [95 %] | Failed, not scored |
|---|---|---|---|---|---|
| 1 | Material OnePlyBot (one-ply greedy) | 100 | 95-1-4 | 0.955 [0.895, 0.981] | 0 |
| 2 | misty v1.6, 5 s a move | 20 | 1-2-17 | 0.100 [0.028, 0.301] | 0 |
| 3a | Policy network, fuzzy board (`policy-conv-fuzzy-r2-s2`) | 99 | 62-0-37 | 0.626 [0.528, 0.715] | 1 |
| 3b | Policy network, every board (`policy-conv-gen0r2-s2`) | 94 | 42-5-47 | 0.473 [0.376, 0.573] | 6 |

By colour (White / Black): row 1: 47-1-2 / 48-0-2; row 2: 0-1-9 / 1-1-8; row 3a: 28-0-21 / 34-0-16;
row 3b: 16-3-26 / 26-2-21.

**Protocol.** Rows 1 and 3: `pair_c.run_evaluation`, your handover's protocol: standard start,
colours alternate (PPO is White in odd games), `rules = teal`, 200-ply cap, game g has seed 1000 + g,
seeds 1001 to 1100. The opponent sections are copied from the team's files (the OnePlyBot section of
the strength arms; the policy section of your handover, with `device = cpu`). Row 2: the misty harness
of 14 November, unchanged: misty commit `5ba2c31`, profile `v1.6`, Stockfish 19 depth-1 leaf, seeds
1001 to 1020, 5 s a move, three games at a time. Team code: `ca3993c`, clean checkout.

### How to read each row

1. **OnePlyBot.** On the same 100 seeds and the same machine the policy network scores 0.930 with the
   fuzzy board (93-0-7, the number of your handover) and 0.860 with every board (86-0-14). Paired by
   seed, PPO is +0.025 [-0.040, +0.090] against the fuzzy-board network and +0.095 [+0.015, +0.175]
   against the every-board network. This opponent is too weak to separate strong players.
2. **misty.** PPO loses 17 of 20. It wins game 18 and draws games 4 and 15 by repetition while behind
   in material. Misty searched a median of 15,710 iterations a move, so it was not held back. The
   search agent with value network v2 scored 0-0-18 (two failed) on the same seeds on 14 November
   (`results/reference-search-agent-vs-misty-2026-11-14.md`). The intervals overlap. Neither player is
   close to misty.
3. **Policy network.** PPO is about level with it. **Row 3a overstates PPO**:
   - The fuzzy-board network always plays its most likely move, so it repeats itself. PPO found two
     short lines that win against it every time they come up.
     As White, 9 games (5, 25, 31, 43, 53, 69, 73, 79, 81):
     `e2e3 d7d5 f1e2 g8f6 e2h5 f6h5 d1h5 g7g6 h5e5 f8g7 e5g7 h8g8 g7g8 b8c6 g8e8`.
     As Black, 12 games (10, 12, 22, 48, 60, 62, 86, 88, 90, 94, 96, 100):
     `d2d4 e7e6 g1f3 f8e7 e2e4 g8f6 b1c3 c7c5 d4c5 e7c5 e4e5 f6g4 h2h3 c5f2 e1f2 g4f2`.
   - 33 of the 62 wins end within 20 plies. The 99 games are only 77 different games. If each
     different game counts once, the result is 40 wins and 37 losses. In games longer than 20 plies PPO
     scores 29-0-37 (0.439). The interval of row 3a treats repeated games as independent, so it is
     too narrow.
   - Against the every-board network there is no such line (94 different games in 94) and the score
     is 0.473.

**Failed games.** All 7 are the policy network's guard tracker: `BeliefBudgetError: no_candidate ...
no descendants of retained support`. Row 3a: game 59. Row 3b: games 21, 33, 59, 61, 63, 98. The
team's convention does not score them. If each counts as a loss for the policy network, the scores
are 0.630 (3a) and 0.505 (3b).

## 3. Earlier results, in Pair B's match script

These use a different protocol: `pair_b/scripts/play_matches.py`'s loop at main `355e5e3`, stand-in
rules, random openings of 2 to 8 plies played with both colours, one-ply bots on a particle tracker.
Do not mix them with section 2.

| Opponent | Games | PPO wins-draws-losses | Score |
|---|---|---|---|
| Random player | 100 | 100-0-0 | 1.000 |
| Piece-count one-ply bot (`material`) | 100 | 86-0-14 | 0.860 |
| Quick Stockfish one-ply bot (`stockfish-d1`) | 99 | 39-4-56 | 0.418 |
| Quick Stockfish, 200 new openings | 399 | 166-20-213 | 0.442 (bootstrap over pairs 0.394 to 0.491) |

Reference in the same script: the piece-count bot scores 0.050 against quick Stockfish (5-0-95).
During training the score against quick Stockfish was 0.065 after hour 1, about 0.30 from hour 2 to
hour 8, and 0.464 at hour 12 (`training/hourly_matches.jsonl`, 100 games an hour).

## 4. Checks that were made

| Check | Outcome |
|---|---|
| The agent sees under Teal's rules what it saw in training (`tests/test_teal_parity.py`) | 6,000 plies of random games and three fixed lines with en passant and castling: the 25 planes, the legal moves and the game end agree with the training environment, under `teal` and `standin` rules |
| The policy network plays in this setup as in yours | Fuzzy board against the OnePlyBot, seeds 1001 to 1100: 93-0-7 (your handover: 93-0-7). Every board: 86-0-14 of 100 (your handover: 125-0-15 of 140) |
| Code state of rows 1 and 3 | Every chunk's `provenance.json`: commit `ca3993c`, clean status, the PPO checkpoint hash |
| Recount | Every arm recounts from `games.jsonl` (`scripts/recount.py`). The 20 misty games were replayed move by move with python-chess (`scripts/recount_misty.py`): 1-2-17 |
| Misty's rules against Teal's rules | 1,647 positions compared in the 20 games: no difference |
| This folder | In a fresh checkout of this branch, the 31 tests pass and the example match replays the recorded games 1 and 2 move for move |

## 5. How to run the PPO agent

It needs torch, numpy and python-chess, which your environment has.

```bash
cd /path/to/CS5446_project                     # this branch, kernels built
PKG=$PWD/pair_b/experiments/ppo_selfplay
export PYTHONPATH=$PWD:$PWD/pair_b/src:$PWD/pair_a_prep/experiments/network_leaf_2026-11/strength:$PKG/player
python -m pytest -q $PKG/tests                 # 31 tests, about 1 minute
python -m pair_c.run_evaluation $PKG/configs/example-ppo-vs-oneply-material.ini   # 2 games, 20 s
python -m pair_c.run_evaluation $PKG/configs/example-ppo-vs-policy-fuzzy.ini      # 2 games
```

The player section, for any configuration of yours:

```ini
[player_a]
name = PPO self-play network
factory = ppo_player:PpoFactory
checkpoint_path = checkpoints/ppo-selfplay-12h/final.pt   ; relative to the package, or absolute
move_choice = sample
device = cpu
leaf_depth = 0
tracker_factory = ppo_player:NoBeliefFactory
```

A full arm, several processes at a time, then the recount:

```bash
python $PKG/scripts/make_configs.py ppo-vs-policy-fuzzy --games 100 --chunk 2 --device cuda
python $PKG/scripts/run_arm.py ppo-vs-policy-fuzzy --repo $PWD --jobs 6
python $PKG/scripts/recount.py pair_c/runs/ppo/ppo-vs-policy-fuzzy
```

Arms of `make_configs.py`: `ppo-vs-oneply-material`, `ppo-vs-policy-fuzzy`, `ppo-vs-policy-every-board`,
and the two check arms `policy-fuzzy-vs-oneply-material`, `policy-every-board-vs-oneply-material`.
Game g always has seed 1000 + g, so new games pair with the records here.

To recount the records in this package:

```bash
mkdir records && for f in $PKG/results/*.tar.gz; do tar xzf "$f" -C records; done
python $PKG/scripts/recount.py records/ppo-vs-oneply-material records/ppo-vs-policy-fuzzy records/ppo-vs-policy-every-board
python $PKG/scripts/recount_misty.py records/ppo-vs-misty-v1.6
python $PKG/scripts/how_games_end.py records/ppo-vs-policy-fuzzy
```

The misty match needs the match harness. It is not in the repository, because it imports misty
(GPL-3.0); Colin has it as a zip with its README and `setup.sh` (it needs Rust). From the harness
folder, with `MISTY_MATCH_REPO` set to the team checkout and `$PKG/player` on PYTHONPATH:
`python -m mistymatch.launch --out <dir> --games 1-20 --workers 3 --ours-config
$PKG/configs/ppo-for-misty.ini`. Put the absolute path of the checkpoint in that file first.

## 6. Things that will bite

- **Repeated games.** From the standard start, a player that always plays its most likely move
  repeats itself, and PPO's sampled openings are narrow. Count different games before you trust an
  interval (row 3a).
- **Two protocols.** 0.955 (section 2) and 0.860 (section 3) are both "PPO against the material
  one-ply bot". They differ in the start (standard against random openings), the rules object and the
  script.
- **The network file has a new hash.** The file that played has SHA-256 `835c75e7...`, and the records
  name it. It stored one local folder path, so the file here is the same network saved again without
  it: SHA-256 `919e7579...`. The weights are identical (`checkpoints/ppo-selfplay-12h/summary.json`
  has one hash over all weights for both).
- **Paths in the records are placeholders** (`<ppo-pilot>`, `<experiments>`, `<team-repo>`,
  `<misty-env>`, `<misty-harness>`). `<ppo-pilot>/runs/long-hourly/final.pt` is the network. The
  configuration hashes in `provenance.json` are those of the files before the replacement.
- **Standard start only.** The agent's memory assumes it; the placeholder tracker refuses an
  `initial_fen`. Every player section needs `leaf_depth`, as you know.
- **The policy network's tracker costs the time.** PPO needs 2 ms a move. 100 games against the policy
  network took 6 to 9 minutes with 8 to 15 processes; a few games take minutes each. The misty match
  took 27 minutes.
- **This setup differs from yours** in two ways: the policy network ran on the CPU, and the four
  kernels were compiled for an Apple chip with clang. The check in section 4 gives the same score as
  your handover against the OnePlyBot.
- **One odd step in the run of row 3a.** A second process, started in parallel with the same scripts
  and configurations, played 70 of its 100 games and was stopped. The other 30 games were played again
  from the start. All 100 have the same commit, configuration and checkpoint in their provenance.

## 7. What is not done

- PPO against the search agent: not played (the team no longer uses the search agent).
- `move_choice = best`, a second training seed, and more than 20 misty games.
- A PPO agent with the 32-plane belief input: planned, not started.
- Nothing of this is in the report.

## 8. Where things are

| What | Where |
|---|---|
| Player for the team's runner | `player/ppo_player.py` (`PpoFactory`, `NoBeliefFactory`) |
| Agent, memory, network, move slots | `player/fowppo/agent.py`, `model.py`, `moves.py`, `env.py` (`remember`, `write_planes`) |
| Training code | `player/fowppo/train.py`, `ppo.py`, `procvec.py`, `env.py`; `training/scripts-as-run/run_long.py` has the recipe |
| Network | `checkpoints/ppo-selfplay-12h/final.pt`, facts and hashes in `summary.json` beside it |
| Example configurations | `configs/` |
| Records of every game | `results/*.tar.gz`: one folder per arm, the runner's files per chunk (`evaluate_config.ini`, `games.jsonl`, `provenance.json`, `summary.json`). `tracker_updates.jsonl` is left out; the same rows are inside `games.jsonl` |
| One row per game, all arms | `results/all_games.csv` (520 games); arm totals in `results/results.json` |
| Scripts | `scripts/make_configs.py`, `run_arm.py`, `recount.py`, `recount_misty.py`, `how_games_end.py` |
| Tests | `tests/test_teal_parity.py` (10), `tests/training/` (21) |
| Training results | `training/hourly_matches.jsonl`, `earlier_matches.json`, `training-logs.tar.gz`, `long-plan.json`, `long-attempts.jsonl` |
| Scripts of section 3, as run | `training/scripts-as-run/` (they expect a copy of team main `355e5e3` beside them; for reading, not for running) |
| Misty harness | Not in the repository (see section 5); Colin has it as a zip |

Versions on the machine that played: Python 3.12.13, torch 2.15.0, numpy 2.5.4, python-chess 1.11.2,
Apple clang 17. Misty is GPL-3.0 and the harness imports it, so the harness stays outside the
repository unless the team decides otherwise.
