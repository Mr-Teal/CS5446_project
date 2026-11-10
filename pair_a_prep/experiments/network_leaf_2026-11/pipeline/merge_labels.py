"""Merge several solver-label folders into one training folder.

Every label run names its parts part-0000.jsonl upward, so copies need a prefix per source or they
overwrite each other. The merged folder gets NO manifest.json: Pair B's validator accepts a folder
without one ("absent; accepted by the training loader"), and with one it would demand every record's
config_id to match it. The sources are validated separately beforehand (validate_labels.py).

Usage: python3 merge_labels.py <out folder> <source folder>...
Each source's parts are copied as part-<parent>-<sourcename>-NNNN.jsonl ("part-*.jsonl" still matches,
which is what train_belief_net.py and eval_belief_net.py read by default). The parent folder is part of
the name because two label rounds both have task-1 .. task-N: with the task name alone the second
round's parts silently overwrote the first round's (found 2026-11-10 on the 480-game merge). Empty parts
are skipped. All sources are read first; if more than one config_id appears, or two parts would land on
the same name, nothing is copied and the script fails, because mixing label meanings is what
label_definitions.md warns against.
"""
import json
import shutil
import sys
from pathlib import Path

out = Path(sys.argv[1])
sources = [Path(p) for p in sys.argv[2:]]
if not sources:
    raise SystemExit(__doc__)

configs, plan, total = {}, [], 0
for src in sources:
    parts = [p for p in sorted(src.glob("part-*.jsonl")) if p.stat().st_size > 0]
    n = 0
    for part in parts:
        with part.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    n += 1
                    cid = json.loads(line).get("config_id")
                    configs[cid] = configs.get(cid, 0) + 1
        plan.append((part, out / f"part-{src.parent.name}-{src.name}-{part.stem.split('-')[-1]}.jsonl"))
    print(f"{src}: {len(parts)} non-empty parts, {n} records")
    total += n
print(f"config_ids: {configs}")
if len(configs) != 1:
    raise SystemExit("refusing to merge: more than one config_id across the sources; nothing copied")
if len({dest for _, dest in plan}) != len(plan):
    raise SystemExit("refusing to merge: two parts would get the same destination name; nothing copied")
out.mkdir(parents=True, exist_ok=True)
for part, dest in plan:
    shutil.copyfile(part, dest)
print(f"merged {total} records from {len(plan)} parts into {out}")
