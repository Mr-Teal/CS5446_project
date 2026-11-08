#!/usr/bin/env bash
# Collect solver labels by self-play from the wt-labels worktree, in one lane.
#
#   OUT=labels-01 GAMES=120 SEED=5001 MEM=4500m MAX_STATES=96000 BUDGET_MS=1000 ./run_labels.sh
#
# The output lives under wt-labels/pair_c/runs/<OUT> (root-owned, like every
# run directory). Re-running with the same OUT resumes: label_run skips games
# whose part file exists, and writes progress.jsonl as it goes.
#
# MEM and MAX_STATES go together (verification log items 20 and 30): 4500m with
# 96000, 8000m with 175000. The guard bounds the belief BEFORE an update, so a
# smaller container than the threshold was sized for is killed mid-update.
# Tracking, not search, sets the cost: about 30 s per labelled ply at a 1 s
# clock with the 96k guard on the standard start.
set -u

REPO=/home/dev/cs5446-review/wt-labels
EXP=/home/dev/cs5446-review/experiment
IMAGE=fow-portability:probe
SF=/usr/games/stockfish
SF_SHA=79aa1e0c17294d94d07df98ebd0c0af04036a905837cfd2f98689d37e0c75013

OUT=${OUT:?set OUT, e.g. labels-01}
GAMES=${GAMES:-120}
SEED=${SEED:-5001}
MEM=${MEM:-4500m}
MAX_STATES=${MAX_STATES:-96000}
BUDGET_MS=${BUDGET_MS:-1000}
EVAL=${EVAL:-material}
SAMPLE=${SAMPLE:-16}
MAX_PLIES=${MAX_PLIES:-200}

COMMIT=$(git -C "$REPO" rev-parse --short HEAD)
if [ -n "$(git -C "$REPO" status --short -- pair_a_prep pair_b pair_c fow_shared)" ]; then
    echo "[$(date -Is)] WARNING: wt-labels has uncommitted source changes; $COMMIT does not identify this code" >&2
fi
mkdir -p "$EXP/logs-labels"
echo "[$(date -Is)] labels $OUT: games=$GAMES seed=$SEED mem=$MEM max_states=$MAX_STATES budget_ms=$BUDGET_MS eval=$EVAL sample=$SAMPLE commit=$COMMIT"
docker run --rm --name "fow-labels-$OUT" --memory=$MEM --memory-swap=$MEM \
    -v "$REPO":/repo -v "$SF":"$SF":ro -e PYTHONPATH=/repo/pair_b/src -w /repo "$IMAGE" \
    python -m pair_a_prep.label_run --out "pair_c/runs/$OUT" --games "$GAMES" --seed "$SEED" \
        --evaluator "$EVAL" --stockfish "$SF" --stockfish-sha256 "$SF_SHA" \
        --time-budget-ms "$BUDGET_MS" --max-plies "$MAX_PLIES" --max-states "$MAX_STATES" \
        --sample-size "$SAMPLE" --commit "$COMMIT" \
    > "$EXP/logs-labels/$OUT.log" 2>&1
status=$?
echo "[$(date -Is)] labels $OUT: exit=$status (log $EXP/logs-labels/$OUT.log; progress $REPO/pair_c/runs/$OUT/progress.jsonl)"
exit $status
