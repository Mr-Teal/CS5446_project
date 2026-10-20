"""Time the honest particle tracker (pairb.tracker) on seeded random games.

    .venv/bin/python scripts/bench_tracker.py --games 5 --plies 40 --particles 256

Plays --games games of up to --plies uniformly random moves with Pair B's stand-in rules. A tracker
for each colour is fed as fow_shared's play_game feeds them, the game-ending view included, and
every update is timed (the referee's work of making the view is not). Prints the median,
95th-percentile and slowest milliseconds per update, the same for the updates after a move the
player did not see (the slow ones: every particle is expanded by every move), and how many updates
had to rebuild. Fog Lab's target is a median of at most 2000 ms at 256 particles.
"""
import argparse
import platform
import random
import statistics
import time

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


def summary(milliseconds: list[float]) -> str:
    p95 = statistics.quantiles(milliseconds, n=100, method="inclusive")[94] if len(milliseconds) > 1 else milliseconds[0]
    return (f"median {statistics.median(milliseconds):.0f} ms, 95th percentile {p95:.0f} ms, "
            f"slowest {max(milliseconds):.0f} ms ({len(milliseconds)} updates)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--games", type=int, default=5)
    ap.add_argument("--plies", type=int, default=40, help="the most plies per game")
    ap.add_argument("--particles", type=int, default=256, help="the tracker's cap")
    ap.add_argument("--guesses", type=int, default=8, help="hypotheses per belief")
    ap.add_argument("--seed", type=int, default=0, help="game g is played with seed + g")
    args = ap.parse_args()

    updates = []
    for game in range(args.games):
        started = time.perf_counter()
        played = play(args.seed + game, args.plies, args.particles, args.guesses)
        updates += played
        print(f"game {game + 1}/{args.games}: {len(played)} updates in {time.perf_counter() - started:.1f} s, "
              f"{sum(rebuilt for _, _, rebuilt in played)} rebuilds", flush=True)
    print(f"\n{args.particles} particles, {args.guesses} guesses, Pair B stand-in rules, "
          f"Python {platform.python_version()} on {platform.machine()}")
    print("every update:            " + summary([ms for ms, _, _ in updates]))
    print("after an unseen move:    " + summary([ms for ms, own, _ in updates if not own]))
    print(f"rebuilds: {sum(rebuilt for _, _, rebuilt in updates)}")


if __name__ == "__main__":
    main()
