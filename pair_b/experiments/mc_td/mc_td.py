"""MC, TD(0) and TD(lambda) value learning against distilling careful Stockfish, on one model.

    python mc_td.py <d2-v2> <d2-check> <d2-v2 trajectories.jsonl> <d2-check trajectories.jsonl> <out dir>

Model (the same for every method): v(s) = tanh(atanh(clip(d1, 0.999)) + x(s) . w + b), side to move's
view, with pairb.linear.features' 1,217 inputs (19 planes x 64 squares, then d1). Loss: mean squared
error in value space plus alpha * |w|^2 (b unpenalised), fitted by damped Gauss-Newton
(Levenberg-Marquardt) as in runs/linear-tanh/linear_tanh.py.

Exact reparameterisation used for speed (same optimum, same predictions): plane 12 is all ones, so
its 64 weights are exactly 0 at the optimum (b absorbs any constant at no penalty); planes 13-16 and
18 repeat one value on all 64 squares, so ridge splits their weight evenly and each becomes one
column of 8 x value with the same alpha; squares that are empty in every board (pawns on the first
and last rank, en passant squares off the sixth rank) keep weight 0. That leaves 750 columns.
full_weights() maps a fit back to the 1,217 weights, and the run checks the two give the same
predictions.

Targets: Distil = d11 (the D2 labels); MC = the game's result from the side to move's view;
TD(0) = -v(s_{t+1}) from the current model, the final result at the last position; TD(lambda) =
the lambda-return built from the same one-step targets. TD is fitted by fitted value iteration
(semi-gradient: targets fixed within a round), each round's fit warm-started from the last, until
the validation error stops improving (cap 15 rounds). Alpha: the grid below, searched upward,
stopping at the first value whose validation error is worse than the best so far (a first run
with a grid ending at 0.1 picked its top value at 100 games, so the grid now goes to 10). Validation
error: MSE against d11 on d2-v2's val records for Distil; MSE against the result on d2-v2's val
trajectories for MC and TD (they never see careful Stockfish).
"""
import hashlib
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

import chess
import numpy as np

from pairb.data import pack, split_of, read_records
from pairb.encode import encode_board, stm_sign
from pairb.linear import features
from pairb.linear_workflow import load_dataset, mask_split, metrics, runtime
from pairb.metrics import paired_difference, paired_regret_difference
from pairb.net1 import D1_CLIP
from pairb.values import rule_value

ALPHAS = (1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0)  # searched upward, so the top end only runs if needed
LAMBDA = 0.8
MAX_ROUNDS = 15
N_GAMES = (100, 300, 1000, 3000, None)  # None: every train-bucket game
N_BOOT, BOOT_SEED = 2000, 0
CHUNK = 8192
METHODS = ("distil", "mc", "td0", "tdlambda")

# ---- the 750-column design ---------------------------------------------------------------------
_PIECE = np.zeros((12, 8, 8), dtype=bool)
_PIECE[:] = True
_PIECE[[0, 6], 0, :] = False  # no pawn on the first or last rank (either side)
_PIECE[[0, 6], 7, :] = False
PIECE_IDX = np.flatnonzero(_PIECE.reshape(-1))  # 736 of the 768 piece-square columns
K = len(PIECE_IDX) + 4 + 8 + 1 + 1  # pieces, 4 castling rights, 8 en passant squares, halfmove, d1
SCALE = np.float32(8.0)  # sqrt(64): one column standing for 64 equal columns under the same ridge


def check_structure(planes):
    """The facts the reparameterisation relies on, asserted on every board used."""
    p = planes
    assert (p[:, 12] == 1).all(), "plane 12 must be all ones"
    for q in (13, 14, 15, 16, 18):
        assert (p[:, q] == p[:, q, :1, :1]).all(), f"plane {q} must be constant over the board"
    assert not p[:, [0, 6]][:, :, [0, 7]].any(), "pawn on a first or last rank"
    ep = p[:, 17].copy()
    ep[:, 5] = 0
    assert not ep.any(), "en passant square off the sixth rank"


def design(planes, d1):
    """(n, K) float32 design from packed planes (pairb.data.pack) and side-to-move d1. Every entry is
    exactly the float64 value pairb.linear.features would use (times 8 for the merged columns)."""
    n = len(d1)
    x = np.empty((n, K), dtype=np.float32)
    for s in range(0, n, CHUNK):
        p = planes[s:s + CHUNK]
        m = len(p)
        x[s:s + m, :736] = p[:, :12].reshape(m, 768)[:, PIECE_IDX]
        x[s:s + m, 736:740] = p[:, 13:17, 0, 0].astype(np.float32) * SCALE
        x[s:s + m, 740:748] = p[:, 17, 5, :]
        x[s:s + m, 748] = (p[:, 18, 0, 0].astype(np.float32) / np.float32(100)) * SCALE  # as data.unpack
    x[:, 749] = d1
    return x


def full_weights(c):
    """The 1,217 weights of pairb.linear.features' columns for a fit on the 750-column design."""
    w = np.zeros((19, 8, 8))
    w[:12].reshape(-1)[PIECE_IDX] = c[:736]
    for i in range(4):
        w[13 + i] = c[736 + i] / 8
    w[17, 5, :] = c[740:748]
    w[18] = c[748] / 8
    return np.concatenate([w.reshape(-1), [c[749]]])


class Rows:
    def __init__(self, x, d1):
        self.x, self.n = x, len(d1)
        self.z0 = np.arctanh(np.clip(np.asarray(d1, dtype=np.float64), -D1_CLIP, D1_CLIP))

    def head(self, n):
        out = Rows.__new__(Rows)
        out.x, out.z0, out.n = self.x[:n], self.z0[:n], n
        return out


def predict(rows, c, b):
    out = np.empty(rows.n)
    for s in range(0, rows.n, CHUNK):
        out[s:s + CHUNK] = np.tanh(rows.z0[s:s + CHUNK] + rows.x[s:s + CHUNK].astype(np.float64) @ c + b)
    return out


def objective(rows, y, c, b, alpha):
    return float(np.mean((predict(rows, c, b) - y) ** 2) + alpha * c @ c)


def fit(rows, y, alpha, c, b, *, iters=40, tol=1e-10):
    """Levenberg-Marquardt on mean((tanh(z0 + x c + b) - y)^2) + alpha |c|^2, as linear_tanh.fit.
    The gradient and the loss are float64; the Gauss-Newton matrix is summed in float32 blocks
    (it only shapes the step, which is accepted only if the float64 loss falls)."""
    n, k = rows.x.shape
    lam, current = 1e-3, objective(rows, y, c, b, alpha)
    history = [current]
    for _ in range(iters):
        h = np.zeros((k + 1, k + 1))
        g = np.zeros(k + 1)
        for s in range(0, n, CHUNK):
            x32 = rows.x[s:s + CHUNK]
            x64 = x32.astype(np.float64)
            v = np.tanh(rows.z0[s:s + CHUNK] + x64 @ c + b)
            d = 1 - v * v
            r = d * (v - y[s:s + CHUNK])
            g[:k] += x64.T @ r
            g[k] += r.sum()
            d32 = d.astype(np.float32)
            xd = x32 * d32[:, None]
            h[:k, :k] += xd.T @ xd
            h[:k, k] += xd.T @ d32
            h[k, k] += float(d @ d)
        h[k, :k] = h[:k, k]
        grad = 2 * g / n
        grad[:k] += 2 * alpha * c
        hess = 2 * h / n
        hess[np.arange(k), np.arange(k)] += 2 * alpha
        scale = np.diag(np.maximum(np.diag(hess), 1e-12))
        while True:
            step = np.linalg.solve(hess + lam * scale, -grad)
            new = objective(rows, y, c + step[:k], b + step[k], alpha)
            if new < current:
                c, b, lam = c + step[:k], b + step[k], max(lam / 3, 1e-9)
                break
            lam *= 4
            if lam > 1e8:
                return c, b, history
        history.append(new)
        if current - new < tol * max(current, 1e-12):
            break
        current = new
    return c, b, history


def mse(p, y):
    return float(np.mean((p - y) ** 2))


# ---- trajectories --------------------------------------------------------------------------------
def build_game(row):
    """Training rows of one finished game: positions s_1 .. s_L, L = T-1, or the position before the
    first one a fog-of-war rule decides. Returns packed planes, side-to-move d1, the result from the
    side to move's view, and the target of the last row (-value of the position after it)."""
    moves, d1w, rules = row["moves"], row["d1"], row["rule"]
    board = chess.Board()
    planes, d1, z, plies = [], [], [], []
    end_value = None
    for t, uci in enumerate(moves):
        board.push_uci(uci)
        ply = t + 1
        if ply == len(moves):  # s_T, the final position: its value is the result
            end_value = row["result"] * stm_sign(board)
            break
        if rules[t] is not None:  # decided by a rule before the end (always a forced draw here)
            end_value = rule_value(board)[1] * stm_sign(board)
            break
        s = stm_sign(board)
        fen_board = chess.Board(board.fen())  # as pairb.data.build_arrays: the board from its FEN
        planes.append(pack(encode_board(fen_board)[None])[0])
        d1.append(np.float32(s * d1w[t]))
        z.append(row["result"] * s)
        plies.append(ply)
    if not planes:
        return None
    return {"game_id": row["game_id"], "planes": np.stack(planes), "d1": np.array(d1, dtype=np.float32),
            "z": np.array(z, dtype=np.float64), "ply": np.array(plies, dtype=np.int16),
            "last_target": -float(end_value)}


def load_trajectories(path, split, workers=10):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    rows = [r for r in rows if split_of(r["game_id"]) == split]
    finished = [r for r in rows if r["result"] is not None]
    with mp.Pool(workers) as pool:
        built = pool.map(build_game, finished, chunksize=16)
    built = [b for b in built if b is not None]
    built.sort(key=lambda b: b["game_id"])
    lengths = np.array([len(b["d1"]) for b in built])
    planes = np.concatenate([b["planes"] for b in built])
    check_structure(planes)
    data = {"planes": planes, "d1": np.concatenate([b["d1"] for b in built]),
            "z": np.concatenate([b["z"] for b in built]),
            "ply": np.concatenate([b["ply"] for b in built]),
            "game_id": np.repeat([b["game_id"] for b in built], lengths),
            "last_target": np.repeat([b["last_target"] for b in built], lengths),
            # distance from the chain's last row: 0 for the last row of each game
            "dist": np.concatenate([np.arange(n - 1, -1, -1) for n in lengths])}
    info = {"games_in_split": len(rows), "unfinished_dropped": len(rows) - len(finished),
            "finished_games": len(built), "positions": int(len(data["z"])),
            "truncated_by_rule": int(sum(any(x is not None for x in r["rule"]) for r in finished))}
    return data, info


def td_levels(dist):
    order = np.argsort(dist, kind="stable")
    bounds = np.searchsorted(dist[order], np.arange(dist.max() + 2))
    return [order[bounds[d]:bounds[d + 1]] for d in range(dist.max() + 1)]


def td_targets(v, levels, last_target, lam):
    """lambda-return, negamax: G_t = -[(1 - lam) v(s_{t+1}) + lam G_{t+1}], G at the last row = the
    final result (or rule value) in that row's view. lam = 0 gives TD(0): -v(s_{t+1})."""
    g = np.empty_like(v)
    g[levels[0]] = last_target[levels[0]]
    for idx in levels[1:]:
        g[idx] = -((1 - lam) * v[idx + 1] + lam * g[idx + 1])
    return g


# ---- methods -------------------------------------------------------------------------------------
def plain_path(train, y, val, y_val, alphas):
    """Plain fits along the alpha grid (warm-started, as linear_tanh), stopping when val MSE rises."""
    c, b, out, best = np.zeros(K), 0.0, [], None
    for alpha in alphas:
        t = time.time()
        c, b, hist = fit(train, y, alpha, c, b)
        pv = predict(val, c, b)
        cand = {"alpha": alpha, "iterations": len(hist) - 1, "train_loss": hist[-1],
                "val_mse": mse(pv, y_val), "val_mae": float(np.mean(np.abs(pv - y_val))),
                "seconds": round(time.time() - t, 1)}
        out.append(cand)
        print(f"    alpha {alpha:g}: {cand['iterations']} it, val MSE {cand['val_mse']:.6f} ({cand['seconds']} s)",
              flush=True)
        if best is None or cand["val_mse"] < best["val_mse"]:
            best = {**cand, "c": c.copy(), "b": b}
        else:
            break
    return best, out


def td_path(train, z_train, levels, last_target, val, z_val, lam, alphas, max_rounds):
    out, best = [], None
    for alpha in alphas:
        t = time.time()
        c, b = np.zeros(K), 0.0
        v = predict(train, c, b)
        rounds = [{"round": 0, "val_mse": mse(predict(val, c, b), z_val)}]
        top = None
        for r in range(1, max_rounds + 1):
            y = td_targets(v, levels, last_target, lam)
            c, b, hist = fit(train, y, alpha, c, b)
            v = predict(train, c, b)
            pv = predict(val, c, b)
            rounds.append({"round": r, "iterations": len(hist) - 1, "train_loss": hist[-1],
                           "target_mse_vs_result": mse(y, z_train), "val_mse": mse(pv, z_val),
                           "val_mae": float(np.mean(np.abs(pv - z_val)))})
            if top is None or rounds[-1]["val_mse"] < top["val_mse"]:
                top = {"round": r, "val_mse": rounds[-1]["val_mse"], "val_mae": rounds[-1]["val_mae"],
                       "c": c.copy(), "b": b}
            else:
                break
        cand = {"alpha": alpha, "rounds_run": len(rounds) - 1, "best_round": top["round"],
                "val_mse": top["val_mse"], "val_mae": top["val_mae"], "rounds": rounds,
                "seconds": round(time.time() - t, 1)}
        out.append(cand)
        print(f"    alpha {alpha:g}: {cand['rounds_run']} rounds, best {cand['best_round']}, "
              f"val MSE {cand['val_mse']:.6f} ({cand['seconds']} s)", flush=True)
        if best is None or cand["val_mse"] < best["val_mse"]:
            best = {**{k: v for k, v in cand.items() if k != "rounds"}, "c": top["c"], "b": top["b"]}
        else:
            break
    return best, out


# ---- evaluation ----------------------------------------------------------------------------------
def evaluate(c, b, ev):
    pv = predict(ev["value_rows"], c, b)
    po = predict(ev["traj_rows"], c, b)
    on = ev["on_trajectory"]
    return pv, po, {
        "value": metrics(pv, ev["value_data"]),
        "value_on_trajectory": {"mae": float(np.mean(np.abs(pv[on] - ev["value_data"]["y"][on]))),
                                "positions": int(on.sum())},
        "outcome": {"mse": mse(po, ev["traj"]["z"]), "mae": float(np.mean(np.abs(po - ev["traj"]["z"]))),
                    "positions": int(len(po))},
    }


def played_children(check_folder, data_rows, traj_path):
    """Mask over d2-check's train value rows: the child that the game actually played (it lies on the
    trajectory). Rows follow build_arrays' order (non-rule records), then mask_split's."""
    records = [r for r in read_records(check_folder) if r["rule"] is None]
    records = [r for r in records if split_of(r["game_id"]) == "train"]
    assert len(records) == len(data_rows["y"])
    moves = {}
    for line in Path(traj_path).read_text().splitlines():
        g = json.loads(line)
        moves[g["game_id"]] = g["moves"]
    mask = np.array([moves[r["game_id"]][r["ply"] - 1] == r["move"] for r in records])
    assert all(r["game_id"] == gid for r, gid in zip(records, data_rows["game_id"]))
    return mask


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    quick = "--quick" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--quick"]
    v2, check, traj_v2, traj_check, out = (Path(a) for a in args[:5])
    out.mkdir(parents=True, exist_ok=True)
    alphas, n_list, max_rounds = (ALPHAS[2:4], (100,), 3) if quick else (ALPHAS, N_GAMES, MAX_ROUNDS)
    t0 = time.time()
    timings = {}

    # Distil rows: d2-v2's D2 records, train and val buckets (rule rows excluded by build_arrays)
    arrays, v2_source = load_dataset(v2)
    train, val = mask_split(arrays, "train"), mask_split(arrays, "val")
    del arrays
    order = np.argsort(train["game_id"], kind="stable")  # first-N games become a prefix of the rows
    train = {k: v[order] for k, v in train.items()}
    check_structure(train["planes"])
    check_structure(val["planes"])
    distil_train = Rows(design(train["planes"], train["d1"]), train["d1"])
    distil_val = Rows(design(val["planes"], val["d1"]), val["d1"])
    distil_y, distil_y_val = train["y"].astype(np.float64), val["y"].astype(np.float64)
    distil_ids = train["game_id"]
    del train["planes"], val["planes"]
    timings["load_d2_v2_records"] = round(time.time() - t0, 1)
    print(f"d2-v2 records: {distil_train.n} train rows, {distil_val.n} val rows", flush=True)

    # MC / TD rows: d2-v2 trajectories (finished games), train and val buckets
    t = time.time()
    traj_train, traj_train_info = load_trajectories(traj_v2, "train")
    traj_val, traj_val_info = load_trajectories(traj_v2, "val")
    rl_train = Rows(design(traj_train["planes"], traj_train["d1"]), traj_train["d1"])
    rl_val = Rows(design(traj_val["planes"], traj_val["d1"]), traj_val["d1"])
    del traj_train["planes"], traj_val["planes"]
    timings["load_d2_v2_trajectories"] = round(time.time() - t, 1)
    print(f"d2-v2 trajectories: {traj_train_info}, val {traj_val_info}", flush=True)

    # Evaluation rows: d2-check train bucket, records (value error, choice) and trajectories (outcome)
    t = time.time()
    check_arrays, check_source = load_dataset(check)
    value_data = mask_split(check_arrays, "train")
    del check_arrays
    check_structure(value_data["planes"])
    ev_traj, ev_traj_info = load_trajectories(traj_check, "train")
    ev = {"value_data": value_data, "value_rows": Rows(design(value_data["planes"], value_data["d1"]),
                                                       value_data["d1"]),
          "traj": ev_traj, "traj_rows": Rows(design(ev_traj["planes"], ev_traj["d1"]), ev_traj["d1"]),
          "on_trajectory": played_children(check, value_data, traj_check)}
    eval_planes = value_data.pop("planes")
    del ev_traj["planes"]
    timings["load_d2_check"] = round(time.time() - t, 1)
    print(f"d2-check: {len(value_data['y'])} value rows, {int(ev['on_trajectory'].sum())} on the trajectory; "
          f"trajectories {ev_traj_info}", flush=True)

    v2_games = {g["game_id"]: g for g in (json.loads(line) for line in (v2 / "games.jsonl").read_text().splitlines())}
    train_games = sorted(g for g in v2_games if split_of(g) == "train")
    references = {
        "d1": {"value": metrics(value_data["d1"].astype(np.float64), value_data),
               "outcome": {"mse": mse(ev_traj["d1"].astype(np.float64), ev_traj["z"]),
                           "mae": float(np.mean(np.abs(ev_traj["d1"] - ev_traj["z"])))}},
        "zero": {"outcome": {"mse": mse(np.zeros(len(ev_traj["z"])), ev_traj["z"])}},
        "d1_val_outcome_mse": mse(traj_val["d1"].astype(np.float64), traj_val["z"]),
    }

    curves, final = [], {}
    for n_games in n_list:
        games = train_games if n_games is None else train_games[:n_games]
        cutoff = games[-1]
        n_distil = int(np.searchsorted(distil_ids, cutoff, side="right"))
        n_rl = int(np.searchsorted(traj_train["game_id"], cutoff, side="right"))
        rl_games = len(np.unique(traj_train["game_id"][:n_rl]))
        point = {"games": len(games), "distil_rows": n_distil, "distil_games": len(np.unique(distil_ids[:n_distil])),
                 "trajectory_rows": n_rl, "trajectory_games": rl_games,
                 "unfinished_dropped": sum(v2_games[g]["result"] is None for g in games), "methods": {}}
        print(f"N = {len(games)} games: distil {n_distil} rows, trajectories {n_rl} rows from {rl_games} games",
              flush=True)
        train_d, train_r = distil_train.head(n_distil), rl_train.head(n_rl)
        z = traj_train["z"][:n_rl]
        dist = traj_train["dist"][:n_rl]
        levels = td_levels(dist)
        last = traj_train["last_target"][:n_rl]
        for method in METHODS:
            t = time.time()
            print(f"  {method}", flush=True)
            if method == "distil":
                best, cands = plain_path(train_d, distil_y[:n_distil], distil_val, distil_y_val, alphas)
            elif method == "mc":
                best, cands = plain_path(train_r, z, rl_val, traj_val["z"], alphas)
            else:
                lam = 0.0 if method == "td0" else LAMBDA
                best, cands = td_path(train_r, z, levels, last, rl_val, traj_val["z"], lam, alphas, max_rounds)
            pv, po, scores = evaluate(best["c"], best["b"], ev)
            seconds = round(time.time() - t, 1)
            point["methods"][method] = {"selected": {k: v for k, v in best.items() if k not in ("c", "b")},
                                        "candidates": cands, **scores, "seconds": seconds}
            print(f"  {method}: alpha {best['alpha']:g}, value MAE {scores['value']['mae']:.5f}, outcome MSE "
                  f"{scores['outcome']['mse']:.5f}, top1 {scores['value']['choice']['top1']:.4f} ({seconds} s)",
                  flush=True)
            if n_games == n_list[-1]:
                final[method] = {"c": best["c"], "b": best["b"], "pv": pv, "po": po, "alpha": best["alpha"]}
        curves.append(point)
    timings["fits_and_evaluation"] = round(time.time() - t0 - sum(timings.values()), 1)

    # whole-game bootstrap at full data
    intervals = {}
    if final:
        y = value_data["y"].astype(np.float64)
        pairs = [("mc", "td0"), ("tdlambda", "mc"), ("distil", "mc"), ("distil", "td0"), ("distil", "tdlambda"),
                 ("tdlambda", "td0")]
        for a, b_ in pairs:
            key = f"{a} - {b_}"
            intervals[key] = {
                "value_error": paired_difference(np.abs(final[a]["pv"] - y), np.abs(final[b_]["pv"] - y),
                                                 value_data["game_id"], n_boot=N_BOOT, seed=BOOT_SEED),
                "outcome_error": paired_difference((final[a]["po"] - ev_traj["z"]) ** 2,
                                                   (final[b_]["po"] - ev_traj["z"]) ** 2,
                                                   ev_traj["game_id"], n_boot=N_BOOT, seed=BOOT_SEED),
                "regret": paired_regret_difference(value_data["parent"], final[a]["pv"], final[b_]["pv"], y,
                                                   games=value_data["game_id"], n_boot=N_BOOT, seed=BOOT_SEED),
            }
        # the reparameterisation check: the 1,217-weight model gives the same predictions
        x_full = features(eval_planes, value_data["d1"], packed=True)
        z0 = np.arctanh(np.clip(value_data["d1"].astype(np.float64), -D1_CLIP, D1_CLIP))
        equivalence = {m: float(np.max(np.abs(np.tanh(z0 + x_full @ full_weights(f["c"]) + f["b"]) - f["pv"])))
                       for m, f in final.items()}
        np.savez_compressed(out / "models.npz", **{f"{m}_w": full_weights(f["c"]) for m, f in final.items()},
                            **{f"{m}_b": np.array(f["b"]) for m, f in final.items()},
                            **{f"{m}_alpha": np.array(f["alpha"]) for m, f in final.items()})
    else:
        equivalence = {}

    script = Path(__file__).resolve()
    report = {
        "question": "MC, TD(0) and TD(lambda) value targets against distilling careful Stockfish (d11), "
                    "same 1,217 inputs and tanh(atanh(d1) + x.w + b) model",
        "settings": {"alphas": list(alphas), "alpha_search": "upward; stop at the first alpha whose validation "
                     "MSE is worse than the best so far", "lambda": LAMBDA, "max_rounds": max_rounds,
                     "stopping": "first round whose validation MSE does not improve on the best", "d1_clip": D1_CLIP,
                     "n_games": [len(train_games) if n is None else n for n in n_list],
                     "lm": {"iters": 40, "tol": 1e-10, "lambda0": 1e-3},
                     "bootstrap": {"resamples": N_BOOT, "seed": BOOT_SEED, "unit": "whole games"},
                     "quick": quick},
        "data": {"d2_v2": {k: v2_source[k] for k in ("dataset", "sha256", "records", "non_rule_rows",
                                                      "rule_rows_excluded")},
                 "d2_check": {k: check_source[k] for k in ("dataset", "sha256", "records", "non_rule_rows",
                                                            "rule_rows_excluded")},
                 "games_jsonl_sha256": {"d2-v2": sha256_file(v2 / "games.jsonl"),
                                        "d2-check": sha256_file(check / "games.jsonl")},
                 "trajectories_sha256": {traj_v2.name: sha256_file(traj_v2), traj_check.name: sha256_file(traj_check)},
                 "distil_train_rows": distil_train.n, "distil_val_rows": distil_val.n,
                 "trajectory_train": traj_train_info, "trajectory_val": traj_val_info,
                 "eval_value_rows": int(len(value_data["y"])),
                 "eval_decisions": int(len(np.unique(value_data["parent"]))),
                 "eval_value_games": int(len(np.unique(value_data["game_id"]))),
                 "eval_on_trajectory_rows": int(ev["on_trajectory"].sum()),
                 "eval_trajectory": ev_traj_info},
        "references": references,
        "curves": curves,
        "intervals_full_data": intervals,
        "reparameterisation_max_abs_prediction_difference": equivalence,
        "code": {"script": script.name, "sha256": sha256_file(script), "runtime": runtime()},
        "timings_seconds": {**timings, "total": round(time.time() - t0, 1)},
    }
    name = "results-quick.json" if quick else "results.json"
    (out / name).write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {out / name} in {report['timings_seconds']['total']} s", flush=True)


if __name__ == "__main__":
    main()
