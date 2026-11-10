ONE-COMMAND EVALUATION HANDOFF — 9 NOVEMBER 2026

Goal: complete the existing Network 1 vs Stockfish D1 comparison on reviewed,
merged code, or return a complete diagnostic showing why it cannot be completed
with this frozen configuration. No Pair A approval, unpublished model, pending
PR66/67, new training, code edits, or intermediate messages are needed.

This replaces the earlier pilot-only ZIP. It controls the stages, gates, logs,
attempt accounting, paired analysis and final return ZIP automatically.

1. SOURCE AND ENVIRONMENT

Use your existing project Python environment with torch, numpy, scipy and chess.
Use Stockfish 19. On your RTX laptop --device auto tries the actual model on CUDA;
if CUDA fails, it chooses CPU BEFORE starting and records why. The chosen device
is then frozen for every official stage; no device change within the experiment.
Missing packages or an unusable CPU setup produce a diagnostic ZIP, not a false
success. You may correct installation/paths and start a NEW output folder, but
do not alter source, weights, settings or scores to make the experiment pass.

Use a clean checkout of:
10352fe54ec5c11acbad8671f165642b812eae78

To preserve your existing checkout, a fresh worktree is suitable. For example,
from your existing Git repo in PowerShell (substitute unused real paths):

git fetch origin
git worktree add --detach C:/experiments/fow-evaluation-source 10352fe54ec5c11acbad8671f165642b812eae78

Activate the existing Python environment, then run this package from OUTSIDE that
checkout. The source and actual engine/checkpoint hashes are checked. The weights
are the existing tracked pair_b/checkpoints/net1-v2/best.pt, not belief-solver-v1.

2. RUN ONCE

From the extracted handoff folder, substituting real paths:

python run.py --repo C:/experiments/fow-evaluation-source --stockfish C:/tools/stockfish.exe --out C:/experiments/fow-evaluation-20261109 --device auto

Defaults: up to FOUR HOURS total, 20 minutes per two-game pair, target 50 seed/
colour pairs (100 batch games). This may use your machine for the full four hours.
The final archive/compression can take additional time after gameplay stops.
If you need a different time allowance, specify --hours BEFORE the run. The
manifest records it. Do not extend a run after seeing scores. A new output folder
is required; no results are overwritten. Do not run multiple copies together.

3. AUTOMATIC STAGES

A. Preflight loads the real model, checks Stockfish 19 and selects the device.
B. Opening check: seed 17, colours swapped, four plies each. Both capped/unscored
   attempts must finish with full solver diagnostics and verified provenance.
C. Readiness: seeds 17 and 18, each in both colours, standard start, 200-ply cap.
   All four attempts must terminate without errors, caps, incomplete solves,
   search overruns or mismatched provenance. Otherwise the batch is not launched.
D. Batch: 50 fixed pairs, seeds 1001..1050, each played with both colours at the
   SAME seed. No early stopping on win rate. Normal failed/capped attempts stay
   in the archive. The declared wall cutoff, hard pair timeout, or three
   consecutive invalid pairs stops the remaining schedule as unplayed.
E. The script writes manifest.json, analysis.json, RESULTS.txt, configs, complete
   per-pair outputs/logs, and prints the location of the final *-return.zip.

No asking Bryan/Colin between stages. A gate failure, process limit, or insufficient
clean pairs is a valid diagnostic completion of this handoff. Return that ZIP
with the failure; do not start experimenting with pruning, budgets or checkpoints.
Ctrl+C stops the running process tree and preserves a partial return archive.
A hard machine/power failure may leave only partial outputs; preserve that whole
folder. Never replace or quietly omit it in a subsequent new run.

4. FROZEN EXPERIMENT AND INTERPRETATION

Network 1 and Stockfish D1 are used in the same sampled-root fixed depth-2 PCFR+
search, 16 solver rounds, max 4096 nodes, four sampled hypotheses, Teal rules,
one-thread/16-MiB Stockfish 19. Both use the same exact-or-fail Python tracker,
with a separate cooperative 16-second/512-MiB logical-memory allowance per update,
no pruning and no resume. Each search has a cooperative five-second allowance.
These are candidate experiment settings, not accepted full-game competition
budgets, OS memory caps, whole-turn deadlines or a full Obscuro reproduction.

The new handoff does not fix the known long-history tracker limitations. Failure
is informative and may prevent a valid strength comparison. The chosen backend
is Python to keep it explicit across hosts; no native build is required.
Network 1 is a per-board learned correction using D1, not whole-belief neural
action selection. Same configured allowances do not imply equal completed work.

Pilot/readiness games are separate from batch results. Caps/errors/timeouts are
not scored as draws or losses. analysis.json reports ALL planned/attempted/
unplayed accounting and the score only on fully clean terminal colour pairs.
That score is conditional on clean completion. If any pair is excluded, it is
not an estimate for all planned seeds. A whole-pair 20,000-resample bootstrap
interval is added only at 20 clean pairs; it does not prove equivalence. The
study cannot establish optimal play or performance of an unpublished model.

5. WHAT TO RETURN

Send Bryan/Colin exactly the *-return.zip printed at the end, plus a one-line
description if the machine itself was interrupted or killed. The ZIP includes
raw outputs and setup/runtime errors automatically; no editing of tables needed.
Do not upload weights, dataset caches, credentials or your whole repo. The script
does not send any files itself and never touches PR33 or remote branches.
