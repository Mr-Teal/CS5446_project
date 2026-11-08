"""How many hypotheses does sample_size actually hand the search, and out of what?"""
import json, sys

path = sys.argv[1]
line = open(path, encoding="utf-8").readline()
g = json.loads(line)
colour = g["player_a_color"]
ups = [u for u in g["tracker_updates"] if u.get("player") == colour]

peak = max(ups, key=lambda u: u["state_count"] or 0)
for label, u in (("peak", peak), ("last", ups[-1])):
    print("%s turn: ply %s  states %s  histories %.3e  returned %s  weighting %s" % (
        label, u["ply"], format(u["state_count"], ","), u["population_size"],
        u["returned_hypotheses"], u["weighting"]))

counts = sorted({u["returned_hypotheses"] for u in ups})
print("returned_hypotheses over the game:", counts)
print("turns where returned < 16: %d of %d" % (
    sum(1 for u in ups if (u["returned_hypotheses"] or 0) < 16), len(ups)))
