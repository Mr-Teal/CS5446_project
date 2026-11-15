"""The belief-input PPO network against a network of the first PPO run, in the team's match loop.

    python head_to_head.py --belief runs/belief-hourly/hour-01.pt \
        --plain ../ppo-pilot-2026-11-14/runs/long-hourly/final.pt --games 200 --out runs/head-to-head/hour-01-vs-final

The protocol is team_match.py's: the team's stand-in rules and referee, fow_shared's play_game loop,
opening i of 2 to 8 random plies from random.Random(seed * 1000 + i) played twice with the colours
swapped, a 200-ply cap, and the team's paired score. Both players draw their moves from their
policies, as in training. Each reads only its own observations: the belief-input player keeps its own
belief sampler, the first run's player its own memory of last-seen pieces. Side "a", whose score is
reported, is the belief-input player.
"""
import argparse
import hashlib
import importlib.util
import json
import multiprocessing as mp
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEAM = HERE / "team_main_355e5e3"
PLAIN = HERE.parent / "ppo-pilot-2026-11-14"
for folder in (TEAM, HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

_worker = {}


def load_plain_agent():
    """The first run's fowppo package under another name, so that both packages live in one process."""
    spec = importlib.util.spec_from_file_location("fowppo_plain", PLAIN / "fowppo" / "__init__.py",
                                                  submodule_search_locations=[str(PLAIN / "fowppo")])
    module = importlib.util.module_from_spec(spec)
    sys.modules["fowppo_plain"] = module
    spec.loader.exec_module(module)
    import fowppo_plain.agent as plain_agent
    return plain_agent


def _start(settings: dict) -> None:
    import torch
    torch.set_num_threads(1)
    import play_matches as team
    from pairb.rules import pick_rules
    from fowppo.agent import PpoAgent
    plain_agent = load_plain_agent()
    side_a = plain_agent.PpoAgent if settings["a_is_plain"] else PpoAgent
    _worker.update(settings=settings, team=team, rules=pick_rules("standin"),
                   belief=side_a.from_checkpoint(settings["belief"], sample=True),
                   plain=plain_agent.PpoAgent.from_checkpoint(settings["plain"], sample=True, name="ppo-plain"))


def _play(number: int) -> dict:
    from fow_shared.evaluation import MatchConfig, play_game
    from pairb.rules import GameReferee
    from fowppo.agent import NoBelief

    settings, team, rules = (_worker[k] for k in ("settings", "team", "rules"))
    moves = team.opening(rules, settings["seed"], number // 2, tuple(settings["opening_plies"]))
    colours = {"white": "a", "black": "b"} if number % 2 == 0 else {"white": "b", "black": "a"}
    seed = settings["seed"] * 1000 + number
    agents = {colour: team.OpeningThenAgent(_worker["belief" if side == "a" else "plain"], moves)
              for colour, side in colours.items()}
    trackers = {colour: NoBelief() for colour in colours}  # placeholders: neither player reads the loop's tracker
    config = MatchConfig(time_budget_ms=60_000, max_plies=settings["max_plies"], seed=seed, rules_id=rules.name,
                         engine_id="ppo-belief-vs-ppo-plain", leaf_depth=0)
    referee = GameReferee(rules)
    game = {"game": number, "opening": {"id": number // 2, "moves": moves}, "seed": seed, "colours": colours}
    started = time.time()
    try:
        result = play_game(referee, agents, trackers, config)
    except Exception as exc:  # recorded and left out of the score, as in the team's runner
        return {**game, "error": f"{type(exc).__name__}: {exc}", "seconds": round(time.time() - started, 1)}
    ended = referee.result()
    blank = [p.diagnostics.get("belief_blank", 0.0) for p in result.plies if colours[p.player] == "a" and p.ply >= len(moves)]
    repairs = [p.diagnostics.get("belief_repairs", 0.0) for p in result.plies if colours[p.player] == "a" and p.ply >= len(moves)]
    return {**game, "winner": result.winner, "winner_side": colours.get(result.winner),
            "reason": "ply_limit" if result.stopped_at_ply_limit else (ended[1] if ended else None),
            "plies": len(result.plies), "stopped_at_ply_limit": result.stopped_at_ply_limit,
            "moves": [p.move for p in result.plies],
            "belief_blank_turns": sum(blank), "belief_turns": len(blank), "belief_repairs": max(repairs, default=0.0),
            "seconds": round(time.time() - started, 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--belief", required=True, help="a network of this folder's run")
    parser.add_argument("--plain", required=True, help="a network of the first run")
    parser.add_argument("--a-is-plain", action="store_true",
                        help="a reference match: --belief names a network of the first run too (side a has no belief input)")
    parser.add_argument("--games", type=int, required=True, help="an even number: each opening is played twice")
    parser.add_argument("--out", required=True)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-plies", type=int, default=200)
    parser.add_argument("--opening-plies", type=int, nargs=2, default=(2, 8))
    args = parser.parse_args()
    if args.games < 2 or args.games % 2:
        parser.error("--games must be even and at least 2")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    files = {name: Path(getattr(args, name)).resolve() for name in ("belief", "plain")}
    settings = {**vars(args), "belief": str(files["belief"]), "plain": str(files["plain"]),
                "opening_plies": list(args.opening_plies)}

    import play_matches as team  # the team's paired score and intervals
    started = time.time()
    games = []
    with mp.get_context("spawn").Pool(args.jobs, initializer=_start, initargs=(settings,)) as pool, \
            open(out / "games.jsonl", "x") as log:
        for game in pool.imap_unordered(_play, range(args.games)):
            games.append(game)
            log.write(json.dumps(game) + "\n")
            log.flush()
    games.sort(key=lambda g: g["game"])
    played = [g for g in games if "error" not in g]
    score = team.paired_score(games)
    wins = sum(g["winner_side"] == "a" for g in played)
    draws = sum(g["winner"] == "draw" for g in played)
    losses = sum(g["winner_side"] == "b" for g in played)
    as_white = [g for g in played if g["colours"]["white"] == "a"]
    summary = {
        "a": "ppo of the first run (no belief input)" if args.a_is_plain else "ppo with belief input",
        "b": "ppo of the first run (no belief input)", "games": len(played),
        "errors": len(games) - len(played), "a_wins": wins, "draws": draws, "a_losses": losses, "score_a": score,
        "a_as_white": [sum(g["winner_side"] == "a" for g in as_white), sum(g["winner"] == "draw" for g in as_white),
                       sum(g["winner_side"] == "b" for g in as_white)],
        "end_reasons": dict(Counter(g["reason"] for g in played)),
        "plies_mean": sum(g["plies"] for g in played) / max(len(played), 1),
        "belief_blank_turn_share": sum(g["belief_blank_turns"] for g in played) / max(sum(g["belief_turns"] for g in played), 1),
        "belief_repairs_per_game": sum(g["belief_repairs"] for g in played) / max(len(played), 1),
        "checkpoints": {name: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                        for name, path in files.items()},
        "settings": {k: settings[k] for k in ("games", "seed", "max_plies", "opening_plies", "jobs")},
        "rules": "pairb-standin", "team_code": "main 355e5e3 (copied, unchanged)",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": round(time.time() - started, 1),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    low, high = score["wilson95"] if score["mean"] is not None else (None, None)
    print(f"{summary['a']} against the first run's network: score {score['mean']}, Wilson 95% {low} to {high}, "
          f"{wins} wins, {draws} draws, {losses} losses, {summary['errors']} failed, {summary['seconds']:.0f} s -> {out}")


if __name__ == "__main__":
    main()
