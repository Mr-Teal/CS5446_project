"""Check the shipped runtime, native rule ABI and the real Stockfish workers."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys

RUNTIME = Path(__file__).resolve().parents[1]
ROOT = RUNTIME.parent
sys.path.insert(0, str(ROOT))

import chess
import numpy
import scipy
from pair_a_prep.zs21.config import load
from pair_a_prep.zs21.engine import EnginePool
from pair_a_prep.zs21.native_tracker import library
from pair_a_prep.zs21.rule_profile import RULES_ID


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=RUNTIME / "out/doctor.json")
    args = parser.parse_args()
    if platform.system() != "Windows" or sys.maxsize <= 2**32:
        raise RuntimeError("this release is validated on 64-bit Windows; see the portability notes")
    runtime = load()
    assets = json.loads((RUNTIME / "assets.manifest.json").read_text(encoding="utf-8"))
    mismatches = [name for name, sha in assets["files"].items()
                  if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != sha]
    if mismatches:
        raise RuntimeError("shipped assets changed; rebuild and record a new version: " + ", ".join(mismatches))
    native_rules = library().zs_rules_id().decode("ascii")
    assert native_rules == RULES_ID
    with EnginePool(runtime["engine"]) as pool:
        evaluations = pool.evaluate([chess.Board()], "white", depth=1)
        assert pool.metadata["workers"] == 4 and pool.metadata["threads"] == 1
        assert all(engine.supports_batch for engine in pool.engines)
        report = dict(status="passed", rules_id=RULES_ID, assets_verified=len(assets["files"]),
                      python=platform.python_version(), numpy=numpy.__version__, scipy=scipy.__version__,
                      python_chess=chess.__version__, engine=pool.metadata["identity"],
                      workers=4, threads_per_worker=1, transport=pool.metadata["transport"],
                      engine_sha256=hashlib.sha256(Path(runtime["engine"]).read_bytes()).hexdigest(),
                      initial_value=evaluations[0].value)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
