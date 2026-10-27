"""Portable source snapshots for engineering evidence, independent of checkout EOLs."""

from hashlib import sha256
from pathlib import Path
import subprocess

REPOSITORY = Path(__file__).resolve().parents[1]
NORMALIZATION = "sha256_utf8_source_bytes_crlf_to_lf_v1"


def normalized_sha256(data):
    return sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def source_manifest(extra=(), root=REPOSITORY):
    """Hash runtime Python sources, including shared adjudication and leaf scoring.

    Paths are repository relative. Tests, local environments and cached artifacts
    are excluded. This describes tested working bytes, including uncommitted edits;
    git revision alone never substitutes for this manifest.
    """
    root = Path(root)
    paths = set()
    for directory in ("fow_shared", "pair_a_prep", "pair_b/src/pairb"):
        for path in (root / directory).rglob("*.py"):
            relative = path.relative_to(root)
            if any(part in {"tests", "local_runs", ".venv", ".pixi", "__pycache__"}
                   for part in relative.parts):
                continue
            paths.add(relative.as_posix())
    paths.update(extra)
    return {name: normalized_sha256((root / name).read_bytes()) for name in sorted(paths)}


def git_revision(root=REPOSITORY):
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                              check=True, text=True, capture_output=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


ARTIFACT_HASH_CONVENTION = "sha256_utf8_artifact_bytes_crlf_to_lf_v1"


def artifact_sha256(data):
    """Hash serialized UTF-8 evidence bytes with CRLF normalized to LF.

    Whitespace, JSON key order and all other bytes remain significant. This is
    not semantic JSON hashing; it only removes Git checkout newline conversion.
    """
    return normalized_sha256(data)
