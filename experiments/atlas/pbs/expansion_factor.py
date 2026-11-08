"""Measure how far one exact update expands a belief that was just pruned.

The guard prunes before updating, so the state count the runner records is the
count AFTER that update. The ratio of the two is the factor by which a threshold
has to be multiplied to get the real peak, which is what a memory cap has to
hold. Turns where the previous recorded count was below the threshold did not
prune and are excluded.
"""
import json
import sys

threshold = int(sys.argv[1])
ratios = []
for path in sys.argv[2:]:
    for game in [json.loads(l) for l in open(path) if l.strip()]:
        turns = [u for u in game["tracker_updates"]
                 if u.get("player") == game["player_a_color"]]
        print(f"\n{path.split('/')[-2]} seed {game['seed']}  threshold {threshold:,}")
        print("  ply   pre-update  pruned to   post-update   factor  complete")
        previous = None
        for u in turns:
            now = u.get("state_count") or 0
            if previous is not None and previous > threshold:
                ratios.append(now / threshold)
                print(f"  {u['ply']:>4}  {previous:>10,}  {threshold:>9,}  "
                      f"{now:>11,}  {now / threshold:>7.1f}  {u.get('support_complete')}")
            previous = now

if ratios:
    ratios.sort()
    print(f"\nprunes observed: {len(ratios)}")
    print(f"expansion factor  min {ratios[0]:.1f}  median {ratios[len(ratios)//2]:.1f}  "
          f"max {ratios[-1]:.1f}")
else:
    print("\nno prune occurred")
