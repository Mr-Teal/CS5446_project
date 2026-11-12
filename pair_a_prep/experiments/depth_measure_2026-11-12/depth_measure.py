"""Depth-limit measurement (12 Nov 2026): does raising the search agent's depth limit give deeper trees now that the
rules, leaf and solver are native, and does the root strategy stop being one-hot?

Fresh solves (no saved tree) of validation positions of the 480-game label set (test games are never read), with the
search agent's self-play configuration except the depth limit: one-sided growth, PCFR+ alternating, up to 65,536
iterations (so the clock binds), 16,384 nodes, 4,096 leaf calls, growth until 70 % of the clock; leaf = value network
v2, checkpoint g237, on cuda. For every position the depth limits run back to back with the same seed.

usage: depth_measure.py --budget-ms 2000 --depths 2 4 6 --positions 200 --out /labels/policy/depth/pass-2000.jsonl
       depth_measure.py ... --max-nodes 65536 --max-leaf-calls 16384   (raise the node and leaf-call caps)
       depth_measure.py --summary /labels/policy/depth/pass-2000.jsonl [...]
"""
import argparse
import glob
import hashlib
import json
import statistics as st
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

CHECKPOINT = "/repo/pair_b/checkpoints/belief-solver-v2-sf8-g237/best.pt"


def split_of(game_id):
    b = int(hashlib.sha1(game_id.encode()).hexdigest(), 16) % 10
    return "train" if b < 8 else ("val" if b == 8 else "test")


def val_positions(n):
    from fow_shared.recording import read_records
    turns, skipped = [], 0
    for path in sorted(glob.glob("/labels/solver-v2-sf8-480/part-*.jsonl")):
        with open(path) as f:
            first = f.readline()
        if not first:
            continue
        split = split_of(json.loads(first)["game_id"])
        if split == "test":
            skipped += 1
            continue
        if split != "val":
            continue
        for r in read_records(path):
            turns.append((r.game_id, r.agent_input))
    step = max(1, len(turns) // n)
    picked = turns[::step][:n]
    print(f"{len(turns)} val positions, {len(picked)} picked (every {step}th); {skipped} test-game files not read",
          flush=True)
    return picked


def tree_stats(root):
    """Decision depth = number of player decisions on a path (1 = our move only). Counts per depth, the deepest path,
    and for each of our root moves the deepest decision below it."""
    per_depth, deepest = Counter(), 0
    root_move_depth = {}

    def walk(node, depth, root_move):
        nonlocal deepest
        if node.payoff is not None or not node.children:
            return
        if node.player is None:
            for child in node.children.values():
                walk(child, depth, root_move)
            return
        depth += 1
        per_depth[depth] += 1
        deepest = max(deepest, depth)
        if root_move is not None:
            root_move_depth[root_move] = max(root_move_depth.get(root_move, 1), depth)
        for action, child in node.children.items():
            walk(child, depth, action if depth == 1 else root_move)

    walk(root, 0, None)
    return per_depth, deepest, root_move_depth


def rss_mb():
    for line in open("/proc/self/status"):
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) // 1024
    return None


def measure(args):
    from pair_a_prep.anytime_agent import AnytimeConfig
    from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
    from pair_a_prep.evaluation_factories import _load_leaf
    from pair_a_prep import _pcfr_native, _rules_native, _leaf_native, _belief_native
    flags = [m.library() is not None for m in (_pcfr_native, _rules_native, _leaf_native, _belief_native)]
    print("native kernels pcfr/rules/leaf/belief:", flags, flush=True)
    if not all(flags):
        raise SystemExit("a native kernel did not load")
    leaf = _load_leaf({"leaf_evaluator": "belief_network", "checkpoint_path": CHECKPOINT, "device": "cuda"})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        done = {(r["game_id"], r["ply"], r["depth_limit"], r.get("max_nodes", 16384))
                for r in map(json.loads, out.read_text().splitlines()) if r}
    positions = val_positions(args.positions)
    with out.open("a") as f:
        for k, (game_id, turn) in enumerate(positions):
            turn = replace(turn, time_budget_ms=args.budget_ms)
            seed = int(hashlib.sha256(f"{game_id}:{turn.observation.ply}".encode()).hexdigest()[:8], 16)
            for depth in args.depths:
                key = (game_id, turn.observation.ply, depth, args.max_nodes)
                if key in done:
                    continue
                config = AnytimeConfig(growth="one_sided", rounds=65536, max_nodes=args.max_nodes,
                                       max_evaluator_calls=args.max_leaf_calls,
                                       stop_on_time=True, expansion_fraction=0.7, growth_headroom=0,
                                       initial_depth=1, max_depth=depth, rounds_per_stage=2, final_rounds=2,
                                       schedule="alternating")
                agent = ChessSubgameAgent(leaf, config, None)
                agent.reset(turn.observation.player, seed)
                row = dict(game_id=game_id, ply=turn.observation.ply, player=turn.observation.player,
                           depth_limit=depth, max_nodes=args.max_nodes, max_leaf_calls=args.max_leaf_calls,
                           budget_ms=args.budget_ms, legal_moves=len(turn.observation.legal_moves),
                           boards=len(turn.belief.hypotheses), error=None)
                started = time.perf_counter()
                try:
                    result = agent.solve(turn)
                except Exception as exc:  # a failed solve is a measurement, not a crash
                    row.update(error=f"{type(exc).__name__}: {exc}", wall_ms=1000 * (time.perf_counter() - started))
                    f.write(json.dumps(row) + "\n"); f.flush()
                    continue
                d = result.decision.diagnostics
                policy = result.decision.root_policy
                per_depth, deepest, root_move_depth = tree_stats(agent.last_projection.tree.root)
                row.update(
                    wall_ms=1000 * (time.perf_counter() - started), elapsed_ms=d.get("elapsed_ms"),
                    nodes=d.get("search_nodes"), iterations=d.get("solver_rounds_this_turn"),
                    expansions=d.get("expansions"), leaf_calls=d.get("evaluator_calls"),
                    nash_gap=d.get("solver_nash_gap"), root_value=d.get("solver_root_value"),
                    growth_stop=[k.split(":", 1)[1] for k in d if k.startswith("growth_stop:")],
                    stop=[k.split(":", 1)[1] for k in d if k.startswith("stop:")],
                    decisions_per_depth={str(k): v for k, v in sorted(per_depth.items())}, deepest=deepest,
                    root_moves_by_depth=dict(Counter(str(v) for v in root_move_depth.values())),
                    top_prob=max(policy.values()), support=sum(1 for p in policy.values() if p > 0.01),
                    argmax=max(policy, key=policy.get), rss_mb=rss_mb(), stop_reason=agent.last_stop_reason)
                f.write(json.dumps(row) + "\n"); f.flush()
            if (k + 1) % 20 == 0:
                print(f"{k + 1} positions done", flush=True)


def summary(paths):
    for path in paths:
        rows = [json.loads(l) for l in open(path) if l.strip()]
        by = {}
        for r in rows:
            by.setdefault((r["depth_limit"], r.get("max_nodes", 16384)), []).append(r)
        base = {(r["game_id"], r["ply"]): r for r in by.get(min(by), []) if not r["error"]}
        print(f"=== {path}: {len({(r['game_id'], r['ply']) for r in rows})} positions")
        print("limit/cap  ok/err  nodes(med)  iters(med)  expans(med)  deepest: share>=3  >=4  >=5  max  "
              "root moves below depth 2 (mean share)  one-hot  top-prob(mean)  nash-gap(med)  same move as first row  "
              "rss MB med/max")
        for depth in sorted(by):
            ok = [r for r in by[depth] if not r["error"]]
            if not ok:
                print(f"{depth}  0/{len(by[depth])}")
                continue
            share_deep = st.mean(sum(v for k, v in r["root_moves_by_depth"].items() if int(k) >= 3)
                                 / max(1, r["legal_moves"]) for r in ok)
            same = [r["argmax"] == base[(r["game_id"], r["ply"])]["argmax"] for r in ok if (r["game_id"], r["ply"]) in base]
            print(f"{str(depth):>12}  {len(ok)}/{len(by[depth]) - len(ok)}  {st.median(r['nodes'] for r in ok):10.0f}  "
                  f"{st.median(r['iterations'] for r in ok):10.0f}  {st.median(r['expansions'] for r in ok):11.0f}  "
                  f"{sum(r['deepest'] >= 3 for r in ok) / len(ok):16.2f}  {sum(r['deepest'] >= 4 for r in ok) / len(ok):4.2f}  "
                  f"{sum(r['deepest'] >= 5 for r in ok) / len(ok):4.2f}  {max(r['deepest'] for r in ok):3d}  "
                  f"{share_deep:36.3f}  {sum(r['top_prob'] >= 0.999 for r in ok) / len(ok):7.2f}  "
                  f"{st.mean(r['top_prob'] for r in ok):14.3f}  {st.median(r['nash_gap'] for r in ok):13.4f}  "
                  f"{sum(same) / max(1, len(same)):.2f}  "
                  f"{st.median(r.get('rss_mb') or 0 for r in ok):.0f}/{max(r.get('rss_mb') or 0 for r in ok)}")
            print("       growth stop reasons:", dict(Counter(s for r in ok for s in r["growth_stop"])))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-ms", type=int, default=2000)
    ap.add_argument("--depths", type=int, nargs="+", default=[2, 4, 6])
    ap.add_argument("--positions", type=int, default=200)
    ap.add_argument("--max-nodes", type=int, default=16384)
    ap.add_argument("--max-leaf-calls", type=int, default=4096)
    ap.add_argument("--out")
    ap.add_argument("--summary", nargs="+")
    a = ap.parse_args()
    if a.summary:
        summary(a.summary)
    else:
        measure(a)
