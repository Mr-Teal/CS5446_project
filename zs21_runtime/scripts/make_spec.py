"""Generate a process launch specification for this checkout."""
import argparse
import json
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=RUNTIME / "out/paper-agent.json")
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    spec = dict(cwd=str(RUNTIME.parent), command=["pixi", "run", "--manifest-path",
                str(RUNTIME / "pixi.toml"), "--locked", "-e", "darkchess", "python", "-X", "utf8",
                "-m", "pair_a_prep.zs21.serve"] + (["--baseline"] if args.baseline else []))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    print(str(args.output.resolve()))


if __name__ == "__main__":
    main()
