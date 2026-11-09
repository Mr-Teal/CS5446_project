#!/bin/bash
# State-representation ablation ladder on one solver-label dataset (runs on the VM as tools/ablation_chain.sh).
# usage: ablation_chain.sh [dataset name]        e.g. ablation_chain.sh solver-v2-sf8-g237
# Trains, with the v1 recipe and the context head off so the three share one architecture (545,297 params):
#   observation : one pseudo-board per belief, fogged observation only ("pure fog", no belief, no sampling)
#   marginals   : one pseudo-board per belief, observation + belief-tracker marginals (no sampled boards)
#   full        : every sampled hypothesis board, context head off (isolates the context head vs the full run)
# The full network WITH context is the main run runs/belief-<dataset> (trained by final_chain.sh).
# Then evaluates each on the validation split. Never touches the test split.
set -u
NAME=${1:-solver-v2-sf8-g237}
cd /home/dev/cs5446-review/labels
T=tools/torch.sh
log() { echo "[$(date -u +%FT%TZ)] $*"; }
for mode in observation marginals full; do
    out="runs/belief-$NAME-$mode-noctx"
    if [ -e "$out" ]; then log "$out exists, skipping"; continue; fi
    log "train --input $mode --no-context -> $out"
    $T pair_b/scripts/train_belief_net.py --data "/labels/$NAME" --out "/labels/$out" --input "$mode" --no-context \
        --device cuda --workers 6 --cache-dir /labels/cache | tail -2
    log "eval $out on val"
    $T pair_b/scripts/eval_belief_net.py --run "/labels/$out" --data "/labels/$NAME" --split val --device cuda --workers 6 --cache-dir /labels/cache > /dev/null 2>&1
    python3 - "$out" "$NAME" <<'EOF'
import json, sys
out, name = sys.argv[1], sys.argv[2]
d = json.load(open(f"{out}/eval-{name}-val.json"))
print(out.split("/")[-1], d["input"], {k: v for k, v in d["network"].items()})
EOF
done
log "ablation chain done"
