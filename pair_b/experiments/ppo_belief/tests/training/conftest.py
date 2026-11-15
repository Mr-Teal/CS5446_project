"""The 27 tests of the belief sampler and the training code (sampler, environment, PPO targets,
long-run features, agent, guard).

Run them like the other tests, with the team repository on PYTHONPATH (fow_shared and pairb come
from there) and the belief sampler built:

    export PYTHONPATH=$REPO:$REPO/pair_b/src:$PKG/player
    python -m pytest -q $PKG/tests/training

`$PKG/player` must be on PYTHONPATH itself (not only on sys.path here), because one test starts
worker processes that import fowppo_belief.
"""
import sys
from pathlib import Path

PLAYER = Path(__file__).resolve().parents[2] / "player"
if str(PLAYER) not in sys.path:
    sys.path.insert(0, str(PLAYER))
