"""The #17 batch table and the checks a table must pass before it is used (match_protocol.md).

    python3 make_batch_table.py --runs <folder holding one summary.json per row> [--out table.md] [--json table.json]

From this folder: python3 make_batch_table.py --runs . --out table.md --json table.json

Standard library only. Each row is a play_matches.py run folder (summary.json and games.jsonl; when games.jsonl is
absent, as in the committed batch folder, games.jsonl.gz is read instead); the first-named side `a` is the side under
test and `b` is quick Stockfish. Scores are a's paired score over complete colour pairs, with Wilson's 95%
interval always and the bootstrap interval only where the runner gave one. A check that fails is printed and
the script exits 1, so a table is never written from runs that differ in code, engine, rules or settings.
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

ORDER = ["random", "material", "linear", "stockfish-d1", "network1", "belief", "stockfish-d11"]
SAME = {  # what every row of one table must share
    "commit": lambda s: s["record"]["git_commit"],
    "source hashes": lambda s: json.dumps(s["record"]["source_sha256"], sort_keys=True),
    "stockfish binary": lambda s: s["record"]["stockfish"]["sha256"],
    "packages": lambda s: json.dumps(s["record"]["packages"], sort_keys=True),
    "rules": lambda s: s["rules"],
    "no-move rule": lambda s: s["no_move_rule"],
    "opponent": lambda s: s["b"],
    "seed": lambda s: s["settings"]["seed"],
    "games planned": lambda s: s["settings"]["games"],
    "max plies": lambda s: s["settings"]["max_plies"],
    "tracker": lambda s: (s["settings"]["particles"], s["settings"]["guesses"]),
    "openings": lambda s: s["openings_rule"],
    "engine policy": lambda s: json.dumps(s["settings"]["engine"], sort_keys=True),
}


def load(runs: Path) -> list[dict]:
    rows = []
    for summary in sorted(runs.glob("*/summary.json")):
        s = json.loads(summary.read_text())
        s["_folder"] = summary.parent.name
        s["_dir"] = str(summary.parent)
        rows.append(s)
    rows.sort(key=lambda s: ORDER.index(s["a"]) if s["a"] in ORDER else len(ORDER))
    return rows


def checks(rows: list[dict]) -> list[str]:
    """Every problem that stops the table being used; [] when the rows can share one table."""
    problems = []
    for name, get in SAME.items():
        values = {str(get(s)) for s in rows}
        if len(values) > 1:
            problems.append(f"rows differ in {name}: {sorted(values)}")
    for s in rows:
        row = s["_folder"]
        if s["record"]["git_status"]:
            problems.append(f"{row}: the tree was not clean: {s['record']['git_status']}")
        if not s.get("completed"):
            problems.append(f"{row}: not completed (stopped_early: {s.get('stopped_early')})")
        recorded = s["games"] + s["errors"]
        if recorded != s["settings"]["games"]:
            problems.append(f"{row}: {s['games']} finished + {s['errors']} failed != {s['settings']['games']} planned")
        unexplained = [g for g in failed_games(s) if not cause(g)]
        if unexplained:
            problems.append(f"{row}: {len(unexplained)} failed games with no recorded error")
        if s.get("diagnostic_errors"):
            problems.append(f"{row}: {s['diagnostic_errors']} diagnostic errors")
    return problems


def read_games(folder: Path) -> str:
    """The row's games.jsonl text, or its gzip copy games.jsonl.gz when games.jsonl is absent."""
    plain = folder / "games.jsonl"
    if plain.exists():
        return plain.read_text(encoding="utf-8")
    return gzip.decompress((folder / "games.jsonl.gz").read_bytes()).decode("utf-8")


def failed_games(s: dict) -> list[dict]:
    return [g for g in map(json.loads, read_games(Path(s["_dir"])).splitlines()) if "error" in g]


def cause(g: dict) -> str:
    """The failure's kind: the exception name before the first colon (e.g. TrackerLost), or '' if none."""
    return g.get("error", "").split(":", 1)[0].strip()


def failures(s: dict) -> str:
    kinds = {}
    for g in failed_games(s):
        kinds[cause(g) or "unrecorded"] = kinds.get(cause(g) or "unrecorded", 0) + 1
    return ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())) or "none"


def fmt(x, digits=2):
    return "n/a" if x is None else f"{x:.{digits}f}"


def table(rows: list[dict]) -> str:
    head = ("| Side (vs quick Stockfish) | Score | Wilson 95% | Bootstrap 95% | W-D-L | Pairs | Plies | "
            "ms/move median (p95) | Value lost | Failed games | Other endings |")
    lines = [head, "|" + "|".join(["---"] * 11) + "|"]
    for s in rows:
        a, score = s["sides"]["a"], s["score_a"]
        w = score["wilson95"]
        boot = f"{fmt(score['ci95'][0])} to {fmt(score['ci95'][1])}" if score["ci95"] else "none"
        other = {k: v for k, v in s["end_reasons"].items() if k != "king_capture" and v}
        lines.append(
            f"| {s['a']} | {fmt(score['mean'])} | {fmt(w[0])} to {fmt(w[1])} | {boot} | "
            f"{a['wins']}-{a['draws']}-{a['losses']} | {score['complete_pairs']} | {fmt(s['plies_mean'], 1)} | "
            f"{fmt(a.get('ms_per_move_median'), 1)} ({fmt(a.get('ms_per_move_p95'), 1)}) | "
            f"{fmt(a.get('value_lost_mean'), 3)} | {failures(s)} | "
            f"{', '.join(f'{k} {v}' for k, v in other.items()) or 'none'} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--out")
    ap.add_argument("--json")
    args = ap.parse_args()
    rows = load(Path(args.runs))
    if not rows:
        sys.exit(f"no summary.json under {args.runs}")
    problems = checks(rows)
    first = rows[0]
    caption = (f"Each side inside the one-ply bot against quick Stockfish, {first['settings']['games']} games "
               f"({first['settings']['games'] // 2} colour pairs), seed {first['settings']['seed']}, rules "
               f"{first['rules']}, no-move rule {first['no_move_rule']} "
               f"({sum(s['errors_no_legal_move'] for s in rows)} no-move failures), "
               f"commit {first['record']['git_commit'][:7]}, "
               f"Stockfish sha256 {first['record']['stockfish']['sha256'][:12]}. Score = the side's paired score; "
               f"equal work per move with the rest of the bot held fixed, not equal computation. "
               f"Failed games are excluded with their pair and counted by cause (match_protocol.md, Failures).")
    text = caption + "\n\n" + table(rows) + "\n\nChecks: " + ("all passed" if not problems else "FAILED") + "\n"
    text += "".join(f"- {p}\n" for p in problems)
    print(text)
    if args.out:
        Path(args.out).write_text(text)
    if args.json:
        Path(args.json).write_text(json.dumps({"caption": caption, "problems": problems, "rows": [
            {k: s[k] for k in ("a", "b", "games", "errors", "errors_no_legal_move", "score_a", "end_reasons",
                               "plies_mean", "seconds_per_game_mean")} | {"side_a": s["sides"]["a"], "folder": s["_folder"]}
            for s in rows]}, indent=1) + "\n")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
