#!/usr/bin/env bash
# Launch the two v2-network-leaf strength arms on the VM (runs there as experiment/launch_netv2_arms.sh).
# usage: launch_netv2_arms.sh [run name, default belief-solver-v2-sf8] [chunks, default 50]
# 1. copies labels/runs/<run>/best.pt into wt-net/pair_b/checkpoints/<run>/best.pt (never committed),
# 2. writes the ini files (make_netv2_inis.py),
# 3. starts run_arm_gpu.sh detached with ARMS="netv2-fe-s16 netv2-vs-fe-s16", interleaved by chunk, logs in
#    experiment/logs-netv2/, driver log experiment/logs-netv2/driver.log.
# One 8000m GPU container at a time (the VM has 15 GB); do not start it while a training container runs.
set -u
RUN=${1:-belief-solver-v2-sf8}
CHUNKS=${2:-50}
R=/home/dev/cs5446-review
EXP=$R/experiment
SRC=$R/labels/runs/$RUN/best.pt
DST=$R/wt-net/pair_b/checkpoints/$RUN/best.pt
[ -f "$SRC" ] || { echo "no checkpoint at $SRC"; exit 1; }
if docker ps --format '{{.Names}}' | grep -q '^fow-'; then echo "a fow- container is already running; refusing to start"; docker ps --format '{{.Names}} {{.Status}}' | grep '^fow-'; exit 1; fi
mkdir -p "$(dirname "$DST")" && cp "$SRC" "$DST" && echo "checkpoint $(sha256sum "$DST" | cut -c1-16) -> $DST"
python3 "$EXP/make_netv2_inis.py" "$EXP" "/repo/pair_b/checkpoints/$RUN/best.pt" "$CHUNKS" || exit 1
mkdir -p "$EXP/logs-netv2"
# LIMIT 3600: the smoke chunk took 1746 s because one game ran to the 200-ply cap and the exact tracker spent
# 1037 s on it; earlier net-arm chunks were median 343 s, p90 602 s, max 1504 s. The head-to-head arm searches on
# both sides, so a 2-game chunk can exceed the old 1800 s. run_arm_gpu.sh reads LIMIT from the environment.
cd "$EXP" && LOGS=$EXP/logs-netv2 LIMIT=${LIMIT:-3600} ARMS="netv2-fe-s16 netv2-vs-fe-s16" CHUNKS="$(seq 1 "$CHUNKS")" \
    nohup setsid ./run_arm_gpu.sh >> "$EXP/logs-netv2/driver.log" 2>&1 < /dev/null &
sleep 3
echo "started; driver pid $! ; tail of driver.log:"; tail -3 "$EXP/logs-netv2/driver.log"
