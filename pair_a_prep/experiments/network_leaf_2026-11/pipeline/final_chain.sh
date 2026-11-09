#!/bin/bash
# Final-round training on the VM (runs there; deployed to /home/dev/cs5446-review/labels/tools/final_chain.sh).
# usage: final_chain.sh [dataset name] [source folder]   e.g. final_chain.sh solver-v2-sf8 atlas-labels-sf8
# merge -> validate -> baselines (material / SF-d1 / SF-d8 / zero on val) -> train plain recipe -> eval on val.
# The residual-over-SF-d1 arm (--use-d1) was dropped on 2026-11-09 23:30 by the user's decision: the leaf
# must not need an engine call at play time. Never touches the test split.
set -u
NAME=${1:-solver-v2-sf8}
SRC=${2:-atlas-labels-sf8}
cd /home/dev/cs5446-review/labels
export PYTHONPATH=/home/dev/cs5446-review/wt-net:/home/dev/cs5446-review/wt-net/pair_b/src
P=/home/dev/fow-chess/.venv/bin/python
T=tools/torch.sh
log() { echo "[$(date -Is)] $*"; }

log "merge $SRC -> $NAME"
python3 tools/merge_labels.py "$PWD/$NAME" "$PWD/$SRC"/task-* | tail -3 || { log "merge failed"; exit 1; }
log "validate"
$T pair_b/scripts/validate_labels.py "/labels/$NAME" --require-played-policy | tail -2
log "baselines on val"
$P tools/baseline_leaf.py "$PWD/$NAME" val --stockfish /usr/games/stockfish --depths 1,8
log "train plain recipe -> runs/belief-$NAME"
$T pair_b/scripts/train_belief_net.py --data "/labels/$NAME" --out "/labels/runs/belief-$NAME" --device cuda --workers 6 --cache-dir /labels/cache | tail -2
log "eval on val"
run="belief-$NAME"
$T pair_b/scripts/eval_belief_net.py --run "/labels/runs/$run" --data "/labels/$NAME" --split val --device cuda --workers 6 --cache-dir /labels/cache > /dev/null 2>&1
python3 - "$run" "$NAME" <<'EOF'
import json, sys, glob
run, data = sys.argv[1], sys.argv[2]
for f in glob.glob(f"runs/{run}/eval-{data}-val.json"):
    d = json.load(open(f))
    net = d.get("network", d)
    print(run, "val:", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in net.items() if isinstance(v, (int, float))})
EOF
log "chain done"
