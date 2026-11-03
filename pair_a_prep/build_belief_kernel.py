"""Build the optional Windows bitboard accelerator using the active Pixi compiler."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).parent
SOURCES = ("belief_kernel.cpp", "zs21/native/inference.cpp", "_belief_native.py")


def source_hashes():
    return {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Optional native backend currently supports Windows; Python backend remains portable")
    compiler = shutil.which("x86_64-w64-mingw32-g++") or shutil.which("g++")
    if compiler is None:
        raise SystemExit("No C++ compiler in activated environment; use Pixi darkchess or Python backend")
    target = subprocess.check_output([compiler, "-dumpmachine"], text=True).strip()
    if sys.maxsize > 2**32 and not target.startswith("x86_64"):
        raise SystemExit(f"A 64-bit Python requires an x86_64 compiler, got {target}: {compiler}")
    directory = ROOT / "_belief_build"
    directory.mkdir(exist_ok=True)
    digest = sha256(json.dumps(source_hashes(), sort_keys=True).encode()).hexdigest()[:16]
    library = directory / f"belief_kernel-{digest}.dll"
    command = [compiler, "-std=c++17", "-O3", "-DNDEBUG", "-shared", "-static-libgcc",
               "-static-libstdc++", str(ROOT / "belief_kernel.cpp"), "-o", str(library)]
    subprocess.run(command, check=True)
    record = {"command": command, "source_sha256": source_hashes(), "library": library.name,
              "dll_sha256": sha256(library.read_bytes()).hexdigest(),
              "compiler": subprocess.check_output([compiler, "--version"], text=True).splitlines()[0]}
    (directory / "manifest.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
