"""Report what the tail guard did in a recorded run."""
import json
import sys


def load(path):
    return [json.loads(l) for l in open(path) if l.strip()]


first = True
for path in sys.argv[1:]:
    for game in load(path):
        turns = [u for u in game["tracker_updates"]
                 if u.get("player") == game["player_a_color"]]
        if first:
            print("tracker_update keys:", sorted(turns[0].keys()), "\n")
            first = False
        states = [u.get("states") or u.get("state_count") or 0 for u in turns]
        pops = [u.get("population_size") or 0 for u in turns]
        incomplete = [u for u in turns if u.get("support_complete") is False]
        label = path.split("/")[-2]
        print(f"{label} seed {game['seed']}: {len(turns)} Pair A turns, "
              f"{len(game['plies'])} plies, winner {game['winner']}")
        print(f"   max states {max(states):,}   max population {max(pops):.4g}")
        print(f"   support_complete false on {len(incomplete)} of {len(turns)} turns")
