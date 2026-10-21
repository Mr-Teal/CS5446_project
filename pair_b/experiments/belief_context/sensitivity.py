"""How much the belief network's value of a board moves when the rest of the belief changes.

    .venv/bin/python experiments/belief_context/sensitivity.py --data "<Pair B>/code/data/d6-check" --out experiments/belief_context/sensitivity.json

For each of --beliefs check beliefs (train bucket of d6-check, in file order), every board is placed
in a second belief built around it by pairb.standin_beliefs.make_turn with another seed, so the same
board sits among different company; the network scores both beliefs and the difference between the
board's two values is recorded. The distribution of that difference, against the network's own board
error on the same boards, says how much "context" the kept network actually reads on practice
beliefs. A rule-decided board has no network value and is skipped. About two minutes with Stockfish
and an Apple GPU.
"""
import argparse
import json
import random
import sys
from pathlib import Path

import chess
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fow_shared.recording import read_records  # noqa: E402
from fow_shared.values import standard_fen  # noqa: E402
from pairb.belief_evaluator import BeliefNetworkEvaluator  # noqa: E402
from pairb.data import split_of  # noqa: E402
from pairb.standin_beliefs import make_turn  # noqa: E402


def check_beliefs(folder: Path, n: int, split: str) -> list:
    out = []
    for part in sorted(folder.glob("part-*.jsonl")):
        for record in read_records(part):
            if split_of(record.game_id) == split:
                out.append(record)
                if len(out) == n:
                    return out
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="the d6-check folder")
    ap.add_argument("--checkpoint", default=str(ROOT / "checkpoints" / "belief-v1-d1" / "best.pt"))
    ap.add_argument("--beliefs", type=int, default=300)
    ap.add_argument("--seed", type=int, default=11, help="the second beliefs are built from this seed (d6-check used 7)")
    ap.add_argument("--device", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        sys.exit(f"{out} exists; choose a new file")
    records = check_beliefs(Path(args.data), args.beliefs, "train")
    rng = random.Random(args.seed)
    with BeliefNetworkEvaluator.from_checkpoint(args.checkpoint, device=args.device) as net:
        originals = net.evaluate_beliefs([r.agent_input for r in records])
        rows = []  # (belief index, board index, value in its own belief, value in the new belief, label, new belief size)
        pending, keys = [], []
        for i, (record, values) in enumerate(zip(records, originals)):
            turn = record.agent_input
            for j, hypothesis in enumerate(turn.belief.hypotheses):
                board = chess.Board(hypothesis.fen)
                second = make_turn(board, random.Random(rng.getrandbits(32)), n_hypotheses=len(turn.belief.hypotheses),
                                   ply=turn.belief.ply)
                fens = [h.fen for h in second.belief.hypotheses]
                if len(fens) < 2 or standard_fen(board) not in fens:
                    continue  # nothing to compare against, or the board itself fell out
                pending.append(second)
                keys.append((i, j, fens.index(standard_fen(board)), values.hypothesis_values[j], record.hypothesis_values[j], len(fens)))
        for start in range(0, len(pending), 64):
            answers = net.evaluate_beliefs(pending[start:start + 64])
            for (i, j, k, own, label, size), answer in zip(keys[start:start + 64], answers):
                rows.append((i, j, own, answer.hypothesis_values[k], label, size))
    own = np.array([r[2] for r in rows]); other = np.array([r[3] for r in rows]); label = np.array([r[4] for r in rows])
    shift = np.abs(own - other)
    error = np.abs(own - label)
    report = {
        "checkpoint": args.checkpoint if not Path(args.checkpoint).is_relative_to(ROOT) else str(Path(args.checkpoint).relative_to(ROOT)),
        "data": Path(args.data).name, "split": "train", "beliefs": len(records), "boards_compared": int(len(rows)),
        "second_belief_seed": args.seed, "device": str(net.device),
        "value_shift_between_beliefs": {"mean": float(shift.mean()), "median": float(np.median(shift)),
                                        "p95": float(np.percentile(shift, 95)), "max": float(shift.max()),
                                        "share_above_0.01": float((shift > 0.01).mean()),
                                        "share_above_0.05": float((shift > 0.05).mean())},
        "board_error_on_the_same_boards": {"mean": float(error.mean()), "median": float(np.median(error))},
        "shift_over_error": float(shift.mean() / error.mean()),
        "note": "practice labels are depth-11 values of each board alone, so the true value of a board does not depend on "
                "its belief; a shift is what the network reads from the company a board keeps, and here it has nothing "
                "to gain from doing so",
    }
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "note"}, indent=1))


if __name__ == "__main__":
    main()
