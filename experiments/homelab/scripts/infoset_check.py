"""What was our search infoset actually sized at, counting retained roots?

Obscuro's MinInfosetSize=256 is a FLOOR topped up on top of the nodes retained
from the previous move (Fig. 9 p.27: I starts as the saved tree's consistent
nodes, then `while |I| < min{|P|, 256}` samples more). Our sample_size is a CAP
on a fresh draw. So the two are only comparable if our retained roots are counted
too. chess_projection's audit records `retained` and `fresh`; this reports both.
"""
import json, statistics, sys

path = sys.argv[1]
rows = []
for line in open(path, encoding="utf-8"):
    if not line.strip():
        continue
    g = json.loads(line)
    colour = g["player_a_color"]
    for p in g["plies"]:
        if p.get("player") != colour:
            continue
        d = p.get("diagnostics") or {}
        rows.append(d)

for key in ("projection:retained", "projection:fresh", "projection:knowledge_roots",
            "projection:outside_current", "projection:incomplete_cut", "search_nodes"):
    vals = [d[key] for d in rows if key in d and d[key] is not None]
    if vals:
        print("%-28s n=%d  mean %.1f  median %g  max %g" % (
            key, len(vals), statistics.mean(vals), statistics.median(vals), max(vals)))

total = [d["projection:retained"] + d["projection:fresh"] for d in rows
         if "projection:retained" in d and "projection:fresh" in d]
if total:
    print("retained+fresh (our |I|)     n=%d  mean %.1f  median %g  max %g" % (
        len(total), statistics.mean(total), statistics.median(total), max(total)))
    print("turns at or above 256:       %d of %d" % (sum(1 for v in total if v >= 256), len(total)))
