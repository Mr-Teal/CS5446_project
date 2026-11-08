#!/usr/bin/env bash
# Run one or more mechanism arms, interleaved by chunk, from the wt-dev worktree.
#
# Differences from run_arms3.sh, each deliberate:
#   REPO is wt-dev, the Obscuro-mechanisms branch. wt-pr2 keeps serving the
#   clock arms; nothing here reads it. Do not edit wt-dev while this runs.
#   ARMS comes from the environment, e.g. ARMS="fe-s16 sf14-fe-s16" ./run_arms4.sh
#   The host Stockfish 14.1 binary is bind-mounted read-only; its NNUE is
#   embedded, so no data directory is needed. Material arms ignore the mount.
#   MEM=8000m is the regime recorded in logs/REGIME-4500m.txt (everything not
#   in that file ran at 8000m). Logs and .done markers live in logs4/ so a
#   mechanism arm can never be mistaken for a wt-pr2 run of the same seeds.
#   LIMIT is unchanged at 1800 s per chunk; cut-off chunks are left unmarked
#   and reported separately from memory kills, as before.
set -u

REPO=/home/dev/cs5446-review/wt-dev
EXP=/home/dev/cs5446-review/experiment
LOGS=${LOGS:-$EXP/logs4}
IMAGE=fow-portability:probe
MEM=${MEM:-8000m}
LIMIT=1800
SF=/usr/games/stockfish
mkdir -p "$LOGS"

ARMS="${ARMS:?set ARMS, e.g. ARMS=\"fe-s16 sf14-fe-s16\"}"
CHUNKS="${CHUNKS:-$(seq 1 50)}"

echo "[$(date -Is)] repo=$REPO commit=$(git -C "$REPO" rev-parse --short HEAD) arms=$ARMS mem=$MEM"
if [ -n "$(git -C "$REPO" status --short -- pair_a_prep pair_b pair_c fow_shared)" ]; then
    echo "[$(date -Is)] WARNING: wt-dev has uncommitted source changes; the commit above does not identify this code" >&2
fi

for chunk in $CHUNKS; do
    for arm in $ARMS; do
        name="$arm-c$chunk"
        log="$LOGS/$name.log"
        if [ -f "$LOGS/$name.done" ]; then
            echo "[$(date -Is)] $name already done, skipping"
            continue
        fi
        out="$REPO/pair_c/runs/strength-$name"
        if [ -d "$out" ]; then
            mv "$out" "$REPO/pair_c/runs/partial-$name-$(date +%m%d-%H%M)" \
                && echo "[$(date -Is)] $name had a stale output directory; set aside"
        fi
        echo "[$(date -Is)] starting $name"
        start=$(date +%s)
        timeout --signal=TERM --kill-after=60 "$LIMIT" \
            docker run --rm --name "fow-$name" --memory=$MEM --memory-swap=$MEM \
            -v "$REPO":/repo -v "$EXP":/exp -v "$SF":"$SF":ro \
            -e PYTHONPATH=/repo/pair_b/src:/exp -w /repo \
            "$IMAGE" python -m pair_c.run_evaluation "/exp/$name.ini" \
            >"$log" 2>&1
        status=$?
        if [ "$status" -eq 124 ]; then
            echo "[$(date -Is)] $name exceeded ${LIMIT}s; removing container" >&2
            docker rm -f "fow-$name" >/dev/null 2>&1
        fi
        echo "[$(date -Is)] $name exit=$status elapsed=$(( $(date +%s) - start ))s"
        # Done means the runner wrote its summary; a killed or cut-off chunk is retried.
        if [ -f "$out/summary.json" ]; then
            touch "$LOGS/$name.done"
        fi
    done
done
echo "[$(date -Is)] mechanism arms: all chunks attempted"
