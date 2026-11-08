"""Is the exact-s16 sample biased by the games its chunks lost to memory?

exact-s16 kept 37 of 100 games; the other 63 died with their chunk when it passed
the 4.5 GiB cap. That is not a random 37 percent. Any paired comparison against
that arm is therefore computed on seeds selected for being cheap to track, and
cheap-to-track plausibly means short, quiet, information-poor games.

pruned-s16 is the control that makes this measurable: it ran all 100 games with
the same seeds and colours, so its per-seed results are available on both the
seeds exact-s16 survived and the seeds it lost. If pruned-s16 scores the same on
both subsets, selection has not moved the quantity being compared. If it scores
differently, the paired estimate carries that bias and the report must say so and
in which direction.

Game length is reported alongside, because it is the mechanism: the belief grows
with the ply, so a long game is what kills a chunk.
"""
from __future__ import annotations

import glob
import json
import statistics
import sys

RUNS = sys.argv[1]


def games(arm):
    out = {}
    for path in sorted(glob.glob(f"{RUNS}/strength-{arm}-c*/games.jsonl")):
        for line in open(path, encoding="utf-8"):
            if not line.strip():
                continue
            record = json.loads(line)
            out[record["seed"]] = record
    return out


def score(record):
    if record.get("status") != "completed" or record.get("stopped_at_ply_limit"):
        return None
    winner = record.get("winner")
    if winner is None or winner == "draw":
        return 0.5
    return 1.0 if winner == record.get("player_a_color") else 0.0


exact = games("exact-s16")
pruned = games("pruned-s16")

survived = set(exact)
lost = set(pruned) - survived

print(f"exact-s16 survived {len(survived)} seeds, lost {len(lost)} of the "
      f"{len(survived) + len(lost)} that pruned-s16 played\n")

print(f"{'pruned-s16 on':28} {'seeds':>6} {'scored':>7} {'score':>7} {'plies':>7} {'aborted':>8}")
for label, seeds in (("seeds exact-s16 survived", survived), ("seeds exact-s16 lost", lost),
                     ("all seeds", survived | lost)):
    rows = [pruned[s] for s in sorted(seeds) if s in pruned]
    scores = [v for v in (score(r) for r in rows) if v is not None]
    plies = [len(r.get("plies") or []) for r in rows]
    aborted = sum(1 for r in rows if r.get("status") != "completed")
    print(f"{label:28} {len(rows):>6} {len(scores):>7} "
          f"{statistics.mean(scores) if scores else float('nan'):>7.3f} "
          f"{statistics.mean(plies) if plies else float('nan'):>7.1f} {aborted:>8}")

print()
print("Pair A's own belief on the seeds it survived, for the mechanism:")
peaks = []
for seed, record in exact.items():
    colour = record.get("player_a_color")
    states = [u["state_count"] for u in record.get("tracker_updates") or []
              if u.get("player") == colour and u.get("state_count") is not None]
    if states:
        peaks.append((max(states), len(record.get("plies") or []), seed))
peaks.sort()
print(f"  survived seeds: peak states median {statistics.median(p for p, _, _ in peaks):,.0f}, "
      f"max {peaks[-1][0]:,} on seed {peaks[-1][2]} over {peaks[-1][1]} plies")
print(f"  longest survived game: {max(p[1] for p in peaks)} plies")
print(f"  pruned-s16 game length on lost seeds vs survived: "
      f"{statistics.mean([len(pruned[s].get('plies') or []) for s in sorted(lost)]):.1f} vs "
      f"{statistics.mean([len(pruned[s].get('plies') or []) for s in sorted(survived) if s in pruned]):.1f}")
