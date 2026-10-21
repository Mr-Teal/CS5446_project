"""Write provenance.json next to a checkpoint trained before its summary recorded provenance (review T9).

    .venv/bin/python scripts/write_provenance.py --run checkpoints/net1-v2 --data ../Pair B/code/data/d2-v2

Records the SHA-256 of each part-*.jsonl and of manifest.json in the training data folder, the
manifest's code hash, seed, creation time and command, the SHA-256 of best.pt, and the training
summary's device, best epoch, epochs run, creation time and arguments. The run must have been
trained on a dataset with the data folder's name, and provenance.json must not exist yet.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

from pairb.provenance import data_source, sha256_of


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="a training run folder holding best.pt and summary.json")
    ap.add_argument("--data", required=True, help="the dataset folder the run was trained on")
    args = ap.parse_args()

    run, data = Path(args.run), Path(args.data)
    for name in ("best.pt", "summary.json"):
        if not (run / name).exists():
            sys.exit(f"{run} has no {name}")
    out = run / "provenance.json"
    if out.exists():
        sys.exit(f"{out} exists; remove it first")
    summary = json.loads((run / "summary.json").read_text())
    if summary["dataset"] != data.name:
        sys.exit(f"{run} was trained on {summary['dataset']}, not {data.name}")

    source = data_source(data)
    modified = max((data / name).stat().st_mtime for name in source["files_sha256"])
    source["files_last_modified"] = datetime.datetime.fromtimestamp(modified).astimezone().isoformat(timespec="seconds")
    today = datetime.date.today().isoformat()
    report = {
        "note": f"Written on {today}, after training, from the local data folder {data.name}: the run cannot be "
                "retrained, so this records the bytes it was trained on. files_last_modified is the newest data "
                "file's time; it should be earlier than training.created.",
        "source": source,
        "checkpoint_sha256": sha256_of(run / "best.pt"),
        "training": {k: summary[k] for k in ("device", "best_epoch", "epochs_run", "created", "args")},
    }
    with open(out, "x") as f:
        f.write(json.dumps(report, indent=2) + "\n")
    print(f"{out}: {data.name} ({len(source['files_sha256'])} files), best.pt {report['checkpoint_sha256'][:12]}")


if __name__ == "__main__":
    main()
