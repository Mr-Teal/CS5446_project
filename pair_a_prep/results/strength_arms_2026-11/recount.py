"""Recount the strength arms from the raw game records in this folder, without the runner's own summaries.

usage:  python3 recount.py [folder with the extracted records]      (default: ./records, after
        mkdir records && for f in strength-*.tar.gz; do tar xzf $f -C records; done)

For every arm it prints
  - the schedule reconciliation: chunks planned, chunks that finished (the runner wrote summary.json), chunks that
    were cut off after writing some games (games.jsonl without summary.json), chunks without any record, and the
    games never played;
  - two scores, because the two conventions differ by a few games:
      "finished chunks"  only games of chunks that finished (what netv2_scores.py and the handover of 10 Nov report);
      "all completed"    every game that reached a result, including first games of chunks that were cut off later;
    each as wins / draws / losses from player_a's side, (wins + draws / 2) / scored games, 95 % Wilson interval;
  - failed games (ended with a runner error, never scored) and terminations.
Plain python3, standard library only.
"""
import collections
import glob
import json
import math
import os
import sys

PLANNED_CHUNKS, GAMES_PER_CHUNK = 50, 2
ARMS = ("fe-s16", "guard-fe-s16", "sf14-fe-s16", "net-fe-s16", "netv2-fe-s16", "netv2-vs-fe-s16",
        "netv2-vs-fe-guard-s16")


def wilson(p, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def line(label, wdl):
    w, d, l = wdl
    n = w + d + l
    score = (w + d / 2) / n if n else 0.0
    lo, hi = wilson(score, n)
    return f"  {label}: scored {n}; W/D/L {w}/{d}/{l}; score {score:.3f} [{lo:.3f}, {hi:.3f}]"


def recount(root, arm):
    term = collections.Counter()
    finished, cut_off, rows, failed, ply_limit = [], [], 0, 0, 0
    wdl = {"finished": [0, 0, 0], "all": [0, 0, 0]}
    names = set()
    for folder in glob.glob(os.path.join(root, f"strength-{arm}-c*")):
        chunk = int(folder.rsplit("-c", 1)[1])
        path = os.path.join(folder, "games.jsonl")
        if not os.path.exists(path):
            continue
        done = os.path.exists(os.path.join(folder, "summary.json"))
        (finished if done else cut_off).append(chunk)
        for text in open(path):
            if not text.strip():
                continue
            g = json.loads(text)
            rows += 1
            names.add((g.get("player_a", "")[:70], g.get("player_b", "")[:70]))
            if g.get("status") != "completed":
                failed += 1
                continue
            if g.get("stopped_at_ply_limit"):
                ply_limit += 1
                continue
            term[g.get("termination")] += 1
            a = g["player_a_color"]
            k = 0 if g["winner"] == a else (2 if g["winner"] in ("white", "black") else 1)
            wdl["all"][k] += 1
            if done:
                wdl["finished"][k] += 1
    planned = PLANNED_CHUNKS * GAMES_PER_CHUNK
    none = sorted(set(range(1, PLANNED_CHUNKS + 1)) - set(finished) - set(cut_off))
    print(arm)
    print(f"  schedule: {PLANNED_CHUNKS} chunks x {GAMES_PER_CHUNK} games = {planned}; finished chunks {len(finished)}; "
          f"cut off after some games {sorted(cut_off) if cut_off else 'none'}; no record {none if none else 'none'}")
    print(f"  game rows {rows}: reached a result {sum(wdl['all'])}, failed {failed}, ply limit {ply_limit}; "
          f"never played {planned - rows}")
    print(line("finished chunks", wdl["finished"]))
    print(line("all completed  ", wdl["all"]))
    print(f"  terminations: {dict(term)}")
    for a, b in sorted(names):
        print(f"  player_a: {a}\n  player_b: {b}")


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "records"
    for arm in ARMS:
        recount(root, arm)
