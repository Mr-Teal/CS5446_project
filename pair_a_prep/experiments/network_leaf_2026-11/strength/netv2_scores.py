"""Scores of the strength arms with 95 % Wilson intervals, from each chunk's summary.json.

usage: python3 netv2_scores.py            (VM host; python3 only)
Score = (wins + 0.5 draws) / scored games; capped and failed games are excluded and counted separately,
as analyse2.py does. For the two netv2 arms it also lists per-chunk results next to the fe-s16 chunk with the
same seeds, for a paired reading.
"""
import glob
import json
import math

R = "/home/dev/cs5446-review"
ARMS = (("fe-s16", "wt-dev", "material-leaf agent vs OnePlyBot"),
        ("sf14-fe-s16", "wt-dev", "Stockfish-d1-leaf agent vs OnePlyBot"),
        ("net-fe-s16", "wt-net", "v1 network leaf (material-label) vs OnePlyBot"),
        ("netv2-fe-s16", "wt-net", "v2 network leaf (solver-d8 labels) vs OnePlyBot"),
        ("netv2-vs-fe-s16", "wt-net", "v2 net leaf vs material-leaf agent, exact (frozen)"),
        ("netv2-vs-fe-guard-s16", "wt-net", "v2 net leaf vs material-leaf agent, guard both"))


def wilson(p, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def chunks(arm, root):
    out = {}
    for f in glob.glob(f"{R}/{root}/pair_c/runs/strength-{arm}-c*/summary.json"):
        d = json.load(open(f))
        n = int(f.split("-c")[-1].split("/")[0])
        out[n] = d
    return out


table = {}
for arm, root, what in ARMS:
    cs = chunks(arm, root)
    W = sum(d["player_a_wins"] for d in cs.values())
    D = sum(d["draws"] for d in cs.values())
    L = sum(d["player_a_losses"] for d in cs.values())
    cap = sum(d["games_capped"] for d in cs.values())
    fail = sum(d["games_failed"] for d in cs.values())
    ms = [d["timing"]["player_a"]["mean_ms_per_move"] for d in cs.values() if d["timing"]["player_a"]["mean_ms_per_move"]]
    g = W + D + L
    p = (W + 0.5 * D) / g if g else 0.0
    lo, hi = wilson(p, g)
    table[arm] = cs
    print(f"{arm:16s} {what:48s} chunks={len(cs):2d} games={g:3d} W/D/L={W}/{D}/{L} score={p:.3f} "
          f"[{lo:.3f}, {hi:.3f}] capped={cap} failed={fail} A ms/move={sum(ms) / max(len(ms), 1):.0f}")

for arm in ("netv2-fe-s16", "netv2-vs-fe-s16", "netv2-vs-fe-guard-s16"):
    cs, ref = table.get(arm, {}), table.get("fe-s16", {})
    both = sorted(set(cs) & set(ref))
    if both:
        a = sum(cs[n]["player_a_wins"] + 0.5 * cs[n]["draws"] for n in both)
        b = sum(ref[n]["player_a_wins"] + 0.5 * ref[n]["draws"] for n in both)
        g = sum(cs[n]["player_a_wins"] + cs[n]["draws"] + cs[n]["player_a_losses"] for n in both)
        print(f"paired on the {len(both)} chunks fe-s16 also has: {arm} {a:.1f} vs fe-s16 {b:.1f} points over {g} games")
