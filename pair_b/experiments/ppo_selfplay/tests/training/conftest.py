"""The 21 tests of the training code (environment, PPO targets, long-run features, agent, guard).

Run them like the other tests, with the team repository on PYTHONPATH (fow_shared comes from there):

    export PYTHONPATH=$REPO:$REPO/pair_b/src:$PKG/player
    python -m pytest -q $PKG/tests/training

`$PKG/player` must be on PYTHONPATH itself (not only on sys.path here), because one test starts
worker processes that import fowppo.
"""
import sys
from pathlib import Path

PLAYER = Path(__file__).resolve().parents[2] / "player"
if str(PLAYER) not in sys.path:
    sys.path.insert(0, str(PLAYER))
