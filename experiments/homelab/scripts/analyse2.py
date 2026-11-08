"""Aggregate every arm on strength AND on what it cost to get there.

analyse.py answered "who scored better". That turned out to be only half the
question: the first round's exact-s256 arm scored 0.042 not because 256
hypotheses play badly but because the search could not be built at all, so
chess_subgame_agent.act() answered the resulting TreeCapacityError with
self._rng.choice(moves) on 71 percent of turns. A score table alone cannot tell
that apart from weak play, which is why these columns exist.

Columns, all restricted to Pair A's own plies:

  score     win 1, draw 0.5, loss 0, over games that completed. A game that
            failed or hit the ply cap is not a draw and is excluded, and counted
            separately, because an aborted tracker is not half a point.
  lost      games whose chunk was killed before they ran, out of 100 attempted.
            A memory kill takes the whole chunk, so this is a feasibility number
            and must not be read as a smaller sample drawn at random.
  fb        share of A moves played as a uniform random legal move after the
            search raised SearchBudgetError or TreeCapacityError. Anything far
            from zero means the arm is not measuring a search.
  rounds    PCFR+ rounds completed on the moves where the search did run.
  ms/mv     wall clock per A move, against the 5,000 ms budget the config gives.
  peak st   largest state_count the tracker held in a game, averaged over games,
            and the single largest over the arm. This is the term that decides
            whether the arm fits in memory: it is the number of distinct positions
            stored in the belief DAG, 78 packed bytes each plus path structure.
  max hist  largest population_size seen, which is a different quantity and is
            why it is reported separately: it counts move HISTORIES consistent
            with the observations, not stored positions. _belief_graph shares path
            prefixes across edges, so this runs to 1e30 and beyond while the
            stored positions stay near a million. It matters here because
            BeliefTracker.prune caps histories, so the pruned arms' cap of 10,000
            is a cut against that number, not against the stored positions.
  trk s     total time Pair A's tracker spent updating, per game.

Pairing is unchanged: seed_for_game is seed + game_index, so a seed fixes the
position and the colour, every arm runs the same seeds, and the paired unit is one
seed. Differencing within a seed removes position difficulty and colour, which
dominate the variance. Fewer than 20 non-constant pairs reports no interval.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import statistics

DEFAULT_ARMS = ["exact-s16", "exact-s256", "pruned-s16", "pruned-s256",
                "clock-s16", "clock-s64"]


def load_arm(runs, arm):
    """Pool an arm's chunks, cross-checking each against the runner's own counts."""
    rows = []
    for directory in sorted(runs.glob(f"strength-{arm}-c*")):
        games = directory / "games.jsonl"
        if not games.is_file():
            continue
        before = len(rows)
        for index, line in enumerate(games.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            rows.append(_row(json.loads(line), directory.name, index))
        _cross_check(directory, rows[before:])
    return rows


def _row(record, chunk, index):
    plies = record.get("plies") or []
    colour = record.get("player_a_color")
    mine = [p for p in plies if p.get("player") == colour]
    diag = [p.get("diagnostics") or {} for p in mine]
    searched = [d for d in diag if "solver_rounds_this_turn" in d]
    # population_size is reported per tracker update and is null for the opponent's
    # particle tracker, so filter on both the player and the field being present.
    updates = [u for u in record.get("tracker_updates") or []
               if u.get("player") == colour and u.get("population_size") is not None]
    return {
        "chunk": chunk, "index": index, "seed": record.get("seed"),
        "status": record.get("status"), "winner": record.get("winner"),
        "a_color": colour, "plies": len(plies),
        "termination": record.get("termination"),
        "ply_limit": bool(record.get("stopped_at_ply_limit")),
        "search_ms": sum(d.get("elapsed_ms", 0.0) for d in diag),
        "moves": len(mine),
        "fallbacks": sum(d.get("fallback", 0.0) for d in diag),
        "rounds": [d["solver_rounds_this_turn"] for d in searched],
        "move_ms": [d.get("elapsed_ms", 0.0) for d in diag],
        "peak_states": max((u["state_count"] for u in updates), default=None),
        "peak_hist": max((u["population_size"] for u in updates), default=None),
        "tracker_ms": sum(u.get("elapsed_ms", 0.0) for u in updates),
    }


def _cross_check(directory, chunk_rows):
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
    if row["status"] != "completed" or row["ply_limit"] or row["a_color"] is None:
        return None
    winner = row["winner"]
    if winner is None or winner == "draw":
        return 0.5
    return 1.0 if winner == row["a_color"] else 0.0


def summarise(rows, attempted):
    pairs = {}
    for row in rows:
        score = score_for(row)
        if score is None:
            continue
        if row["seed"] is None:
            raise SystemExit("a game record has no seed; cannot pair across arms")
        if row["seed"] in pairs:
            raise SystemExit(f"seed {row['seed']} appears twice in one arm; chunk seeds overlap")
        pairs[row["seed"]] = score
    moves = sum(r["moves"] for r in rows)
    rounds = [v for r in rows for v in r["rounds"]]
    move_ms = [v for r in rows for v in r["move_ms"]]
    peaks = [r["peak_states"] for r in rows if r["peak_states"] is not None]
    hists = [r["peak_hist"] for r in rows if r["peak_hist"] is not None]
    return {
        "games": len(rows), "lost": attempted - len(rows),
        "scored": len(pairs),
        "failed": sum(1 for r in rows if r["status"] != "completed"),
        "ply_capped": sum(1 for r in rows if r["ply_limit"]),
        "score_rate": (statistics.mean(pairs.values()) if pairs else None),
        "mean_plies": statistics.mean([r["plies"] for r in rows]) if rows else None,
        "fb": (sum(r["fallbacks"] for r in rows) / moves) if moves else None,
        "rounds": statistics.mean(rounds) if rounds else None,
        "move_ms": statistics.mean(move_ms) if move_ms else None,
        "peak_states": statistics.mean(peaks) if peaks else None,
        "max_states": max(peaks) if peaks else None,
        "max_hist": max(hists) if hists else None,
        "tracker_s": statistics.mean([r["tracker_ms"] / 1000 for r in rows]) if rows else None,
        "pair_scores": pairs,
    }


def paired_bootstrap(left, right, draws=20000, seed=20261102):
    shared = sorted(set(left) & set(right))
    if len(shared) < 20:
        return None
    diffs = [left[k] - right[k] for k in shared]
    if all(d == diffs[0] for d in diffs):
        return {"pairs": len(shared), "mean": diffs[0], "degenerate": True}
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(draws))
    return {"pairs": len(shared), "mean": statistics.mean(diffs),
            "lo": means[int(0.025 * draws)], "hi": means[int(0.975 * draws)],
            "degenerate": False,
            "p_two_sided": 2 * min(sum(1 for m in means if m <= 0),
                                   sum(1 for m in means if m >= 0)) / draws}


def fmt(value, spec):
    return format(value, spec) if value is not None else "-"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=pathlib.Path, required=True)
    parser.add_argument("--arms", nargs="+", default=DEFAULT_ARMS)
    parser.add_argument("--attempted", type=int, default=100,
                        help="games launched per arm, so losses can be counted")
    args = parser.parse_args()

    summaries = {}
    for arm in args.arms:
        rows = load_arm(args.runs, arm)
        if rows:
            summaries[arm] = summarise(rows, args.attempted)

    print(f"{'arm':12} {'gm':>4} {'lost':>5} {'scr':>4} {'fail':>5} {'cap':>4} "
          f"{'score':>7} {'plies':>6} {'fb':>5} {'rounds':>7} {'ms/mv':>7} "
          f"{'peak st':>9} {'max st':>9} {'trk s':>7} {'max hist':>10}")
    for arm, s in summaries.items():
        print(f"{arm:12} {s['games']:>4} {s['lost']:>5} {s['scored']:>4} {s['failed']:>5} "
              f"{s['ply_capped']:>4} {fmt(s['score_rate'], '7.3f')} "
              f"{fmt(s['mean_plies'], '6.1f')} {fmt(s['fb'], '5.2f')} "
              f"{fmt(s['rounds'], '7.1f')} {fmt(s['move_ms'], '7.0f')} "
              f"{fmt(s['peak_states'], '9.0f')} {fmt(s['max_states'], '9.0f')} "
              f"{fmt(s['tracker_s'], '7.1f')} "
              f"{('%10.1e' % s['max_hist']) if s['max_hist'] is not None else '-':>10}")
    print()
    print(f"lost = games whose chunk was killed before they ran, of {args.attempted} attempted")
    print("fb   = share of A moves played as a uniform random legal move after the")
    print("       search raised SearchBudgetError or TreeCapacityError")
    print()

    arms = list(summaries)
    for i, a in enumerate(arms):
        for b in arms[i + 1:]:
            result = paired_bootstrap(summaries[a]["pair_scores"], summaries[b]["pair_scores"])
            label = f"{a} - {b}"
            if result is None:
                shared = len(set(summaries[a]["pair_scores"]) & set(summaries[b]["pair_scores"]))
                print(f"{label:26} {shared} shared seeds, below the 20 needed for an interval")
            elif result["degenerate"]:
                print(f"{label:26} every pair differs by {result['mean']:+.3f} "
                      f"over {result['pairs']} pairs; bootstrap degenerate")
            else:
                print(f"{label:26} {result['mean']:+.3f}  95% CI "
                      f"[{result['lo']:+.3f}, {result['hi']:+.3f}]  "
                      f"p={result['p_two_sided']:.4f}  n={result['pairs']}")


if __name__ == "__main__":
    main()
