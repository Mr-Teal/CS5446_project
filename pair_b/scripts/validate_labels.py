"""Check a solver-label handoff without PyTorch, Stockfish, or dataset cache writes."""
import argparse
from pathlib import Path
import sys

# Also works from a source checkout with only the shared dependencies installed.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pair_b" / "src"))

from pairb.label_validation import validate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="one JSONL file or a label-run folder")
    parser.add_argument("--pattern", default="part-*.jsonl", help="file glob when source is a folder")
    parser.add_argument("--require-d1", action="store_true", help="require D1 on non-rule-decided boards")
    parser.add_argument("--require-played-policy", action="store_true",
                        help="require played_policy:<uci> on every record (full solver-label runs)")
    parser.add_argument("--splits", help="training splits.json to check against the selected dataset")
    args = parser.parse_args(argv)
    report = validate(args.source, pattern=args.pattern, require_d1=args.require_d1,
                      require_played_policy=args.require_played_policy, splits=args.splits)
    for severity, messages in (("ERROR", report.errors), ("WARNING", report.warnings)):
        for message in messages:
            print(f"{severity} {message}")
    counts = ", ".join(f"{name}={report.splits[name]}" for name in ("train", "val", "test"))
    print(f"{'FAIL' if report.errors else 'PASS'}: {report.records} parsed records, {report.files} files, "
          f"{len(report.games)} games ({counts}); {len(report.errors)} errors, {len(report.warnings)} warnings")
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
