"""Lets the tests use the team repository's shared rules fixtures (pair_a_prep), next to pair_b."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if (ROOT / "pair_a_prep").is_dir() and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
