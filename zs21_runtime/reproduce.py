"""Portable entry point; Python is launched by the locked Pixi environment."""
from pathlib import Path
import os
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
commands = {"play": "ui", "evaluate": "match", "replay": "replay",
            "small-games": "validation", "serve": "serve"}
if len(sys.argv) < 2 or sys.argv[1] not in (*commands, "test"):
    raise SystemExit("Usage: reproduce.py {play|evaluate|replay|small-games|serve|test} [options]")
command, arguments = sys.argv[1], sys.argv[2:]
if command == "test":
    import pytest
    (ROOT / "zs21_runtime/out").mkdir(parents=True, exist_ok=True)
    raise SystemExit(pytest.main(["-q", "tests", "pair_a_prep/tests", *arguments]))
if command == "play" and "--engine" not in arguments:
    from pair_a_prep.zs21.config import load
    arguments += ["--engine", load()["engine"]]
sys.argv = [f"pair_a_prep.zs21.{commands[command]}", *arguments]
runpy.run_module(sys.argv[0], run_name="__main__")
