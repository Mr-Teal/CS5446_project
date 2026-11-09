#!/bin/bash
# Generalisation sweep for the plain (engine-free) belief network, approved by the user 2026-11-10 ~02:20.
# Runs on the VM as tools/gen_sweep.sh. WAITS until no strength-arm driver (run_arm_gpu.sh) and no fow- container
# is running, because the VM (15 GB) takes one 8000m container at a time. Then trains, 3 seeds each, ~3 min a run:
#   base      v1 recipe (lr 2e-3, wd 1e-4, 6 blocks x 64 channels)      -> run-to-run spread of the recipe itself
#   wd1e-3    weight decay x10
#   small     3 blocks x 32 channels (about a quarter of the parameters)
#   lr1e-3    half the learning rate
# Epoch selection on position error can be read post hoc from metrics.jsonl (the trainer selects on board MSE).
# Evaluates every run on the validation split only. Never touches the test split.
set -u
NAME=${1:-solver-v2-sf8}
cd /home/dev/cs5446-review/labels
T=tools/torch.sh
log() { echo "[$(date -u +%FT%TZ)] $*"; }
log "waiting for the strength arms to finish"
while ps -eo args | grep -q "[.]/run_arm_gpu.sh" || docker ps --format '{{.Names}}' | grep -q '^fow-'; do sleep 300; done
log "arms finished; starting the sweep on $NAME"
for seed in 0 1 2; do
  for variant in base wd1e-3 small lr1e-3; do
    out="runs/gen-$NAME-$variant-s$seed"
    [ -e "$out" ] && { log "$out exists, skipping"; continue; }
    extra=""
    case $variant in
      wd1e-3) extra="--weight-decay 1e-3" ;;
      small)  extra="--blocks 3 --channels 32" ;;
      lr1e-3) extra="--lr 1e-3" ;;
    esac
    log "train $variant seed $seed -> $out"
    $T pair_b/scripts/train_belief_net.py --data "/labels/$NAME" --out "/labels/$out" --seed "$seed" $extra \
        --device cuda --workers 6 --cache-dir /labels/cache | tail -1
    $T pair_b/scripts/eval_belief_net.py --run "/labels/$out" --data "/labels/$NAME" --split val --device cuda --workers 6 --cache-dir /labels/cache > /dev/null 2>&1
    python3 - "$out" "$NAME" <<'EOF'
import json, sys
out, name = sys.argv[1], sys.argv[2]
d = json.load(open(f"{out}/eval-{name}-val.json"))["network"]
rows = [json.loads(l) for l in open(f"{out}/metrics.jsonl")]
best_pos = min(rows, key=lambda r: r["val"]["root_mae"])
print(out.split("/")[-1], "val board", d["board_mae"], "position", d["root_mae"], "| best-by-position epoch", best_pos["epoch"], "position", round(best_pos["val"]["root_mae"], 4), "| epochs", len(rows))
EOF
  done
done
log "gen sweep done"
