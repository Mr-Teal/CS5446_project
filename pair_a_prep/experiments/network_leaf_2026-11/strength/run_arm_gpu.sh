#!/usr/bin/env bash
# Network-leaf strength arm: run_arms4.sh with the GPU torch container.
# Differences from run_arms4.sh: REPO is wt-net (final-integration + network leaf,
# contains cca2fe2); --gpus all; fow-chess venv + uv python mounted; venv python;
# PYTHONPATH adds /repo; logs in logs-net/. Same 1800 s limit, same 8000m cap as fe-s16.
set -u
REPO=/home/dev/cs5446-review/wt-net
EXP=/home/dev/cs5446-review/experiment
LOGS=${LOGS:-$EXP/logs-net}
IMAGE=fow-portability:probe
MEM=${MEM:-8000m}
LIMIT=${LIMIT:-1800}
SF=/usr/games/stockfish
PY=/home/dev/fow-chess/.venv/bin/python
mkdir -p "$LOGS"
ARMS="${ARMS:?set ARMS}"
CHUNKS="${CHUNKS:-$(seq 1 50)}"
echo "[$(date -Is)] repo=$REPO commit=$(git -C "$REPO" rev-parse --short HEAD) arms=$ARMS mem=$MEM ckpt=$(sha256sum "$REPO/pair_b/checkpoints/belief-solver-v1/best.pt" | cut -c1-16)"
if [ -n "$(git -C "$REPO" status --short -uno -- pair_a_prep pair_b pair_c fow_shared)" ]; then
    echo "[$(date -Is)] WARNING: wt-net has uncommitted source changes (network-leaf factory)" >&2
fi
for chunk in $CHUNKS; do
    for arm in $ARMS; do
        name="$arm-c$chunk"; log="$LOGS/$name.log"
        if [ -f "$LOGS/$name.done" ]; then echo "[$(date -Is)] $name already done, skipping"; continue; fi
        out="$REPO/pair_c/runs/strength-$name"
        if [ -d "$out" ]; then
            mv "$out" "$REPO/pair_c/runs/partial-$name-$(date +%m%d-%H%M)" && echo "[$(date -Is)] $name had a stale output directory; set aside"
        fi
        echo "[$(date -Is)] starting $name"; start=$(date +%s)
        timeout --signal=TERM --kill-after=60 "$LIMIT" \
            docker run --rm --name "fow-$name" --gpus all --memory=$MEM --memory-swap=$MEM \
            -v "$REPO":/repo -v "$EXP":/exp -v "$SF":"$SF":ro \
            -v /home/dev/fow-chess/.venv:/home/dev/fow-chess/.venv:ro \
            -v /home/dev/.local/share/uv/python:/home/dev/.local/share/uv/python:ro \
            -e PYTHONPATH=/repo:/repo/pair_b/src:/exp -e PYTHONDONTWRITEBYTECODE=1 -w /repo \
            "$IMAGE" "$PY" -m pair_c.run_evaluation "/exp/$name.ini" >"$log" 2>&1
        status=$?
        if [ "$status" -eq 124 ]; then echo "[$(date -Is)] $name exceeded ${LIMIT}s; removing container" >&2; docker rm -f "fow-$name" >/dev/null 2>&1; fi
        echo "[$(date -Is)] $name exit=$status elapsed=$(( $(date +%s) - start ))s"
        if [ -f "$out/summary.json" ]; then touch "$LOGS/$name.done"; fi
    done
done
echo "[$(date -Is)] network arm: all chunks attempted"
