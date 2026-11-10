GPU EVALUATION HANDOFF — 9 NOVEMBER 2026

Frozen source: PR76 aaa000a034ae5275afe981402891596e660312a4.
Network 1 vs Stockfish 19 D1 with identical uniform-growth anytime search and
approximate bounded-history native tracking. This package supersedes the old
fixed-depth/Python-exact controller. Do not pool earlier experiments with it.

SETUP
Use the existing torch/numpy/scipy/chess Python environment. The source checkout
must be outside this package. Create it once from the main project repository:

git worktree add --detach C:/Projects/PycharmProjects/CS5446_evaluation aaa000a034ae5275afe981402891596e660312a4

--detach is only for worktree creation; it is not a run.py option. If the worktree
already exists at this commit, do not create it again. Build native tracking from
C:/Projects/PycharmProjects/CS5446_evaluation:

pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -m pair_a_prep.build_belief_kernel

Use the existing Network 1 checkpoint and validated SF19 Windows universal binary.
CUDA cuda:0 is mandatory: model/device failures stop with diagnostics, with no CPU
fallback. Stockfish and native tracking remain on CPU. The --stockfish argument supplies the local engine path; both player sections
are written automatically into generated pair configs. No manual INI edits are
needed for this controller.

The only allowed checkout changes are the two local readiness INIs:
pair_c/configs/network1-bounded-readiness.ini
pair_c/configs/network1-bounded-readiness-seed18.ini
Their contents and hashes are archived; status must remain identical throughout.
Runtime source must match the pinned commit. Do not discard other work to pass a
check: use a fresh checkout when needed. Native source/binary identity is checked
by preflight and the build manifest/binary hash is frozen for the experiment.

RUN (from this handoff directory, with the torch-enabled environment active)

python run.py --repo C:/Projects/PycharmProjects/CS5446_evaluation --stockfish C:/Projects/PycharmProjects/CS5446_project/pair_c/stockfish/stockfish-windows-x86-64-universal.exe --out C:/Projects/PycharmProjects/CS5446_evaluation_output --device cuda:0

The output directory AND its -return.zip must not exist. Defaults are 50 pairs
(seeds 1001..1050), four hours total and 20 minutes per pair. Change --hours or
--pair-timeout-minutes only BEFORE launching; never extend based on scores.
One process at a time. Compression takes additional time after the run stops.

STAGES AND STOPPING
1. Check source/checkpoint/engine/native identities and actual CUDA model use.
2. Repeat seed17 four-ply colour-swapped opening check (expected unscored caps).
3. Repeat seed17 and seed18 full-game GPU readiness (200-ply cap) in this archive.
   Previous successful readiness remains supporting evidence, not batch data.
4. If all gates pass, run the 50 fixed colour pairs; seed stays fixed within each
   pair. Never stop on win rate. A hard pair timeout, total cutoff or three
   consecutive invalid batch pairs stops the remaining schedule as unplayed.
5. Write manifest.json, analysis.json, RESULTS.txt and the final -return.zip.

Failures/caps/fallbacks/search overruns/provenance mismatches exclude a pair from
clean-pair scoring. Gate failures stop before batch. Missing records remain
unknown, not draws. Ctrl+C stops the child process tree and archives partial
outputs. Power/OS kills may prevent finalization: retain the entire output folder
and report the interruption. Never overwrite earlier results.

FROZEN SETTINGS AND INTERPRETATION
Anytime PCFR+: uniform growth, initial depth1/max2, 4096 nodes, 128 evaluator calls,
16 solver rounds, rounds_per_stage=2, final_rounds=2; Teal rules; four hypotheses.
Network1 device cuda:0, existing net1-v2/best.pt; SF19 one thread/16 MiB hash.
Tracker: native bounded-history, 8192 retained full paths, up to8 bounded recovery
replays, shared60s per private update; search has a separate cooperative5s budget.
Pruning/recovery are part of this approximate policy. Incomplete support after
pruning is expected, not a failure. Partial/failed expansion still fails.
8192 histories is not a transient-memory/RSS cap. There is no hard whole-turn
limit. Watch host memory/process health during execution; cooperative clocks can
overrun before returning. Equal budgets do not imply equal completed computation.

Only clean terminal batch colour pairs contribute to scores; opening/readiness
are excluded. If any pair is excluded, the score is conditional on completion,
not a result over all planned seeds. At least20 clean pairs enable a20000-resample
whole-pair bootstrap interval; it does not establish equivalence. Search/work and
tracker timing are in per-pair inspection metrics and raw diagnostics. Search
records in failed games may omit partial work; logical bytes are not RSS.

RETURN
Return the entire printed -return.zip, including failures. It includes generated
configs, raw game/private tracker records, provenance, native build identity,
controller copy and analysis. Do not upload weights, executable, caches or whole
repo. Report any machine/power/operator interruption. The script does not send,
push, merge, or modify PR33. Use the results to prepare the evaluation/diagnostic
PR with identities, actual device, all outcome counts and supporting archive.
