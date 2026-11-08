"""Report what each probe actually spent, per move of Pair A.

Only Pair A's plies are counted: the opponent's cost is not ours to tune, and
mixing the two halves hides exactly the quantity being measured.

Fallback is the column that decides whether a candidate is usable at all. A
fallback move is a uniform random legal move (chess_subgame_agent.act), so a
candidate with a high fallback rate is not a weaker search, it is no search.
"""
from __future__ import annotations

import glob
import json
import statistics
import sys


def mean(values):
    return statistics.mean(values) if values else float("nan")


print(f"{'probe':16} {'plies':>5} {'fb':>5} {'rounds':>7} {'nodes':>7} {'evals':>6} "
      f"{'ms/mv':>7} {'maxms':>7} {'cap:node':>8} {'cap:budget':>10} {'result':>12}")

for path in sorted(glob.glob(sys.argv[1] + "/probe-*/games.jsonl")):
    tag = path.split("/")[-2].replace("probe-", "")
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    if not rows:
        print(f"{tag:16} no games recorded")
        continue
    record = rows[0]
    mine = [p for p in record.get("plies") or [] if p.get("player") == record.get("player_a_color")]
    diag = [p["diagnostics"] for p in mine]
    searched = [d for d in diag if "solver_rounds_this_turn" in d]
    outcome = (record.get("winner") or "draw")
    if record.get("stopped_at_ply_limit"):
        outcome += "/ply-cap"
    print(f"{tag:16} {len(mine):>5} "
          f"{mean([d.get('fallback', 0.0) for d in diag]):>5.2f} "
          f"{mean([d['solver_rounds_this_turn'] for d in searched]):>7.1f} "
          f"{mean([d['search_nodes'] for d in searched]):>7.0f} "
          f"{mean([d.get('evaluator_calls', 0.0) for d in diag]):>6.1f} "
          f"{mean([d['elapsed_ms'] for d in diag]):>7.0f} "
          f"{max([d['elapsed_ms'] for d in diag], default=0):>7.0f} "
          f"{sum(d.get('stop:TreeCapacityError', 0.0) for d in diag):>8.0f} "
          f"{sum(d.get('stop:SearchBudgetError', 0.0) for d in diag):>10.0f} "
          f"{outcome:>12}")

print()
print("fb = share of A moves played as a uniform random legal move after the search")
print("     raised TreeCapacityError or SearchBudgetError; cap: columns count those.")
print("rounds/nodes/evals are averaged over the moves where the search did run.")
