#!/usr/bin/env bash
# Run the two clock arms, interleaved by chunk.
#
# Interleaved so that stopping at any point leaves both arms on the same seeds,
# which is what makes the comparison paired. Sequential within a chunk: one exact
# game has reached 4.27 GiB, the VM has 15.9 GB with no swap and about 8.5 GB held
# by unrelated work, so two 4.5 GiB containers at once is not safe.
#
# These arms spend about 4.1 s of search per Pair A move against the baseline's
# 0.4 s, so a chunk costs roughly ten times what the first round cost. The elapsed
# time per chunk is logged so the run can be cut short on evidence rather than

# MEMORY REGIME CHANGE, 2026-11-03, at the user's instruction.
# logs/REGIME-4500m.txt lists the 152 chunks already completed under MEM=4500m
# (both clock arms plus the round-1 exact/pruned arms). EVERYTHING NOT IN THAT
# FILE runs at 8000m -- including retries of failed chunks numbered below 32,
# because the loop reruns any chunk lacking a .done marker. So the regime split is
# per chunk by that file, NOT by chunk number. The cap rise was made possible by
# stopping the UVF Gemma container (4.47 GiB freed; host available 6.3 -> 10.9 GB).
#
# Note LIMIT below is unchanged at 1800 s. A larger cap lets long games keep
# running, so some chunks that previously died of memory will now be cut off by
# the wall clock instead. Both outcomes must be counted separately.
# guesswork.
set -u

REPO=/home/dev/cs5446-review/wt-pr2
EXP=/home/dev/cs5446-review/experiment
LOGS=$EXP/logs
IMAGE=fow-portability:probe
MEM=8000m
mkdir -p "$LOGS"

ARMS="clock-s16 clock-s64"
CHUNKS="$(seq 1 50)"

# Per-chunk wall clock ceiling. Chunks c1 to c7 took 180 to 675 s, then
# clock-s16-c8 (seed 1015, game 1) ran 4 h 38 m at 103 percent CPU and 2.7 GiB of
# its 4.4 GiB cap without finishing a single game: CPU bound, not memory bound.
# One such seed stalls the whole interleaved run, so a chunk that exceeds this is
# cut off and left unmarked. The cost is one pathological seed; the alternative is
# losing the other ninety-odd games to it.
LIMIT=1800

for chunk in $CHUNKS; do
    for arm in $ARMS; do
        name="$arm-c$chunk"
        log="$LOGS/$name.log"
        if [ -f "$LOGS/$name.done" ]; then
            echo "[$(date -Is)] $name already done, skipping"
            continue
        fi
        # run_evaluation refuses to write into an existing output directory, so a
        # chunk killed by the memory cap or the limit above would fail instantly
        # on every later pass with FileExistsError. Set the directory aside
        # instead of deleting it: a chunk that died during its second game has a
        # first game recorded in games.jsonl, and the "partial-" prefix keeps that
        # out of the analysis glob while leaving it on disk.
        out="$REPO/pair_c/runs/strength-$name"
        if [ -d "$out" ]; then
            mv "$out" "$REPO/pair_c/runs/partial-$name-$(date +%m%d-%H%M)" \
                && echo "[$(date -Is)] $name had a stale output directory; set aside"
        fi
        echo "[$(date -Is)] starting $name"
        start=$(date +%s)
        timeout --signal=TERM --kill-after=60 "$LIMIT" \
            docker run --rm --name "fow-$name" --memory=$MEM --memory-swap=$MEM \
            -v "$REPO":/repo -v "$EXP":/exp \
            -e PYTHONPATH=/repo/pair_b/src:/exp -w /repo \
            "$IMAGE" python -m pair_c.run_evaluation "/exp/$name.ini" \
            >"$log" 2>&1
        status=$?
        # timeout kills the docker client; the container outlives it, so remove it
        # by name rather than leaving it holding 4.5 GiB against the next chunk.
        if [ "$status" -eq 124 ]; then
            echo "[$(date -Is)] $name exceeded ${LIMIT}s; removing container" >&2
            docker rm -f "fow-$name" >/dev/null 2>&1
        fi
        echo "[$(date -Is)] $name exit=$status elapsed=$(( $(date +%s) - start ))s"
        # Exit 1 means games failed, which is a result; a config error that played
        # nothing exits non-zero too. Mark done only when the runner reported
        # results, so a bad chunk is retried rather than silently skipped.
        if grep -q "^Results:" "$log"; then
            touch "$LOGS/$name.done"
        else
            echo "[$(date -Is)] $name produced no results (exit $status); not marking done" >&2
        fi
    done
done

echo "[$(date -Is)] clock arms: all chunks attempted"
