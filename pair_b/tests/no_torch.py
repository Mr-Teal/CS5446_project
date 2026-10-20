"""Test helper: run code in a fresh interpreter where `import torch` fails, as on an Intel Mac.

torch has no build for Intel Macs, so pyproject.toml asks for it only on other machines. Putting None
in sys.modules['torch'] makes `import torch` raise ModuleNotFoundError (an ImportError), whether or
not the machine running the tests has torch.
"""
import subprocess
import sys
from pathlib import Path

PAIR_B = Path(__file__).resolve().parents[1]  # the pair_b/ folder


def run_without_torch(code: str, cwd: Path, timeout: float = 300) -> subprocess.CompletedProcess:
    """Run `code` with `python -c` in `cwd`, with `import torch` blocked. Returns the finished process,
    its stdout and stderr captured as text."""
    block = "import sys; sys.modules['torch'] = None\n"
    return subprocess.run([sys.executable, "-c", block + code], cwd=cwd, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
