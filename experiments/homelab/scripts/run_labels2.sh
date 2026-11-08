#!/usr/bin/env bash
# Resume solver-label collection with the fixed runner (pair-a/solver-labels 87b3089,
# worktree wt-labels2) into the ORIGINAL output folder under wt-labels, so the games
# collected under 30b5753 are kept and skipped. Same protocol as run_labels.sh:
#
#   OUT=labels-01 GAMES=120 SEED=5001 MEM=4500m MAX_STATES=96000 BUDGET_MS=5000 ./run_labels2.sh
#
# Differences from run_labels.sh: REPO is wt-labels2; the runs directory of wt-labels
# is mounted at /runs and --out is absolute; the dirty-tree check ignores untracked
# files (the old check flagged the untracked pair_c/runs/ directory as source changes).
set -u

REPO=/home/dev/cs5446-review/wt-labels2
RUNS=/home/dev/cs5446-review/wt-labels/pair_c/runs
EXP=/home/dev/cs5446-review/experiment
IMAGE=fow-portability:probe
SF=/usr/games/stockfish
SF_SHA=79aa1e0c17294d94d07df98ebd0c0af04036a905837cfd2f98689d37e0c75013

OUT=${OUT:?set OUT, e.g. labels-01}
GAMES=${GAMES:-120}
SEED=${SEED:-5001}
MEM=${MEM:-4500m}
MAX_STATES=${MAX_STATES:-96000}
BUDGET_MS=${BUDGET_MS:-5000}
EVAL=${EVAL:-material}
SAMPLE=${SAMPLE:-16}
MAX_PLIES=${MAX_PLIES:-200}

COMMIT=$(git -C "$REPO" rev-parse --short HEAD)
if [ -n "$(git -C "$REPO" status --short -uno -- pair_a_prep pair_b pair_c fow_shared)" ]; then
    echo "[$(date -Is)] WARNING: $REPO has uncommitted source changes; $COMMIT does not identify this code" >&2
fi
mkdir -p "$EXP/logs-labels"
echo "[$(date -Is)] labels $OUT (resume, fixed runner): games=$GAMES seed=$SEED mem=$MEM max_states=$MAX_STATES budget_ms=$BUDGET_MS eval=$EVAL sample=$SAMPLE commit=$COMMIT out=$RUNS/$OUT"
docker run --rm --name "fow-labels-$OUT" --memory=$MEM --memory-swap=$MEM \
    -v "$REPO":/repo -v "$RUNS":/runs -v "$SF":"$SF":ro -e PYTHONPATH=/repo/pair_b/src -w /repo "$IMAGE" \
    python -u -m pair_a_prep.label_run --out "/runs/$OUT" --games "$GAMES" --seed "$SEED" \
        --evaluator "$EVAL" --stockfish "$SF" --stockfish-sha256 "$SF_SHA" \
        --time-budget-ms "$BUDGET_MS" --max-plies "$MAX_PLIES" --max-states "$MAX_STATES" \
        --sample-size "$SAMPLE" --commit "$COMMIT" \
    >> "$EXP/logs-labels/$OUT.log" 2>&1
status=$?
echo "[$(date -Is)] labels $OUT: exit=$status (log $EXP/logs-labels/$OUT.log; progress $RUNS/$OUT/progress.jsonl)"
exit $status
