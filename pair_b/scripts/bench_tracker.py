"""Time the honest particle tracker (pairb.tracker) on seeded random games.

    .venv/bin/python scripts/bench_tracker.py --games 5 --plies 40 --particles 256

Plays --games games of up to --plies uniformly random moves with Pair B's stand-in rules. A tracker
for each colour is fed as fow_shared's play_game feeds them, the game-ending view included, and
every update is timed (the referee's work of making the view is not). Prints the median,
95th-percentile and slowest milliseconds per update, the same for the updates after a move the
player did not see (the slow ones: every particle is expanded by every move), and how many updates
had to rebuild; --out also writes them as JSON, with the settings, and refuses to overwrite. Fog
Lab's target is a median of at most 2000 ms at 256 particles.
"""
import argparse
import json
import platform
import random
import statistics
import sys
import time
from pathlib import Path

from pairb.provenance import git_commit, runtime
from pairb.rules import GameReferee, StandinRules
from pairb.tracker import ParticleTracker

COLOURS = ("white", "black")


def play(seed: int, plies: int, particles: int, guesses: int) -> list[tuple[float, bool, bool]]:
    """One seeded random game: (milliseconds, own move given, rebuilt) for every tracker update."""
    rules = StandinRules()
    referee = GameReferee(rules)
    referee.reset(seed)
    rng = random.Random(seed)
    trackers = {player: ParticleTracker(rules, n_particles=particles, n_hypotheses=guesses) for player in COLOURS}
    for index, player in enumerate(COLOURS):
        trackers[player].reset(player, seed + index)
    updates = []

    def update(player: str, own_move: str | None) -> None:
        observation = referee.observe(player)
        started = time.perf_counter()
        trackers[player].update(observation, own_move=own_move)
        updates.append(((time.perf_counter() - started) * 1000, own_move is not None, trackers[player].rebuilt))

    for player in COLOURS:
        update(player, None)
    for _ in range(plies):
        if referee.is_terminal():
            break
        mover = referee.current_player()
        moves = referee.observe(mover).legal_moves
        if not moves:
            break
        move = rng.choice(moves)
        referee.apply(move)
        for player in COLOURS:
            update(player, move if player == mover else None)
    return updates


def stats(milliseconds: list[float]) -> dict:
    p95 = statistics.quantiles(milliseconds, n=100, method="inclusive")[94] if len(milliseconds) > 1 else milliseconds[0]
    return {"updates": len(milliseconds), "median_ms": statistics.median(milliseconds), "p95_ms": p95,
            "max_ms": max(milliseconds)}


def summary(milliseconds: list[float]) -> str:
    s = stats(milliseconds)
    return (f"median {s['median_ms']:.0f} ms, 95th percentile {s['p95_ms']:.0f} ms, "
            f"slowest {s['max_ms']:.0f} ms ({s['updates']} updates)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--games", type=int, default=5)
    ap.add_argument("--plies", type=int, default=40, help="the most plies per game")
    ap.add_argument("--particles", type=int, default=256, help="the tracker's cap")
    ap.add_argument("--guesses", type=int, default=8, help="hypotheses per belief")
    ap.add_argument("--seed", type=int, default=0, help="game g is played with seed + g")
    ap.add_argument("--out", help="also write the results to this JSON file, which must not exist yet")
    args = ap.parse_args()
    if args.out and Path(args.out).exists():
        sys.exit(f"{args.out} exists; choose a new file")

    updates, games = [], []
    for game in range(args.games):
        started = time.perf_counter()
        played = play(args.seed + game, args.plies, args.particles, args.guesses)
        updates += played
        games.append({"seed": args.seed + game, "updates": len(played),
                      "rebuilds": sum(rebuilt for _, _, rebuilt in played),
                      "seconds": round(time.perf_counter() - started, 1)})
        print(f"game {game + 1}/{args.games}: {len(played)} updates in {games[-1]['seconds']:.1f} s, "
              f"{games[-1]['rebuilds']} rebuilds", flush=True)
    print(f"\n{args.particles} particles, {args.guesses} guesses, Pair B stand-in rules, "
          f"Python {platform.python_version()} on {platform.machine()}")
    print("every update:            " + summary([ms for ms, _, _ in updates]))
    print("after an unseen move:    " + summary([ms for ms, own, _ in updates if not own]))
    print(f"rebuilds: {sum(rebuilt for _, _, rebuilt in updates)}")
    if args.out:
        report = {"settings": {"games": args.games, "plies": args.plies, "particles": args.particles,
                               "guesses": args.guesses, "seed": args.seed, "rules": StandinRules.name},
                  "games": games, "every_update": stats([ms for ms, _, _ in updates]),
                  "after_unseen_move": stats([ms for ms, own, _ in updates if not own]),
                  "rebuilds": sum(rebuilt for _, _, rebuilt in updates), "machine": platform.machine(),
                  "git_commit": git_commit(), "runtime": runtime()}
        with open(args.out, "x") as f:
            f.write(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
