"""Compare Pair B's stand-in views with Pair A's RulesAdapter.observe() on every view of random games.

    PYTHONPATH=<worktree>:<worktree>/pair_b/src .venv/bin/python observe_agreement.py --games 500 --out <file>

Needs pair_a_prep.rules_adapter, which is on Teal's branch pair-a/rules-interface and not on main,
so run it with a worktree of that branch first on PYTHONPATH. Game g plays uniformly random legal
moves from random.Random(seed + g) with the stand-in rules, until the game ends or --plies; Teal's
adapter is stepped through the same moves from its own start. At every ply, and once after the
game ends, both players' views are compared on the fields in COMPARED, and the two rules' results
(winner and reason). The stand-in leaves captured_own_piece_at empty, so it is not compared. A game
is stopped at its first difference, which is counted and kept as an example. Refuses to overwrite.
"""
import argparse
import hashlib
import json
import platform
import random
import subprocess
import time
from pathlib import Path

import chess

from pairb.rules import StandinRules, TealRules

# The checkout whose pairb and pair_a_prep are in use (the worktree), found from the module itself,
# since main has no pairb.provenance to ask.
CHECKOUT = Path(__import__("pairb.rules").rules.__file__).resolve().parents[3]

COMPARED = ("side_to_move", "ply", "visible_squares", "visible_pieces", "legal_moves", "terminal", "outcome")


def view(observation) -> tuple:
    return tuple(getattr(observation, field) for field in COMPARED)


def play(standin, teal, seed: int, plies: int) -> tuple[int, int, str | None, dict | None]:
    """Views compared in one game, how many of them were game-ending views, how the game ended (None
    at the ply cap), and the first difference, if any."""
    rng = random.Random(seed)
    ours, theirs = standin.initial_state(), teal.initial_state()
    compared = terminal = 0
    for ply in range(plies + 1):
        for player in ("white", "black"):
            a, b = standin.observe(ours, player), teal.observe(theirs, player)
            compared += 1
            terminal += a.terminal
            if view(a) != view(b):
                fields = [f for f, x, y in zip(COMPARED, view(a), view(b)) if x != y]
                return compared, terminal, None, {"seed": seed, "ply": ply, "player": player, "fields": fields,
                                                  "fen": standin.board(ours).fen()}
        ended = standin.terminal(ours)
        if ended != teal.terminal(theirs):
            return compared, terminal, None, {"seed": seed, "ply": ply, "fields": ["result"],
                                              "fen": standin.board(ours).fen()}
        if ended is not None or ply == plies:
            return compared, terminal, ended and ended[1], None
        move = rng.choice(sorted(standin.legal_moves(ours)))
        ours, theirs = standin.apply_move(ours, move), teal.apply_move(theirs, move)
    return compared, terminal, None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--games", type=int, default=500)
    ap.add_argument("--plies", type=int, default=300, help="the most plies per game")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    started = time.time()
    standin, teal = StandinRules(), TealRules()
    views, terminal_views, endings, differences = 0, 0, {}, []
    for game in range(args.games):
        compared, terminal, ending, difference = play(standin, teal, args.seed + game, args.plies)
        views += compared
        terminal_views += terminal
        endings[ending or "ply cap"] = endings.get(ending or "ply cap", 0) + 1
        if difference:
            differences.append(difference)
    adapter = CHECKOUT / "pair_a_prep" / "rules_adapter.py"
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=CHECKOUT, capture_output=True, text=True).stdout.strip()
    report = {
        "games": args.games, "plies_cap": args.plies, "seed": args.seed,
        "seeds": "game g plays random legal moves from random.Random(seed + g)",
        "views_compared": views, "game_ending_views": terminal_views, "endings": endings, "fields_compared": list(COMPARED) + ["result (winner, reason) after every ply"],
        "games_with_a_difference": len(differences), "first_differences": differences[:5],
        "rules": {"standin": StandinRules.name, "teal": TealRules.name},
        "checkout_commit": head or None, "rules_adapter_sha256": hashlib.sha256(adapter.read_bytes()).hexdigest(),
        "seconds": round(time.time() - started, 1),
        "runtime": {"python": platform.python_version(), "python_chess": chess.__version__},
    }
    with open(args.out, "x") as f:
        f.write(json.dumps(report, indent=2) + "\n")
    print(f"{views:,} views in {args.games} games, {len(differences)} games with a difference, "
          f"{report['seconds']} s -> {args.out}")


if __name__ == "__main__":
    main()
