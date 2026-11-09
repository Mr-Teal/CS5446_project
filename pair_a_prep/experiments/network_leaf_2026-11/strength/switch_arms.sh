#!/bin/bash
# Switch the running strength-arm driver to a new ARMS set without losing finished chunks (VM side).
# usage: ARMS="netv2-fe-s16 netv2-vs-fe-guard-s16" switch_arms.sh [limit seconds, default 10800]
# Stops the driver loop (exact pid), lets its current container finish or be cut under its own timeout, marks
# every chunk that has a summary.json as done, then relaunches run_arm_gpu.sh with the new ARMS (done chunks skip).
set -u
E=/home/dev/cs5446-review/experiment
L=$E/logs-netv2
LIMIT=${1:-10800}
: "${ARMS:?set ARMS}"
log() { echo "[$(date -u +%FT%TZ)] $*"; }
for p in $(pgrep -f "^bash ./run_arm_gpu.sh"); do kill "$p" && log "stopped driver pid $p"; done
while docker ps --format '{{.Names}}' | grep -q '^fow-'; do sleep 20; done
log "no fow- container running"
for s in /home/dev/cs5446-review/wt-net/pair_c/runs/strength-netv2-*-c*/summary.json; do
    [ -f "$s" ] || continue
    n=$(basename "$(dirname "$s")"); n=${n#strength-}
    [ -f "$L/$n.done" ] || { touch "$L/$n.done"; log "marked $n done"; }
done
cd "$E" && LOGS=$L LIMIT=$LIMIT ARMS="$ARMS" CHUNKS="$(seq 1 50)" \
    nohup setsid ./run_arm_gpu.sh >> "$L/driver.log" 2>&1 < /dev/null &
sleep 3
log "driver relaunched: ARMS=\"$ARMS\" LIMIT=$LIMIT"
