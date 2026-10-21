"""Position-level overlap between an evaluation dataset's split and a fitting dataset's train+val rows.

Game IDs restart at g-000000 per generated dataset, so ID strings collide although the games differ.
This checks what actually matters for leakage: whether the same positions (FEN without the fullmove
number, i.e. everything the 19-plane encoding sees) or the same parent decisions appear in both.
Writes a JSON report to argv[3] (refuses overwrite) and prints it.
"""
import json
import sys
from pathlib import Path

from pairb.data import split_of


def key(fen):
    return " ".join(fen.split()[:5])  # board, turn, castling, ep, halfmove; drop fullmove


def rows(folder):
    for part in sorted(Path(folder).glob("part-*.jsonl")):
        with part.open() as f:
            for line in f:
                yield json.loads(line)


def main():
    fit, ev, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    fit_pos, fit_parent, fit_ids = set(), set(), {"train": set(), "val": set()}
    for r in rows(fit):
        s = split_of(r["game_id"])
        if r["rule"] is None and s in ("train", "val"):
            fit_pos.add(key(r["fen"]))
            fit_parent.add(key(r["parent_fen"]))
            fit_ids[s].add(r["game_id"])
    n = same_pos = 0
    parents, parents_hit, games, games_hit, ids = set(), set(), set(), set(), set()
    for r in rows(ev):
        if r["rule"] is not None or split_of(r["game_id"]) != "train":
            continue
        n += 1
        games.add(r["game_id"])
        p = f"{r['game_id']}|{r['parent_fen']}"
        parents.add(p)
        if key(r["fen"]) in fit_pos:
            same_pos += 1
        if key(r["parent_fen"]) in fit_parent:
            parents_hit.add(p)
            games_hit.add(r["game_id"])
    report = {
        "fit": Path(fit).name, "eval": Path(ev).name, "eval_split": "train",
        "eval_rows": n, "eval_parents": len(parents), "eval_games": len(games),
        "id_string_overlap_with_fit_train": len(games & fit_ids["train"]),
        "id_string_overlap_with_fit_val": len(games & fit_ids["val"]),
        "rows_whose_position_is_in_fit_train_val": same_pos,
        "parents_whose_position_is_a_fit_parent": len(parents_hit),
        "games_with_such_a_parent": len(games_hit),
        "overlapping_parent_keys": sorted(parents_hit),
    }
    with out.open("x") as f:
        f.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "overlapping_parent_keys"}, indent=2))


if __name__ == "__main__":
    main()
