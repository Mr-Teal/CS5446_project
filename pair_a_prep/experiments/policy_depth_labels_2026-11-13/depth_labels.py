"""Depth-2 and depth-6 policy labels from the same leaf (13 Nov 2026), for the policy-network retest.

For each selected train/val position of the 480-game label set (test games never read): two fresh solves by the
search agent with value network v2 g237 as the leaf (cuda), native kernels, cap 262,144 nodes and leaf calls:
depth limit 2 at 2 s (its tree is solved completely well inside 2 s; 2, 5 and 15 s gave identical statistics) and
depth limit 6 at 2 s (same one-hot rate as at 5 s in the depth measurement, half the tree, half the memory). Rows use the afterstate-q-v1 fields the policy-network loader reads (moves, weights,
action_values per board and move, policy_last, policy_mean, played, ...). policy_mean is set equal to policy_last:
this branch does not export the average strategy. Extra fields: depth_limit, tree size, and the purification
test on val positions only (null on train rows).

Selection: every 2nd position of every val game, every 4th of every train game; game k (sorted ids) goes to shard
k % shards; within a shard all val positions come first. Resume: rows already written for (game, ply, depth) are
skipped.

usage: depth_labels.py --shard I --shards N --out /labels/policy/depthlabels
"""
import argparse
import glob
import hashlib
import importlib.util
import json
import time
from dataclasses import replace
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "depth_measure", "/repo/pair_a_prep/experiments/depth_measure_2026-11-12/depth_measure.py")
dm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dm)

SETTINGS = {2: 2000, 6: 2000}   # depth limit -> clock in ms (depth 6 at 2 s mixes as at 5 s: 56 % vs 54 % one-hot)


def per_board_values(agent, turn, moves):
    """Q(h, a) for every hypothesis (record order) and root move, and whether the move's child was searched further,
    under the final solved profile; aliased hypotheses share their root's row."""
    from pair_a_prep.toy_games import information_sets, value_walk
    projection, profile = agent.last_projection, agent.last_solver.policy()
    q_by_id, deep_by_id = {}, {}
    for identity, root in zip(projection.root_ids, projection.tree.continuations):
        sets = information_sets(root)
        local = tuple({key: profile[p][key] for key in sets[p]} for p in (0, 1))
        q_by_id[identity] = {a: value_walk(child, local) for a, child in root.children.items()}
        deep_by_id[identity] = {a: bool(child.children) for a, child in root.children.items()}
    ids = [projection.aliases.get(k, k) for k in projection.current_ids]
    q = [[min(1.0, max(-1.0, q_by_id[i][a])) for a in moves] for i in ids]
    deep = [[int(deep_by_id[i][a]) for a in moves] for i in ids]
    return q, deep


def selected():
    from fow_shared.recording import read_records
    games = {}
    for path in sorted(glob.glob("/labels/solver-v2-sf8-480/part-*.jsonl")):
        with open(path) as f:
            first = f.readline()
        if not first:
            continue
        gid = json.loads(first)["game_id"]
        split = dm.split_of(gid)
        if split == "test":
            continue
        recs = list(read_records(path))
        step = 2 if split == "val" else 4
        games.setdefault(gid, (split, []))[1].extend(recs[::step])
    return games


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None, help="stop after this many positions (smoke)")
    ap.add_argument("--part", type=int, nargs=2, default=None, metavar=("J", "M"),
                    help="take only every M-th position of this shard's work list, starting at J (parallel resume)")
    args = ap.parse_args()
    from pair_a_prep.anytime_agent import AnytimeConfig
    from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
    from pair_a_prep.evaluation_factories import _load_leaf
    from pair_a_prep import _pcfr_native, _rules_native, _leaf_native, _belief_native
    if not all(m.library() is not None for m in (_pcfr_native, _rules_native, _leaf_native, _belief_native)):
        raise SystemExit("a native kernel did not load")
    leaf = _load_leaf({"leaf_evaluator": "belief_network", "checkpoint_path": dm.CHECKPOINT, "device": "cuda"})
    games = selected()
    mine = [g for k, g in enumerate(sorted(games)) if k % args.shards == args.shard]
    work = [(gid, r) for split in ("val", "train") for gid in mine if games[gid][0] == split for r in games[gid][1]]
    print(f"shard {args.shard}/{args.shards}: {len(mine)} games, {len(work)} positions "
          f"({sum(1 for g in mine if games[g][0] == 'val')} val games first)", flush=True)
    suffix = f"-p{args.part[0]}" if args.part else ""
    if args.part:
        work = work[args.part[0]::args.part[1]]
    outs = {d: Path(args.out) / f"d{d}" / f"resolve-{args.shard}-of-{args.shards}{suffix}.jsonl" for d in SETTINGS}
    done = set()
    for d, path in outs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        for old in path.parent.glob(f"resolve-{args.shard}-of-{args.shards}*.jsonl"):  # every part of this shard
            done |= {(r["game_id"], r["ply"], d)
                     for r in (json.loads(line) for line in old.read_text().splitlines() if line.strip())}
    files = {d: path.open("a") for d, path in outs.items()}
    started, n = time.time(), 0
    for gid, rec in work:
        turn0 = rec.agent_input
        ply, moves = turn0.observation.ply, list(turn0.observation.legal_moves)
        seed = int(hashlib.sha256(f"{gid}:{ply}".encode()).hexdigest()[:8], 16)
        for depth, budget in SETTINGS.items():
            if (gid, ply, depth) in done:
                continue
            config = AnytimeConfig(growth="one_sided", rounds=65536, max_nodes=262144, max_evaluator_calls=262144,
                                   stop_on_time=True, expansion_fraction=0.7, growth_headroom=0, initial_depth=1,
                                   max_depth=depth, rounds_per_stage=2, final_rounds=2, schedule="alternating")
            agent = ChessSubgameAgent(leaf, config, None)
            agent.reset(turn0.observation.player, seed)
            turn = replace(turn0, time_budget_ms=budget)
            row = dict(schema="afterstate-q-v1", game_id=gid, ply=ply, player=turn.observation.player,
                       split=dm.split_of(gid), moves=moves, weights=[h.weight for h in turn.belief.hypotheses],
                       played=rec.decision.move, depth_limit=depth, time_budget_ms=budget,
                       evaluator="belief-solver-v2-sf8-g237", error=None)
            try:
                result = agent.solve(turn)
                policy = result.decision.root_policy
                q, deep = per_board_values(agent, turn, moves)
                p = [float(policy.get(a, 0.0)) for a in moves]
                d = result.decision.diagnostics
                row.update(action_values=q, deepened=deep, policy_last=p, policy_mean=p,
                           hypothesis_values=list(result.hypothesis_values), root_value=result.root_value,
                           diag=dict(search_nodes=d.get("search_nodes"), solver_rounds_this_turn=d.get("solver_rounds_this_turn"),
                                     evaluator_calls=d.get("evaluator_calls"), expansions=d.get("expansions"),
                                     elapsed_ms=d.get("elapsed_ms"), nash_gap=d.get("solver_nash_gap")),
                           **(dm.purification_test(agent, policy) if row["split"] == "val" else
                              dict(br_mixed=None, br_pure=None, purify_loss=None)))
            except Exception as exc:
                row.update(error=f"{type(exc).__name__}: {exc}")
            files[depth].write(json.dumps(row) + "\n")
            files[depth].flush()
        n += 1
        if args.limit is not None and n >= args.limit:
            break
        if n % 25 == 0:
            el = time.time() - started
            print(f"{n}/{len(work)} positions, {el / n:.1f} s each, rss {dm.rss_mb()} MB", flush=True)
    print(f"shard {args.shard} DONE", flush=True)


if __name__ == "__main__":
    main()
