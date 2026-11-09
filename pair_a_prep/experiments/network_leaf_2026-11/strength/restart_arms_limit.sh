#!/bin/bash
# Raise the per-chunk time limit of the running strength arms without losing finished chunks (VM side).
# Why: the head-to-head arm (both sides search 5 s/move with exact trackers) needs ~65 min per 2-game chunk; the
# 3600 s limit set at launch would cut most of them. usage: restart_arms_limit.sh [new limit seconds, default 10800]
set -u
E=/home/dev/cs5446-review/experiment
L=$E/logs-netv2
NEWLIMIT=${1:-10800}
log() { echo "[$(date -u +%FT%TZ)] $*"; }
# 1. pause the generalisation sweep: it starts training as soon as it sees no driver and no container
for p in $(pgrep -f "^/bin/bash tools/gen_sweep.sh"); do kill "$p" && log "paused gen_sweep pid $p"; done
# 2. stop the driver loop only (exact pid); its current container keeps running under its own timeout
for p in $(pgrep -f "^bash ./run_arm_gpu.sh"); do kill "$p" && log "stopped driver pid $p"; done
# 3. wait for that container to finish or be cut
while docker ps --format '{{.Names}}' | grep -q '^fow-'; do sleep 20; done
log "no fow- container running"
# 4. a chunk whose summary exists is done even if the driver died before writing its marker
for s in /home/dev/cs5446-review/wt-net/pair_c/runs/strength-netv2-*-c*/summary.json; do
    [ -f "$s" ] || continue
    n=$(basename "$(dirname "$s")"); n=${n#strength-}
    [ -f "$L/$n.done" ] || { touch "$L/$n.done"; log "marked $n done"; }
done
# 5. relaunch the same two arms, interleaved, with the new limit (done chunks are skipped)
cd "$E" && LOGS=$L LIMIT=$NEWLIMIT ARMS="netv2-fe-s16 netv2-vs-fe-s16" CHUNKS="$(seq 1 50)" \
    nohup setsid ./run_arm_gpu.sh >> "$L/driver.log" 2>&1 < /dev/null &
sleep 3
log "driver relaunched with LIMIT=$NEWLIMIT"
# 6. resume the sweep (it waits again for the arms to finish)
cd /home/dev/cs5446-review/labels && nohup setsid tools/gen_sweep.sh solver-v2-sf8 >> runs/gen_sweep_solver-v2-sf8.log 2>&1 < /dev/null &
log "gen_sweep resumed"
