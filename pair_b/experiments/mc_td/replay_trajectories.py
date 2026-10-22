"""Rebuild the full move sequence of D2 games from their seeds, and score every position on them
with Stockfish depth 1 the way the D2 labels were made.

    python replay_trajectories.py <dataset folder> <out.jsonl> --splits train val --workers 10

Each game is replayed with pairb.d2.play_game (the generator itself: same seed, same eps range,
same 300-ply cap, Stockfish 19 with 1 thread and 16 MB hash). The replay is checked against
games.jsonl (plies, result, termination, eps, opening plies) and against the stored records:
the parent FEN at every parent ply, and the depth-1 value of every child of those parents.

Depth-1 values on the trajectory: the value of position s_{t+1} is the score of the played move
in one MultiPV depth-1 call at s_t, ucinewgame before each call, the game's move history sent with
the position. That is how make_d2 scored children when D2 was made (16 Oct; children_scores sent
the board with its history until commit 305b94a on 18 Oct), so these values match the stored d1
labels exactly. Values are White's view, tanh(cp / 600), a forced mate exactly +-1, rounded to 6
decimals, as in the records.

Writes one JSON line per game (sorted by game_id) and <out>.manifest.json. Reads the dataset only.
"""
import argparse
import hashlib
import json
import multiprocessing as mp
import sys
import time
from collections import defaultdict
from pathlib import Path

import chess
import chess.engine

from pairb.d2 import play_game
from pairb.data import split_of
from pairb.stockfish import StockfishEvaluator
from pairb.values import rule_value, score_to_value

STOCKFISH = "/opt/homebrew/bin/stockfish"
MAX_PLIES, EPS_RANGE = 300, (0.02, 0.15)  # make_d2 defaults, as used for d2-v2 and d2-check


def multipv_scores(engine, board):
    """{uci: White-view Score} for every legal move, one MultiPV depth-1 call with the history."""
    n = board.legal_moves.count()
    infos = engine.analyse(board, chess.engine.Limit(depth=1), multipv=n, game=object())
    return {info["pv"][0].uci(): info["score"].white() for info in infos}


def replay_game(engine, game, parent_check, need_d1):
    t0 = time.time()
    moves, info = play_game(game["seed"], engine, MAX_PLIES, EPS_RANGE)
    check = {"plies": len(moves) == game["plies"], "result": info["result"] == game["result"],
             "termination": info["termination"] == game["termination"], "eps": info["eps"] == game["eps"],
             "opening_plies": info["opening_plies"] == game["opening_plies"],
             "parents": sorted(parent_check) == sorted(game["parents"])}
    n = len(moves)
    board = chess.Board()
    d1, rules, calls = [], [], 0
    fen_ok, children, children_ok, mismatches, missing_scores = 0, 0, 0, [], 0
    stop = False  # a rule decided a position before the end: positions after it are not used
    for t in range(n):
        want_traj = need_d1 and not stop and t <= n - 2
        scores = None
        if want_traj or t in parent_check:
            if rule_value(board) is None:
                scores = multipv_scores(engine, board)
                calls += 1
                if sorted(scores) != sorted(m.uci() for m in board.legal_moves):
                    missing_scores += 1
        if t in parent_check:
            stored_fen, stored = parent_check[t]
            fen_ok += board.fen() == stored_fen
            for uci, v in stored.items():
                if v is None:
                    continue
                children += 1
                mine = None if scores is None or uci not in scores else round(score_to_value(scores[uci]), 6)
                if mine == v:
                    children_ok += 1
                elif len(mismatches) < 5:
                    mismatches.append({"ply": t, "move": uci, "stored": v, "replay": mine})
        board.push_uci(moves[t])
        if want_traj:
            rule = rule_value(board)
            rules.append(rule[0] if rule else None)
            if scores is None or moves[t] not in scores:
                d1.append(None)
            else:
                d1.append(round(score_to_value(scores[moves[t]]), 6))
            if rule is not None:
                stop = True
    final_rule = rule_value(board)
    check.update({"parent_fen_ok": fen_ok, "parent_fens": len(parent_check), "children_compared": children,
                  "children_d1_ok": children_ok, "mismatches": mismatches, "missing_scores": missing_scores})
    return {"game_id": game["game_id"], "split": split_of(game["game_id"]), "plies": n,
            "result": game["result"], "termination": game["termination"], "moves": moves,
            "d1": d1 if need_d1 else None, "rule": rules if need_d1 else None,
            "final_rule": final_rule[0] if final_rule else None, "check": check,
            "engine_calls": calls, "seconds": round(time.time() - t0, 3)}


def run_worker(task):
    worker, games, checks, need = task
    out = []
    with StockfishEvaluator(depth=1, path=STOCKFISH) as ev:  # Threads 1, Hash 16, as make_d2
        name = ev.engine.id.get("name", "unknown")
        for i, g in enumerate(games):
            out.append(replay_game(ev.engine, g, checks[g["game_id"]], need[g["game_id"]]))
            if (i + 1) % 200 == 0:
                print(f"worker {worker}: {i + 1}/{len(games)} games", file=sys.stderr, flush=True)
    return out, name


def stored_checks(folder, keep):
    """{game_id: {parent ply: (parent FEN, {move: stored d1 value or None})}} from the records."""
    checks = defaultdict(dict)
    for path in sorted(Path(folder).glob("part-*.jsonl")):
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                if r["game_id"] not in keep:
                    continue
                parent_ply = r["ply"] - 1
                entry = checks[r["game_id"]].setdefault(parent_ply, (r["parent_fen"], {}))
                entry[1][r["move"]] = None if r["d1"] is None else r["d1"]["v"]
    return checks


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("out")
    ap.add_argument("--splits", nargs="+", default=["train", "val"])
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()
    folder, out = Path(args.folder), Path(args.out)
    if out.exists():
        raise SystemExit(f"{out} exists; refusing to overwrite")
    start = time.time()
    games = [json.loads(line) for line in (folder / "games.jsonl").read_text().splitlines()]
    games = [g for g in games if split_of(g["game_id"]) in args.splits]
    keep = {g["game_id"] for g in games}
    checks = stored_checks(folder, keep)
    checks = {gid: checks.get(gid, {}) for gid in keep}
    need = {g["game_id"]: g["result"] is not None for g in games}  # unfinished games: replay check only
    workers = max(1, min(args.workers, len(games)))
    tasks = []
    for w in range(workers):
        mine = games[w::workers]
        tasks.append((w, mine, {g["game_id"]: checks[g["game_id"]] for g in mine},
                      {g["game_id"]: need[g["game_id"]] for g in mine}))
    print(f"{len(games)} games from {folder.name} ({', '.join(args.splits)}), {workers} workers", flush=True)
    with mp.Pool(workers) as pool:
        results = pool.map(run_worker, tasks)
    rows = sorted((r for res in results for r in res[0]), key=lambda r: r["game_id"])
    tmp = out.with_suffix(out.suffix + ".part")
    with open(tmp, "x") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    tmp.rename(out)
    flags = ("plies", "result", "termination", "eps", "opening_plies", "parents")
    summary = {
        "games": len(rows),
        "replay_exact": sum(all(r["check"][k] for k in flags) for r in rows),
        **{f"{k}_match": sum(r["check"][k] for r in rows) for k in flags},
        "parent_fens": sum(r["check"]["parent_fens"] for r in rows),
        "parent_fen_ok": sum(r["check"]["parent_fen_ok"] for r in rows),
        "children_compared": sum(r["check"]["children_compared"] for r in rows),
        "children_d1_ok": sum(r["check"]["children_d1_ok"] for r in rows),
        "missing_scores": sum(r["check"]["missing_scores"] for r in rows),
        "games_with_mismatch": [r["game_id"] for r in rows if r["check"]["mismatches"]][:20],
        "unfinished_games": sum(r["result"] is None for r in rows),
        "trajectory_positions": sum(len(r["d1"]) for r in rows if r["d1"] is not None),
        "rule_decided_before_end": sum(any(x is not None for x in r["rule"]) for r in rows if r["rule"]),
        "engine_calls": sum(r["engine_calls"] for r in rows),
    }
    manifest = {
        "dataset": folder.name, "splits": args.splits, "command": [Path(sys.argv[0]).name, *sys.argv[1:]],
        "games_jsonl_sha256": sha256_file(folder / "games.jsonl"), "out_sha256": sha256_file(out),
        "stockfish": {"path": STOCKFISH, "name": results[0][1], "threads": 1, "hash_mb": 16,
                      "play": "pairb.d2.play_game, depth 1, one ucinewgame per game",
                      "d1": "MultiPV depth 1 at s_t with the game history, ucinewgame before each call; "
                            "the played move's score is d1 of s_{t+1}"},
        "value_conversion": "pairb.values.score_to_value (fow_shared.values.cp_to_score: tanh(cp/600); "
                            "mate exactly +-1), White's view, rounded to 6 decimals",
        "workers": workers, "summary": summary, "seconds": round(time.time() - start, 1),
    }
    Path(str(out) + ".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
