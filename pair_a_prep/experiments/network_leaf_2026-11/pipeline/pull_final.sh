#!/bin/bash
# Laptop side of the final round: Atlas -> laptop -> VM, then start tools/final_chain.sh on the VM (detached).
# usage: pull_final.sh [name] ; assumes the wg_peer17 tunnel is already Connected (the caller restores it).
set -u
NAME=${1:-solver-v2-sf8}
D=/private/tmp/claude-501/-Users-tommy2131-Desktop-school-doc-NUS/9a179d7b-673c-4a9a-bd4f-fbcb26bb4543/scratchpad
ATLAS="ssh -o ConnectTimeout=20 -o HostName=172.25.195.51 -o HostKeyAlias=atlas8.nus.edu.sg"
mkdir -p "$D/labels-sf8-final/atlas"
echo "[$(date -Is)] pull Atlas -> laptop"
rsync -a --timeout=60 -e "$ATLAS" --include='task-*/' --include='part-*.jsonl' --include='progress.jsonl' --include='manifest.json' --exclude='*' \
    atlas:/hpctmp/tommy.21.31/fow/repo-exp/pair_c/runs/labels-sf8/ "$D/labels-sf8-final/atlas/" || exit 1
python3 -I "$D/deploy/filter_complete.py" "$D/labels-sf8-final/atlas" "$D/labels-sf8-final/push" || exit 1
echo "[$(date -Is)] push laptop -> VM atlas-labels-sf8"
ssh -o ConnectTimeout=20 homelab 'rm -rf /home/dev/cs5446-review/labels/atlas-labels-sf8'
rsync -a --timeout=120 -e "ssh -o ConnectTimeout=20" "$D/labels-sf8-final/push/" homelab:/home/dev/cs5446-review/labels/atlas-labels-sf8/ || exit 1
echo "[$(date -Is)] start final_chain.sh on the VM"
ssh -o ConnectTimeout=20 homelab "cd /home/dev/cs5446-review/labels && ls atlas-labels-sf8/task-*/part-*.jsonl | wc -l && nohup setsid tools/final_chain.sh $NAME atlas-labels-sf8 > runs/final_chain_$NAME.log 2>&1 < /dev/null & sleep 2; echo started"
