#!/bin/bash
# Start Fog Lab with Pair A's bot available, from the wt-final worktree, in the portability image.
# Serves on the VM's 127.0.0.1:$PORT (default 8777) (container shares the host network). From the laptop, with the
# WireGuard tunnel up:   ssh -N -L 8765:127.0.0.1:8777 homelab   then open http://127.0.0.1:8765
# Stop with:  sudo docker kill fow-lab
set -u
W=${W:-/home/dev/cs5446-review/wt-final}
PORT=${PORT:-8777}  # 8765 is taken on the VM by another service
sudo docker rm -f fow-lab >/dev/null 2>&1 || true
sudo docker run -d --name fow-lab --memory=3000m --network host \
  -v "$W":/repo -v /usr/games/stockfish:/usr/games/stockfish:ro \
  -e PYTHONPATH=/repo:/repo/pair_b/src -e PATH=/usr/local/bin:/usr/bin:/bin:/usr/games \
  -w /repo/pair_b fow-portability:probe python -m pairb.lab --port "$PORT" >/dev/null
sleep 3
sudo docker logs fow-lab 2>&1 | tail -n 2
