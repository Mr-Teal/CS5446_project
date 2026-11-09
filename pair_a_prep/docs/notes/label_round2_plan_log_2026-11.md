# Round two: Stockfish-depth-10 solver labels -> belief network -> leaf (plan, 2026-11-09 00:50 SGT)

User's decisions (chat, 8-9 Nov): collect labels on Atlas with a Stockfish depth-10 leaf; "train midpoint
and last" (train once when about half the games are in, once on the full set); 20 tasks x 12 games = 240;
afterwards also test a policy head trained from the labels' root_policy as a growth prior.

## State

- Atlas (`/hpctmp/$USER/fow`): `bin/stockfish` = Stockfish 14.1 built from the sf_14.1 source with GCC 13.3.0,
  ARCH x86-64-avx2 (compute nodes EPYC 7R13), sha256 222fa1bd...; net nn-13406b1dcbe0.nnue (47 MB).
  `repo-exp/` = pair-a/experiments-20261108 (6995d6c, has the #68 en-passant fix) + patched
  `pair_a_prep/label_run.py` (flags --leaf-depth, --stockfish-call-timeout-s, --expansion-fraction; logs
  each fallback's reason to stderr). PBS script `label_sf10.pbs` (array 1-20; resubmit one task with N=).
  Serial queue: 1 cpu, 15 GB, 72 h; max 40 running jobs per user.
- Homelab VM: smoke copy of the same code at `/tmp/smoke-exp`; VM Stockfish is Debian 14.1 (`/usr/games/stockfish`).
- Laptop: patched `label_run.py` and the PBS script in `scratchpad/deploy/`; timing script `time_leaf_depth.py`.

## Measurements so far (VM, 6 hypothesis boards, ~20 children each)

evaluate_children per call: depth 1 = 3 ms, depth 4 = 4 ms, depth 7 = 34 ms, depth 10 = 227 ms (max 432 ms).
16-ply smoke, depth 10, 20 s clock, default expansion_fraction 0.7: 14 searched plies -> 9 labels, 5 fallbacks
(no label). Cause (code): the tree must be built before 70 % of the clock (`anytime_agent.py` growth_deadline;
`chess_search.py` "budget exhausted during tree construction"); 16 roots x one depth-10 MultiPV call on
opening positions with 25-35 legal moves can exceed 14 s. Two fixes smoked in parallel (seed 778):
A = 20 s + expansion_fraction 0.85; B = 30 s + 0.7. Result: see `/tmp/smoke-A.log`, `/tmp/smoke-B.log` on the VM.

## Steps

1. Pick A or B from the smoke (fallbacks near zero). Put the chosen BUDGET_MS / EXPANSION into `label_sf10.pbs`
   and submit: `qsub -J 1-20 -v TAG=labels-sf10,GAMES=12,BUDGET_MS=...,MAX_STATES=96000,SEED_BASE=50001 label_sf10.pbs`.
2. Watcher (cron, 2-hourly): `qstat -u $USER`; count finished parts per task; a task killed by memory
   (Exit_status 9 / 137 in `logs/`) is resubmitted with `-v ...,N=<task>` (resume skips finished parts).
   Tunnel: `scutil --nc start "wg_peer17"` before, leave it Disconnected after.
3. Midpoint (about 120 finished games): rsync finished `part-*.jsonl` Atlas -> laptop -> VM; validate
   (Pair B validator), merge as `solver-v2-sf10-mid` (merge_labels.py refuses mixed config_ids; the new
   protocol id differs from v1); train with `train_belief_net.py` (same settings as v1: 6 res blocks x 64, 128-dim,
   context on, AdamW 2e-3, wd 1e-4, cosine, batch 64 beliefs / 4,096 boards, patience 5); baseline the labels
   with `baseline_material.py` AND with the Stockfish-d1 value (the labels now carry engine knowledge, so the
   right offline baseline is Stockfish d1, not material); report board/position MAE on the val split only.
4. Strength arm on the VM: `net-sf10-fe-s16` = fe-s16 ini with `leaf_evaluator = belief_network`,
   `checkpoint_path` = the new best.pt, GPU container, <= 6 workers, seeds 1001-1100; compare paired with
   fe-s16 (material), sf14-fe-s16 (Stockfish d1) and net-fe-s16 (v1 network) via `analyse.py`.
5. Final (all 240 games): repeat 3-4 as `solver-v2-sf10`.
6. Policy head (after 5): train a move prior from `root_policy` in the records (needs a move encoding and a
   policy head in pair_b; `train_belief_net.py` reads only hypothesis_values today); plug it into the one-sided
   growth sampler (`sampler.select(tree, solver, max_depth, deadline)` in `anytime_agent.py`) as an expansion
   prior; measure nodes/leaf calls per move and paired strength against the value-only agent.
7. Record every number in the verification log (items 70+); Atlas numbers acknowledge NUSREC-HPC-00001; the
   test split stays unused until a single `--final` evaluation.

## Not to do

Do not mix v1 and v2 labels; do not edit `repo-exp` while jobs run (copy to a new folder for changes); never
pytest on Atlas login nodes; keep VM eval workers <= 6; kill only by exact pid / container id.

## Decision 2026-11-09 evening: depth 8, 30 s clock, growth window 0.85 (user chose option B)

Submitted from /hpctmp/tommy.21.31/fow as PBS array 1038003[] (19 tasks started immediately, 1 queued):
`qsub -J 1-20 -v TAG=labels-sf8,GAMES=12,BUDGET_MS=30000,MAX_STATES=96000,SEED_BASE=50001 label_sf8.pbs`
Output: repo-exp/pair_c/runs/labels-sf8/task-N/ ; logs/fow-labels-sf8.o1038003.N after a task ends.
Atlas repo-exp/pair_a_prep/label_run.py now = scratchpad/deploy/patch/label_run.py (md5 8eea4b3e...), with
--leaf-depth, --stockfish-call-timeout-s, --expansion-fraction and the fallback stderr line.

Why not depth 10 / why 30 s (homelab smokes, seed 778, same game for E and F):
- E = depth 8, 20 s, 0.85: 14 plies, 2 fallbacks ("budget exhausted during tree construction"), both cut
  at 18.0 s after 173 and 214 engine calls (~0.08 s per call).
- F = depth 10, 60 s: 14 plies, 3 fallbacks, cut at 54 s after 93-124 calls (~0.5 s per call).
- The fallback is the initial projection (project_chess, deadline = solve_deadline = 0.9 x clock), not growth:
  growth-phase SearchBudgetError is caught inside the round loop (chess_subgame_agent.py). Construction cost
  = evaluator_calls - expansions in the record diagnostics. Over the 19,749 labels-01 records on the VM
  (/home/dev/cs5446-review/labels/solver-v1): p50 16, p90 54, p95 86, p99 200, max 705 calls;
  >150: 1.8 %, >200: 1.0 %, >300: 0.3 %.
- Depth 8 at ~0.08 s/call (VM; Atlas assumed ~1.3x slower, unverified): 20 s clock -> ~180-220 calls fit
  -> ~1-2 % of moves lost; 30 s -> ~270-330 calls -> <1 %. Lost moves are the many-root positions, so the
  loss is biased; 30 s was the agreed fallback if the 20 s smoke lost moves.
- Collection time: per labelled move ~30 s clock + tracking; 12 games/task; if all 20 tasks run at once
  the array should finish in roughly a day (assumption: ~100 own moves per game, tracking ~10 s/move).

Watcher: session cron every 2 h (off-minute :23) -> scratchpad/deploy/watch-sf8.log; resubmits dead tasks
with -v ...,N=<task>; starts the midpoint pipeline (solver-v2-sf8-mid) at >= 120 games and the final
pipeline (solver-v2-sf8) at 240. Dataset names: solver-v2-sf8-mid, solver-v2-sf8 (replace the sf10 names above).

## Midpoint result 2026-11-09 ~20:10 SGT (solver-v2-sf8-mid: 122 games, 5,572 records; val = 16 games, 735 beliefs, 11,112 boards)

| evaluator on the val boards | board MAE | position MAE |
|---|---|---|
| belief-solver-v2-sf8-mid (v1 recipe, best epoch 3 of 8, 4,555 train beliefs) | 0.407 | 0.372 |
| material leaf | 0.326 | 0.301 |
| Stockfish 14.1 depth 1 | 0.144 | 0.118 |
| Stockfish 14.1 depth 8 (the label leaf) | 0.094 | 0.074 |
| constant 0 | 0.612 | 0.583 |

Validation curve oscillates 0.39-0.56 while train MSE falls 0.36 -> 0.10: a 561k-parameter network overfits
4.5k beliefs. v1 had 15.6k train beliefs and reached 0.091 on the smoother material labels (|v|<0.1 on 17 % of
boards vs 7.8 % here). The labels sit 0.094 from the depth-8 leaf and 0.144 from depth 1: most of a label is
engine knowledge the network would have to learn from scratch. Tools: labels/tools/baseline_leaf.py (VM),
runs/baseline_v2_sf8_mid_val.log, runs/belief-solver-v2-sf8-mid/{summary.json,metrics.jsonl}.
Open decision for the final round: (a) same recipe on 240 games; (b) attach Stockfish-d1 values to the records
and train with --use-d1 (learn the solver-minus-d1 residual, Pair B's Network-1 design on our labels); (c) smaller
model / lower lr / mirror augmentation. Atlas numbers: NUSREC-HPC-00001.

## Final-round recipe (agreed with the user 2026-11-09 ~22:00, "ok try") — supersedes step 5 above

Three trainings on the complete labels-sf8 set, judged on the val split only, against material / SF-d1 / SF-d8 / zero:
1. plain v1 recipe (learning-curve point 122 -> 240 games);
2. (already answered on the midpoint, see below) lr 5e-4: no help -> not repeated on the final set;
3. residual over Stockfish d1: tools/add_d1.py attaches "d1:<i>" (StockfishEvaluator depth 1, acting player's
   view) to every record -> validate --require-d1 -> train_belief_net.py --use-d1.
Decision rule: a network earns a place as a search leaf only if its val board MAE beats SF-d1 clearly (0.144 on
the midpoint val). No strength arm against the material bot (SF leaf already at 1.000 there) unless that happens.
Scripts: laptop scratchpad/deploy/pull_final.sh (Atlas -> laptop -> VM, then starts the VM chain),
filter_complete.py, VM tools/final_chain.sh (merge, validate, baselines, train plain, add_d1, validate d1,
train --use-d1, eval both) -> runs/final_chain_solver-v2-sf8.log, runs/belief-solver-v2-sf8{,-d1}/.
Midpoint side results: lr 5e-4 run (runs/belief-solver-v2-sf8-mid-lr5e-4): best epoch 1, val board MAE 0.478;
train MSE kept falling to 0.096 while val got worse -> generalisation gap, not step-size instability.
Same-metric check of the kept midpoint checkpoint: train-split board MAE 0.287 vs val 0.407 (it does not even fit
its own training games well; SF-d1 gets 0.144 untrained).

## Midpoint, residual over Stockfish d1 (2026-11-09 ~21:55 SGT): runs/belief-solver-v2-sf8-mid-d1

Same 122 games / 5,572 records, d1 attached by tools/add_d1.py (45 s, 4 workers), validator PASS with --require-d1,
train_belief_net.py --use-d1 (13 epochs, best 8, ~10 s/epoch). Val = 16 games, 735 beliefs, 10,876 boards:

| evaluator | board MAE | position MAE |
|---|---|---|
| residual network (reads SF-d1, predicts solver - d1) | 0.128 | 0.097 |
| Stockfish d1 alone (the network's input) | 0.145 | 0.118 |
| Stockfish d8 (the label leaf) | 0.094 | 0.074 |
| plain network from planes only (same data) | 0.407 | 0.372 |
| material | 0.326 | 0.301 |

Paired position-MAE difference network - d1 = -0.021, 95 % CI [-0.031, -0.013], bootstrap over whole games (2,000
resamples; eval JSON runs/belief-solver-v2-sf8-mid-d1/eval-solver-v2-sf8-mid-d1-val.json). The curve is flat and
stable (val 0.123-0.143 every epoch, no swings), unlike the plain network. First network in the project that beats
its engine input; it recovers ~1/3 of the d1 -> d8 gap on boards and ~1/2 on positions with 99 training games.
Final-round trigger: one-shot cron 23:50 runs pull_final.sh -> final_chain.sh (plain + residual on 240 games).

## Decision 2026-11-09 23:30: residual-over-Stockfish-d1 variant discarded (user)

The user discarded the `--use-d1` variant: a network leaf must produce the position value on its own,
without an engine call at play time. The residual network reads Stockfish depth 1 as an input and corrects
it (belief_net.py line 47: tanh(atanh(d1) + out)), so at play time it still needs one depth-1 call per
hypothesis board. Who decided what: the variant exists in Pair B's belief network (D6, `use_d1`, same
pattern as their Network 1 / D3); I (Claude) proposed training it as arm 3 of tonight's suggestion, the
user approved with "ok try" at ~21:00, and the user withdrew it at 23:30 after the play-time engine
dependence was spelled out. The midpoint number (val 0.128 board / 0.097 position, see above) stays as
a record only; it is not a leaf candidate and must not appear as a "network leaf" result.

Final round now: merge -> validate -> baselines -> plain (engine-free) network -> eval on val, nothing else.
tools/final_chain.sh on the VM and the one-shot trigger (01:08) updated accordingly. The decision rule
is unchanged: the plain network is a leaf candidate only if it beats SF-d1 clearly (midpoint: 0.407 vs 0.144).

## Result on 237 of 240 games (2026-11-10 00:05, started early on the user's "ok test now")

Data: 237 games (task 13 at 11/12 and task 20 at 10/12 still running on Atlas), 11,469 records, 1,215 fallbacks
(9.6 %), 15 failed games kept with their partial records. Split by game hash: train 196 / val 25 / test 16
(test untouched). Dataset `solver-v2-sf8-g237` on the VM; run `runs/belief-solver-v2-sf8-g237`; chain log
`runs/final_chain_solver-v2-sf8-g237.log`. Plain (engine-free) network only, v1 recipe, best epoch 13 of 18.
Atlas labels collected under NUSREC-HPC-00001.

| Evaluator (val, 25 games, 17,868 boards; network 17,518 after rule-decided boards) | Board MAE | Position MAE |
|---|---|---|
| Plain network, 196 training games (this run)                                       | 0.260 | 0.232 |
| Plain network, 99 training games (midpoint checkpoint, same 25 val games)           | 0.377 | 0.343 |
| Material                                                                           | 0.309 | 0.286 |
| Stockfish depth 1                                                                  | 0.141 | 0.114 |
| Stockfish depth 8 (label leaf)                                                     | 0.092 | 0.070 |
| Zero                                                                               | 0.602 | 0.576 |

Reading: doubling the training games cut the plain network's board error from 0.377 to 0.260 on the same
validation games, so the learning curve is still steep and data is the limit. It now beats material
(0.309) but is far from Stockfish depth 1 (0.141): not a leaf candidate under the decision rule; no strength
arm. Curve still swings (val 0.26-0.45 across epochs; train MSE 0.049 at epoch 18 vs val board MSE 0.148),
so the generalisation gap remains. The midpoint comparison is clean: the game hash fixes each game's split,
so the midpoint network's training games are all in today's train split and none in val.

## State-representation ablation (2026-11-10 00:20, user: "test if pure mist (no sampling) works, to prove our state rep is useful")

Code: `pair_b/src/pairb/belief_ablation.py` (new, VM worktree wt-net, uncommitted) + `--input {full,marginals,observation}`
in `train_belief_net.py` / `eval_belief_net.py` (the checkpoint records the mode; eval collapses the arrays the same
way); `tools/ablation_chain.sh`, `tools/compare_runs.py` (paired position-error difference, bootstrap over whole
games). Laptop copies in `deploy/ablation/` (originals in `deploy/ablation/orig/`). Plane roles verified on the
g237 arrays: planes 0-5, 12-20, 23-27, 30 identical across a belief's hypotheses; 6-11, 21, 22, 28, 29, 31 differ.
Dataset solver-v2-sf8-g237, v1 recipe, context head OFF for the three ablation runs (545,297 params each).

| Input the network sees (val, 25 games, 1,181 positions)                                   | Position MAE | vs full+context, paired diff [CI95] |
|---|---|---|
| full: 16 sampled hypothesis boards + context head (ours, main run, 561,681 params)         | 0.232 | reference |
| full, context head off                                                                      | 0.225 | -0.006 [-0.024, +0.010] |
| marginals: ONE pseudo-board per position = observation + belief probability planes (14-20) + weighted average of the hypothesis-dependent planes; no sampled boards | 0.233 | +0.002 [-0.016, +0.019] |
| observation only ("pure fog"): one pseudo-board, hidden planes zero                          | 0.411 | +0.180 [+0.119, +0.245] |
| (references: material on the true hypothesis boards 0.286, SF-d1 0.114, SF-d8 0.070, zero 0.576) | | |

Reading: (1) the belief is what matters: without it the network is at 0.411, with it 0.23, a 0.18 gap whose
interval excludes zero by a wide margin. (2) HOW the belief is encoded does not matter at this data size: the
marginal probability planes on a single board do as well as the 16 sampled boards, and the cross-hypothesis
context head adds nothing measurable. The marginal variant is ~15x cheaper per position and trained more
smoothly (best epoch 24, train MSE 0.011). Caveats: "marginals" here are the marginals OF THE SAMPLED SET
(encode_belief sums the record's hypothesis weights), so this does not test exact tracker marginals vs sampling;
the targets were produced by the solver from those same 16 boards, so the full representation had the label's own
inputs and still did not win; 196 training games. Honest claim for the deck: the belief-conditioned input is
essential (0.41 -> 0.23); the sampled-board + context design is not shown to beat a marginal encoding.
Rerun on the full 240 set is scheduled with the 01:08 trigger (ablation_chain.sh solver-v2-sf8 + compare_runs).

## Strength arms for the v2 network leaf (2026-11-10 00:40, user: "verify this new agent's performance by competing with other agents")

Harness (existing, VM): `pair_c.run_evaluation <ini>` via `experiment/run_arm_gpu.sh` (GPU torch container, 8000m
cap, 1800 s per chunk, 2 games per chunk, 5 s per move, 200-ply cap, alternating colours, per-game seeds
1001+2(N-1); summary.json per chunk). The network leaf hook is commit d63de87 on pair-a/network-leaf
(`leaf_evaluator = belief_network`, `checkpoint_path`, `device = cuda`), evaluate_children 6.9 ms on cuda.
Existing arms vs the Material OnePlyBot (particle tracker), same seeds: fe-s16 (material leaf) 0.919 [0.834, 0.962]
over 74 games; sf14-fe-s16 (Stockfish 14.1 d1 leaf) 1.000 [0.962, 1.000] over 96; net-fe-s16 (v1 network leaf,
material-label training) 0.967 [0.907, 0.989] over 90. The OnePlyBot opponent is close to saturated for a
Stockfish leaf, so the discriminating arm is the head-to-head below.

New arms (files `deploy/strength/`: `make_netv2_inis.py`, `launch_netv2_arms.sh`, `netv2_scores.py`; on the VM in
`experiment/`), checkpoint = the 240-game plain network `runs/belief-solver-v2-sf8/best.pt` copied to
`wt-net/pair_b/checkpoints/belief-solver-v2-sf8/best.pt` (never committed):
- `netv2-fe-s16-cN`: v2 network leaf vs Material OnePlyBot (comparable with the three arms above).
- `netv2-vs-fe-s16-cN`: v2 network leaf vs the material-leaf subgame agent (same search both sides, only the leaf
  differs; 5 s per move each) -> isolates the leaf's contribution to play.
Interleaved by chunk, 50 chunks each (100 games per arm), ~11 h; launched by the 01:08 trigger (step 3c) after
the 240-game training and ablation, because the VM (15 GB) takes one 8000m container at a time.
Smoke: `netv2g237-smoke-c1` (g237 checkpoint, 2 games vs OnePlyBot) started 00:38 -> result below.

## Final result (240 games, 2026-11-10 01:15)

Atlas run labels-sf8 complete: 20 tasks x 12 games = 240 games, 11,679 records, 1,251 fallbacks (9.7 %), 16 failed
games kept with partial records (14 BeliefBudgetError no_candidate, 2 EngineTerminatedError), all jobs exit 0 (task 13
resumed after a memory kill; tasks 5/6 resumed with the reviving leaf). Collected under NUSREC-HPC-00001. Dataset
`solver-v2-sf8` on the VM (train 199 / val 25 / test 16 games by game hash; test untouched). Plain engine-free
network only; the residual-over-SF-d1 arm was discarded by the user (23:30). Chain log
`runs/final_chain_solver-v2-sf8.log`; run `runs/belief-solver-v2-sf8` (best epoch 7 of 12).

| Evaluator (val, 25 games, 17,868 boards; network 17,518 after rule-decided boards) | Board MAE | Position MAE |
|---|---|---|
| Plain network, 199 training games (this run)                                       | 0.276 | 0.246 |
| Plain network, 196 training games (g237 run, same recipe, same val games)          | 0.260 | 0.232 |
| Plain network, 99 training games (midpoint checkpoint, same val games)              | 0.377 | 0.343 |
| Material                                                                           | 0.309 | 0.286 |
| Stockfish depth 1                                                                  | 0.141 | 0.114 |
| Stockfish depth 8 (label leaf)                                                     | 0.092 | 0.070 |
| Zero                                                                               | 0.602 | 0.576 |

Reading: the 240-game run landed WORSE than the 237-game run (0.246 vs 0.232 position) with 3 more training games
and the same recipe: that gap is training variance (the curve swings 0.25-0.61 across epochs; patience stopped it at
epoch 12 with best epoch 7). So single-run differences of ~0.015 position MAE are NOT interpretable; the learning
curve (0.343 -> 0.23-0.25 from 99 to ~200 games) and the gaps to material (0.286) and SF-d1 (0.114) are. Not a leaf
candidate under the offline rule; the strength arms measure play directly.

### State-representation ablation on the 240-game set (same 25 val games; context head off for the three ablations)

| Input the network sees                                   | Position MAE | paired diff vs this run's full+context [CI95] |
|---|---|---|
| full + context (this run, reference)                     | 0.246 | reference |
| full, context head off                                   | 0.232 | -0.014 [-0.028, -0.002] |
| marginals, one pseudo-board, no sampling                 | 0.249 | +0.002 [-0.013, +0.020] |
| observation only ("pure fog")                            | 0.400 | +0.154 [+0.109, +0.200] |
| full + context, the g237 run (same recipe, other draw)   | 0.232 | -0.015 [-0.030, +0.001] |

Reading, consistent with g237: (1) the belief input is essential, +0.15 to +0.18 without it on both datasets, far
outside any noise. (2) Context head and sampled boards vs marginals: all within +-0.015, which is exactly the
run-to-run spread of the SAME recipe (last row), so neither helps nor hurts measurably. The bootstrap CI covers game
sampling only, not training variance; "full no-context beats full" here is a seed effect (its CI excludes zero but the
same-recipe rerun differs by the same amount). A real test of context/sampling needs several seeds per arm.
Files: `runs/ablation_chain_solver-v2-sf8.log`, `runs/ablation_compare_solver-v2-sf8-val.json`.

### Strength arms launched 01:15 (user: "verify this new agent's performance by competing with other agents")

Smoke `netv2g237-smoke-c1` (g237 leaf vs Material OnePlyBot, 2 games): game 1 WON as White (99 plies, king capture,
0 fallbacks, 3.6 s/move, ~1,190 nodes, 655 rounds/move); game 2 hit the 200-ply cap (excluded from scoring). Chunk
wall time 1746 s, of which the exact belief tracker spent 1,037 s in game 2 (one update 371 s) -> raised the per-chunk
limit to 3600 s (`run_arm_gpu.sh` now reads LIMIT; earlier net-arm chunks: median 343 s, p90 602 s, max 1504 s).
Leaf checkpoint for the arms = `belief-solver-v2-sf8-g237` (0.232), the better validation draw of the two same-recipe
runs (model selection on val only; the 240-run checkpoint is 0.246). Arms `netv2-fe-s16` (vs OnePlyBot; references
fe-s16 0.919, sf14-fe-s16 1.000, net-fe-s16 v1 0.967) and `netv2-vs-fe-s16` (vs the material-leaf subgame agent),
interleaved, 50 chunks x 2 games, one 8000m container at a time. Driver `experiment/logs-netv2/driver.log`, scores
`python3 experiment/netv2_scores.py`. ETA: ~6 min/chunk bot arm + ~12 min/chunk head-to-head -> ~15 h for 100 games
each; ~45 games per arm by 08:00.

## Correction and leaf-mode check (2026-11-10 01:55, after the user asked to "use the fuzzy board one")

How the search really uses the leaf: `pair_a_prep/chess_search.py:177` calls `evaluator.evaluate_children(state.fen)`
on ONE concrete board at a time (all children of a frontier board); the belief enters only at the root chance node.
`pairb/belief_evaluator.py` therefore scores each board as a belief of one hypothesis (`_alone`: weight 1,
probability planes = that board's own enemy pieces, population 1). Consequences:
- My earlier claim "the marginal variant needs 1 network call per position instead of 16 at play time" was WRONG for
  the current integration: the leaf is already called per board, never with the 16-board belief. The 16-vs-1 saving
  and a belief-aware leaf would need a search change (evaluate frontier boards per information set with
  `evaluate_beliefs`), i.e. Pair A core work, not an adapter.
- Neither network sees a multi-board belief during play, so both have a train/play mismatch. Measured on the g237
  val boards presented one at a time ("leaf mode", `compare_runs.py --leaf-mode`, modes in `belief_ablation.LEAF_MODES`):

| Network (g237 run) | belief-mode board MAE (as trained) | leaf-mode board MAE (as the search uses it) | leaf-mode diff vs full+context [CI95] |
|---|---|---|---|
| full + context (the leaf in the running arms) | 0.260 | 0.281 | reference |
| full, no context                              | 0.260 | 0.270 | -0.011 [-0.032, +0.008] |
| marginals ("fuzzy board")                     | 0.238 (on fuzzy boards) | 0.292 | +0.011 [-0.011, +0.032] |

Reading: the play-time mismatch costs the full network ~0.02; the fuzzy-trained network is not better as a per-board
leaf (slightly worse, within noise). Decision taken: keep the running arms with the full+context g237 leaf; do NOT
swap in the marginal network. "Use the fuzzy board" at play time = search change (per-infoset leaf evaluation),
proposed to the user as a design step, not done tonight. File: `runs/leafmode_compare_solver-v2-sf8-g237-val.json`.

## Approved 2026-11-10 ~02:20 (user: "sure for both policy head and generalization"); Atlas facts; self-play

Atlas: only the `serial` queue is enabled for us (CPU, 1 core / 15 GB per job; 81 running cluster-wide); no GPU queue.
So Atlas can generate Stockfish-leaf labels but cannot train or run the network leaf at speed (CPU evaluate_children
~1.2 s vs 6.9 ms on the VM GPU). /hpctmp has 377 TB free; labels-sf8 is 130 MB.

ROUND 3 LABELS (proposed, NOT submitted: the auto-mode classifier refused the qsub as a shared-cluster mutation; needs
the user to run or approve it): same config as round 2 so records pool (config_id unchanged), reviving-leaf runner:
  cd /hpctmp/tommy.21.31/fow && qsub -J 1-20 -v TAG=labels-sf8-r3,GAMES=12,BUDGET_MS=30000,MAX_STATES=96000,SEED_BASE=80001 label_sf8b.pbs
Seeds 81001-100001 (+2i per game), disjoint from round 2 (51001-70025). ~5 h; then 480 games -> next learning-curve point.

GENERALISATION SWEEP: `tools/gen_sweep.sh` (laptop deploy/ablation/gen_sweep.sh) deployed and started detached on the
VM; it waits until the strength arms' driver and containers are gone, then trains 3 seeds x {base, wd 1e-3, small
3x32, lr 1e-3} on solver-v2-sf8 and evaluates on val; also prints the epoch that would have been picked on position
error. Log `runs/gen_sweep_solver-v2-sf8.log`. 12 runs, ~40 min GPU.

POLICY HEAD (design; implementation next):
- Target per record: `decision.root_policy` (raw solver policy over `observation.legal_moves`; sums to 1; same for every
  hypothesis board of the belief). `played_policy:<uci>` diagnostics hold the purified policy; use the raw one as prior.
- Head: on each board's 512 trunk features (so the per-board leaf path can query it), logits over from-to squares
  (64x64 = 4096, promotion = queen; mirrored like the planes), masked to the legal moves, softmax; loss = weighted
  cross-entropy to root_policy, weight = hypothesis weight, added to the value loss with a coefficient (start 1.0).
- Use: growth prior in the one-sided expansion (order/limit which children are expanded first) so construction fits the
  clock; fallbacks today 9.7 % of moves. Needs: move encoding in `fow_shared`/pairb, loader arrays for the policy
  (CACHE_VERSION bump), trainer flag `--policy`, evaluator method returning the prior, hook in the growth path. Measure:
  policy top-1 / cross-entropy on val, then fallback rate and strength in an arm.

SELF-PLAY (user asked): the current pipeline is already one step of expert iteration: the agent played itself (both
sides the same agent) with a Stockfish-d8 leaf, the search's values/policies are the targets, the network imitates them.
Closing the loop = use the trained network as the leaf, play again, relabel with search-over-network values (+ game
outcomes as in AlphaZero), retrain, repeat. Mechanically possible on the VM GPU (label_run with leaf_evaluator=
belief_network via the d63de87 factory; ~1 game per 5-10 min per process), NOT on Atlas (CPU leaf too slow). Caveats:
our improvement operator is a 1-2 ply belief search (weak vs 800-sim MCTS), the seed network already comes from
Stockfish labels (not from scratch), and hundreds of games per day is 3-4 orders below AlphaZero scale; from a random
network it would not learn chess at our scale. The defensible version: 1-2 iterations of seeded self-play, value target
= mix of search value and game outcome, policy target = root policy; report whether play improves vs the seed.

## Round 3 submitted (2026-11-10 02:50, user: "submit round 3")

`qsub -J 1-20 -v TAG=labels-sf8-r3,GAMES=12,BUDGET_MS=30000,MAX_STATES=96000,SEED_BASE=80001 label_sf8b.pbs` ->
PBS array **1038307[]** (13 R / 7 Q at submission). Same config as round 2 (depth 8, 30 s, expansion 0.85, 16 samples,
max_states 96000) so config_id and records pool; reviving-leaf runner (label_run2) for every task this time. Output
`repo-exp/pair_c/runs/labels-sf8-r3/task-N/`, seeds 80001+1000N (+2i per game), logs `logs/1038307[N].venus01.OU`.
NUSREC-HPC-00001. Expected ~5 h (round 2 took ~5 h with 20 tasks at once). Resubmit a dead task with
`qsub -v TAG=labels-sf8-r3,GAMES=12,BUDGET_MS=30000,MAX_STATES=96000,SEED_BASE=80001,N=<task> label_sf8b.pbs`
(after `clear_dead_engine_games.py repo-exp/pair_c/runs/labels-sf8-r3 task-N` if it died with an engine error).
When complete: pull with a copy of pull_final.sh pointed at labels-sf8-r3 (push dir -> VM atlas-labels-sf8-r3), merge
rounds 2+3 into `solver-v2-sf8-480` (merge_labels.py with both task-* sets), validate, baselines on val, train the plain
recipe with 3 seeds, compare with the 240-game numbers (learning-curve point at ~400 training games).

## Generalisation sweep result (2026-11-10 02:31, 12 runs on solver-v2-sf8, val = same 25 games; 4000m cap alongside the arms)

| Variant (3 seeds)            | Position MAE s0 / s1 / s2 | mean  | Board MAE mean | Note |
|---|---|---|---|---|
| base (lr 2e-3, wd 1e-4, 6x64) | 0.252 / 0.235 / 0.260     | 0.249 | 0.280 | spread +-0.012; main run (seed 0) gave 0.246, so same-seed GPU runs differ too |
| wd 1e-3                       | 0.220 / 0.247 / 0.247     | 0.238 | 0.268 | one good draw, two average |
| small (3 blocks x 32 ch)      | 0.256 / 0.233 / 0.230     | 0.240 | 0.270 | quarter of the parameters, same quality |
| lr 1e-3                       | 0.228 / 0.232 / 0.236     | 0.232 | 0.265 | best mean AND tightest spread (+-0.004) |

Epoch selection on position error instead of board MSE changes the pick by at most 0.007 (wd1e-3 s1) -> not worth a
trainer change. Decision: recipe v2 = lr 1e-3, everything else as v1; ~0.017 better position MAE than base on
average, three out of three seeds under 0.237. The generalisation gap itself (train MSE far below val) remains; the
"small" result says capacity is not the limit either, which points back at data. No run was killed under the 4000m
cap (training container ~2 GB).

## Policy head, training side done; first result is weak (2026-11-10 03:40-04:00)

Code (VM wt-net, uncommitted; laptop `deploy/policy/` + `deploy/ablation/`): `pairb/moves.py` (4096 from-to slots in the
mirrored plane frame, promotions share the pawn move's slot), `pairb/policy_eval.py` (position-level CE / top-1 vs the
solver's root policy, plus the uniform-prior CE), `belief_data.py` CACHE_VERSION 3 (adds `policy` (beliefs x 4096
float16) and `legal` mask per record), `belief_net.py` `policy_head=True` (Linear 512->128->4096 on the per-board trunk
features; `forward(..., return_policy=True)` returns (values, logits)), trainer `--policy-weight`, eval reports
"policy". Tests: `pair_b/tests/test_moves.py` + existing belief tests: 19 passed, 2 skipped (VM container).

Target statistics (solver-v2-sf8): 31 legal moves per position on average; the raw root policy is nearly deterministic:
mean entropy 0.39 nats (uniform 3.37), 58 % of positions put > 0.9 on one move, mean max prob 0.82. So the attainable
cross-entropy is ~0.4 and the task is a 1-of-31 classification from 9,666 training positions.

| Run (240 games, lr 1e-3, 30 epochs/patience 5, best epoch by board MSE) | val position MAE | policy CE | top-1 |
|---|---|---|---|
| no policy head (gen sweep, 3 seeds)                                       | 0.228-0.236 | n/a (uniform 3.37) | n/a |
| policy weight 1.0                                                          | 0.281 | 3.23 | 0.18 |
| policy weight 0.3                                                          | 0.258 | 3.28 | 0.16 |

Reading: (1) sharing the trunk HURTS the value head (+0.03 to +0.05 position MAE), (2) the head barely beats a uniform
prior (3.23 vs 3.37 nats against an attainable ~0.4) and its val CE worsens from epoch 7 on while top-1 creeps to ~0.2
(it overfits the 9.7k positions), (3) top-1 of 18 % against 3 % for uniform shows some signal, but as a growth prior what
matters is top-k coverage of the solver's move, not measured yet. Next (cheap, tomorrow): top-3/top-5 coverage on val;
head-only training on the frozen value trunk (no interference) with early stopping on policy CE; if coverage stays low,
the prior is not worth a search change at this data size and the fallback problem is better attacked by the search
change (per-infoset leaf evaluation) and more data. Runs: `runs/belief-solver-v2-sf8-policy-pw1.0-lr1e-3`,
`runs/belief-solver-v2-sf8-policy-pw0.3-lr1e-3`.

## Head-to-head arm switched to the guard tracker (2026-11-10 04:05)

The exact-tracker head-to-head chunks 2 and 3 died with exit 137 (container memory kill at 8000m) after 23 and 37
minutes: two exact belief trackers plus two searches in one process spike past 8 GB on long games (chunk 4 was at
2.9 GB when checked). Only chunk 1 (2 games, both won by the network leaf) completed. Decision: new arm
`netv2-vs-fe-guard-s16` = same two agents but BOTH with the tail-guarded tracker (`guard_tracker:Factory`,
`max_states = 96000`), which is the label agent's own tracker setting (label_sf8.pbs MAX_STATES=96000) and had 2
memory kills in 49 chunks in the guard-fe-s16 arm (score 0.863 vs exact 0.919 vs the bot, overlapping intervals).
`switch_arms.sh` stops the driver, waits for the running container, marks finished chunks, relaunches with
ARMS="netv2-fe-s16 netv2-vs-fe-guard-s16", LIMIT 10800. The exact head-to-head arm is frozen at 1 chunk (kept as
a note). Reference for the bot arm stays as before (exact tracker on our side, as in fe-s16 / sf14-fe-s16 / net-fe-s16).
Round 3 at 04:00: 34/240 games, 13 R / 7 Q, fallbacks 12.3 % so far (early games), 1 failed game.
