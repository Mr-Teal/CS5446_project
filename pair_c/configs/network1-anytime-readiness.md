> **Follow-up:** this exact-tracker configuration timed out on Pair C's host.
> Retain it as historical evidence. For the opt-in approximate replacement,
> use [bounded-history readiness](network1-bounded-readiness.md).

# Network 1 versus Stockfish D1: tested anytime handoff

Configuration: `network1-anytime-readiness.ini`. Use main `10352fe` or a revision
containing PR65 and PR70. No PR66/67, new training or checkpoint is required.
This is uniform-growth anytime PCFR+, not the Obscuro subgame/gadget agent.

## Setup and run

Use the project's existing torch-enabled Python environment. Build the optional
native tracker using a matching C++ compiler, from repository root:

```powershell
python -m pair_a_prep.build_belief_kernel
```

On Windows the existing ZS21 Pixi environment supplies the compiler:

```powershell
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -m pair_a_prep.build_belief_kernel
```

Then return to the torch-enabled environment for evaluation. `tracker_backend =
native` is deliberate: a missing/mismatched library must fail rather than
silently running a different backend. Use the existing pinned Network 1
checkpoint. Edit `stockfish_path` on BOTH sides to the local SF19 Windows
universal executable. Its expected name and SHA256 are enforced. Other engine
binaries/platforms require a separately recorded configuration.

```powershell
python pair_c/run_evaluation.py pair_c/configs/network1-anytime-readiness.ini
```

The output directory must not exist. CPU is the tested default. Pair C can
select `device = cuda:0` for Network 1 after its own environment check, recording
that device/hardware change. This handoff does not certify CUDA execution.

## What changed after PR74

Both players use the same planner, budgets, rules and exact tracker. Only the
leaf/model/device-related settings differ. Initial depth is 1, maximum depth 2,
4096 nodes, 128 evaluator calls, 16 solver rounds and a cooperative 5-second
search allowance. Growth that cannot fit retains the prior valid tree instead
of requiring a full depth-2 tree before any decision. Initial preparation can
still use an explicit uniform fallback; inspect diagnostics rather than hiding it.

The tracker returns four sampled complete histories, uses native acceleration,
a 60-second allowance per private update, no resumes and no logical memory cap.
It does not prune. This changes the failed Python/16-second/512-MiB configuration
and must remain a separate experiment. Tracking and search have separate clocks;
there is no hard whole-turn deadline or RSS guarantee. Sampling does not bound
internal history support. Arrange process/time monitoring for longer batches.

## Local readiness result, 9 November 2026

Windows, Python 3.12.15, torch 2.14.1+cpu, NumPy 2.5.4, python-chess 1.11.2,
real SF19 and the committed Network 1 weights. Native kernel built from current
main source. Two standard-start seed-17 games, colours swapped, 200-ply cap:

| Network 1 colour | Result | Plies | Fallbacks | Search budget overruns |
| --- | --- | ---: | ---: | ---: |
| White | Loss by king capture | 46 | 0 | 0 |
| Black | Win by king capture | 14 | 0 | 0 |

Two terminal games, zero failed/capped attempts, 60 legal moves recorded.
Maximum observed private tracker update was 2324.645 ms. The production runner
exited successfully. This accepts this local readiness pair, not general
full-game reliability or a strength estimate. Clock-limited trajectories can
vary across runs/hardware. It is not a replay of the identical failed trajectory.

The earlier anytime/Python/512-MiB pair is preserved: White failed tracking at
ply60; Black won in 14 plies. The failure is not a loss/draw, and its surviving
100% score is not a strength result. No 100-game batch has been run here.

## Pair C next steps

Run this readiness pair first on the intended host/device. Then copy the INI,
set seed 18 and a fresh output directory for a second readiness pair. Review
both before scaling. Keep the seed fixed WITHIN each colour-swapped pair; vary
it BETWEEN pairs. A formal 50-pair batch therefore needs separate pair INIs
(seeds 17 through 66), not one 100-game run reusing the same seed. Freeze the
source/device/engine before the batch and retain every attempted, terminal,
capped, failed and unplayed count. Stop and return records if readiness fails.

Archive copied INI, provenance, games/tracker JSONL and summary. Report actual
depth/work, fallback rates, search and tracking time; identical caps do not mean
equal computation. Do not pool with PR74 or the old one-ply evaluator batch.

Raw local validation records and the build manifest are published in
[the evidence handoff](../evaluation_diagnostic_20261109_anytime/README.md).
