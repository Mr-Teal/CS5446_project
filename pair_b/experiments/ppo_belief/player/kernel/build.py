"""Compile the belief sampler for this machine (once, before the player or the tests are used).

    python pair_b/experiments/ppo_belief/player/kernel/build.py

Writes build/belief_sampler.dll, .dylib or .so beside this file, and build/manifest.json with the
source hashes and the compiler. belief_sampler.cpp includes the team's rules code,
pair_a_prep/zs21/native/inference.cpp (moves, play, matches), from the repository this file is in.
The compiler and the flags are those of pair_a_prep/build_belief_kernel.py.
"""
import json
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]  # kernel -> player -> ppo_belief -> experiments -> pair_b -> repository root
RULES = REPO / "pair_a_prep" / "zs21" / "native" / "inference.cpp"
SUFFIX = {"darwin": ".dylib", "win32": ".dll"}.get(sys.platform, ".so")


def main():
    if not RULES.is_file():
        sys.exit(f"{RULES} is missing: this file must stay inside the team repository")
    compiler = (shutil.which("x86_64-w64-mingw32-g++") if sys.platform == "win32" else None) \
        or shutil.which("g++") or shutil.which("c++")
    if compiler is None:
        sys.exit("no C++ compiler on PATH")
    build = HERE / "build"
    build.mkdir(exist_ok=True)
    library = build / f"belief_sampler{SUFFIX}"
    command = [compiler, "-std=c++17", "-O3", "-DNDEBUG", "-shared"]
    if sys.platform != "darwin":
        command += ["-static-libgcc", "-static-libstdc++"]
    if sys.platform != "win32":
        command.append("-fPIC")
    command += ["-I", str(REPO), str(HERE / "belief_sampler.cpp"), "-o", str(library)]
    subprocess.run(command, check=True)
    record = {"command": [compiler, *command[1:]],
              "source_sha256": {"belief_sampler.cpp": sha256((HERE / "belief_sampler.cpp").read_bytes()).hexdigest(),
                                "pair_a_prep/zs21/native/inference.cpp": sha256(RULES.read_bytes()).hexdigest()},
              "library": library.name, "library_sha256": sha256(library.read_bytes()).hexdigest(),
              "compiler": subprocess.check_output([compiler, "--version"], text=True).splitlines()[0]}
    (build / "manifest.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"built {library.name} with {record['compiler']}")


if __name__ == "__main__":
    main()
