"""Aggregate the strength arms and test the differences that matter.

Reads every pair_c/runs/strength-<arm>-c<chunk>/ directory, pools the chunks per
arm, and reports score rate with a paired bootstrap over colour pairs.

Why paired: seed_for_game is seed + game_index, so every game has its own seed and
colour alternates with the index. The same seed therefore means the same position
and the same colour in every arm, and the natural unit is one seed. Differencing
within a seed removes both the position's difficulty and the colour, which are the
dominant sources of variance. Section 5 of the report sets 20 non-constant paired
units as the threshold for a bootstrap; below that this reports raw rates and says so.

Score convention: a win is 1, a draw 0.5, a loss 0, from Pair A's side. Games that
failed or hit the ply cap are excluded from the score and counted separately,
because a tracker that aborts is not a draw.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import statistics


def load_arm(runs, arm):
    """Pool an arm's chunks. Returns per-game rows in seed order.

    Each chunk's scores are checked against the runner's own summary.json, so a
    disagreement between this file's reading of a result and the runner's is an
    error rather than a silently different number.
    """
    rows = []
    for directory in sorted(runs.glob(f"strength-{arm}-c*")):
        games = directory / "games.jsonl"
        if not games.is_file():
            continue
        before = len(rows)
        for index, line in enumerate(games.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            record = json.loads(line)
            plies = record.get("plies") or []
            rows.append({
                "chunk": directory.name,
                "index": index,
                "seed": record.get("seed"),
                "status": record.get("status"),
                "winner": record.get("winner"),
                "a_color": record.get("player_a_color"),
                "plies": len(plies),
                "termination": record.get("termination"),
                "ply_limit": bool(record.get("stopped_at_ply_limit")),
                "search_ms": sum(p.get("elapsed_ms", 0) for p in plies),
            })
        _cross_check(directory, rows[before:])
    return rows


def _cross_check(directory, chunk_rows):
    """Our wins and draws for a chunk must equal the runner's own counts."""
    summary = directory / "summary.json"
    if not summary.is_file():
        return  # a chunk killed mid-run writes no summary; its games still count
    recorded = json.loads(summary.read_text(encoding="utf-8"))
    scores = [score_for(r) for r in chunk_rows]
    wins = sum(1 for s in scores if s == 1.0)
    draws = sum(1 for s in scores if s == 0.5)
    if (wins, draws) != (recorded["player_a_wins"], recorded["draws"]):
        raise SystemExit(
            f"{directory.name}: computed {wins} wins and {draws} draws, "
            f"runner recorded {recorded['player_a_wins']} and {recorded['draws']}")


def score_for(row):
    """Pair A's score, or None when the game produced no result.

    winner is a colour. A completed game with no winner is a draw and scores 0.5;
    a ply-capped or failed game is not a draw and is excluded from the score.
    """
    if row["status"] != "completed" or row["ply_limit"] or row["a_color"] is None:
        return None
    winner = row["winner"]
    if winner is None or winner == "draw":
        return 0.5
    return 1.0 if winner == row["a_color"] else 0.0


def pair_key(row):
    """One seed is one game and one paired unit, shared across arms."""
    if row["seed"] is None:
        raise SystemExit("a game record has no seed; cannot pair across arms")
    return row["seed"]


def summarise(rows):
    scored = [(pair_key(r), score_for(r)) for r in rows]
    valid = [(k, s) for k, s in scored if s is not None]
    pairs = {}
    for key, score in valid:
        if key in pairs:
            raise SystemExit(f"seed {key} appears twice in one arm; chunk seeds overlap")
        pairs[key] = score
    return {
        "games": len(rows),
        "scored": len(valid),
        "failed": sum(1 for r in rows if r["status"] != "completed"),
        "ply_capped": sum(1 for r in rows if r["ply_limit"]),
        "score_rate": (sum(s for _, s in valid) / len(valid)) if valid else None,
        "mean_plies": statistics.mean([r["plies"] for r in rows]) if rows else None,
        "mean_search_s": statistics.mean([r["search_ms"] / 1000 for r in rows]) if rows else None,
        "complete_pairs": len(pairs),
        "pair_scores": pairs,
    }


def paired_bootstrap(left, right, draws=20000, seed=20261102):
    """Bootstrap the difference in pair scores over shared colour pairs."""
    shared = sorted(set(left) & set(right))
    if len(shared) < 20:
        return None
    diffs = [left[k] - right[k] for k in shared]
    if all(d == diffs[0] for d in diffs):
        return {"pairs": len(shared), "mean": diffs[0], "degenerate": True}
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        means.append(statistics.mean(rng.choices(diffs, k=len(diffs))))
    means.sort()
    return {"pairs": len(shared), "mean": statistics.mean(diffs),
            "lo": means[int(0.025 * draws)], "hi": means[int(0.975 * draws)],
            "degenerate": False,
            "p_two_sided": 2 * min(sum(1 for m in means if m <= 0),
                                   sum(1 for m in means if m >= 0)) / draws}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=pathlib.Path, required=True)
    parser.add_argument("--arms", nargs="+", default=["exact-s16", "exact-s256", "pruned-s16", "pruned-s256"])
    parser.add_argument("--regime-file", type=pathlib.Path, default=None,
                        help="chunk names collected under the old 4500m cap (logs/REGIME-4500m.txt); "
                             "splits each arm's games by cap, since the cap was raised mid-run")
    args = parser.parse_args()
    old_cap = set(args.regime_file.read_text(encoding="utf-8").split()) if args.regime_file else set()

    summaries = {}
    for arm in args.arms:
        rows = load_arm(args.runs, arm)
        if rows:
            summaries[arm] = summarise(rows)
            # A chunk killed for memory writes no rows, so a short arm is itself a
            # feasibility result and must not be read as a smaller sample by chance.
            summaries[arm]["missing"] = 100 - len(rows)
            # Directory strength-<arm>-c<n> was collected as chunk <arm>-c<n>.
            summaries[arm]["games_old_cap"] = sum(1 for r in rows if r["chunk"][len("strength-"):] in old_cap)

    print(f"{'arm':14} {'games':>6} {'lost':>5} {'scored':>7} {'failed':>7} {'capped':>7} "
          f"{'score':>8} {'plies':>7} {'search s':>9}")
    for arm, s in summaries.items():
        rate = f"{s['score_rate']:.3f}" if s["score_rate"] is not None else "-"
        print(f"{arm:14} {s['games']:>6} {s['missing']:>5} {s['scored']:>7} {s['failed']:>7} "
              f"{s['ply_capped']:>7} {rate:>8} {s['mean_plies']:>7.1f} {s['mean_search_s']:>9.1f}")
    print()
    print("lost = games whose chunk was killed for memory before they ran "
          "(out of 100 attempted per arm)")
    if old_cap:
        # Losses under two caps are two populations; never quote them as one rate.
        print()
        print("games by memory cap: @4500m were collected before the cap was raised, "
              "@8000m after (including retries of killed chunks)")
        print(f"{'arm':14} {'@4500m':>7} {'@8000m':>7}")
        for arm, s in summaries.items():
            print(f"{arm:14} {s['games_old_cap']:>7} {s['games'] - s['games_old_cap']:>7}")

    arms = list(summaries)
    print()
    for i, a in enumerate(arms):
        for b in arms[i + 1:]:
            result = paired_bootstrap(summaries[a]["pair_scores"], summaries[b]["pair_scores"])
            label = f"{a} - {b}"
            if result is None:
                print(f"{label:30} too few complete pairs for a paired bootstrap")
            elif result["degenerate"]:
                print(f"{label:30} every pair differs by {result['mean']:+.3f} "
                      f"over {result['pairs']} pairs; bootstrap degenerate")
            else:
                print(f"{label:30} {result['mean']:+.3f}  95% CI "
                      f"[{result['lo']:+.3f}, {result['hi']:+.3f}]  "
                      f"p={result['p_two_sided']:.4f}  n={result['pairs']} pairs")


if __name__ == "__main__":
    main()
