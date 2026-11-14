# Handover: policy network, ready to test against the search agent (15 Nov 2026)

Branch `pair-a/policy-net-20261112`. Everything below (code, checkpoints, the guard tracker) is committed on it.
The job left to do: play the **policy network** (a searchless player) against the **search agent** (our Obscuro
replication) and report the score. Nothing of that match has been run yet.

## 1. What the policy network is

One network call per move, no search.

1. **Input: the belief.** The tracker keeps the boards that are consistent with everything we have seen, and hands
   the player a sample of up to 16 of them, each with a weight. Each board is turned into 32 planes of 8 x 8 by the
   plane builder (`fow_shared/features.py::encode_belief`, plane list at `features.py:22-33`): our pieces, the enemy
   pieces on that board, what we can see, enemy-piece probability per square (already averaged over the boards),
   castling, en passant, clocks.
2. **Two input modes** (the checkpoint says which one it needs; the player reads it, nothing to configure):
   - **every-board input**: each board goes through the encoder (stem + 6 residual blocks, 64 channels) on its own;
     the boards' feature maps are averaged with the board weights (`pair_b/src/pairb/policy_net.py:91-95`).
   - **fuzzy-board input**: the boards are first collapsed into ONE picture (`pairb/belief_ablation.collapse`, mode
     `marginals`): planes known to us kept, enemy pieces kept only on squares we see, the probability planes 14-19
     kept, the per-board planes 21, 22, 28, 29, 31 averaged with the weights. One encoder pass per move.
3. **Output: a move distribution.** A convolutional head gives 64 move-type planes (56 queen-like moves + 8 knight
   jumps) per from-square, placed into the 4,096 from-to slots (`policy_net.py:96-98`). Illegal moves are masked
   **before** the softmax (`policy_net.py:106`), so the output is a distribution over the legal moves only.
4. **Move choice** (`pair_b/src/pairb/policy_agent.py`): the most probable legal move. No sampling. Promotions are
   always to a queen (the 4,096 slots do not distinguish the promotion piece). Exact ties: seeded random pick.
   About 1-6 ms per move.

Training: 503,552 parameters, AdamW (lr 1e-3, weight decay 1e-4), 64 beliefs per batch, early stop on validation
cross-entropy (patience 5). Target = the root strategy of a re-solve of each stored position by the search agent
(native solver, Stockfish 14.1 depth-8 leaf, 30 s, 65,536 rounds). Labels: 58,693 positions = 56,437 train (480-game
set + generation-0 self-play games) and 2,256 validation. Part of the self-play and labelling ran on NUS HPC Atlas
(NUSREC-HPC-00001). The test games were never read.

## 2. Checkpoints (all in `pair_b/checkpoints/`)

| checkpoint | input | trained on | validation regret | top-1 |
|---|---|---|---|---|
| `policy-conv-fuzzy-r2-s2` | fuzzy board | 56,437 positions | 0.0824 (seed 2) | 0.449 |
| `policy-conv-gen0r2-s2` | every board | 56,437 positions | 0.0825 (seed 2) | 0.454 |
| `policy-conv-gen0-s0` | every board | 41,013 positions | 0.0887 (seed 0) | 0.433 |

Each is the lowest-regret seed of three. **Regret** = how much worse the network's chosen move is than the best
move, in the re-solve's move values (scale -1 to 1), averaged over the 2,256 validation positions; **top-1** = how
often it picks the re-solve's best move. The search agent's leaf in the match below is
`belief-solver-v2-sf8-g237` (value network v2 g237), also committed there.

## 3. Results so far

**Offline** (2,256 validation positions, mean of 3 seeds; intervals 95 %, resampling whole games):

| policy network | regret | top-1 | vs one-ply lookahead |
|---|---|---|---|
| every board, 18,391 positions | 0.1000 | 0.416 | +0.007 [-0.005, +0.019] |
| every board, 41,013 positions | 0.0908 | 0.434 | -0.003 [-0.014, +0.009] |
| every board, 56,437 positions | 0.0849 | 0.452 | -0.008 [-0.019, +0.003] |
| fuzzy board, 56,437 positions | 0.0911 | 0.446 | -0.002 [-0.013, +0.009] |
| one-ply lookahead with value network v2 g237 (no training) | 0.0933 | 0.326 | |

Fuzzy minus every board: +0.006 [+0.002, +0.010] (slightly worse offline). More data helped steadily (about -0.009
regret per doubling). Two things that did not help: the belief as input versus one board (within +-0.006 in every
test), and soft targets built from the move values (-0.007, within noise).

**Against OnePlyBot** (Material OnePlyBot = greedy one-move material bot; 5 s per move, 200 plies max, alternating
colours, the same seeds for every player; both sides use their own tracker):

| player | games | W-D-L | score [95 %] |
|---|---|---|---|
| policy network, fuzzy board (`policy-conv-fuzzy-r2-s2`) | 100 | 93-0-7 | 0.930 [0.863, 0.966] |
| policy network, every board (`policy-conv-gen0r2-s2`) | 140 | 125-0-15 | 0.893 [0.831, 0.934] |
| leaf average (value network v2 g237 on each board, no search) | 96 | 82-5-9 | 0.880 [0.800, 0.931] |
| search agent, Python solver, value network v2 g237 (handover of 12 Nov) | 99 | | 0.960 |

Paired on the same seeds: fuzzy minus every board +0.070 [-0.010, +0.150] (100 games); fuzzy minus leaf average
+0.047 [-0.031, +0.125] (96 games). No difference is significant: OnePlyBot is too weak to separate these players
(most games end the same way for all of them). That is why the next test is against the search agent.

## 4. How to run a match

1. Check out `pair-a/policy-net-20261112`. Install the dependencies from `pyproject.toml` plus PyTorch (the runs
   used torch 2.11.0+cu128, python-chess 1.11.2, numpy 2.5.3, Python 3.12, CUDA GPU).
2. Build the four C++ kernels, then check they load (the code silently falls back to slow Python when one is
   missing or stale, and the search agent would then be a different, much weaker player):
   ```bash
   python -m pair_a_prep.build_pcfr_kernel
   python -m pair_a_prep.build_rules_kernel
   python -m pair_a_prep.build_leaf_kernel
   python -m pair_a_prep.build_belief_kernel
   python -c "from pair_a_prep import _pcfr_native as a, _rules_native as b, _leaf_native as c, _belief_native as d; print([m.library() is not None for m in (a, b, c, d)])"
   # must print [True, True, True, True]
   ```
3. Run one config (one chunk = 2 games, one per colour) **from the repository root** (the checkpoint paths in the
   config are read relative to the current folder):
   ```bash
   export PYTHONPATH=$PWD:$PWD/pair_b/src:$PWD/pair_a_prep/experiments/network_leaf_2026-11/strength
   python -m pair_c.run_evaluation policy-vs-search-c1.ini
   ```
   Results land in the `[output] directory`: `summary.json` (wins, draws, losses, failed and capped games, timing)
   and `games.jsonl` (every move). Give each process at least 8 GB of memory: the trackers have rare large spikes.
4. Seeds: chunk c uses `seed = 999 + 2c` (chunk 1 = 1001), so results pair with the OnePlyBot games above.

## 5. Proposed match config (recommended values; please check the marked lines)

```ini
; policy-vs-search-c1.ini -- policy network (player_a) vs search agent (player_b)
[player_a]
name = Policy network, no search (fuzzy board, 56,437 positions, seed 2)
factory = pairb.policy_agent:PolicyFactory
checkpoint_path = pair_b/checkpoints/policy-conv-fuzzy-r2-s2/best.pt   ; CHOICE A
device = cuda
leaf_depth = 0
tracker_factory = guard_tracker:Factory
max_states = 96000
sample_size = 16
max_candidates = none
tracker_policy = exact
tracker_backend = auto

[player_b]
name = Search agent, native solver, value network v2 g237 leaf
factory = pair_a_prep.evaluation_factories:SearchFactory
search_mode = subgame
leaf_evaluator = belief_network
checkpoint_path = pair_b/checkpoints/belief-solver-v2-sf8-g237/best.pt
device = cuda
leaf_depth = 0
solver_rounds = 65536          ; CHOICE B
max_nodes = 16384
max_evaluator_calls = 4096
stop_on_time = true
tracker_factory = guard_tracker:Factory   ; CHOICE C
max_states = 96000
sample_size = 16
max_candidates = none
tracker_policy = exact
tracker_backend = auto

[match]
games = 2
alternating_colors = true
rules = teal
time_budget_ms = 5000
max_plies = 200
initial_fen =
seed = 1001
seed_mode = per_game

[output]
directory = pair_c/runs/policy-vs-search-c1
hash_rules = pair_c/hash_rules.json
```

- **CHOICE A, which policy checkpoint.** The fuzzy one played best against OnePlyBot (not significantly). The
  every-board one (`policy-conv-gen0r2-s2`) is slightly better offline (+0.006 regret, outside noise). Either
  works; the player reads the input mode from the checkpoint.
- **CHOICE B, the search agent's rounds.** With the native solver, `65536` lets the 5 s clock decide when to stop
  (as in self-play). Do NOT use `1024` (the value in the older strength configs, which ran the Python solver):
  the native solver finishes 1,024 rounds in about 0.7 s and would use a seventh of its time.
- **CHOICE C, the search agent's tracker.** Guarded at 96,000 states, same as the policy side and self-play. The
  older search-agent arm used the unguarded exact tracker (`pair_a_prep.evaluation_factories:HistoryTrackerFactory`
  with no `max_states`), which can run out of memory in long games.

## 6. Things that will bite

- Every player section needs `leaf_depth` (the runner refuses to start without it).
- `SearchFactory` reads only these search keys: `search_mode`, `solver_rounds`, `max_nodes`, `max_evaluator_calls`,
  `stop_on_time`, `growth`, `initial_depth`, `max_depth`, `rounds_per_stage`, `final_rounds`, `purify`,
  `submission_reserve_fraction` (`pair_a_prep/evaluation_factories.py`, class `SearchFactory`). Others are ignored
  without a warning. In particular `growth_headroom` is always 0 here (self-play used 2,048) and the expansion
  fraction is always 0.7.
- Time: the search agent uses its full 5 s on every move, so a game takes minutes (my estimate 4-5 min, not
  measured), not the seconds the OnePlyBot games took. 40 games about 3 h, 100 games about 7-8 h, one process.
- Do not score a fuzzy-board checkpoint with `pair_b/scripts/eval_policy_net.py` (it refuses); use
  `pair_b/scripts/eval_policy_depth.py`, which builds the right input per checkpoint.

## 7. What to report back

Per player: W-D-L overall and by colour; failed and capped games (both in `summary.json`); mean time per move
(`summary.json` -> `timing`); the commit and the config used. Keep the `pair_c/runs/...` folders: `games.jsonl` lets
us pair results by seed and replay any game.

## 8. Where things are

| what | where |
|---|---|
| player | `pair_b/src/pairb/policy_agent.py` (`PolicyAgent`, `PolicyFactory`) |
| network | `pair_b/src/pairb/policy_net.py` (design `pooled-conv`) |
| data, both input modes | `pair_b/src/pairb/policy_data.py` (`fuzzy_positions`, `load_positions`) |
| training / offline evaluation | `pair_b/scripts/train_policy_net.py`, `pair_b/scripts/eval_policy_depth.py` |
| tests | `pair_b/tests/test_policy_net.py` (30 tests) |
| guard tracker | `pair_a_prep/experiments/network_leaf_2026-11/strength/guard_tracker.py` |
| match runner | `pair_c/run_evaluation.py` (see `pair_c/README.md`) |

The labels and training data (about 58,700 re-solved positions, several GB) are not in the repository; they are
only needed to retrain, not to play.
