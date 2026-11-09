"""Attribute a move's tree construction and growth time to rules operations (phase B1 of the native port).

usage, inside labels/tools/torch_port.sh, with the arguments of profile_move.py:
    profile_construction.py --data /labels/<dataset> --checkpoint /repo/pair_b/checkpoints/<run>/best.pt \
        --moves 3 --pcfr-backend native --rounds 4096 --max-depth 4

Same agent configuration and record choice as profile_move.py. Prints, per position, the cumulative and own
time of the rules operations that tree construction calls (observe, legal_moves, apply_move, terminal,
visible_squares, _extend, observation_key, board copies, the planes encoder), and who calls observe.
"""
import argparse
import cProfile
import dataclasses
import glob
import pstats
import time

from fow_shared.recording import read_records

TARGETS = [
    ("chess_search", "reconstruct_roots"), ("chess_search", "_build_roots"), ("chess_search", "expand"),
    ("chess_projection", "project_chess"),
    ("rules_adapter", "observe"), ("rules_adapter", "visible_squares"), ("rules_adapter", "legal_moves"),
    ("rules_adapter", "apply_move"), ("rules_adapter", "terminal"), ("rules_adapter", "__post_init__"),
    ("chess_search", "_extend"), ("chess_search", "observation_key"), ("dataclasses", "asdict"),
    ("json/__init__", "dumps"), ("values", "fog_legal_moves"), ("values", "terminal_score"),
    ("values", "_is_fog_threefold_repetition"), ("chess/__init__", "copy"), ("chess/__init__", "push"),
    ("chess/__init__", "pop"), ("chess/__init__", "generate_pseudo_legal_moves"),
    ("chess/__init__", "generate_castling_moves"), ("chess/__init__", "fen"), ("chess/__init__", "__init__"),
    ("_rules_native", ""), ("_rules_native", "_analyze"), ("_rules_native", "apply_move"),
    ("_rules_native", "observation_key"), ("_rules_native", "native"), ("_rules_native", "materialize"),
    ("features", ""), ("pairb/observe", ""), ("chess/", ""), ("belief_evaluator", "evaluate_children"), ("pcfr", "solve"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--moves", type=int, default=3)
    ap.add_argument("--budget-ms", type=int, default=5000)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--plies", default="4,30,70")
    ap.add_argument("--pcfr-backend", default=None, choices=("python", "native"))
    ap.add_argument("--rounds", type=int, default=1024)
    ap.add_argument("--max-depth", type=int, default=2)
    ap.add_argument("--max-nodes", type=int, default=16384)
    args = ap.parse_args()

    if args.pcfr_backend is not None:
        from pair_a_prep import pcfr
        pcfr.PCFRPlus.BACKEND = args.pcfr_backend
    from pair_a_prep.anytime_agent import AnytimeConfig
    from pair_a_prep.chess_subgame_agent import ChessSubgameAgent
    from pairb.belief_evaluator import BeliefNetworkEvaluator

    leaf = BeliefNetworkEvaluator.from_checkpoint(args.checkpoint, device=args.device)
    config = AnytimeConfig(growth="one_sided", rounds=args.rounds, max_nodes=args.max_nodes, max_evaluator_calls=4096,
                           stop_on_time=True, expansion_fraction=0.7, initial_depth=1, max_depth=args.max_depth,
                           rounds_per_stage=2, final_rounds=2, schedule="alternating")
    targets = [int(x) for x in args.plies.split(",")][: args.moves]
    picked = {}
    for path in sorted(glob.glob(f"{args.data}/part-*.jsonl"))[:40]:
        for record in read_records(path):
            ply = record.agent_input.observation.ply
            for t in targets:
                if t not in picked and abs(ply - t) <= 2 and len(record.agent_input.belief.hypotheses) >= 8:
                    picked[t] = record
        if len(picked) == len(targets):
            break

    for t in targets:
        record = picked.get(t)
        if record is None:
            continue
        turn = dataclasses.replace(record.agent_input, time_budget_ms=args.budget_ms)
        agent = ChessSubgameAgent(leaf, config, None)
        agent.reset(turn.observation.player, 7)
        profiler = cProfile.Profile()
        started = time.perf_counter()
        profiler.enable()
        decision = agent.act(turn)
        profiler.disable()
        elapsed = time.perf_counter() - started
        d = decision.diagnostics
        print(f"\n=== ply {turn.observation.ply}: wall {elapsed:.2f} s | nodes {d.get('search_nodes')} | "
              f"expansions {d.get('expansions')} | stop {[k[5:] for k in d if k.startswith('stop:') and d[k]]}")
        stats = pstats.Stats(profiler)
        print(f"  {'function':58s} {'calls':>8s} {'own s':>7s} {'cum s':>7s}")
        for module, name in TARGETS:
            rows = [(k, v) for k, v in stats.stats.items()
                    if module in k[0].replace("\\", "/") and (not name or k[2] == name)]
            if not rows:
                continue
            calls = sum(v[1] for _, v in rows)
            own = sum(v[2] for _, v in rows)
            # cumulative: sum over distinct entries (recursion counted once by cProfile per entry)
            cum = sum(v[3] for _, v in rows)
            label = f"{module}:{name or '*'}"
            print(f"  {label:58s} {calls:8d} {own:7.3f} {cum:7.3f}")
        print("  callers of rules_adapter.observe (cum s):")
        for key, value in stats.stats.items():
            if "rules_adapter" in key[0] and key[2] == "observe":
                for caller, info in sorted(value[4].items(), key=lambda kv: -kv[1][3]):
                    print(f"    {caller[0].split('/')[-1]}:{caller[1]}({caller[2]}) calls {info[1]} cum {info[3]:.3f}")
        for name in ("copy", "generate_pseudo_legal_moves", "__init__", "push"):
            print(f"  callers of chess {name} (cum s):")
            for key, value in stats.stats.items():
                if "chess/__init__" in key[0] and key[2] == name:
                    for caller, info in sorted(value[4].items(), key=lambda kv: -kv[1][3])[:5]:
                        print(f"    {caller[0].split('/')[-1]}:{caller[1]}({caller[2]}) calls {info[1]} cum {info[3]:.3f}")
    leaf.close()


if __name__ == "__main__":
    main()
