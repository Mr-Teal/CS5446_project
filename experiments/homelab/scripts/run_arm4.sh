#!/usr/bin/env bash
# Run the three strength arms, interleaved by chunk.
#
# Interleaved rather than arm-by-arm so that stopping early still leaves the arms
# balanced on identical seeds: after chunk N every arm has played the same 20*N
# games from the same seeds, which is what makes the comparison paired.
#
# Sequential by design. One exact game reached 4.27 GiB and the VM has 15 GB with
# no swap and roughly 8 GB held by unrelated processes, so two of these at once is
# not safe and even one needs a cap well under what is free. Each chunk is a
# separate container with a hard --memory cap, so an out-of-memory kill takes at
# most five games, not the host.
set -u

REPO=/home/dev/cs5446-review/wt-pr2
EXP=/home/dev/cs5446-review/experiment
LOGS=$EXP/logs
IMAGE=fow-portability:probe
MEM=4500m
mkdir -p "$LOGS"

ARMS="pruned-s256"
CHUNKS="$(seq 1 50)"

for chunk in $CHUNKS; do
    for arm in $ARMS; do
        name="$arm-c$chunk"
        log="$LOGS/$name.log"
        if [ -f "$LOGS/$name.done" ]; then
            echo "[$(date -Is)] $name already done, skipping"
            continue
        fi
        echo "[$(date -Is)] starting $name"
        docker run --rm --memory=$MEM --memory-swap=$MEM \
            -v "$REPO":/repo -v "$EXP":/exp \
            -e PYTHONPATH=/repo/pair_b/src:/exp -w /repo \
            "$IMAGE" python -m pair_c.run_evaluation "/exp/$name.ini" \
            >"$log" 2>&1
        status=$?
        echo "[$(date -Is)] $name exit=$status"
        # Exit 1 means some games failed, which is a result, but so does a config
        # error that played nothing. Mark done only when the runner actually
        # reported results, so a bad chunk is retried rather than silently skipped.
        if grep -q "^Results:" "$log"; then
            touch "$LOGS/$name.done"
        else
            echo "[$(date -Is)] $name produced no results (exit $status); not marking done" >&2
        fi
        tail -3 "$log" | sed "s/^/    /"
    done
done

echo "[$(date -Is)] all chunks attempted"
