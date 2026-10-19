"""Where things are, for Fog Lab: the team repository's root, the folder the app keeps its files in, and the interpreter
of each environment; and how the app writes a file there so that nobody reads half of it (write_atomically).

The first four are plain functions of their arguments, so the test runner and the start command can use them, and tests
can check them for a Windows layout on any machine. Paths are pathlib's and are passed on as they are, spaces included.
"""
import contextlib
import os
import sys
import tempfile
from pathlib import Path


def repo_root(start: Path | None = None) -> Path:
    """The nearest folder at or above `start` (default: this file) that holds both fow_shared/ and pair_b/: the root of
    the team repository, where Pair A's and Bryan's folders are too. FileNotFoundError when there is none."""
    here = Path(__file__ if start is None else start).resolve()
    for folder in (here, *here.parents):
        if (folder / "fow_shared").is_dir() and (folder / "pair_b").is_dir():
            return folder
    raise FileNotFoundError(f"no folder at or above {here} holds both fow_shared/ and pair_b/")


def ensure_repo_on_path() -> Path:
    """Put the repository's root first on sys.path unless it is there, so that pair_a_prep and pair_b_prep can be
    imported as the tests' conftest.py makes them importable. Returns the root."""
    root = repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def venv_python(project: Path, windows: bool | None = None) -> Path:
    """The interpreter of `project`'s virtual environment: project/.venv/bin/python, or
    project/.venv/Scripts/python.exe on Windows. `windows` None means the machine this runs on (os.name == "nt")."""
    if windows is None:
        windows = os.name == "nt"
    return Path(project, ".venv", *(("Scripts", "python.exe") if windows else ("bin", "python")))


def lab_home(repo: Path) -> Path:
    """The folder where the app keeps saved games and test runs: pair_b/.fog_lab (git-ignored)."""
    return Path(repo) / "pair_b" / ".fog_lab"


def write_atomically(path: Path, text: str) -> None:
    """Write `text` to `path` as UTF-8 so that a reader sees the whole file or none: into a temporary file in the same
    folder (.saving-*.tmp, which the saved games' listing skips), then renamed over the name. The folder must exist.
    Whatever goes wrong, the temporary file is removed and the error passed on."""
    handle, temporary = tempfile.mkstemp(dir=Path(path).parent, prefix=".saving-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
