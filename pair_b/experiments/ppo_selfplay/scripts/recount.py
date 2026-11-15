"""Recount one arm from its game records: python recount.py runs/<name> [...]

Score = (wins + draws / 2) / scored games, from player A's side (the PPO network), with a 95 % Wilson
interval: the convention and the formula of the team's recount.py. A game is scored when it reached a
result on the board. A failed game (a runner error, in practice a belief tracker that lost every
consistent history) and a game stopped at the ply cap are listed and not scored. A second line counts
each failed game against the side whose tracker failed.
"""
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path


def wilson(score: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    denominator = 1 + z * z / n
    centre = (score + z * z / (2 * n)) / denominator
    half = z * math.sqrt(score * (1 - score) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def line(wins: int, draws: int, losses: int) -> str:
    n = wins + draws + losses
    if not n:
        return "no scored game"
    score = (wins + draws / 2) / n
    low, high = wilson(score, n)
    return f"{wins}-{draws}-{losses} of {n}, score {score:.3f} [{low:.3f}, {high:.3f}]"


def recount(folder: Path) -> dict:
    rows = []
    for path in sorted(folder.glob("games-*/games.jsonl")):
        rows += [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines() if text.strip()]
    rows.sort(key=lambda r: r["seed"])
    seeds = [r["seed"] for r in rows]
    assert len(seeds) == len(set(seeds)), "a seed was played twice"
    tally = {"all": Counter(), "white": Counter(), "black": Counter()}
    failed, capped, plies, reasons = [], [], [], Counter()
    ms = {"a": [], "b": []}
    tracker_ms = {"a": 0.0, "b": 0.0}
    outcomes = {}
    for r in rows:
        game = r["seed"] - 1000
        for update in r.get("tracker_updates", []):
            tracker_ms[r["player_by_color"][update["player"]]] += update["elapsed_ms"]
        if r["status"] != "completed":
            sides = sorted({r["player_by_color"][u["player"]] for u in r.get("tracker_updates", []) if u["outcome"] == "failed"})
            failed.append({"game": game, "seed": r["seed"], "a_color": r["player_a_color"], "error": r.get("error"),
                           "failed_tracker_side": sides or None})
            outcomes[game] = "failed"
            continue
        for ply in r["plies"]:
            ms[r["player_by_color"][ply["player"]]].append(ply["elapsed_ms"])
        if r["stopped_at_ply_limit"]:
            capped.append(game)
            outcomes[game] = "capped"
            continue
        result = "draw" if r["winner"] == "draw" else "win" if r["winner"] == r["player_a_color"] else "loss"
        outcomes[game] = result
        tally["all"][result] += 1
        tally[r["player_a_color"]][result] += 1
        plies.append(len(r["plies"]))
        reasons[r["termination"]] += 1
    wdl = {key: (c["win"], c["draw"], c["loss"]) for key, c in tally.items()}
    w, d, l = wdl["all"]
    n = w + d + l
    score = (w + d / 2) / n if n else None
    a_failed = sum(1 for f in failed if f["failed_tracker_side"] == ["a"])
    b_failed = sum(1 for f in failed if f["failed_tracker_side"] == ["b"])
    first = json.loads((sorted(folder.glob("games-*/provenance.json"))[0]).read_text(encoding="utf-8")) if rows else {}
    return {
        "arm": folder.name, "player_a": rows[0]["player_a"] if rows else None, "player_b": rows[0]["player_b"] if rows else None,
        "game_rows": len(rows), "scored": n, "wins": w, "draws": d, "losses": l, "score": score,
        "wilson95": list(wilson(score, n)) if n else None,
        "as_white": list(wdl["white"]), "as_black": list(wdl["black"]),
        "failed": failed, "capped": capped,
        "score_if_failed_games_count_against_the_failing_side": line(w + b_failed, d, l + a_failed),
        "terminations": dict(reasons),
        "plies_median": statistics.median(plies) if plies else None, "plies_min": min(plies, default=None),
        "plies_max": max(plies, default=None),
        "mean_ms_per_move": {side: statistics.mean(values) if values else None for side, values in ms.items()},
        "max_ms_per_move": {side: max(values, default=None) for side, values in ms.items()},
        "tracker_seconds_total": {side: value / 1000 for side, value in tracker_ms.items()},
        "team_commit": first.get("git_commit"), "team_status": first.get("git_status"),
        "checkpoint_sha256": {"a": first.get("sha256", {}).get("player_a_checkpoint"),
                              "b": first.get("sha256", {}).get("player_b_checkpoint")},
        "outcome_by_game": outcomes,
    }


def main():
    for name in sys.argv[1:]:
        folder = Path(name)
        s = recount(folder)
        (folder / "summary.json").write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
        print(f"## {s['arm']}")
        print(f"A: {s['player_a']}")
        print(f"B: {s['player_b']}")
        print(f"A's W-D-L: {line(s['wins'], s['draws'], s['losses'])}")
        print(f"  as White {'-'.join(map(str, s['as_white']))}, as Black {'-'.join(map(str, s['as_black']))}")
        print(f"  game rows {s['game_rows']}, failed {len(s['failed'])}, stopped at the ply cap {len(s['capped'])}")
        for f in s["failed"]:
            print(f"    failed game {f['game']} (A {f['a_color']}): tracker side {f['failed_tracker_side']}: {f['error']}")
        if s["failed"]:
            print(f"  with failed games counted against the failing side: {s['score_if_failed_games_count_against_the_failing_side']}")
        print(f"  ends {s['terminations']}; plies median {s['plies_median']}, range {s['plies_min']} to {s['plies_max']}")
        print(f"  mean ms per move: A {s['mean_ms_per_move']['a'] or 0:.1f}, B {s['mean_ms_per_move']['b'] or 0:.1f}; "
              f"tracker seconds in total: A {s['tracker_seconds_total']['a']:.0f}, B {s['tracker_seconds_total']['b']:.0f}")
        print(f"  team commit {s['team_commit']}; A checkpoint {str(s['checkpoint_sha256']['a'])[:12]}, B checkpoint {str(s['checkpoint_sha256']['b'])[:12]}")
        print()


if __name__ == "__main__":
    main()
