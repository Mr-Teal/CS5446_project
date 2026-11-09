#!/bin/bash
# Start Fog Lab on the VM with the GPU, so the network scorers (Network 1, belief network, belief network v2) can
# run at speed inside Pair A's subgame bot. Same as experiment/foglab_up.sh otherwise: the portability image,
# host network, serves on 127.0.0.1:$PORT. From the laptop, with the WireGuard tunnel up:
#   ssh -N -L 8765:127.0.0.1:8777 homelab      then open http://127.0.0.1:8765
# In the New game panel choose bot "Pair A subgame agent" and scorer "Belief network v2 (solver labels, engine-free)".
# Stop with:  docker kill fow-lab
# Memory cap 4500m: the tail guard (96,000 states) was sized for 4.5 GB; one arm container (8000m) may run alongside.
set -u
W=${W:-/home/dev/cs5446-review/wt-net}
PORT=${PORT:-8777}
PY=/home/dev/fow-chess/.venv/bin/python
docker rm -f fow-lab >/dev/null 2>&1 || true
docker run -d --name fow-lab --gpus all --memory=4500m --memory-swap=4500m --network host \
  --user 1000:1000 -e HOME=/tmp -e USER=dev -e LOGNAME=dev -e TORCHINDUCTOR_CACHE_DIR=/tmp/inductor \
  -v "$W":/repo -v /usr/games/stockfish:/usr/games/stockfish:ro \
  -v /home/dev/fow-chess/.venv:/home/dev/fow-chess/.venv:ro \
  -v /home/dev/.local/share/uv/python:/home/dev/.local/share/uv/python:ro \
  -e PYTHONPATH=/repo:/repo/pair_b/src -e PYTHONDONTWRITEBYTECODE=1 -e PATH=/usr/local/bin:/usr/bin:/bin:/usr/games \
  -w /repo/pair_b fow-portability:probe "$PY" -m pairb.lab --port "$PORT" --device cuda --stockfish /usr/games/stockfish >/dev/null
sleep 4
docker logs fow-lab 2>&1 | tail -n 3
