"""Compare one recorded game between two platforms, field by field.

Reports the first ply whose move differs, and for every ply before that, which
diagnostic keys disagree and by how much. Timing fields are expected to differ
and are reported separately from the rest, because only the non-timing fields
bear on whether the two platforms made the same decision.
"""
import json
import sys

TIMING = {"elapsed_ms", "over_budget", "submission_reserve_ms"}


def load(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def cmp_dict(a, b, prefix=""):
    diffs = []
    for k in sorted(set(a) | set(b)):
        va, vb = a.get(k, "<absent>"), b.get(k, "<absent>")
        if isinstance(va, dict) and isinstance(vb, dict):
            diffs += cmp_dict(va, vb, f"{prefix}{k}.")
        elif va != vb:
            diffs.append((f"{prefix}{k}", va, vb))
    return diffs


def main():
    ga = load(sys.argv[1])
    gb = load(sys.argv[2])
    idx = int(sys.argv[3])
    a, b = ga[idx], gb[idx]
    print(f"seed {a['seed']}  A plays {a['player_a_color']}")
    print(f"  plies: {len(a['plies'])} vs {len(b['plies'])}")
    print(f"  winner: {a['winner']} vs {b['winner']}")

    first = None
    for i, (pa, pb) in enumerate(zip(a["plies"], b["plies"])):
        if pa["move"] != pb["move"]:
            first = i
            break
    if first is None:
        print("  moves: identical over the shared prefix")
    else:
        pa, pb = a["plies"][first], b["plies"][first]
        print(f"\n  FIRST MOVE DIFFERENCE at ply {first} "
              f"({pa['player']}, {pa['agent_name']}): {pa['move']} vs {pb['move']}")

    end = first if first is not None else min(len(a["plies"]), len(b["plies"]))
    timing_only = 0
    real = []
    for i in range(end):
        d = cmp_dict(a["plies"][i], b["plies"][i])
        nd = [x for x in d if x[0].split(".")[-1] not in TIMING]
        if d and not nd:
            timing_only += 1
        if nd:
            real.append((i, a["plies"][i]["player"], a["plies"][i]["agent_name"], nd))
    print(f"\n  plies before that point: {end}")
    print(f"    differing only in timing fields: {timing_only}")
    print(f"    differing in a non-timing field: {len(real)}")
    for i, player, agent, nd in real[:12]:
        print(f"      ply {i} ({player}, {agent}):")
        for k, va, vb in nd[:8]:
            print(f"        {k}: {va!r} vs {vb!r}")

    # Tracker updates: the belief itself.
    ta, tb = a["tracker_updates"], b["tracker_updates"]
    print(f"\n  tracker updates: {len(ta)} vs {len(tb)}")
    tdiff = []
    for i, (ua, ub) in enumerate(zip(ta, tb)):
        d = [x for x in cmp_dict(ua, ub) if x[0].split(".")[-1] not in TIMING]
        if d:
            tdiff.append((i, ua.get("ply"), d))
    print(f"    differing in a non-timing field: {len(tdiff)} of {min(len(ta), len(tb))}")
    for i, ply, d in tdiff[:10]:
        print(f"      update {i} (ply {ply}): " +
              "; ".join(f"{k}: {va!r} vs {vb!r}" for k, va, vb in d[:4]))


if __name__ == "__main__":
    main()
