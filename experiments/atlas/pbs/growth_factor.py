"""How much can one exact belief update multiply the state count?

This sets the tail guard's threshold. The guard prunes before updating and keys
on the count the previous update left, so it reacts one update late: starting
from a threshold T it can be carried to T * g by the next update, where g is the
per-update growth factor measured here. The threshold has to be chosen so that
T * g still fits the memory cap, not so that T does.

Measured over Pair A's own tracker updates in the recorded exact-s16 games, which
is the unpruned arm and therefore the honest source for how the exact update
behaves. Only updates whose predecessor is large enough to matter are counted:
growth off a handful of states says nothing about growth off a million.
"""
import json
import pathlib
import sys

runs = pathlib.Path(sys.argv[1])
arm = sys.argv[2] if len(sys.argv) > 2 else "exact-s16"
floor = int(sys.argv[3]) if len(sys.argv) > 3 else 1000

ratios, big_ratios, peaks = [], [], []
games = 0
for games_file in sorted(runs.glob(f"strength-{arm}-c*/games.jsonl")):
    for line in games_file.read_text().splitlines():
        if not line.strip():
            continue
        game = json.loads(line)
        turns = [u for u in game["tracker_updates"]
                 if u.get("player") == game["player_a_color"]]
        if not turns:
            continue
        games += 1
        counts = [u.get("state_count") or 0 for u in turns]
        peaks.append(max(counts))
        for before, after in zip(counts, counts[1:]):
            if before >= floor:
                ratios.append(after / before)
                if before >= 10 * floor:
                    big_ratios.append(after / before)


def describe(name, values):
    if not values:
        print(f"{name}: none")
        return
    values = sorted(values)
    def q(p):
        return values[min(len(values) - 1, int(p * len(values)))]
    print(f"{name}: n={len(values)}  median {q(0.5):.2f}  p90 {q(0.90):.2f}  "
          f"p99 {q(0.99):.2f}  p999 {q(0.999):.2f}  max {values[-1]:.2f}")


print(f"{arm}: {games} games with tracker records")
describe(f"growth factor, previous >= {floor:,}", ratios)
describe(f"growth factor, previous >= {10 * floor:,}", big_ratios)
peaks.sort()
print(f"per-game peak states: median {peaks[len(peaks)//2]:,}  max {peaks[-1]:,}")
