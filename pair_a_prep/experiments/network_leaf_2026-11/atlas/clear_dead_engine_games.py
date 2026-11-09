"""Remove the placeholder parts of games that died with a dead engine and produced no records, so a
resumed task replays them. Keeps every part that holds records (also failed games with partial records).

usage: python3 clear_dead_engine_games.py <run dir> <task-N> [<task-M> ...]
"""
import json
import os
import sys

root = sys.argv[1]
for task in sys.argv[2:]:
    p = os.path.join(root, task, "progress.jsonl")
    rows = [json.loads(l) for l in open(p) if l.strip()]
    keep = []
    for r in rows:
        dead = r.get("error") and "EngineTerminated" in str(r["error"]) and r.get("records", 0) == 0
        if not dead:
            keep.append(r)
            continue
        part = os.path.join(root, task, r["part"])
        if os.path.exists(part):
            n = sum(1 for l in open(part) if l.strip())
            if n == 0:
                os.remove(part)
                print(task, "game", r["index"], r["part"], "empty -> removed, row dropped")
            else:
                keep.append(r)
                print(task, "game", r["index"], r["part"], "has", n, "records -> kept")
        else:
            print(task, "game", r["index"], r["part"], "no part file -> row dropped")
    keep.sort(key=lambda r: r["index"])
    with open(p, "w") as f:
        for r in keep:
            f.write(json.dumps(r) + "\n")
    parts = sorted(x for x in os.listdir(os.path.join(root, task)) if x.startswith("part-"))
    print(task, "progress rows now", len(keep), "parts now", len(parts))
