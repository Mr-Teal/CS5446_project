#!/bin/bash
# GPU torch container (PLAN.md section 2). Usage: torch.sh <python args...>
exec docker run --rm --gpus all --memory=4000m --memory-swap=4000m --user 1000:1000 -e HOME=/tmp \
  -e USER=dev -e LOGNAME=dev -e TORCHINDUCTOR_CACHE_DIR=/tmp/inductor \
  -v /home/dev/fow-chess/.venv:/home/dev/fow-chess/.venv:ro \
  -v /home/dev/.local/share/uv/python:/home/dev/.local/share/uv/python:ro \
  -v /home/dev/cs5446-review/wt-net:/repo -v /home/dev/cs5446-review/labels:/labels \
  -v /home/dev/cs5446-review/wt-labels/pair_c/runs:/homelab-runs:ro \
  -w /repo -e PYTHONPATH=/repo:/repo/pair_b/src -e PYTHONDONTWRITEBYTECODE=1 \
  fow-portability:probe /home/dev/fow-chess/.venv/bin/python "$@"
