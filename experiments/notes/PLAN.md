# Solver labels -> belief network -> verified leaf (plan, written 2026-11-04 04:35 SGT)

User's instruction (2026-11-04 ~04:05 SGT): "after data collection start training and verify the
trained leaf's performance". The cron watcher (every 2 h at :17, recreated as needed) checks progress and
runs this plan when both label sites are complete. Everything heavy runs on the homelab VM inside a
memory-capped container; nothing runs on the laptop; nothing from the NUS admin folder goes anywhere.

(Rebuilt 2026-11-05 01:40 SGT from the session transcript after the laptop reboot wiped the scratchpad;
durable copy: VM /home/dev/cs5446-review/labels/docs-recovered-20261105/label-training/PLAN.md.)

## 1. Inputs

| Site | Where | Volume | Complete when |
|---|---|---|---|
| Homelab | `/home/dev/cs5446-review/wt-labels/pair_c/runs/labels-01/` | 120 games | `manifest.json` exists there |
| Atlas | `/hpctmp/$USER/fow/repo-labels/pair_c/runs/labels-01/task-{1..10}/` | 10 x 24 games | no label job Q/R and every task folder has a manifest (section 7); a task killed by memory is resubmitted with resume until it does |

Both share one protocol id: code 30b5753 (87b3089 after the fix; same protocol), material leaf, 5 s clock,
sample 16, tail guard 96,000, 200-ply cap, 2-8 unlabelled opening plies, both colours labelled. Seeds are
disjoint (homelab 5001+2i; Atlas task N uses 5001+1000N as its base). First homelab game: 45 plies, 39
records, 5 guard prunes, 641 s. Expect ~40-55 records per game, so ~5,000-6,500 homelab and ~10,000-13,000
Atlas records.

Transfer Atlas -> laptop -> VM (the two hosts never see each other):
```
# tunnel DOWN
rsync -az --include='*/' --include='part-*.jsonl' --include='progress.jsonl' --include='manifest.json' --exclude='*' \
  atlas:/hpctmp/tommy.21.31/fow/repo-labels/pair_c/runs/labels-01/ \
  /private/tmp/claude-501/-Users-tommy2131-Desktop-school-doc-NUS/9a179d7b-673c-4a9a-bd4f-fbcb26bb4543/scratchpad/label-training/atlas-labels-01/
# tunnel UP
ssh homelab mkdir -p /home/dev/cs5446-review/labels
rsync -az .../atlas-labels-01/ homelab:/home/dev/cs5446-review/labels/atlas-labels-01/
```

## 2. Environment on the VM (verified 2026-11-04 04:20 SGT)

The portability image has Python 3.12.16 but no torch. The fow-chess venv has torch 2.11.0+cu128
and python-chess 1.11.2 on uv's CPython 3.12.14. Mounting the venv and uv's python at their own
paths into the image, with `--gpus all` (nvidia runtime is installed), gives torch with CUDA inside
a capped container: `python 3.12.14 torch 2.11.0+cu128 cuda True NVIDIA GeForce RTX 5070 Ti`.
`systemd-run --user -p MemoryMax` does NOT cap on this VM (tested), so docker is the only cap.
Run as `--user 1000:1000` (dev) with `HOME=/tmp`: verified cuda True and files under /labels owned by
dev (as root they come out root-owned and need sudo to remove). uid 1000 has no passwd entry in
the image, and torch.compile's inductor cache calls getpass.getuser() -> KeyError; `-e USER=dev -e LOGNAME=dev
-e TORCHINDUCTOR_CACHE_DIR=/tmp/inductor` avoids it (found in the step-0 smoke, 2026-11-04 04:30 UTC).
`/home/dev/cs5446-review/labels/runs` was root-owned from an earlier container and is now chowned to dev.

```
TORCH="docker run --rm --gpus all --memory=8000m --memory-swap=8000m --user 1000:1000 -e HOME=/tmp \
  -e USER=dev -e LOGNAME=dev -e TORCHINDUCTOR_CACHE_DIR=/tmp/inductor \
  -v /home/dev/fow-chess/.venv:/home/dev/fow-chess/.venv:ro \
  -v /home/dev/.local/share/uv/python:/home/dev/.local/share/uv/python:ro \
  -v /home/dev/cs5446-review/wt-net:/repo -v /home/dev/cs5446-review/labels:/labels \
  -v /home/dev/cs5446-review/wt-labels/pair_c/runs:/homelab-runs:ro \
  -w /repo -e PYTHONPATH=/repo:/repo/pair_b/src -e PYTHONDONTWRITEBYTECODE=1 \
  fow-portability:probe /home/dev/fow-chess/.venv/bin/python"
```
`wt-net` = worktree at `pair-a/network-leaf` (final-integration + the belief_network leaf kind; the two
changed files are UNCOMMITTED in wt-net and in no other place since the laptop clone was wiped).
Pair B's pyproject pins torch>=2.14.1; 2.11 imports all training modules. If training fails with
a torch API error, that pin is the first suspect.

Latency measured with `belief-v1-pure`: `evaluate_children` 6.9 ms on cuda, 1,168 ms on cpu. The
network leaf is therefore GPU-only, and at most ~700 evaluator calls fit a 5 s move (the arms cap
4,096; the material leaf costs microseconds).

## 3. Steps

0. **Smoke, before the data is complete** (first check with >= 10 homelab games): validate the
   homelab folder, train 2 epochs on it alone, evaluate on val. DONE 2026-11-04 04:30 UTC (section 5b).
   Note: splits are sha1(game_id) % 10: 0-7 train, 8 val, 9 test; a tiny set may lack val games.
1. **Validate** each source folder (homelab; each Atlas task):
   `$TORCH pair_b/scripts/validate_labels.py <folder> --require-played-policy`. Expect 0 errors.
2. **Merge** into one folder without a manifest (one config_id enforced, parts prefixed per source):
   `python3 merge_labels.py /home/dev/cs5446-review/labels/solver-v1 /homelab-runs/labels-01 /labels/atlas-labels-01/task-*`
   (run inside the container so the paths resolve, or with host paths). Validate the merged folder too;
   "manifest absent; accepted by the training loader" is the expected warning.
3. **Train** (no `--use-d1`: solver labels carry no quick-Stockfish diagnostics):
   `$TORCH pair_b/scripts/train_belief_net.py --data /labels/solver-v1 --out /labels/runs/belief-solver-v1 --device cuda --workers 6 --cache-dir /labels/cache`
   Defaults: 30 epochs, patience 5, batch 64 beliefs, 4,096 boards per step. Planes cache ~20k beliefs
   x 16 boards x 4 KiB ~ 1.3 GB. `--out` must not exist. Minutes on this GPU.
   Then the ablation Pair B's README leaves to our labels, same command with `--no-context` ->
   `/labels/runs/belief-solver-v1-noctx`.
4. **Offline evaluation** (how well the network predicts the solver's values on held-out games):
   `$TORCH pair_b/scripts/eval_belief_net.py --run /labels/runs/belief-solver-v1 --data /labels/solver-v1 --split val --device cuda`
   Report board MAE and position MAE for both runs. No built-in baseline without d1, so compute two
   with `baseline_material.py` (in labels/tools on the VM): the material evaluator's value of each
   hypothesis (position value = weighted mean) and the constant 0, on the same val beliefs. The test
   split only once, at the end, with `--final`.
5. **Strength arm** (the trained leaf in play): copy `best.pt` to
   `wt-net/pair_b/checkpoints/belief-solver-v1/best.pt` (untracked, never commit). Arm `net-fe-s16`
   = the fe-s16 ini with `leaf_evaluator = belief_network`, `checkpoint_path = /repo/pair_b/checkpoints/belief-solver-v1/best.pt`,
   `device = cuda`, same budget (1,024 rounds, 16,384 nodes, 4,096 evaluator calls, stop_on_time),
   50 chunks x 2 games, seeds 1001-1100, opponent Material OnePlyBot 256/8/2000, rules teal,
   5,000 ms, 200 plies. Driver `run_arm_gpu.sh` = run_arms4.sh with `--gpus all`, the venv mounts,
   the venv python, PYTHONPATH `/repo:/repo/pair_b/src:/exp`, MEM 4500m, one lane, logs in
   `logs-net/`. Start it when memory allows (lane B 8 GB + labels 4.5 GB already; wait for the label
   lane to finish). Analyse with `analyse.py --runs runs-all --arms fe-s16 sf14-fe-s16 net-fe-s16`
   (refresh the runs-all symlinks first). The comparison of interest: net-fe-s16 against fe-s16
   (material leaf, 0.924) and sf14-fe-s16 (Stockfish leaf, 1.000) on shared seeds.
6. **Record**: results and claim limits into report-rewrite/docs/notes/verification-log.md; Atlas
   labels carry the NUSREC-HPC-00001 acknowledgement. Then CronDelete the watcher.

## 4. Decisions for the user (ask, do not assume)

- Train the `--use-d1` variant too? It needs a quick-Stockfish value on every hypothesis, added
  offline (~20k beliefs x 16 boards x ~2 ms ~ 11 min with Stockfish 14.1), and the leaf then calls
  Stockfish per board in play. Default here: planes-only first.
- If one site stalls, train on the other alone rather than wait?
- The leaf's slowness (6.9 ms per call) may cost more than its accuracy gains; if net-fe-s16 loses
  to fe-s16, a follow-up is a cheaper network or batching children, not a conclusion about labels.

## 5. Findings from the toolchain smoke (2026-11-04 04:45 SGT)

- `labels-smoke` and `labels-smoke2` under wt-labels/pair_c/runs are STALE pre-fix runs (records carry the
  agent config id `sampled-I2-gadget-pcfr-prototype-v2:...` and two played_policy rows fail validation,
  the purify rounding bug fixed before 30b5753). Never merge them. `labels-smoke3` and `labels-01` have
  the protocol id format. The merge script now refuses mixed config_ids before copying anything.
- The validator, the loader (load_arrays + cache) and the baseline script all run on real solver
  labels in the GPU container. `train_belief_net.py` crashes with "need at least one array to
  concatenate" (rows_of on an empty val split) before reaching its own "no validation games" message
  when no game hashes to bucket 8; harmless, it means too few games. Step 0 needs >= ~10 games.
- Early number, ONE game (seed 5001, 39 records, train split): the material evaluator alone predicts
  the solver's hypothesis values with board MAE 0.059 and position MAE 0.059; the constant 0 gives
  0.709. So the solver labels sit close to material counting, and the network's useful signal is the
  residual above that baseline. Report the network against the material baseline, not against zero.

## 5b. Step-0 smoke on 17 games (2026-11-04 04:30 UTC, verification-log item 52)

Validator PASS (1,059 records, 17 games: train 14, val 1, test 2, 0 errors). 2-epoch train: 899 train
beliefs / 13,928 boards, 1.6-1.8 s per epoch, val board MAE 0.5847 -> 0.5781, root MAE 0.5667
(labels/runs/smoke-1104). Eval val: board MAE 0.5781, root MAE 0.5667. Baselines on the same val game:
material board MAE 0.0884 / position 0.0865, zero 0.5265 / 0.5183. Toolchain check only.

## 6. Incident 2026-11-03 22:47 UTC (verification-log item 47)

- Atlas tasks 1 and 4 died: `BeliefBudgetError: no_candidate` (guard pruned the true history, a later
  view matched nothing) and `ValueError: values must be finite and in [-1, 1]` (rounding at a decided
  position). label_run 30b5753 has no per-game guard, so a dead game kills the task. Expect ~10%/game
  -> ~9 games per 24-game task under the old code. Tasks that die leave no manifest.
- Fix: `_unit()` clamp in `label()`, per-game try/except in `collect()` (records so far written, `error`
  row in progress.jsonl, run continues), `failed` in the manifest, two tests. Copied to Atlas as
  `/hpctmp/$USER/fow/repo-labels2` (rsync, not a git repo); PBS test job 1032521: **21 passed**
  2026-11-04 07:17 SGT. Committed 2026-11-04 as **87b3089** on pair-a/solver-labels and pushed to the VM
  (origin); the laptop worktree that held it was wiped by the reboot, the VM has it (wt-labels2).
- Guard array 1031480 was released 2026-11-04 00:50 UTC, then held again at 03:0x UTC when the label
  tasks were resubmitted; `qrls "1031480[]"` once no label job is Q.
- Dead tasks (02:47 UTC Nov 4): 1 (0 games), 2 (14), 3 (3), 4 (6), 6 (4), 7 (10), 8 (2), 9 (5), 10 (10); eight
  dead beliefs, one rounding value (9 deaths in 71 game starts, 12.7 %/game). Only task 5 still ran then.
- Resubmission: `label_arm2.pbs` (cd repo-labels2, PYTHONPATH on repo-labels2, `--commit 87b3089`,
  `TASK=${PBS_ARRAY_INDEX:-$N}`, OUT absolute into the original task folder so finished parts are skipped):
  `qsub -v TAG=labels-01,GAMES=24,BUDGET_MS=5000,MAX_STATES=96000,N=<task> label_arm2.pbs`. Records from
  both code versions share the protocol id (the protocol dict has no commit), so they pool.
- The merge (step 2) takes the task folders that exist, with or without manifests; validate each.
- Homelab VM froze at ~22:45 UTC Nov 3 (swap thrash: orphan fe-s64-c27 + fe-s64-c32 + labels) and was
  recovered by the user with alt-sysrq-f at 03:34 UTC Nov 4.

## 7. Resubmission 2026-11-04 03:0x UTC (user: "ok both" = reset the VM, commit the fix)

- Fix committed as **87b3089** on pair-a/solver-labels; pushed to the VM 03:42 UTC.
- Atlas: nine dead tasks resubmitted as single jobs: task 1 = 1032729, 2 = 1032730, 3 = 1032731,
  4 = 1032732, 6 = 1032733, 7 = 1032734, 8 = 1032735, 9 = 1032736, 10 = 1032737. Task 5 continued as
  1032509[5] (old code). Guard array 1031480 held again (38 Q).
- Memory kills (items 54, 56, 57): the guard prunes BEFORE an update, so one update can exceed any cap
  (homelab 4.5 GB container at game 33; Atlas 15 GB job cgroup: tasks 1, 5, 7 at 15.7 GB RSS). Remedy
  is resume: homelab `run_labels2.sh` restarted 07:58 UTC (driver 3503579); Atlas resubmitted task 1 =
  1033280, task 5 = 1033281 (fixed code), task 7 = 1033441. Never lower the 15 GB request.
- Complete with manifest (as of 16:47 UTC Nov 4): tasks 2 (1032730), 3 (1032731), 4 (1032732), 6 (1032733).
- Homelab lane: 87b3089 in worktree `wt-labels2`, `experiment/run_labels2.sh` (REPO wt-labels2, runs dir of
  wt-labels mounted at /runs, --out /runs/labels-01, `python -u`, log appended to logs-labels/labels-01.log,
  driver log logs-labels/driver2-labels-01.log). wt-labels is DETACHED at 30b5753 and must stay: the
  output folder lives there. Lane B (run_arms4.sh) runs fe-s256 chunks at 8000m that die at their own cap.
- DONE 03:43 UTC Nov 4 (verification-log item 51): VM recovered; old lane stopped at 15 games; worktree
  wt-labels2 = 87b3089; resume skipped 0-14. Watch for orphans: `docker ps` containers fow-fe-s*-cNN "Up"
  far beyond 30 min while the lane B driver log has moved on.
