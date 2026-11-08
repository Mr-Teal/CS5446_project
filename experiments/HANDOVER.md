# Pair A handover, 2026-11-08

State of Pair A's subgame agent, the solver-label pipeline and the trained network leaf, written for the
presentation and for whoever picks this up next. Every number below comes from a run log or a results file on
the homelab VM or Atlas. Numbers from Atlas acknowledge NUSREC-HPC-00001. Nothing here is claimed as a
replication of Obscuro or ZS21; section 6 lists the gaps.

## 1. Summary

- **Strength vs the greedy bot.** With the clock used fully (5 s per move), the agent beats the greedy
  Material OnePlyBot 0.919-0.924 with the material leaf and 1.000 with a Stockfish 14.1 depth-1 leaf.
- **The trained leaf.** A belief network trained on 19,749 of the agent's own solver labels beats the same
  bot 87-0-3 (0.967) as the agent's leaf. On the 66 seeds both leaves finished, it does better on 5 and
  worse on 1 (sign test p = 0.22): **as good as the material leaf, not shown to be better.**
- **Offline, the network is worse than the formula behind its labels.** Board MAE is 0.091, against 0.059 for
  material counting.
- **This is one step of an AlphaZero-style loop, not the loop.** Labels -> network -> leaf has been done once.
  The next step (new labels from the network-leaf agent, retrain, repeat) has not been run.
- **Memory is the binding constraint.** Exact belief tracking costs more memory than the papers' setting at
  256 roots and on long games. The 256-root arm completed only 17 of 50 chunks at 15 GB on Atlas.

## 2. This branch

`pair-a/experiments-20261108` holds everything in one place: the code that produced the results, the results,
and this document.

- **Code** = `pair-a/network-leaf` (d63de87: `leaf_evaluator = belief_network`, 11 tests pass) merged with
  `pair-a/solver-labels` (87b3089: the label runner, a dead game no longer kills the run). Both sit on
  `pair-a/final-integration` (8830785 = main as of 2026-11-03 + the #65-#68 stack + the label runner), so this
  branch also carries #66/#67, which are still open, and it does not merge cleanly into current main.
- **Data** = `experiments/` (layout in section 8). The raw solver labels (953 MB) are the release asset
  `labels-solver-v1.tar.gz` on the GitHub release `experiments-20261108`.

Related PRs: #65 and #68 merged; #66 (packed belief states) and #67 (Obscuro mechanisms, cca2fe2) open.

## 3. The agent as measured

Subgame PCFR+ with one-sided GT-CFR growth (`pair_a_prep`), Obscuro's mechanisms per #67. Strength-arm
settings (`experiment/fe-s16-cN.ini`):

| Setting | Value |
|---|---|
| Clock | 5 s per move, `stop_on_time = true`, 200-ply cap, tracking excluded from the clock |
| Search budget | 1,024 PCFR+ rounds, 16,384 nodes, 4,096 leaf calls; growth to 70 % of the clock, depth <= 2 |
| Belief | exact history tracker, 16 sampled roots per search |
| Leaf | material `tanh(cp/600)`, Stockfish 14.1 depth 1, or the belief network |
| Opponent | Material OnePlyBot (greedy: best material one move ahead), particle tracker 256 / 8 / 2,000 |
| Seeds | 1001-1100 (50 chunks x 2 games, alternating colours), teal rules |

Measured search: median 218 nodes per move (p90 2,077), one Python core. Obscuro reports 1,070,552 nodes per
search on 5 cores.

## 4. Results

### 4.1 Strength vs the greedy bot (homelab VM, same platform, same seeds)

| Arm | What changes | Games | Score | Source |
|---|---|---|---|---|
| exact-s16 | 8-round baseline (harness default), exact belief | 37 | 0.635 | log items 21, 31 |
| pruned-s16 | baseline with a pruned belief | 100 | 0.481 | items 21, 31 |
| clock-s16 | baseline + full clock | 80 | 0.900 | item 31 |
| fe-s16 | full clock + #67 mechanisms, material leaf | 74-79 | 0.919-0.924 | item 40; 0.919 = 68-0-6 from summaries, 0.924 from `analyse.py` incl. first games of cut-off chunks |
| sf14-fe-s16 | as fe-s16, Stockfish 14.1 depth-1 leaf | 96 scored | 1.000 | item 31 |
| guard-fe-s16 | as fe-s16, belief tail-guarded at 96k states | 99 | not re-scored here | items 31, 40 |
| **net-fe-s16** | as fe-s16, **trained network leaf** | **90** | **0.967 (87-0-3)** | item 68 |

Paired differences (seed by seed, `analyse.py`):
- Full clock vs baseline on exact belief: +0.258 [0.076, 0.439], p = 0.007, n = 33.
- Exact vs pruned belief: +0.210 [0.048, 0.387], p = 0.016, n = 31.
- Stockfish leaf vs material leaf: +0.079 [0.026, 0.145], p = 0.003, n = 76.
- Network leaf vs material leaf: 5 seeds better, 1 worse, 60 equal, sign test p = 0.22, n = 66.

Ceiling: the greedy bot no longer separates the top arms (0.92-1.00). A stronger opponent is needed to rank the
network leaf against Stockfish.

### 4.2 Atlas replication (NUSREC-HPC-00001)

At 15 GB per job, baseline 8-round search: exact-s16 48 games 0.598, pruned-s16 100 games 0.448, guard-s16
(300k) 86 games 0.614. Exact vs guard on shared seeds: -0.025, p = 0.57 (indistinguishable). Atlas and homelab
results are never paired with each other: identical seeds diverge across platforms (item 17).

fe-s256 (256 roots, exact belief) on Atlas: 17 of 50 chunks finished, 33 killed at the 15 GB cgroup. The 17
finished score 0.441 (13-4-17), a survivor sample that is not comparable to fe-s16. On the VM, 16 of 50 chunks
finished before the 30-minute limit.

### 4.3 Solver labels and the trained network

Labels: the fe-s16-style agent in self-play (material leaf, 5 s, 16 roots, 96k tail guard), per-hypothesis
values in [-1, 1], root value, root and played policy.

| Source | Games | Records | Validation |
|---|---|---|---|
| Atlas, 10 tasks x 24 (NUSREC-HPC-00001) | 240 (5 failed) | 14,073 | 0 errors |
| Homelab | 96 of 120 (stopped) | 5,676 | 0 errors |
| Merged `solver-v1` | 336 (train 268 / val 34 / test 34) | 19,749 | 0 errors, one config_id |

Network `belief-solver-v1` (Pair B `train_belief_net.py`): 6 residual blocks x 64 channels, 128-dim
embedding, 32 input planes, belief context on, 561,681 parameters; AdamW lr 0.002, weight decay 1e-4,
cosine schedule; batch 64 beliefs / 4,096 boards; best epoch 7 of 12 (patience 5). Latency on the RTX 5070 Ti:
0.49 ms per 8-board belief at batch 1, 0.022 ms at batch 64.

Validation split (34 games, 2,196 beliefs):

| Predictor | Board MAE | Position MAE |
|---|---|---|
| Material `tanh(cp/600)` | 0.059 | 0.059 |
| Network, no context | 0.088 | 0.080 |
| Network | 0.091 | 0.084 |
| Constant 0 | 0.589 | 0.584 |

Why the network trails material offline: the labels come from a 2-ply search that scores leaves with material,
so most of each label is the material count; the network relearns it from 268 games. The test split has not
been used.

## 5. Failure modes worth knowing

- **Dead belief.** The tail guard prunes uniformly before an update; if the true history is pruned, a later
  observation matches nothing (`BeliefBudgetError: no_candidate`). About 1 game in 60 in arms; there is no
  recovery (Obscuro tops up to 256 roots).
- **Memory kills.** One belief update can grow the state set 4-23x, so any cap can be crossed mid-update:
  docker exit 137, PBS Exit_status 9. Remedy is resume, not a smaller request.
- **Orphan containers.** `run_arms4.sh`'s `timeout` kills the docker client, not the container. Orphans froze
  the VM twice (Nov 3-4, Nov 4-5). Check `docker ps` for `fow-*` containers older than 30 min.
- **Greedy bot's tracker.** Two network-arm games ended with the opponent's `TrackerLost`; not our agent.

## 6. Distance to the papers

| | Obscuro | ZS21 | Ours |
|---|---|---|---|
| Leaf | SF14 depth 1, tanh(cp/600) | SF13 depth 1, tanh(x/6 pawns) | material, SF14.1 depth 1, or network |
| Roots | 256 (MinInfosetSize) | L = 200 | 16 |
| Search | 1.07M nodes, 10.7 plies, 5 cores | LP, 1-KLSS, 6 cores | ~386 rounds, median 218 nodes, 1 core |
| Belief | exact positions, avg 17,264 | up to 1e7 | exact histories, tail guard |

Neither paper released code. A faithful replication needs a compiled solver and tracker, root top-up and full
KLUSS; hardware is not the blocker (the VM matches the papers' core counts).

## 7. Open items

1. Merge #66 -> #67; then the code in this branch can go to main (solver-labels 87b3089, network-leaf d63de87).
2. A stronger opponent than the greedy bot to rank network vs Stockfish leaf.
3. Second loop iteration: labels from the network-leaf agent, retrain, re-test.
4. Residual target (label minus material) as a cheaper way to beat the material baseline offline.
5. Test-split evaluation of `belief-solver-v1`, once, with `--final`.

## 8. Where things are

```
experiments/
  homelab/                         homelab VM, Proxmox guest, one Python core per chunk
    runs/baseline-and-clock/       strength-{exact,pruned}-s{16,256}-cN, strength-clock-s{16,64}-cN
    runs/mechanisms/               strength-{fe-s16,sf14-fe-s16,guard-fe-s16,fe-s64,fe-s256}-cN
    runs/network-leaf/             strength-net-fe-s16-cN
    configs/                       every arm's .ini (611)
    scripts/                       drivers (run_arms*.sh, run_arm_gpu.sh, run_labels*.sh), analyse.py,
                                   selection_check.py, make_arms*.py
    logs/                          driver and chunk logs; logs/REGIME-4500m.txt, logs4/REGIME-2000m.txt
                                   record which chunks ran at which memory cap
  atlas/                           NUS HPC Atlas, 15 GB jobs (NUSREC-HPC-00001)
    runs-baseline/                 strength-{exact,pruned,guard}-s16-cN
    runs-mechanisms/               strength-{fe-s16,guard-fe-s16,fe-s256}-cN
    pbs/                           PBS scripts and env.sh;  logs/  PBS output
  labels/
    collection/                    per-site progress.jsonl and manifests (raw labels: release asset)
    training/belief-solver-v1{,-noctx}/   best.pt, metrics.jsonl, summary.json, splits.json
    tools/                         merge_labels.py, baseline_material.py, torch.sh, train_v1.sh
  notes/                           verification-log.md (items 1-68, every number above),
                                   obscuro-vs-ours.md, zs21-vs-ours.md, PLAN.md (label -> network -> leaf)
```

Each `strength-*` folder has `summary.json` (W/D/L), `games.jsonl` (every game), `evaluate_config.ini`,
`provenance.json` and `tracker_updates.jsonl`. Score an arm with
`python experiments/homelab/scripts/analyse.py --runs <runs dir> --arms <arm> ...`. Atlas and homelab runs are
never paired with each other. Checkpoint `belief-solver-v1/best.pt` has sha256 prefix 48251445d554afce.

Prepared with Claude Code (Anthropic) from the run logs; numbers were checked against the result files.
