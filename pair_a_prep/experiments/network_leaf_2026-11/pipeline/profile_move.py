"""Profile one 5 s move of the subgame agent with the network leaf: where the clock goes.

usage, inside tools/torch.sh or torch4g.sh:
    profile_move.py --data /labels/<dataset> --checkpoint /repo/pair_b/checkpoints/<run>/best.pt [--moves 3] [--budget-ms 5000]

Takes stored records (their AgentInput carries the observation and the 16 sampled hypotheses, so no tracker is
needed), builds ChessSubgameAgent in the strength arms' configuration, and runs act() under cProfile. Prints the
agent's own diagnostics (nodes, evaluator calls, rounds, elapsed) and the cumulative time of the main modules.
"""
import argparse
import cProfile
import dataclasses
import pstats
import io
import glob
import time

from fow_shared.recording import read_records


def _families(stats) -> dict:
    """Own time per module family from a pstats.Stats."""
    families = {"pair_a_prep.chess_search": 0.0, "pair_a_prep.pcfr": 0.0, "pair_a_prep._pcfr_native": 0.0,
                "pair_a_prep.one_sided": 0.0, "pair_a_prep.chess_projection": 0.0, "pair_a_prep.chess_gadgets": 0.0,
                "pair_a_prep.cross_turn": 0.0, "pair_a_prep.rules": 0.0, "pair_a_prep._rules_native": 0.0,
                "pair_a_prep._leaf_native": 0.0, "pairb.belief_evaluator": 0.0, "fow_shared.features": 0.0,
                "torch": 0.0, "chess/": 0.0, "pairb.observe": 0.0, "fow_shared.values": 0.0, "toy_games": 0.0}
    for (filename, _line, _func), (_cc, _nc, tt, _ct, _callers) in stats.stats.items():
        name = filename.replace("\\", "/")
        for key in families:
            if key.replace(".", "/") in name:
                families[key] += tt
                break
    return families


def replay_game(args, leaf, config) -> None:
    """Consecutive own turns of one recorded game through one agent: the saved tree is projected and rebased
    each turn, so the cross-turn gadget path runs from turn 2. Profiles turns 2..N together."""
    from pair_a_prep.chess_subgame_agent import ChessSubgameAgent

    games = {}
    for path in sorted(glob.glob(f"{args.data}/part-*.jsonl"))[:40]:
        for record in read_records(path):
            games.setdefault((record.game_id, record.agent_input.observation.player), []).append(record)
        if any(len(v) >= args.game_turns for v in games.values()):
            break
    key = next((k for k, v in games.items() if len(v) >= args.game_turns), None)
    if key is None:
        print("no game with that many own turns in the first part files")
        return
    turns = sorted(games[key], key=lambda r: r.agent_input.observation.ply)[: args.game_turns]
    agent = ChessSubgameAgent(leaf, config, None)
    agent.reset(key[1], 7)
    profiler = cProfile.Profile()
    print(f"=== game {key[0]} as {key[1]}: {len(turns)} own turns, budget {args.budget_ms} ms, profiling turns 2..{len(turns)}")
    for index, record in enumerate(turns, start=1):
        turn = dataclasses.replace(record.agent_input, time_budget_ms=args.budget_ms)
        if index >= 2:
            profiler.enable()
        started = time.perf_counter()
        try:
            decision = agent.act(turn)
        except ValueError as exc:
            # The record's own move is the LABEL agent's; when this agent's purified policy gave it zero
            # probability, the saved tree cannot be projected onto it (a real game never does this). Start fresh.
            if index >= 2:
                profiler.disable()
            print(f"turn {index} ply {turn.observation.ply}: projection refused ({exc}); saved tree dropped, fresh turn")
            agent.saved = None
            if index >= 2:
                profiler.enable()
            started = time.perf_counter()
            decision = agent.act(turn)
        elapsed = time.perf_counter() - started
        if index >= 2:
            profiler.disable()
        d = decision.diagnostics
        proj = {k[11:]: f"{v:g}" for k, v in d.items() if k.startswith("projection:")}
        print(f"turn {index} ply {turn.observation.ply}: wall {elapsed:.2f} s | nodes {d.get('search_nodes')} | "
              f"rounds {d.get('solver_rounds_this_turn')} | expansions {d.get('expansions')} | "
              f"mode_switches {d.get('mode_switches')} | fallback {d.get('fallback')} | "
              f"stop {[k[5:] for k in d if k.startswith('stop:') and d[k]]} | projection {proj} | move {decision.move}")
    stats = pstats.Stats(profiler)
    total = stats.total_tt
    print(f"own time by module over turns 2..{len(turns)} (s, of {total:.2f} profiled):")
    for key_, value in sorted(_families(stats).items(), key=lambda kv: -kv[1]):
        if value > 0.01:
            print(f"  {key_:28s} {value:6.2f}  ({100 * value / total:4.1f} %)")
    buf = io.StringIO()
    pstats.Stats(profiler, stream=buf).sort_stats("cumulative").print_stats(18)
    lines = [l for l in buf.getvalue().splitlines() if l.strip() and not l.startswith("Ordered") and "function calls" not in l]
    print("top cumulative:")
    for l in lines[:22]:
        print("  " + l.strip()[:160])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--moves", type=int, default=3)
    ap.add_argument("--budget-ms", type=int, default=5000)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--plies", default="4,30,70", help="target plies to pick records near (one per move)")
    ap.add_argument("--pcfr-fast", type=int, default=None, choices=(0, 1),
                    help="force PCFRPlus.FAST_PREPARE (the level-wise prediction walk) on or off")
    ap.add_argument("--pcfr-backend", default=None, choices=("python", "native"),
                    help="force PCFRPlus.BACKEND (native: the C++ round, which must be built)")
    ap.add_argument("--rounds", type=int, default=1024, help="AnytimeConfig.rounds, the PCFR+ round cap per move")
    ap.add_argument("--max-depth", type=int, default=2, help="AnytimeConfig.max_depth, the subgame tree depth cap in plies")
    ap.add_argument("--max-nodes", type=int, default=16384, help="AnytimeConfig.max_nodes")
    ap.add_argument("--game-turns", type=int, default=0,
                    help="replay this many consecutive own turns of ONE recorded game through one agent instead of "
                         "isolated positions, so cross-turn projection and gadget mode run from the second turn on; "
                         "the profile covers turns 2..N")
    args = ap.parse_args()

    if args.pcfr_fast is not None:
        from pair_a_prep import pcfr
        pcfr.PCFRPlus.FAST_PREPARE = bool(args.pcfr_fast)
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

    if args.game_turns:
        replay_game(args, leaf, config)
        leaf.close()
        return

    # one record per target ply, from the first part files
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
            print(f"no record near ply {t}")
            continue
        turn = dataclasses.replace(record.agent_input, time_budget_ms=args.budget_ms)  # keeps history + paths
        agent = ChessSubgameAgent(leaf, config, None)
        agent.reset(turn.observation.player, 7)
        profiler = cProfile.Profile()
        started = time.perf_counter()
        profiler.enable()
        decision = agent.act(turn)
        profiler.disable()
        elapsed = time.perf_counter() - started
        d = decision.diagnostics
        print(f"\n=== ply {turn.observation.ply} ({turn.observation.player}), {len(turn.belief.hypotheses)} hypotheses, "
              f"{len(turn.observation.legal_moves)} legal moves: wall {elapsed:.2f} s | nodes {d.get('search_nodes')} | "
              f"evaluator calls {d.get('evaluator_calls')} | rounds {d.get('solver_rounds_this_turn')} | "
              f"expansions {d.get('expansions')} | fallback {d.get('fallback')} | move {decision.move} | "
              f"stop {[k[5:] for k in d if k.startswith('stop:') and d[k]]} | "
              f"depth {{{', '.join(f'{k}={v:g}' for k, v in d.items() if 'depth' in k)}}}")
        stats = pstats.Stats(profiler)
        total = stats.total_tt
        # time by module family (tottime = own time inside that module's functions)
        families = {"pair_a_prep.chess_search": 0.0, "pair_a_prep.pcfr": 0.0, "pair_a_prep._pcfr_native": 0.0,
                    "pair_a_prep.one_sided": 0.0,
                    "pair_a_prep.chess_projection": 0.0, "pair_a_prep.chess_gadgets": 0.0, "pair_a_prep.rules": 0.0,
                    "pairb.belief_evaluator": 0.0, "fow_shared.features": 0.0, "torch": 0.0, "chess/": 0.0,
                    "pairb.observe": 0.0, "fow_shared.values": 0.0}
        for (filename, _line, _func), (_cc, _nc, tt, _ct, _callers) in stats.stats.items():
            for key in families:
                probe = key.replace(".", "/")
                if probe in filename.replace("\\", "/"):
                    families[key] += tt
                    break
        print(f"own time by module (s, of {total:.2f} profiled):")
        for key, value in sorted(families.items(), key=lambda kv: -kv[1]):
            if value > 0.01:
                print(f"  {key:28s} {value:6.2f}  ({100 * value / total:4.1f} %)")
        buf = io.StringIO()
        pstats.Stats(profiler, stream=buf).sort_stats("cumulative").print_stats(12)
        lines = [l for l in buf.getvalue().splitlines() if l.strip() and not l.startswith("Ordered") and "function calls" not in l]
        print("top cumulative:")
        for l in lines[:16]:
            print("  " + l.strip()[:150])
    leaf.close()


if __name__ == "__main__":
    main()
