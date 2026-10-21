"""Which data files, checkpoint and code a result came from, by SHA-256 (review T9).

The linear baseline's reports set the standard; the network scripts write the same fields.
"""
import hashlib
import json
import platform
import subprocess
from pathlib import Path

import chess
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PARTS = "part-*.jsonl"  # the record files of a dataset folder
MANIFEST_FIELDS = ("code_sha256", "seed", "created", "command", "stockfish")  # how the data were made


def sha256_of(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def data_files(folder, pattern: str = PARTS) -> dict:
    """The SHA-256 of each record file (`pattern`) and of manifest.json in a dataset folder, and
    of the lot. A pattern other than the default is recorded with them."""
    folder = Path(folder)
    files = sorted(folder.glob(pattern))
    if not files:
        raise ValueError(f"no {pattern} records found")
    manifest = folder / "manifest.json"
    if manifest.exists():
        files.append(manifest)
    hashes = {p.name: sha256_of(p) for p in files}
    out = {"dataset": folder.name, "files_sha256": hashes,
           "sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()}
    if pattern != PARTS:
        out["pattern"] = pattern
    return out


def _portable(value):
    """`value` with the home folder written as ~, so a committed report names no local user."""
    if isinstance(value, str):
        return value.replace(str(Path.home()), "~")
    if isinstance(value, list):
        return [_portable(v) for v in value]
    if isinstance(value, dict):
        return {k: _portable(v) for k, v in value.items()}
    return value


def data_source(folder, pattern: str = PARTS) -> dict:
    """data_files, plus the manifest's record of how the data were made ({} without a manifest),
    with the home folder written as ~ (the manifest's own SHA-256 still pins its bytes)."""
    manifest = Path(folder) / "manifest.json"
    made = json.loads(manifest.read_text()) if manifest.exists() else {}
    return {**data_files(folder, pattern), "manifest": {k: _portable(made[k]) for k in MANIFEST_FIELDS if k in made}}


def git_commit() -> str | None:
    """HEAD of the checkout this code runs from, or None outside git or without git."""
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def runtime() -> dict:
    paths = sorted([*ROOT.glob("src/pairb/*.py"), *ROOT.glob("scripts/*.py"),
                    *ROOT.parent.glob("fow_shared/*.py")])
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(ROOT.parent)).encode())
        digest.update(path.read_bytes())
    return {"python": platform.python_version(), "platform": platform.platform(),
            "numpy": np.__version__, "python_chess": chess.__version__,
            "source_sha256": digest.hexdigest()}
