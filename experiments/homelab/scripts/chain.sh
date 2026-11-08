#!/usr/bin/env bash
# Start arm 4 as soon as the three-arm driver reports it has attempted everything,
# so the host is never idle and never running two of these at once.
set -u
LOGS=/home/dev/cs5446-review/experiment/logs
while ! grep -q "all chunks attempted" "$LOGS/driver.log" 2>/dev/null; do
    sleep 60
done
echo "[$(date -Is)] three-arm driver finished; starting arm 4"
cd /home/dev/cs5446-review/experiment && ./run_arm4.sh
echo "[$(date -Is)] arm 4 finished"
