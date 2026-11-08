"""Is our belief in the same regime as the paper's?

Obscuro reports "Average number of possible positions: 17,264" (p.21) and bounds
|P| <= 10^6 "usually" (p.4). Our arm table reports PEAK state_count per game,
which is not the same statistic. This computes the per-turn average over all of
Pair A's turns in an arm, which is the comparable one, plus the distribution, so
the comparison to 17,264 is like for like.
"""
import glob, json, statistics, sys

runs, arm = sys.argv[1], sys.argv[2]
counts, per_game_peak = [], []
for path in sorted(glob.glob(f"{runs}/strength-{arm}-c*/games.jsonl")):
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        g = json.loads(line)
        colour = g["player_a_color"]
        mine = [u["state_count"] for u in g["tracker_updates"]
                if u.get("player") == colour and u.get("state_count") is not None]
        if mine:
            counts.extend(mine)
            per_game_peak.append(max(mine))

q = statistics.quantiles(counts, n=100)
print(f"{arm}: {len(per_game_peak)} games, {len(counts)} Pair A turns")
print(f"  per-turn states: mean {statistics.mean(counts):,.0f}  median {statistics.median(counts):,.0f}")
print(f"  p75 {q[74]:,.0f}  p90 {q[89]:,.0f}  p99 {q[98]:,.0f}  max {max(counts):,}")
print(f"  turns above the paper's 17,264 average: {sum(1 for c in counts if c > 17264)} "
      f"({100 * sum(1 for c in counts if c > 17264) / len(counts):.0f}%)")
print(f"  turns above the paper's 10^6 bound:     {sum(1 for c in counts if c > 10**6)} "
      f"({100 * sum(1 for c in counts if c > 10**6) / len(counts):.1f}%)")
print(f"  per-game peak: mean {statistics.mean(per_game_peak):,.0f}  max {max(per_game_peak):,}")
