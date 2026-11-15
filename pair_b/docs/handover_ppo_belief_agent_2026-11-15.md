# Handover: PPO self-play agent with the belief input, and its matches (15 Nov 2026)

This handover covers a second PPO agent for fog-of-war chess. It is the first PPO agent
(`pair_b/docs/handover_ppo_agent_2026-11-15.md`, `pair_b/experiments/ppo_selfplay/`) with one change:
its input is the team's 32-plane belief picture. It also covers its matches against the same three
opponents and against the first PPO agent. Everything is in `pair_b/experiments/ppo_belief/` (`$PKG`
below); file paths in this document are relative to that folder. Contact: Colin.

**The job left to do:** decide which of these results go into the report, and use this agent as one
more player in your own matches if you need more games. Section 5 shows how to run it.

In this document "PPO-belief" is this agent and "PPO" is the first agent.

## 1. What the PPO-belief agent is

One network call per move. No search, no engine. The network, the PPO update, the rewards, the
training opponents and the move output are the first agent's. Only the input differs.

1. **Input: the team's belief planes, as one fuzzy board.** 32 planes of 8 x 8
   (`fow_shared/features.py`, `PLANE_NAMES`), collapsed to one board as your fuzzy-board policy network
   reads them (`pairb/belief_ablation.py`, mode `marginals`): own pieces, enemy pieces in view, what
   we see, the chance of each enemy piece type on each square, the population, what the opponent
   probably sees, castling rights, en passant, clocks. Three differences of form: planes are stored as
   0 to 255; rows run from the player's own side outward (the order of the move output); and plane 23
   (capture recency), which your networks leave empty, marks the square where the opponent's last move
   took a piece.
2. **Its own belief sampler** (`player/kernel/belief_sampler.cpp`, about 370 lines of C++). The
   player does not use the runner's tracker. It feeds its own observations and its own moves to a
   sampler that keeps **at most 1,024 positions**:
   - The rules are `pair_a_prep/zs21/native/inference.cpp` (`moves`, `play`, `matches`), included
     unchanged.
   - Under 1,024 positions the sample is exact: every position that fits, weighted by its number of
     move histories. The tests compare it with the `zs_*` tracker of that file, ply by ply.
   - Above it, 1,024 histories are drawn at random, so the sample can miss the true position.
   - When no sampled position fits a new view, the sampled positions are repaired (squares in view
     are overwritten with what the player sees; unseen enemy pieces keep their squares where the view
     allows it). A repaired position is kept only if `matches` accepts it.
   - **So the belief is an approximation of the team's belief.** In 60 games played by the first PPO
     agent the true position was among the kept positions on 30 % of turns, 39 % of turns came after a
     repair, and no turn was left without a belief. The picture gave a hidden enemy piece's true square
     a chance of 0.61 on average (0.57 with 64 positions kept, 0.62 with 16,384). The first agent's
     memory planes mark the true square of 52 % of hidden pieces.
   - An exact belief was not possible in self-play: in games played by the first agent the exact set
     held a median of 201 positions and more than 16,384 on 9 % of turns.
3. **Network:** 4 residual blocks of 64 channels, 384,393 weights (`player/fowppo_belief/model.py`;
   the first layer reads 32 planes instead of 25).
4. **Output and move choice:** as the first agent. 4,096 move slots, illegal moves masked, queen
   promotions only, a move drawn from the policy (`move_choice = sample`). About 1.2 ms a move on a CPU,
   the belief update included.
5. **Training:** the first agent's recipe, for 5 hours instead of 12.2 on the same laptop: 61.9
   million moves, 2,106 updates, no restart. The learning rate follows the first run's line (3e-4
   falling to 3e-5 over 12.2 hours) and stops at 5 hours (1.9e-4), so both runs train with the same
   rate after h hours. 10 worker processes instead of 8 (speed only). `ppo.py`, `train.py`, `model.py`,
   `moves.py` and `procvec.py` are the first agent's files, byte for byte.

## 2. Results against the same opponents, and against the first PPO agent

Scores are from the PPO-belief agent's side: (wins + draws / 2) / scored games, 95 % Wilson interval.
The last column is the first PPO agent on the same protocol and seeds (its handover, section 2).

| # | Opponent | Scored games | PPO-belief wins-draws-losses | Score [95 %] | Not scored | PPO, for comparison |
|---|---|---|---|---|---|---|
| 1 | Material OnePlyBot (one-ply greedy) | 100 | 99-0-1 | 0.990 [0.946, 0.998] | 0 | 0.955 (95-1-4) |
| 2 | misty v1.6, 5 s a move | | | being played, see the next commit | | 0.100 (1-2-17) |
| 3a | Policy network, fuzzy board (`policy-conv-fuzzy-r2-s2`) | 97 | 82-0-15 | 0.845 [0.760, 0.904] | 2 failed, 1 at the ply cap | 0.626 (62-0-37) |
| 3b | Policy network, every board (`policy-conv-gen0r2-s2`) | 100 | 77-2-21 | 0.780 [0.689, 0.850] | 0 | 0.473 (42-5-47) |
| 4 | PPO, the first agent (`ppo-selfplay-12h`) | 100 | 63-3-34 | 0.645 [0.547, 0.732] | 0 | |

By colour (White / Black): row 1: 49-0-1 / 50-0-0; row 3a: 44-0-3 / 38-0-12;
row 3b: 46-0-4 / 31-2-17; row 4: 31-1-18 / 32-2-16.

**Protocol.** The first agent's, unchanged. Rows 1, 3 and 4: `pair_c.run_evaluation`, standard start,
colours alternate (PPO-belief is White in odd games), `rules = teal`, 200-ply cap, game g has seed
1000 + g, seeds 1001 to 1100. The opponent sections are the ones of the first agent's matches; in
row 4 the opponent is the first agent with its own player section. Row 2: the misty harness of
14 November, unchanged: misty commit `5ba2c31`, profile `v1.6`, Stockfish 19 depth-1 leaf, seeds 1001
to 1020, 5 s a move, three games at a time. Team code: `ca3993c`, clean checkout. The PPO-belief
network is the final network of the 5-hour run.

### How to read each row

1. **OnePlyBot.** 99 of 100. On the same seeds PPO-belief is +0.035 [-0.010, +0.080] against PPO: no
   difference shown. This opponent is too weak to separate the two.
2. **misty.** The 20 games were still being played when this file was committed; the result follows in
   the next commit.
3. **Policy network.** PPO-belief is ahead of it with both checkpoints. **Both rows contain repeated
   games, row 3a most of all**, as the first agent's row 3a did:
   - Row 3a. The fuzzy-board network always plays its most likely move. PPO-belief won one short
     game 26 times as White (`g1f3 d7d5 c2c4 d5c4 d1a4 g8f6 a4e8`) and another 23 times as Black
     (`d2d4 g8f6 g1f3 c7c5 d4c5 d8a5 b1c3 f6e4 c3e4 a5e1`). The 97 games are only 50 different games.
     If each different game counts once, the result is 35 wins and 15 losses. In games longer than
     20 plies it is 30-0-15 (0.667). The interval of row 3a treats repeated games as independent, so
     it is too narrow.
   - Row 3b. One short game was won 22 times as White (`g1f3 d7d5 c2c4 d5c4 d1a4 b8c6 f3e5 c6e5
     a4e8`). The 100 games are 74 different games. Each different game once: 51-2-21. Games longer
     than 20 plies: 43-2-21 (0.667).
   - On the same seeds PPO-belief is +0.229 [+0.104, +0.354] against PPO in row 3a and +0.314
     [+0.170, +0.452] in row 3b. For PPO the same counts were 40-37 (each different game once, row 3a)
     and 0.473 (row 3b, no repeats). So the gain over PPO does not come from the repeats alone.
   - `scripts/different_games.py` prints these counts and the repeated move lists.
4. **PPO.** 63 wins, 34 losses, 3 draws; 100 different games. See section 3 for 2,400 more games with
   random openings (0.569).

**Not scored.** Row 3a, games 19 and 63: the policy network's guard tracker (`BeliefBudgetError:
no_candidate ... no descendants of retained support`), as in the first agent's matches. Row 3a, game
35 reached the 200-ply cap. If the two failed games count as losses for the policy network, row 3a is
0.848 (84-0-15).

**The belief during these matches.** No turn of PPO-belief was without a belief. Repairs per game:
0.3 (row 1), 0.5 (row 3a), 1.2 (row 3b), 2.4 (row 4). Positions kept, median: 22 to 54.

## 3. The two PPO agents during training, in Pair B's match script

These use the protocol of the first agent's handover, section 3: `pair_b/scripts/play_matches.py`'s
loop at main `355e5e3`, stand-in rules, random openings of 2 to 8 plies played with both colours,
one-ply bots on a particle tracker. Do not mix them with section 2.

Final networks (PPO-belief after 5 hours and 61.9 million moves; PPO after 12.2 hours and 389.5
million moves). The difference is taken opening by opening; its range comes from resampling openings.

| Opponent | Games | PPO-belief | PPO | PPO-belief minus PPO |
|---|---|---|---|---|
| Random player | 100 | 1.000 (100-0-0) | 1.000 (100-0-0) | |
| Piece-count one-ply bot (`material`) | 100 | 0.970 (96-2-2) | 0.860 (86-0-14) | +0.110 [+0.035, +0.185] |
| Quick Stockfish one-ply bot (`stockfish-d1`) | 100 | 0.410 (40-2-58) | 0.418 (39-4-56) | -0.005 [-0.153, +0.148] |
| Quick Stockfish, 200 new openings | 400 | 0.500 (194-10-195) | 0.442 (166-20-213) | +0.056 [-0.019, +0.133] |
| Each other, three matches | 2,400 | 0.569 (1,325-81-994) [0.550, 0.588] | | |

During training (100 games each against the two bots; the direct match is against PPO's final
network, 200 to 2,400 games; `training/half_hourly_matches.jsonl`, `training/other_matches.json`):

| Hours | PPO-belief: moves trained | Piece-count bot | Quick Stockfish | Direct match against PPO's final network | PPO at the same hour: moves, bot / Stockfish |
|---|---|---|---|---|---|
| 0.5 | 9.1 M | 0.865 | 0.310 | 0.207 | 12.6 M: 0.720 / 0.070 |
| 1 | 15.6 M | 0.900 | 0.295 | 0.307 | 16.9 M: 0.615 / 0.065 |
| 1.5 | 21.8 M | 0.965 | 0.400 | 0.378 | |
| 2 | 27.2 M | 0.900 | 0.315 | 0.415 | 50.5 M: 0.890 / 0.355 |
| 2.5 | 32.6 M | 0.945 | 0.485 | 0.458 | |
| 3 | 38.6 M | 0.950 | 0.305 | 0.487 | 81.0 M: 0.830 / 0.250 |
| 3.5 | 45.3 M | 0.910 | 0.390 | 0.491 | |
| 4 | 50.8 M | 0.985 | 0.520 | 0.525 | 112.0 M: 0.872 / 0.316 |
| 4.5 | 57.3 M | 0.980 | 0.425 | 0.517 | |
| 5 | 61.9 M | 0.970 | 0.410 | 0.569 | 144.2 M: 0.857 / 0.300 |

For reference, against its own final network PPO's 1-hour network scores 0.117 and its 2-hour network
0.230 (200 games each). At equal training moves: PPO's network of 32.6 million moves scores 0.810
against the piece-count bot and 0.145 against quick Stockfish.

**Reading.** With the belief input PPO learns much faster: after 30 minutes and 9 million moves it
plays at the level PPO reached after about 2 hours and 50 million moves. After 5 hours, with 16 % of
PPO's training moves, it is ahead of the 12.2-hour agent in direct games and against the piece-count
bot. Against quick Stockfish the difference is within chance. Single rounds of 100 games swing by
about 0.1.

## 4. Checks that were made

| Check | Outcome |
|---|---|
| Under the cap the sampler holds the team's exact information set (`tests/training/test_kernel.py`) | The same positions as the `zs_*` tracker of `pair_a_prep/zs21/native/inference.cpp`, ply by ply |
| The weights count move histories | Equal to a brute-force count in Python with `pairb/observe.py`, which also checks the C++ rules against the Python rules |
| The 32 planes are the team's | Equal to `fow_shared.features.encode_belief` followed by `pairb.belief_ablation.collapse(..., "marginals")` on the kept positions, also after pruning and repair (rows flipped, 0 to 255) |
| The sampler never sees the true board | The self-play step, which is handed the true board to compute the two views, leaves the samplers exactly as they are left when handed the two views only |
| After pruning and repair every kept position fits the player's view | Checked with `matches` on every turn of 120 games with caps of 4 and 64 |
| The agent sees under Teal's rules what it saw in training (`tests/test_teal_parity.py`) | 6,000 plies of random games, 6,000 more with a cap of 8 (1,176 repairs), and three fixed lines with en passant and castling: the 32 planes, the legal moves and the game end agree with the training environment, under `teal` and `standin` rules |
| Code state of rows 1, 3 and 4 | Every chunk's `provenance.json`: commit `ca3993c`, clean status, the checkpoint hashes |
| Recount | Every arm recounts from `games.jsonl` with the first agent's `scripts/recount.py` |
| This folder | In a checkout of this branch, with the sampler built from the repository's own `inference.cpp`, the 39 tests pass and the three example matches replay the recorded games 1 and 2 move for move |

## 5. How to run the PPO-belief agent

It needs torch, numpy and python-chess, which your environment has, and a C++ compiler for the
belief sampler (the compiler and flags of `pair_a_prep/build_belief_kernel.py`).

```bash
cd /path/to/CS5446_project                     # this branch, kernels built
PKG=$PWD/pair_b/experiments/ppo_belief
python $PKG/player/kernel/build.py             # once: builds the belief sampler beside its source
export PYTHONPATH=$PWD:$PWD/pair_b/src:$PWD/pair_a_prep/experiments/network_leaf_2026-11/strength:$PKG/player:$PWD/pair_b/experiments/ppo_selfplay/player
python -m pytest -q $PKG/tests                 # 39 tests, about 1 minute
python -m pair_c.run_evaluation $PKG/configs/example-belief-vs-oneply-material.ini   # 2 games
python -m pair_c.run_evaluation $PKG/configs/example-belief-vs-policy-fuzzy.ini      # 2 games
python -m pair_c.run_evaluation $PKG/configs/example-belief-vs-ppo.ini               # 2 games
```

The last folder on PYTHONPATH is the first agent's player; it is needed only for matches against it.

The player section, for any configuration of yours:

```ini
[player_a]
name = PPO self-play network with belief input
factory = ppo_belief_player:PpoBeliefFactory
checkpoint_path = checkpoints/ppo-belief-5h/final.pt   ; relative to the package, or absolute
move_choice = sample
device = cpu
leaf_depth = 0
tracker_factory = ppo_belief_player:NoBeliefFactory
```

A full arm, several processes at a time, then the recount:

```bash
python $PKG/scripts/make_configs.py belief-vs-policy-fuzzy --games 100 --chunk 2 --device cuda
python $PKG/scripts/run_arm.py belief-vs-policy-fuzzy --repo $PWD --jobs 6
python pair_b/experiments/ppo_selfplay/scripts/recount.py pair_c/runs/ppo-belief/belief-vs-policy-fuzzy
python $PKG/scripts/different_games.py pair_c/runs/ppo-belief/belief-vs-policy-fuzzy
```

Arms of `make_configs.py`: `belief-vs-oneply-material`, `belief-vs-policy-fuzzy`,
`belief-vs-policy-every-board`, `belief-vs-ppo`. Game g always has seed 1000 + g, so new games pair
with the records here and with the first agent's.

To recount the records in this package:

```bash
mkdir records && for f in $PKG/results/*.tar.gz; do tar xzf "$f" -C records; done
python pair_b/experiments/ppo_selfplay/scripts/recount.py records/belief-vs-oneply-material records/belief-vs-policy-fuzzy records/belief-vs-policy-every-board records/belief-vs-ppo
python pair_b/experiments/ppo_selfplay/scripts/recount_misty.py records/belief-vs-misty-v1.6
python $PKG/scripts/different_games.py records/belief-vs-policy-fuzzy records/belief-vs-policy-every-board
```

The misty match needs the match harness, which is not in the repository (see the first agent's
handover, section 5). From the harness folder, with `MISTY_MATCH_REPO` set to the team checkout and
`$PKG/player` on PYTHONPATH: `python -m mistymatch.launch --out <dir> --games 1-20 --workers 3
--ours-config $PKG/configs/belief-for-misty.ini`. Put the absolute path of the checkpoint in that
file first.

To train again: `python -m fowppo_belief.train --name <name> --minutes <minutes>` with `$PKG/player`
on PYTHONPATH; `training/scripts-as-run/run_long.py` has the recipe of the 5-hour run.

## 6. Things that will bite

- **Build the sampler first.** Without `player/kernel/build/belief_sampler.*` the player and the
  tests stop with a message that names the build command. It was compiled and run with Apple clang on
  an Apple chip only. The build script uses the compiler and the flags of the team's kernel builds, but
  it was not run on Linux or Windows.
- **The belief is a sample with repairs, not the team's belief** (section 1). If this agent does
  badly somewhere, that can be the approximation and not the idea of a belief input.
- **Repeated games.** From the standard start a player that always plays its most likely move
  repeats itself. Count different games before you trust an interval (rows 3a and 3b).
- **Two protocols.** 0.990 (section 2) and 0.970 (section 3) are both "PPO-belief against the material
  one-ply bot". They differ in the start (standard against random openings), the rules object and the
  script.
- **Unequal training.** PPO-belief trained for 5 hours and 61.9 million moves, PPO for 12.2 hours and
  389.5 million moves. Each is one run from one seed. A difference between the two can partly be luck.
- **Its moves are drawn at random, and so is its belief sample.** Both use the game's seed, so a
  replay with the same seed gives the same game, as the example matches show.
- **Paths in the records are placeholders** (`<ppo-belief>`, `<ppo-pilot>`, `<experiments>`,
  `<team-repo>`, `<misty-env>`, `<misty-harness>`). `<ppo-belief>/runs/belief-1/final.pt` is the
  network of this folder (same file, SHA-256 `dd48fc11...`); `<ppo-pilot>/runs/long-hourly/final.pt` is
  the first agent's network. The configuration hashes in `provenance.json` are those of the files
  before the replacement.
- **Standard start only.** The sampler assumes it; the placeholder tracker refuses an `initial_fen`.
- **This setup differs from yours** as in the first agent's matches: the policy network ran on the
  CPU, and the four team kernels were compiled for an Apple chip with clang.

## 7. What is not done

- A longer run. PPO-belief was still improving against PPO when the 5 hours ended.
- A second training seed for either agent, `move_choice = best`, and more than 20 misty games.
- The every-board form of the input (16 boards of 32 planes).
- An exact belief, or a larger sample than 1,024 positions, in training.
- PPO-belief against the search agent.
- Nothing of this is in the report.

## 8. Where things are

| What | Where |
|---|---|
| Player for the team's runner | `player/ppo_belief_player.py` (`PpoBeliefFactory`, `NoBeliefFactory`) |
| Belief sampler | `player/kernel/belief_sampler.cpp`, `player/kernel/build.py`; its Python side is `player/fowppo_belief/belief.py` |
| Agent, network, move slots | `player/fowppo_belief/agent.py` (`ObservedBelief`, `PpoAgent`), `model.py`, `moves.py` |
| Training code | `player/fowppo_belief/env.py` (the only training file that differs from the first agent's), `train.py`, `ppo.py`, `procvec.py`; `training/scripts-as-run/run_long.py` has the recipe |
| Network | `checkpoints/ppo-belief-5h/final.pt`, facts and hashes in `summary.json` beside it |
| Example configurations | `configs/` |
| Records of every game of section 2 | `results/*.tar.gz`: one folder per arm, the runner's files per chunk (`evaluate_config.ini`, `games.jsonl`, `provenance.json`, `summary.json`). `tracker_updates.jsonl` is left out; the same rows are inside `games.jsonl` |
| One row per game, all arms | `results/all_games.csv` (400 games); arm totals in `results/results.json` |
| Scripts | `scripts/make_configs.py`, `run_arm.py`, `different_games.py`; the recount scripts are the first agent's |
| Tests | `tests/test_teal_parity.py` (12), `tests/training/` (27) |
| Training results | `training/half_hourly_matches.jsonl`, `other_matches.json` (every other match of section 3), `final-summary.txt` (the numbers of section 3), `final-network-matches.tar.gz` (the games of the final network's direct matches and 400-game matches), `training-logs.tar.gz`, `belief-plan.json`, `belief-attempts.jsonl` |
| Scripts of section 3, as run | `training/scripts-as-run/` (they expect copies of team main `355e5e3` and of the first agent's folder beside them; for reading, not for running) |

Versions on the machine that played: Python 3.12.13, torch 2.15.0, numpy 2.5.4, python-chess 1.11.2,
Apple clang 17. Training used Python 3.14.6 and torch 2.14.1 on the same machine.
