#!/usr/bin/env bash
# Start the mechanism arms in two lanes once the clock driver has exited.
#
# Lane A (4500m): guard-fe-s16. The tail guard bounds the belief, so this arm is
#   the one that can live in the smaller container; its configs were generated
#   with GUARD_MAX_STATES=96000 for exactly this cap (verification log item 20).
# Lane B (8000m): sf14-fe-s16, then fe-s16, then fe-s64, then fe-s256, one arm
#   at a time so complete arms land early. These carry the exact belief and need
#   the larger cap; they can still be killed on long games, as every exact arm is.
#
# 4500m + 8000m = 12.5 GB of caps on a 15.9 GB host whose other work (Gemma, VS
# Code) was stopped for this run; the host keeps about 1.5 GB plus 8 GB of swap.
# Both lanes use run_arms4.sh, so markers live in logs4/ and the code is wt-dev
# at the commit the driver prints. Each lane logs to logs4/lane-{A,B}.driver.log.
set -u

EXP=/home/dev/cs5446-review/experiment
CLOCK_PID=${CLOCK_PID:-2781115}
cd "$EXP"
mkdir -p logs4

echo "[$(date -Is)] waiting for the clock driver (pid $CLOCK_PID) to exit"
while kill -0 "$CLOCK_PID" 2>/dev/null; do
    sleep 60
done
echo "[$(date -Is)] clock driver gone; starting lanes"

ARMS=guard-fe-s16 MEM=4500m ./run_arms4.sh > logs4/lane-A.driver.log 2>&1 &
LANE_A=$!
(
    for arm in sf14-fe-s16 fe-s16 fe-s64 fe-s256; do
        ARMS=$arm MEM=8000m ./run_arms4.sh
    done
) > logs4/lane-B.driver.log 2>&1 &
LANE_B=$!
echo "[$(date -Is)] lane A pid $LANE_A (guard-fe-s16 @4500m), lane B pid $LANE_B (sf14 -> fe-s16 -> fe-s64 -> fe-s256 @8000m)"
wait "$LANE_A" "$LANE_B"
echo "[$(date -Is)] both lanes finished"
