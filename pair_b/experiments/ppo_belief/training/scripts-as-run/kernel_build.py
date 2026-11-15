"""Compile the belief sampler for this machine.

    python kernel/build.py

Writes kernel/build/belief_sampler.dylib (.so on Linux) and kernel/build/manifest.json with the
source hashes and the compiler. belief_sampler.cpp includes team_inference.cpp, an unchanged copy of
the team's pair_a_prep/zs21/native/inference.cpp at commit ca3993c (the rules: moves, play, matches).
"""
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES = ("belief_sampler.cpp", "team_inference.cpp")
TEAM_INFERENCE_SHA256 = "7b95d76abdf2954940cbd47d9f9eeb907fc6c4a2f1027e3d08e54d3929ccb296"  # git show ca3993c:...


def main():
    hashes = {name: sha256((HERE / name).read_bytes()).hexdigest() for name in SOURCES}
    if hashes["team_inference.cpp"] != TEAM_INFERENCE_SHA256:
        sys.exit("team_inference.cpp is not the team's file at ca3993c")
    build = HERE / "build"
    build.mkdir(exist_ok=True)
    library = build / ("belief_sampler.dylib" if sys.platform == "darwin" else "belief_sampler.so")
    command = ["c++", "-std=c++17", "-O3", "-DNDEBUG", "-shared", "-fPIC", str(HERE / "belief_sampler.cpp"),
               "-o", str(library)]
    subprocess.run(command, check=True, cwd=HERE)
    compiler = subprocess.check_output(["c++", "--version"], text=True).splitlines()[0]
    (build / "manifest.json").write_text(json.dumps({
        "command": command, "source_sha256": hashes, "library": library.name,
        "library_sha256": sha256(library.read_bytes()).hexdigest(), "compiler": compiler}, indent=2) + "\n")
    print(f"built {library.name} with {compiler}")


if __name__ == "__main__":
    main()
