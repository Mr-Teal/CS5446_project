"""Build from the shipped corresponding sources using the active Pixi compiler."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

RUNTIME = Path(__file__).resolve().parents[1]
ROOT = RUNTIME.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-only", action="store_true")
    parser.add_argument("--generic", action="store_true", help="SSE2 engine instead of AVX2/BMI2; timing requires separate validation")
    parser.add_argument("--output", type=Path, help="optional separate build directory for verification")
    parser.add_argument("--native", action="store_true",
                        help="build the inference library for this host instead of the mingw DLL; "
                             "implies --native-only and does not reproduce the audited Windows artifact")
    args = parser.parse_args()
    default_cxx = "c++" if args.native else "x86_64-w64-mingw32-g++"
    compiler = shutil.which(os.environ.get("CXX", default_cxx))
    if compiler is None:
        raise RuntimeError("no C++ compiler found; run with the Pixi darkchess environment"
                           if not args.native else "no host C++ compiler found; set CXX")
    native_source = ROOT / "pair_a_prep/zs21/native/inference.cpp"
    suffix = ".dll"
    if args.native:
        suffix = ".dylib" if sys.platform == "darwin" else ".so"
    native_target = (args.output / f"inference{suffix}") if args.output else native_source.with_suffix(suffix)
    native_target.parent.mkdir(parents=True, exist_ok=True)
    if args.native:
        args.native_only = True
        common = ["-O3", "-std=c++17", "-fPIC", "-fvisibility=hidden"]
    else:
        common = ["-O3", "-std=c++17", "-static-libgcc", "-static-libstdc++", "-static"]
    subprocess.run([compiler, "-shared", *common, str(native_source), "-o", str(native_target)], check=True)
    targets = [native_target]
    sources = [native_source]
    if not args.native_only:
        src = RUNTIME / "third_party/stockfish13/src"
        cpp = sorted(src.glob("*.cpp")) + [src / "syzygy/tbprobe.cpp", src / "nnue/evaluate_nnue.cpp",
                                           src / "nnue/features/half_kp.cpp"]
        engine_dir = args.output or RUNTIME / "engines/stockfish13-batch-v6"
        engine_dir.mkdir(parents=True, exist_ok=True)
        target = engine_dir / "stockfish13.exe"
        flags = ["-DNDEBUG", "-DIS_64BIT", "-DUSE_SSE2", "-msse2", "-DNNUE_EMBEDDING_OFF", "-pthread"]
        if not args.generic:
            flags += ["-DUSE_AVX2", "-DUSE_SSSE3", "-DUSE_SSE41", "-DUSE_POPCNT", "-DUSE_PEXT",
                      "-mavx2", "-mssse3", "-msse4.1", "-mpopcnt", "-mbmi2"]
        subprocess.run([compiler, *common, *flags, *(str(p) for p in cpp), "-o", str(target)], check=True)
        network = RUNTIME / "engines/stockfish13-batch-v6/nn-62ef826d1a6d.nnue"
        if network.parent != engine_dir:
            shutil.copy2(network, engine_dir / network.name)
        targets.append(target)
        sources.extend(p for p in src.rglob("*") if p.is_file())
    record = dict(compiler=subprocess.check_output([compiler, "--version"], text=True),
                  generic=args.generic, artifacts={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in targets},
                  sources={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    report = (args.output or RUNTIME / "engines/stockfish13-batch-v6") / "build-manifest.json"
    report.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record["artifacts"]))


if __name__ == "__main__":
    main()
