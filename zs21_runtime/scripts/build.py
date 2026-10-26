"""Build from the shipped corresponding sources using the active Pixi compiler."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

RUNTIME = Path(__file__).resolve().parents[1]
ROOT = RUNTIME.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-only", action="store_true")
    parser.add_argument("--generic", action="store_true", help="SSE2 engine instead of AVX2/BMI2; timing requires separate validation")
    parser.add_argument("--output", type=Path, help="optional separate build directory for verification")
    args = parser.parse_args()
    compiler = shutil.which(os.environ.get("CXX", "x86_64-w64-mingw32-g++"))
    if compiler is None:
        raise RuntimeError("run with the Pixi darkchess environment")
    native_source = ROOT / "pair_a_prep/zs21/native/inference.cpp"
    native_target = (args.output / "inference.dll") if args.output else native_source.with_suffix(".dll")
    native_target.parent.mkdir(parents=True, exist_ok=True)
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
