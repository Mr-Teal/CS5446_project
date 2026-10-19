"""Compare linear, depth-1 and material on identical D2 rows; optionally add Network 1."""
import argparse
import hashlib
import json
from pathlib import Path

from pairb.linear import LinearCorrection
from pairb.linear_workflow import evaluate, load_dataset, mask_split, metrics, write_json
from pairb.metrics import paired_regret_difference


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--split", choices=["train", "val", "test"], default="val")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--allow-seen-games", action="store_true", help="diagnostic evaluation on seen game IDs")
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--net1-run", help="optional Network 1 run; requires torch; evaluated on the SAME rows")
    ap.add_argument("--net1-splits", help="Network 1's original splits.json; defaults to net1-run/splits.json")
    ap.add_argument("--out", required=True, help="new JSON file; never overwritten")
    args = ap.parse_args()
    if args.split == "test" and not args.final:
        ap.error("test split is reserved for the final evaluation; pass --final")
    try:
        path = Path(args.run) / "best.npz"
        model = LinearCorrection.load(path)
        arrays, source = load_dataset(args.data)
        report = evaluate(model, arrays, source, args.split, n_boot=args.n_boot,
                          allow_seen_games=args.allow_seen_games)
        report["checkpoint_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        if args.net1_run:
            import torch
            from pairb.data import ENCODING
            from pairb.evaluate import predict
            from pairb.net1 import Network1
            ckpath = Path(args.net1_run) / "best.pt"
            ckpt = torch.load(ckpath, map_location="cpu", weights_only=True)
            if ckpt.get("encoding") != ENCODING:
                raise ValueError("Network 1 checkpoint has incompatible encoding")
            net = Network1(**ckpt["config"])
            net.load_state_dict(ckpt["state_dict"])
            data = mask_split(arrays, args.split)
            split_path = Path(args.net1_splits) if args.net1_splits else Path(args.net1_run) / "splits.json"
            net_evidence = None
            if args.net1_splits or split_path.exists():
                splits = json.loads(split_path.read_text())
                if not all(isinstance(splits.get(k), list) and all(isinstance(g, str) for g in splits[k])
                           for k in ("train", "val")):
                    raise ValueError("Network 1 split evidence must contain train and val game lists")
                game_ids = set(data["game_id"].tolist())
                overlaps = {k: len(game_ids & set(splits[k])) for k in ("train", "val")}
                if any(overlaps.values()) and not args.allow_seen_games:
                    raise ValueError("Network 1 evaluation overlaps fitting/selection games; "
                                     "use --allow-seen-games for diagnostics only")
                net_evidence = {"overlaps": overlaps, "independent_games": not any(overlaps.values()),
                                "splits_sha256": hashlib.sha256(split_path.read_bytes()).hexdigest()}
            pred = predict(net, torch.from_numpy(data["planes"]), torch.from_numpy(data["d1"])).numpy()
            report["network"] = metrics(pred, data)
            report["network_checkpoint_sha256"] = hashlib.sha256(ckpath.read_bytes()).hexdigest()
            report["network_split_evidence"] = net_evidence
            report["independence_scope"] = "independent_games describes linear only; network_split_evidence is null when unavailable"
            linear = model.predict(data["planes"], data["d1"], packed=True)
            report["linear_minus_network_regret"] = paired_regret_difference(
                data["parent"], linear, pred, data["y"], games=data["game_id"], n_boot=args.n_boot)
        write_json(args.out, report)
    except (ValueError, FileExistsError) as exc:
        ap.error(str(exc))
    print(f"linear MAE {report['linear']['mae']:.6f}; d1 {report['baseline']['mae']:.6f}; "
          f"regret difference {report['regret_difference']['mean']:+.6f} -> {args.out}")


if __name__ == "__main__":
    main()
