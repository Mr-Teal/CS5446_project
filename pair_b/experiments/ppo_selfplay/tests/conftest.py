"""Run these tests with the team repository on PYTHONPATH, as in pair_b/docs/handover_ppo_agent_2026-11-15.md, section 5:

    export PYTHONPATH=$REPO:$REPO/pair_b/src:$PKG/player
    python -m pytest -q $PKG/tests
"""
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / "player"))

try:
    import fow_shared.evaluation  # noqa: F401
    import pairb.rules  # noqa: F401
except ImportError as error:
    raise RuntimeError("the team repository and its pair_b/src are not on PYTHONPATH; see pair_b/docs/handover_ppo_agent_2026-11-15.md, section 5") from error
