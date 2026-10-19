"""Train a NumPy ridge correction on D2 data; validation selects alpha, test stays held out."""
import argparse
import json

from pairb.linear_workflow import train


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--alphas", type=float, nargs="+", default=[1e-5, 1e-4, 1e-3, 1e-2, 0.1, 1.0])
    args = ap.parse_args()
    try:
        summary = train(args.data, args.out, args.alphas)
    except (ValueError, FileExistsError) as exc:
        ap.error(str(exc))
    print(json.dumps({"selected_alpha": summary["selected_alpha"], "n_train": summary["n_train"],
                      "n_val": summary["n_val"], "checkpoint": args.out + "/best.npz"}))


if __name__ == "__main__":
    main()
