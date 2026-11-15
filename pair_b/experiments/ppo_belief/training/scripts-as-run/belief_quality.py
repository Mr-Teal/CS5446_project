"""Measure the belief sampler on games played by the first run's final network (no belief input).

    python belief_quality.py --games 60 --caps 256 1024 4096

The games do not depend on the samplers: both sides are moved by the plain PPO network, which reads
its own 25 planes. For each cap, both players' samplers follow the same games. Reported per cap:

  boards        positions kept, mean and median, on the player's turn
  true kept     how often the true position is one of them (a measurement made with the true board)
  repaired      share of turns that come after at least one repair in that game, and repairs per game
  blank         share of turns on which the picture shows the view only
  hidden piece  the chance the picture gives to the true square of an enemy piece that is out of view,
                averaged over such pieces; the same for the enemy king alone
  ms per ply    time in bs_step (both players) per ply

For comparison: "memory" is how often the plain player's own memory planes (last seen square) mark
the true square of a hidden enemy piece.
"""
import argparse
import importlib.util
import random
import sys
import time
from pathlib import Path

import chess
import numpy as np
import torch

HERE = Path(__file__).resolve().parent
PLAIN = HERE.parent / "ppo-pilot-2026-11-14"
sys.path.insert(0, str(HERE))

from fowppo import belief, env as E  # noqa: E402


def load_plain():
    """The first run's package under another name, so that both packages live in one process."""
    spec = importlib.util.spec_from_file_location("fowppo_plain", PLAIN / "fowppo" / "__init__.py",
                                                  submodule_search_locations=[str(PLAIN / "fowppo")])
    module = importlib.util.module_from_spec(spec)
    sys.modules["fowppo_plain"] = module
    spec.loader.exec_module(module)
    import fowppo_plain.env as plain_env
    import fowppo_plain.model as plain_model
    return plain_env, plain_model


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--games", type=int, default=60)
    parser.add_argument("--caps", type=int, nargs="+", default=[256, 1024, 4096])
    parser.add_argument("--checkpoint", default=str(PLAIN / "runs" / "long-hourly" / "final.pt"))
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    torch.set_num_threads(1)
    plain_env, plain_model = load_plain()
    saved = torch.load(args.checkpoint, map_location="cpu")
    model = plain_model.PolicyValueNet(saved["config"]["blocks"], saved["config"]["channels"])
    model.load_state_dict(saved["model"])
    model.eval()
    rng = random.Random(args.seed)
    generator = torch.Generator().manual_seed(args.seed)
    samplers = {cap: (belief.create(), belief.create()) for cap in args.caps}
    stats = {cap: {"turns": 0, "boards": [], "kept": 0, "after_repair": 0, "blank": 0, "repairs": 0, "seconds": 0.0,
                   "piece": [], "king": [], "plies": 0} for cap in args.caps}
    memory_hits, memory_pieces, plies_total = 0, 0, []
    for g in range(args.games):
        game = plain_env.Game()
        for cap in args.caps:
            for color in (chess.BLACK, chess.WHITE):
                belief.reset(samplers[cap][color], game.board, color, args.seed * 100003 + g * 2 + color, cap)
        opening = rng.randint(0, 8)
        while True:
            board, color = game.board, game.board.turn
            enemy = board.occupied_co[not color]
            seen = plain_env.seen_bb(board, color)
            hidden = enemy & ~seen
            kinds = (board.pawns, board.knights, board.bishops, board.rooks, board.queens, board.kings)
            flip = 0 if color == chess.WHITE else 56
            if game.ply >= opening:
                for k, kind in enumerate(kinds):  # the plain player's memory of last seen squares
                    for square in chess.scan_forward(kind & hidden):
                        memory_pieces += 1
                        memory_hits += bool(game.memory[color][k] & chess.BB_SQUARES[square])
                for cap in args.caps:
                    handle = samplers[cap][color]
                    state, s = belief.counters(handle), stats[cap]
                    s["turns"] += 1
                    s["boards"].append(0 if state["blank"] else state["boards"])
                    s["kept"] += belief.weight_of(handle, board) > 0
                    s["after_repair"] += state["repairs"] > 0
                    s["blank"] += state["blank"]
                    picture = belief.planes(handle)
                    for k, kind in enumerate(kinds):
                        for square in chess.scan_forward(kind & hidden):
                            chance = picture[E.P_PROBABILITY + k][square ^ flip] / 255
                            s["piece"].append(chance)
                            if k == 5:
                                s["king"].append(chance)
            if game.ply < opening:
                move = rng.choice(plain_env._available_fog_moves(board))
                if move.promotion not in (None, chess.QUEEN):
                    move = chess.Move(move.from_square, move.to_square, chess.QUEEN)
            else:
                table = plain_env.legal_actions(board)
                planes = np.zeros((1, plain_env.N_PLANES, 64), dtype=np.uint8)
                plain_env.encode(game, color, planes[0])
                mask = np.zeros((1, 4096), dtype=np.bool_)
                mask[0, list(table)] = True
                with torch.no_grad():
                    logits, _ = model(torch.from_numpy(planes), torch.from_numpy(mask))
                move = table[int(torch.multinomial(torch.softmax(logits[0].double(), dim=0), 1, generator=generator))]
            captured = -1
            if board.is_en_passant(move):
                captured = move.to_square + (-8 if color == chess.WHITE else 8)
            elif enemy & chess.BB_SQUARES[move.to_square]:
                captured = move.to_square
            if game.play(move) is not None:
                break
            for cap in args.caps:
                began = time.perf_counter()
                belief.step(samplers[cap][chess.WHITE], samplers[cap][chess.BLACK], game.board, move, captured, color, game.ply)
                stats[cap]["seconds"] += time.perf_counter() - began
                stats[cap]["plies"] += 1
        plies_total.append(game.ply)
        for cap in args.caps:
            stats[cap]["repairs"] += sum(belief.counters(h)["repairs"] for h in samplers[cap])
    print(f"{args.games} games by the plain final network, mean {np.mean(plies_total):.1f} plies; "
          f"plain memory marks the true square of {memory_hits / memory_pieces:.3f} of the hidden enemy pieces")
    print("cap    boards mean/median   true kept   after repair   repairs/game   blank    hidden piece   hidden king   ms per ply")
    for cap in args.caps:
        s = stats[cap]
        print(f"{cap:5d}  {np.mean(s['boards']):8.0f} / {np.median(s['boards']):5.0f}   {s['kept'] / s['turns']:9.3f}   "
              f"{s['after_repair'] / s['turns']:12.3f}   {s['repairs'] / args.games:12.2f}   {s['blank'] / s['turns']:6.4f}   "
              f"{np.mean(s['piece']):12.3f}   {np.mean(s['king']):11.3f}   {1000 * s['seconds'] / s['plies']:10.3f}")


if __name__ == "__main__":
    main()
