"""Write one split of a D2-format dataset as a single gzipped part, so an evaluation can be rerun
without Stockfish or the full dataset.

    .venv/bin/python scripts/freeze_split.py --data data/d2-check --split train --out data/d2-check-train

Copies every record line whose game falls in the split (rule-decided rows too), as written and in
the source's order, into part-00.jsonl.gz, and writes manifest.json with the source's name,
SHA-256 and manifest, the split rule and the record count. The gzip bytes do not depend on when
the file was written. --out must not exist yet.
"""
import argparse
import datetime
import gzip
import json
import sys
from pathlib import Path

from pairb.data import record_lines, split_of
from pairb.provenance import data_source, portable

SPLIT_RULE = "sha1 of game_id modulo 10: 0-7 train, 8 validation, 9 test (pairb.data.split_of)"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="a D2-format dataset folder")
    ap.add_argument("--split", choices=["train", "val", "test"], required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        sys.exit(f"{out} exists; choose a new folder")
    source = data_source(args.data)
    lines = [line for line in record_lines(args.data) if split_of(json.loads(line)["game_id"]) == args.split]
    if source != data_source(args.data):
        sys.exit("the dataset changed while it was read; use a finished data run")
    if not lines:
        sys.exit(f"no {args.split} records in {args.data}")

    out.mkdir(parents=True)
    with open(out / "part-00.jsonl.gz", "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        gz.write("".join(f"{line}\n" for line in lines).encode())
    manifest = {
        "dataset": out.name, "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "records": len(lines), "split": args.split, "split_rule": SPLIT_RULE,
        "note": f"Every {args.split} record of {source['dataset']}, copied line for line in its order.",
        "source": source,
        "command": portable(["freeze_split.py", "--data", args.data, "--split", args.split, "--out", args.out]),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    size = (out / "part-00.jsonl.gz").stat().st_size
    print(f"{out}: {len(lines):,} {args.split} records of {source['dataset']}, {size / 1e6:.1f} MB gzipped")


if __name__ == "__main__":
    main()
