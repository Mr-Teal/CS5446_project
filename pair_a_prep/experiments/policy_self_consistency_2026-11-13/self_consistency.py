"""Self-consistency ceiling of the policy labels (13 Nov 2026): solve the same val position twice with different random
seeds (same leaf value network v2 g237, same 2 s clock, same caps, depth limit 2 and 6) and measure how often the
two solves agree. A network that imitated one solve perfectly could not agree with another solve more often than this.

Solve A is the existing label row in /labels/policy/depthlabels/d{2,6}/ (seed from "game:ply"); solve B is new, seed
from "game:ply:seed2". Val positions only; test games never read.

usage: self_consistency.py --positions 200 --part J M --out /labels/policy/selfcons
       self_consistency.py --summary /labels/policy/selfcons
"""
import argparse
import glob
import hashlib
import importlib.util
import json
import statistics as st
from dataclasses import replace
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "depth_labels", "/repo/pair_a_prep/experiments/policy_depth_labels_2026-11-13/depth_labels.py")
dl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dl)
dm = dl.dm


def label_rows(depth):
    rows = {}
    for path in sorted(glob.glob(f"/labels/policy/depthlabels/d{depth}/resolve-*.jsonl")):
        for line in open(path):
            if line.strip():
                r = json.loads(line)
                if r.get("error") is None and r["split"] == "val":
                    rows[(r["game_id"], r["ply"])] = r
    return rows


def qstar(row):
    w = [x / sum(row["weights"]) for x in row["weights"]]
    return [sum(w[h] * row["action_values"][h][a] for h in range(len(w))) for a in range(len(row["moves"]))]


def compare(a, b):
    """a, b: rows with moves (same order), policy_last, action_values, weights."""
    pa, pb, qa, qb = a["policy_last"], b["policy_last"], qstar(a), qstar(b)
    ia, ib = max(range(len(pa)), key=pa.__getitem__), max(range(len(pb)), key=pb.__getitem__)
    support_a = {i for i, p in enumerate(pa) if p > 0.01}
    return dict(same_top=ia == ib, b_top_in_a_support=ib in support_a,
                tv=0.5 * sum(abs(x - y) for x, y in zip(pa, pb)),
                regret_b_under_a=max(qa) - qa[ib], regret_a_under_b=max(qb) - qb[ia],
                a_onehot=max(pa) >= 0.999, b_onehot=max(pb) >= 0.999,
                q_diff=max(abs(x - y) for x, y in zip(qa, qb)), a_purify_loss=a.get("purify_loss"))


def run(args):
    from fow_shared.recording import read_records
    from pair_a_prep.anytime_agent import AnytimeConfig
    from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
    from pair_a_prep.evaluation_factories import _load_leaf
    rows = {d: label_rows(d) for d in (2, 6)}
    keys = sorted(set(rows[2]) & set(rows[6]))
    step = max(1, len(keys) // args.positions)
    keys = keys[::step][:args.positions][args.part[0]::args.part[1]]
    wanted = set(keys)
    records = {}
    for path in sorted(glob.glob("/labels/solver-v2-sf8-480/part-*.jsonl")):
        with open(path) as f:
            first = f.readline()
        if not first or dm.split_of(json.loads(first)["game_id"]) != "val":
            continue
        for r in read_records(path):
            k = (r.game_id, r.agent_input.observation.ply)
            if k in wanted:
                records[k] = r
    leaf = _load_leaf({"leaf_evaluator": "belief_network", "checkpoint_path": dm.CHECKPOINT, "device": "cuda"})
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    path = out / f"part-{args.part[0]}-of-{args.part[1]}.jsonl"
    done = set()
    if path.exists():
        done = {(r["game_id"], r["ply"], r["depth"]) for r in map(json.loads, path.read_text().splitlines()) if r}
    print(f"{len(keys)} val positions in this part", flush=True)
    with path.open("a") as f:
        for n, k in enumerate(keys):
            rec = records[k]
            moves = list(rec.agent_input.observation.legal_moves)
            seed = int(hashlib.sha256(f"{k[0]}:{k[1]}:seed2".encode()).hexdigest()[:8], 16)
            for depth in (2, 6):
                if (k[0], k[1], depth) in done:
                    continue
                config = AnytimeConfig(growth="one_sided", rounds=65536, max_nodes=262144, max_evaluator_calls=262144,
                                       stop_on_time=True, expansion_fraction=0.7, growth_headroom=0, initial_depth=1,
                                       max_depth=depth, rounds_per_stage=2, final_rounds=2, schedule="alternating")
                agent = ChessSubgameAgent(leaf, config, None)
                agent.reset(rec.agent_input.observation.player, seed)
                turn = replace(rec.agent_input, time_budget_ms=2000)
                row = dict(game_id=k[0], ply=k[1], depth=depth, error=None)
                try:
                    result = agent.solve(turn)
                    q, _ = dl.per_board_values(agent, turn, moves)
                    b = dict(moves=moves, weights=[h.weight for h in turn.belief.hypotheses], action_values=q,
                             policy_last=[float(result.decision.root_policy.get(m, 0.0)) for m in moves])
                    row.update(compare(rows[depth][k], b))
                except Exception as exc:
                    row.update(error=f"{type(exc).__name__}: {exc}")
                f.write(json.dumps(row) + "\n"); f.flush()
            if (n + 1) % 20 == 0:
                print(f"{n + 1}/{len(keys)}", flush=True)
    print("DONE", flush=True)


def summary(folder):
    rows = [json.loads(l) for p in glob.glob(f"{folder}/part-*.jsonl") for l in open(p) if l.strip()]
    for depth in (2, 6):
        ok = [r for r in rows if r["depth"] == depth and not r["error"]]
        if not ok:
            continue
        mixed = [r for r in ok if (r["a_purify_loss"] or 0) > 0.005]
        def line(name, rs):
            return (f"  {name}: n {len(rs)}, same top move {sum(r['same_top'] for r in rs) / len(rs):.3f}, "
                    f"B's top in A's support {sum(r['b_top_in_a_support'] for r in rs) / len(rs):.3f}, "
                    f"TV mean {st.mean(r['tv'] for r in rs):.3f}, regret of B's top under A's values "
                    f"{st.mean(r['regret_b_under_a'] for r in rs):.4f}, both one-hot "
                    f"{sum(r['a_onehot'] and r['b_onehot'] for r in rs) / len(rs):.3f}")
        print(f"depth {depth}: errors {sum(1 for r in rows if r['depth'] == depth and r['error'])}")
        print(line("all", ok))
        if mixed:
            print(line("genuinely mixed in A", mixed))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--positions", type=int, default=200)
    ap.add_argument("--part", type=int, nargs=2, default=(0, 1))
    ap.add_argument("--out", default="/labels/policy/selfcons")
    ap.add_argument("--summary")
    a = ap.parse_args()
    summary(a.summary) if a.summary else run(a)
