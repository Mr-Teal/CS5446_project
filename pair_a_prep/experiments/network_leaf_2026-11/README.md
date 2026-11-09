# network_leaf_2026-11: scripts behind the 2026-11-10 handover

See `pair_a_prep/docs/handover_2026-11-10.md` for definitions, results and how these fit together.

- `atlas/`: PBS scripts for the Stockfish-d8 label rounds (`label_sf8.pbs` ran the first wave of round 2 with
  the runner of that day; `label_sf8b.pbs` ran the resubmissions and round 3 and refers to the module
  `pair_a_prep.label_run2`, which is this branch's `pair_a_prep/label_run.py`), label statistics, and the
  cleanup of engine-dead placeholder games before a resume.
- `pipeline/`: merge, validate, baselines, training chains, the input-mode ablation chain, the generalisation
  sweep, paired comparison of runs, the GPU container wrappers, and the laptop-side pull script. `add_d1.py`
  belongs to the closed residual variant and is kept only so its one recorded number can be reproduced.
- `strength/`: strength-arm generator (`make_netv2_inis.py`, from the earlier arms' ini templates), launcher,
  scorer, driver (`run_arm_gpu.sh`, LIMIT and MEM from the environment), arm-set switch, and the guard tracker
  factory used by the guard arms.

Paths inside the scripts are the VM's (`/home/dev/cs5446-review/...`) and the laptop's scratchpad; adjust before
running elsewhere. Nothing here reads the test split.
