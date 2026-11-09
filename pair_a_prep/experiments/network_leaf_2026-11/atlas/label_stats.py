"""Search statistics over the label records written so far (light JSON pass; safe on a login node).

usage: python label_stats.py <run dir with task-*/>
"""
import glob
import json
import sys
from collections import Counter

root = sys.argv[1]
rows = []
errors = []
games = 0
for p in sorted(glob.glob(f"{root}/task-*/progress.jsonl")):
    for line in open(p):
        if line.strip():
            r = json.loads(line)
            games += 1
            if r.get("error"):
                errors.append((p.split("/")[-2], r.get("game_id") or r.get("game"), str(r["error"])[:300]))
for f in sorted(glob.glob(f"{root}/task-*/part-*.jsonl")):
    for line in open(f):
        if not line.strip():
            continue
        r = json.loads(line)
        d = r["decision"]["diagnostics"]
        rows.append(dict(calls=d.get("evaluator_calls", 0), exp=d.get("expansions", 0),
                         ms=d.get("elapsed_ms", 0), fresh=d.get("projection:fresh", 0),
                         roots=d.get("projection:knowledge_roots", 0), retained=d.get("projection:retained", 0),
                         rounds=d.get("solver_rounds_this_turn", 0), nodes=d.get("search_nodes", 0),
                         stop=[k for k in d if k.startswith("growth_stop:") and d[k]],
                         ply=r["agent_input"]["observation"]["ply"]))
n = len(rows)
print(f"games(progress rows)={games} records={n} failed_games={len(errors)}")
for e in errors:
    print("ERROR", *e)
if not n:
    sys.exit()

def pct(vals, ps=(0.5, 0.9, 0.95, 0.99)):
    v = sorted(vals)
    out = {p: v[min(len(v) - 1, int(p * len(v)))] for p in ps}
    out["max"] = v[-1]
    return out

cons = [r["calls"] - r["exp"] for r in rows]
print("construction calls (calls-expansions):", pct(cons))
print("total calls:", pct([r["calls"] for r in rows]))
print("elapsed_ms:", pct([r["ms"] for r in rows]))
print("fresh roots:", pct([r["fresh"] for r in rows]), " knowledge roots:", pct([r["roots"] for r in rows]))
print("solver rounds this turn:", pct([r["rounds"] for r in rows]), " nodes:", pct([r["nodes"] for r in rows]))
print("growth stop reasons:", Counter(s for r in rows for s in r["stop"]).most_common())
# seconds per engine call on moves that used the whole clock (growth ran to the deadline)
full = [r for r in rows if "growth_stop:growth_deadline" in r["stop"] and r["calls"] > 0]
if full:
    print(f"moves that hit the growth deadline: {len(full)}; ms/call on them:",
          pct([r["ms"] / r["calls"] for r in full]))
print("records by ply bucket:", sorted(Counter(r["ply"] // 20 * 20 for r in rows).items()))
