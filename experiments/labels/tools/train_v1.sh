#!/bin/bash
cd /home/dev/cs5446-review/labels
T=tools/torch.sh
echo "[$(date -Is)] train belief-solver-v1"
$T pair_b/scripts/train_belief_net.py --data /labels/solver-v1 --out /labels/runs/belief-solver-v1 --device cuda --workers 6 --cache-dir /labels/cache
echo "[$(date -Is)] exit=$?"
echo "[$(date -Is)] train belief-solver-v1-noctx"
$T pair_b/scripts/train_belief_net.py --data /labels/solver-v1 --out /labels/runs/belief-solver-v1-noctx --device cuda --workers 6 --cache-dir /labels/cache --no-context
echo "[$(date -Is)] exit=$?"
