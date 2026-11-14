# Bounded-history evaluation handoff

Use `network1-bounded-readiness.ini` instead of the exact tracker configuration
from PR75. Both players use the same uniform-growth anytime search. Only the
leaf/model/device differs: existing Network 1 versus Stockfish D1. This is not
a full Obscuro reproduction or a whole-belief learned strategy.

## Policy change

`tracker_policy = bounded-history` enables an explicitly approximate tracker.
After each complete private update, it uniformly retains at most 8192 COMPLETE
history paths, including repetition context and hypothetical moves needed by
Pair A search. `sample_size = 4` independently limits the agent input. After
pruning, population_size is unknown and weighting is
`uniform_over_returned_histories`; support_complete is false. A sample is not
a posterior probability over the full game.

If no retained path explains a new observation, up to eight independent
bounded replays use ONLY that player's saved observations and known own moves.
The same 60-second update allowance covers the failed attempt, all replays,
pruning and output. No hidden referee board, unseen actual opponent move or
stale belief is used. If recovery/time fails the attempt still fails explicitly.
Retained support is bounded; transient expansion, stored prefixes and process
RSS are not hard-capped. Search's cooperative 5-second allowance is separate.
The exact and budgeted-exact defaults are unchanged.

## Run

Use this branch's runtime changes, not just the INI copied to old main. In an
existing compatible environment, build the native kernel:

```powershell
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -m pair_a_prep.build_belief_kernel
```

Return to the torch-enabled environment. Edit BOTH `stockfish_path` entries to
the same local SF19 executable. Name/hash and existing checkpoint identity are
validated. CPU is the default; CUDA requires its own readiness test. Then:

```powershell
python pair_c/run_evaluation.py pair_c/configs/network1-bounded-readiness.ini
```

Use a fresh output directory. First run the seed17 colour pair, then a copy
with seed18 and another output path. For a later batch, vary the seed BETWEEN
pairs, keeping it fixed WITHIN each pair. Do not rerun the old package generator
that overwrites planner/tracker settings. This policy is a distinct experiment;
do not combine its outcomes with exact-tracker failures or the old one-ply batch.

## Failure diagnosis and replay

Every tracker JSONL row now preserves its private `observation` and `own_move`,
including the failed update, plus pruning/rebuild counters. These records are
for offline audit; do not give the opponent's rows or post-game logs to agents.
The two private streams allow deterministic tracker replay even if search was
clock-dependent. Old failed games omitted moves and cannot be reconstructed
from aggregate counts alone. Keep configs, source/checkpoint/engine/native
identities, full game/tracker records, failed/capped/unplayed attempts, fallback
rates and separate tracker/search timing. A successful pair is readiness
coverage, not proof of universal reliability or stronger play.

Replay any NEW recorded private stream without loading a model or engine:

```powershell
python -m pair_c.replay_tracking pair_c/runs/network1-bounded-readiness-seed17 --game 1 --player black --output pair_c/runs/replay-black.jsonl
```

The output path must not exist. The command reads only the selected player's
observations/own actions and the original tracker configuration/seed; referee
FENs and opponent moves are not consumed. Older aggregate-only traces are
rejected explicitly.

## Validated readiness scope

Two CPU colour pairs (seeds17/18) completed: 67/14 plies before the DAG pruning
optimization and 61/35 after it. All four were terminal, zero failures/caps,
zero uniform fallbacks/search overruns; actual pruning and recovery occurred.
Tracker updates reached 12.70 seconds. Private replay audits and 208 tracker
plus 47 separately invoked Pair C regressions passed; overlapping follow-up
checks are not added. Full scopes and raw artifacts are in
[the evidence directory](../evaluation_diagnostic_20261109_bounded/README.md).
Run local readiness on Pair C's actual host/device before scaling. These
checks enable continued testing, not a guarantee for every seed or hardware.
