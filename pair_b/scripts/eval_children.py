"""Per-move accuracy: how close the scorers' values for the children of a position are to careful Stockfish.

    .venv/bin/python scripts/eval_children.py --data data/d2-check --out checkpoints/belief-v1-d1/eval-children-d16.json

Draws --parents positions at random from the training games of a D2-format dataset; the validation and
test games are never read. For every move the fog-of-war rules allow, the belief network, Network 1 and
quick Stockfish value the board after the move in the two ways a search can ask: one evaluate_children call
on the parent (quick Stockfish's depth-1 MultiPV scores, as a search uses them) and one evaluate_boards call
on the children (a depth-1 call per board). Each value is compared with Stockfish's at --depth on the same
board. Writes the mean absolute errors and three paired differences (95% bootstrap intervals that resample
whole games) to --out, the only file this writes. The networks are read from net1-v2/ and belief-v1-d1/ in
--checkpoints, on --device (cpu, as for the saved result). The defaults (100 parents, depth 16) took about
12 minutes on a Mac.
"""
import argparse
import datetime
import json
import random
from pathlib import Path

import chess
import numpy as np

from fow_shared.values import fog_legal_moves, standard_fen
from pairb.belief_eval import paired_difference
from pairb.belief_evaluator import BeliefNetworkEvaluator
from pairb.data import split_of
from pairb.network_evaluator import NetworkEvaluator
from pairb.stockfish import StockfishEvaluator

ROOT = Path(__file__).resolve().parents[1]
SPLIT = "train"  # the games the parents come from: the test games stay untouched until the final report
BELIEF_RUN, NET1_RUN = "belief-v1-d1", "net1-v2"  # the folders of --checkpoints the two networks are read from
KEYS = ("belief_children", "belief_boards", "net1_children", "net1_boards", "sf_children", "sf_boards")


def pick_parents(data_dir: Path, n: int, seed: int) -> list[tuple[str, str]]:
    """n (game_id, parent_fen) pairs from the training games: the distinct parents in the part files, sorted,
    shuffled with `seed`, and the first n (all of them when there are fewer)."""
    parents = set()
    for part in sorted(Path(data_dir).glob("part-*.jsonl")):
        with part.open(encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                if split_of(record["game_id"]) == SPLIT:
                    parents.add((record["game_id"], record["parent_fen"]))
    ordered = sorted(parents)
    random.Random(seed).shuffle(ordered)
    return ordered[:n]


def measure(data_dir: Path, checkpoints: Path, n_parents: int, depth: int, seed: int, device: str) -> dict:
    """The report for n_parents parents (fewer if the data has fewer): the mean absolute error of each of six
    columns against Stockfish at `depth`, and the paired differences between them. Every engine is quit
    before this returns or raises."""
    parents = pick_parents(data_dir, n_parents, seed)
    if not parents:
        raise ValueError(f"no parents to score: {data_dir} has no part-*.jsonl record of a {SPLIT} game "
                         f"(or n_parents is {n_parents})")
    values = {key: [] for key in KEYS}
    target, games = [], []
    with (
        BeliefNetworkEvaluator.from_checkpoint(checkpoints / BELIEF_RUN / "best.pt", device=device) as belief,
        NetworkEvaluator.from_checkpoint(checkpoints / NET1_RUN / "best.pt", device=device) as net1,
        StockfishEvaluator(depth=1) as quick,
        StockfishEvaluator(depth=depth) as careful,
    ):
        for game_id, fen in parents:
            board = chess.Board(fen)
            player = "white" if board.turn == chess.WHITE else "black"
            moves, children = [], []
            for move in fog_legal_moves(board):
                child = board.copy(stack=False)
                child.push(move)  # push_uci would refuse fog-only moves
                moves.append(move.uci())
                children.append(standard_fen(child))
            by_move = {"belief_children": belief.evaluate_children(fen), "net1_children": net1.evaluate_children(fen),
                       "sf_children": quick.evaluate_children(fen)}
            by_board = {"belief_boards": belief.evaluate_boards(children, player),
                        "net1_boards": net1.evaluate_boards(children, player),
                        "sf_boards": quick.evaluate_boards(children, player)}
            for key, answer in by_move.items():
                values[key] += [answer[uci] for uci in moves]
            for key, answer in by_board.items():
                values[key] += answer
            target += careful.evaluate_boards(children, player)
            games += [game_id] * len(moves)

    target, games = np.array(target), np.array(games)
    error = {key: np.abs(np.array(values[key]) - target) for key in KEYS}
    return {
        "data": Path(data_dir).resolve().name, "split": SPLIT, "seed": seed,
        "parents": len(parents), "children": len(games), "target_depth": depth,
        "mae": {key: float(error[key].mean()) for key in KEYS},
        "belief_children - net1_children": paired_difference(error["belief_children"], error["net1_children"], games),
        "belief_children - belief_boards": paired_difference(error["belief_children"], error["belief_boards"], games),
        "net1_boards - net1_children": paired_difference(error["net1_boards"], error["net1_children"], games),
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="a D2-format dataset folder (part-*.jsonl)")
    ap.add_argument("--checkpoints", default=str(ROOT / "checkpoints"),
                    help=f"the folder holding {NET1_RUN}/ and {BELIEF_RUN}/ (default: pair_b/checkpoints)")
    ap.add_argument("--parents", type=int, default=100, help="how many parent positions to draw (default: %(default)s)")
    ap.add_argument("--depth", type=int, default=16,
                    help="depth of the Stockfish every value is compared with (default: %(default)s)")
    ap.add_argument("--seed", type=int, default=5, help="seeds the choice of parents (default: %(default)s)")
    ap.add_argument("--device", default="cpu", help="cpu, mps or cuda (default: %(default)s)")
    ap.add_argument("--out", required=True, help="the result file (JSON), the only file this writes")
    args = ap.parse_args()
    out = Path(args.out)
    if not out.parent.is_dir():
        ap.error(f"the folder for --out does not exist: {out.parent}")  # before minutes of measuring, not after

    report = measure(Path(args.data), Path(args.checkpoints), args.parents, args.depth, args.seed, args.device)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
