"""Whether this host can run the audited ZS21 delivery artifacts.

Two parts of the ZS21 runtime are pinned to one platform on purpose. The process
service must start through `pixi run` (see `protocol.py`) so that every agent
process comes from the locked environment, and `zs21_runtime/pixi.toml` declares
which platforms that lock covers. The batch engine is a prebuilt Stockfish 13
binary whose hash is recorded in the delivery manifests, so it cannot be
substituted without changing what was audited.

Callers use these checks to skip a path explicitly rather than fail opaquely.
Neither check is a fallback: when one returns False the audited artifact is
genuinely unavailable here, and any substitute would not be the same artifact.
"""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import sys
import tomllib

_CONDA_PLATFORM = {"win32": "win-64", "darwin": "osx-64", "linux": "linux-64"}


def _repository() -> Path:
    return Path(__file__).resolve().parents[2]


def conda_platform() -> str | None:
    """This host as a conda platform string, or None if pixi would not know it."""
    if sys.platform == "darwin":
        import platform
        return "osx-arm64" if platform.machine() == "arm64" else "osx-64"
    return _CONDA_PLATFORM.get(sys.platform)


def locked_runtime_available() -> tuple[bool, str]:
    """True when `pixi run -e darkchess` can resolve on this host, with the reason."""
    manifest = _repository() / "zs21_runtime/pixi.toml"
    if not manifest.is_file():
        return False, f"missing {manifest}"
    if shutil.which("pixi") is None:
        return False, "pixi is not on PATH"
    try:
        declared = tomllib.loads(manifest.read_text(encoding="utf-8"))["workspace"]["platforms"]
    except (KeyError, tomllib.TOMLDecodeError) as exc:
        return False, f"cannot read platforms from pixi.toml: {exc}"
    current = conda_platform()
    if current not in declared:
        return False, f"pixi.toml locks platforms {declared}; this host is {current}"
    return True, f"locked runtime covers {current}"


def audited_engine_available() -> tuple[bool, str]:
    """True when the engine named by the runtime config is present, with the reason."""
    try:
        from .config import load
        engine = Path(load()["engine"])
    except Exception as exc:  # a missing or unreadable config is the same answer here
        return False, f"cannot read the runtime config: {type(exc).__name__}: {exc}"
    if not engine.is_file():
        return False, f"audited engine not present on this host: {engine}"
    if engine.suffix.lower() == ".exe" and sys.platform != "win32":
        return False, f"audited engine is a Windows binary: {engine.name}"
    if not os.access(engine, os.X_OK):
        return False, f"audited engine is not executable here: {engine}"
    return True, f"audited engine present: {engine}"
