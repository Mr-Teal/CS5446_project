"""Fingerprint a recorded chunk so two platforms can be compared exactly.

exact-s16 sets no search-budget keys, so SearchFactory leaves stop_on_time at
false: the agent stops after a fixed number of PCFR+ rounds and never reads the
wall clock. Its moves therefore cannot depend on how fast the machine is, and a
homelab chunk and an Atlas chunk running the same seed must agree move for move.
Anything that disagrees is a real platform difference, not noise.

Every field that measures time is dropped -- elapsed_ms, and over_budget with
it, since that is derived from elapsed_ms against the move budget. What is left
is the decision itself: the move played, the size of the tree searched, the
rounds solved, and the belief the tracker returned.
"""
import hashlib
import json
import sys
from pathlib import Path

TIMING = {"elapsed_ms", "over_budget"}


def strip(obj):
    if isinstance(obj, dict):
        return {k: strip(v) for k, v in sorted(obj.items()) if k not in TIMING}
    if isinstance(obj, list):
        return [strip(v) for v in obj]
    return obj


def fingerprint(chunk_dir):
    games = chunk_dir / "games.jsonl"
    if not games.exists():
        return None
    out = []
    for line in games.read_text().splitlines():
        if not line.strip():
            continue
        g = json.loads(line)
        moves = [p["move"] for p in g["plies"]]
        body = strip({"plies": g["plies"], "tracker_updates": g["tracker_updates"]})
        out.append({
            "game": g["game"],
            "seed": g["seed"],
            "color": g["player_a_color"],
            "status": g["status"],
            "winner": g["winner"],
            "termination": g["termination"],
            "n_plies": len(moves),
            "moves": " ".join(moves),
            "digest": hashlib.sha256(
                json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()[:16],
        })
    return out


def main():
    root = Path(sys.argv[1])
    for chunk in sys.argv[2:]:
        d = root / f"strength-exact-s16-c{chunk}"
        rec = fingerprint(d)
        if rec is None:
            print(f"c{chunk}\tMISSING")
            continue
        for r in rec:
            print(
                f"c{chunk}\tgame{r['game']}\tseed{r['seed']}\t{r['color']}\t"
                f"{r['status']}\t{r['winner']}\t{r['termination']}\t"
                f"plies={r['n_plies']}\tdigest={r['digest']}"
            )
            print(f"\tmoves: {r['moves']}")


if __name__ == "__main__":
    main()
