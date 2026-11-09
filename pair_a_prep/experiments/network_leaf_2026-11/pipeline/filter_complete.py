"""Keep only the parts of games that have a progress row (complete or failed-with-partial-records games),
so a part still being written is never shipped. usage: python3 filter_complete.py <src run dir> <dst dir>"""
import glob
import json
import os
import shutil
import sys

src, dst = sys.argv[1], sys.argv[2]
if os.path.exists(dst):
    shutil.rmtree(dst)
os.makedirs(dst)
games = records = fallbacks = failed = 0
for task in sorted(glob.glob(f"{src}/task-*")):
    prog = os.path.join(task, "progress.jsonl")
    if not os.path.exists(prog):
        continue
    rows = [json.loads(l) for l in open(prog) if l.strip()]
    out = os.path.join(dst, os.path.basename(task))
    os.makedirs(out)
    kept = []
    for r in rows:
        part = r.get("part")
        if part and os.path.exists(os.path.join(task, part)) and os.path.getsize(os.path.join(task, part)) > 0:
            shutil.copy2(os.path.join(task, part), os.path.join(out, part))
            kept.append(r)
    with open(os.path.join(out, "progress.jsonl"), "w") as f:
        for r in kept:
            f.write(json.dumps(r) + "\n")
    games += len(kept)
    records += sum(r.get("records", 0) for r in kept)
    fallbacks += sum(r.get("fallbacks", 0) for r in kept)
    failed += sum(1 for r in kept if r.get("error"))
print(f"kept games={games} records={records} fallbacks={fallbacks} ({100 * fallbacks / max(1, records + fallbacks):.1f}%) failed_games={failed}")
