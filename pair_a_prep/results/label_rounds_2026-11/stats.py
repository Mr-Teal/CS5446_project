"""Counts of the label rounds and of generation-0 self-play, from the per-game logs in this folder.

usage:  python3 stats.py          (run in this folder; standard library only)

Each *-progress.jsonl file has one row per attempted game, written by pair_a_prep/label_run.py when the game ended:
game id, seed, plies, labelled positions ("records"), fallbacks, tracker prunings ("guards"), winner, wall time and
the error if the game failed. The label records themselves are not in git.
"""
import collections
import json
import statistics as st

FILES = (("label round 2 (SF-d8 leaf, 30 s, Atlas)", "round2-progress.jsonl"),
         ("label round 3 (SF-d8 leaf, 30 s, Atlas)", "round3-progress.jsonl"),
         ("generation-0 self-play, VM (value network v2 leaf on GPU, 2 s)", "gen0-vm-progress.jsonl"),
         ("generation-0 self-play, Atlas (value network v2 leaf on one CPU thread, 12 s)", "gen0-atlas-progress.jsonl"))

for name, path in FILES:
    rows = [json.loads(line) for line in open(path) if line.strip()]
    ok = [r for r in rows if not r.get("error")]
    errors = collections.Counter((r["error"] or "").split(":")[0] for r in rows if r.get("error"))
    winners = collections.Counter(str(r.get("winner")) for r in ok)
    fallbacks = sum(r["fallbacks"] for r in rows)
    records = sum(r["records"] for r in rows)
    plies = sum(r["plies"] for r in rows)
    print(name)
    print(f"  games {len(rows)}, completed {len(ok)}, failed {dict(errors)}")
    print(f"  labelled positions {records}, fallbacks {fallbacks} "
          f"({100 * fallbacks / (fallbacks + records):.1f} % of labelled-or-fallback moves, "
          f"{100 * fallbacks / plies:.1f} % of {plies} plies)")
    print(f"  plies per game: median {st.median(r['plies'] for r in rows)} over all games, "
          f"{st.median(r['plies'] for r in ok)} over completed games")
    print(f"  completed games by winner {dict(winners)}, stopped at the ply limit "
          f"{sum(1 for r in ok if r.get('stopped_at_ply_limit'))}")
    print(f"  wall time per completed game: median {st.median(r['wall_s'] for r in ok):.0f} s")
