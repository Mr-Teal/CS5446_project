"""The belief-input run beside the first PPO run: every number of the README's result section.

    python final_summary.py

Reads the match records of both runs. A match is scored by complete colour pairs (both games of an
opening), as the team's paired_score does. Where both agents played the same openings against the
same opponent, the difference is taken opening by opening and its 95% range comes from resampling
the openings (10,000 resamples, seed 0).
"""
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
PLAIN = HERE.parent / "ppo-pilot-2026-11-14" / "runs"
RNG = np.random.default_rng(0)


def games(folder: Path) -> list:
    return [json.loads(line) for line in (folder / "games.jsonl").read_text().splitlines()]


def pair_scores(folder: Path) -> dict:
    """{opening id: side a's score over the two games of that opening} for the complete pairs."""
    by_opening = {}
    for game in games(folder):
        by_opening.setdefault(game["opening"]["id"], []).append(game)
    pairs = {}
    for opening, pair in by_opening.items():
        if len(pair) == 2 and all("error" not in g for g in pair):
            pairs[opening] = sum(1.0 if g["winner_side"] == "a" else 0.5 if g["winner"] == "draw" else 0.0 for g in pair) / 2
    return pairs


def tally(folder: Path) -> str:
    played = [g for g in games(folder) if "error" not in g]
    wins = sum(g["winner_side"] == "a" for g in played)
    draws = sum(g["winner"] == "draw" for g in played)
    return f"{wins}-{draws}-{len(played) - wins - draws}"


def spread(values: np.ndarray) -> tuple:
    boots = values[RNG.integers(0, len(values), size=(10_000, len(values)))].mean(axis=1)
    return float(values.mean()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def one(label: str, folder: Path) -> None:
    mean, low, high = spread(np.array(list(pair_scores(folder).values())))
    print(f"  {label:58s} {tally(folder):12s} {mean:.3f}  [{low:.3f}, {high:.3f}]")


def difference(label: str, belief: Path, plain: Path) -> None:
    a, b = pair_scores(belief), pair_scores(plain)
    shared = sorted(set(a) & set(b))
    mean, low, high = spread(np.array([a[i] - b[i] for i in shared]))
    print(f"  {label:58s} {len(shared):4d} openings  {mean:+.3f}  [{low:+.3f}, {high:+.3f}]")


def main():
    print("Final networks against the team's players (wins-draws-losses, score, 95% range over openings)")
    for opponent, games_text in (("random", "100 games"), ("material", "100 games"), ("stockfish-d1", "100 games")):
        one(f"belief input, 5 h, {opponent}, {games_text}", RUNS / "belief-hourly" / f"final-vs-{opponent}")
        one(f"first run, 12.2 h, {opponent}, {games_text}", PLAIN / "long-hourly" / f"final-vs-{opponent}")
    one("belief input, 5 h, stockfish-d1, 400 games (seed 1)", RUNS / "matches" / "final-vs-stockfish-d1-400-seed1")
    one("belief input, 4 h, stockfish-d1, 400 games (seed 1)", RUNS / "matches" / "hour-04-vs-stockfish-d1-400-seed1")
    one("first run, 12.2 h, stockfish-d1, 400 games (seed 1)", PLAIN / "matches" / "final-vs-stockfish-d1-400-seed1")

    print("\nBelief input minus first run, opening by opening (same openings, same opponent)")
    difference("5 h minus 12.2 h, material, 100 games", RUNS / "belief-hourly" / "final-vs-material", PLAIN / "long-hourly" / "final-vs-material")
    difference("5 h minus 12.2 h, stockfish-d1, 100 games", RUNS / "belief-hourly" / "final-vs-stockfish-d1", PLAIN / "long-hourly" / "final-vs-stockfish-d1")
    difference("5 h minus 12.2 h, stockfish-d1, 400 games (seed 1)", RUNS / "matches" / "final-vs-stockfish-d1-400-seed1",
               PLAIN / "matches" / "final-vs-stockfish-d1-400-seed1")
    difference("4 h minus 12.2 h, stockfish-d1, 400 games (seed 1)", RUNS / "matches" / "hour-04-vs-stockfish-d1-400-seed1",
               PLAIN / "matches" / "final-vs-stockfish-d1-400-seed1")
    difference("30 min minus 30 min, material, 100 games", RUNS / "belief-hourly" / "hour-0.50-vs-material", RUNS / "plain-reference" / "plain-30min-12.6M-vs-material")
    difference("30 min minus 30 min, stockfish-d1, 100 games", RUNS / "belief-hourly" / "hour-0.50-vs-stockfish-d1", RUNS / "plain-reference" / "plain-30min-12.6M-vs-stockfish-d1")
    for hour, label in ((1, "hour-01"), (2, "hour-02"), (3, "hour-03"), (4, "hour-04")):
        for opponent in ("material", "stockfish-d1"):
            difference(f"{hour} h minus {hour} h, {opponent}, 100 games", RUNS / "belief-hourly" / f"{label}-vs-{opponent}",
                       PLAIN / "long-hourly" / f"{label}-vs-{opponent}")

    print("\nDirect matches: belief-input network against the first run's final network (side a = belief input)")
    head = RUNS / "head-to-head"
    for label, folder in (("30 min, 200 games (seed 0)", "belief-hour-0.50-vs-first-run-final"),
                          ("1 h, 200 games (seed 0)", "belief-1h-vs-first-run-final"),
                          ("1.5 h, 200 games (seed 0)", "belief-hour-1.50-vs-first-run-final"),
                          ("2 h, 1,000 games (seed 1)", "belief-hour-02-vs-first-run-final-1000-seed1"),
                          ("2.5 h, 400 games (seed 0)", "belief-hour-2.50-vs-first-run-final"),
                          ("3 h, 1,000 games (seed 1)", "belief-hour-03-vs-first-run-final-1000-seed1"),
                          ("3.5 h, 400 games (seed 0)", "belief-hour-3.50-vs-first-run-final"),
                          ("4 h, 1,000 games (seed 1)", "belief-hour-04-vs-first-run-final-1000-seed1"),
                          ("4.5 h, 1,000 games (seed 1)", "belief-hour-4.50-vs-first-run-final-1000-seed1"),
                          ("5 h, 400 games (seed 0)", "belief-final-vs-first-run-final"),
                          ("5 h, 1,000 games (seed 1)", "belief-final-vs-first-run-final-1000-seed1"),
                          ("5 h, 1,000 games (seed 2)", "belief-final-vs-first-run-final-1000-seed2")):
        one(label, head / folder)
    final = [head / name for name in ("belief-final-vs-first-run-final", "belief-final-vs-first-run-final-1000-seed1",
                                      "belief-final-vs-first-run-final-1000-seed2")]
    pooled = np.concatenate([np.array(list(pair_scores(folder).values())) for folder in final])
    mean, low, high = spread(pooled)
    wins = draws = losses = 0
    for folder in final:
        w, d, l = (int(x) for x in tally(folder).split("-"))
        wins, draws, losses = wins + w, draws + d, losses + l
    print(f"  {'5 h, the three matches together, 2,400 games':58s} {f'{wins}-{draws}-{losses}':12s} {mean:.3f}  [{low:.3f}, {high:.3f}]")
    for label, folder in (("first run 1 h against its final network, 200 games", "reference-first-run-1h-vs-first-run-final"),
                          ("first run 2 h against its final network, 200 games", "reference-first-run-2h-vs-first-run-final")):
        one(label, head / folder)

    print("\nBelief-input run, all ten match rounds together (100 games each)")
    table = [json.loads(line) for line in (RUNS / "belief-hourly" / "table.jsonl").read_text().splitlines()]
    for opponent in ("material", "stockfish-d1"):
        for name, rows in (("rounds 0.5 h to 2 h", table[:4]), ("rounds 2.5 h to 5 h", table[4:])):
            w = sum(r[opponent]["wins"] for r in rows)
            d = sum(r[opponent]["draws"] for r in rows)
            l = sum(r[opponent]["losses"] for r in rows)
            print(f"  {opponent:13s} {name:22s} {w}-{d}-{l}  {(w + d / 2) / (w + d + l):.3f}")
    plain = [json.loads(line) for line in (PLAIN / "long-hourly" / "table.jsonl").read_text().splitlines()]
    for name, rows in (("first run, hours 2 to 8", plain[1:8]), ("first run, hours 9 to 12 and final", plain[8:])):
        for opponent in ("material", "stockfish-d1"):
            w = sum(r[opponent]["wins"] for r in rows)
            d = sum(r[opponent]["draws"] for r in rows)
            l = sum(r[opponent]["losses"] for r in rows)
            print(f"  {opponent:13s} {name:34s} {w}-{d}-{l}  {(w + d / 2) / (w + d + l):.3f}")


if __name__ == "__main__":
    main()
