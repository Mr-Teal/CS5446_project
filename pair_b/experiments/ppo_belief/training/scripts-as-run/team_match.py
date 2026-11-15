"""The PPO network against one of the team's players, in the team's own match loop.

    python team_match.py --checkpoint runs/pilot-30min/final.pt --opponent stockfish-d1 --games 200 \
        --out runs/matches/pilot-vs-stockfish-d1

Everything except the PPO player is the team's code, unchanged (team main 355e5e3, copied into
team_main_355e5e3/ and fow_shared/): the stand-in rules and referee, fow_shared's play_game loop,
the opponent (the one-ply belief bot on a particle tracker of 256 particles and 8 guesses, or the
random player), the openings (opening i is 2 to 8 random plies from random.Random(seed * 1000 + i),
played twice with the colours swapped) and the paired score with its intervals. This is the
protocol of the team's 200-game batch of 27 October, with two differences: the code is the newer
main, and the games run in several processes (every game still starts with a clean Stockfish and
its own seed, so a game does not depend on which process plays it).

The PPO player (fowppo.agent.PpoAgent) reads only its own observations and its own moves. From them
it keeps its own belief sampler, the one it was trained with (kernel/belief_sampler.cpp, same cap); the
match loop's tracker for its colour is a placeholder that it never reads.
Side "a", whose score is reported, is the PPO player.
"""
import argparse
import hashlib
import json
import multiprocessing as mp
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEAM = HERE / "team_main_355e5e3"
for folder in (TEAM, HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

OPPONENTS = ("random", "material", "stockfish-d1", "stockfish-d11")
_worker = {}


def _start(settings: dict) -> None:
    """Once per process: the network, the rules and the opponent's scorer (its own Stockfish)."""
    import torch
    torch.set_num_threads(1)
    import play_matches as team
    from pairb.lab.scorers import ScorerOptions
    from pairb.rules import pick_rules
    from fowppo.agent import PpoAgent

    scorer = None
    if settings["opponent"] != "random":
        scorer = team.open_side(settings["opponent"], ScorerOptions(HERE, settings["stockfish"], None))
    _worker.update(settings=settings, team=team, rules=pick_rules("standin"), scorer=scorer,
                   ppo=PpoAgent.from_checkpoint(settings["checkpoint"], sample=settings["mode"] == "sample"))


def _play(number: int) -> dict:
    from fow_shared.evaluation import MatchConfig, play_game
    from pairb.bot import OnePlyBot
    from pairb.rules import GameReferee
    from pairb.tracker import ParticleTracker
    from fowppo.agent import NoBelief

    settings, team, rules, scorer = (_worker[k] for k in ("settings", "team", "rules", "scorer"))
    moves = team.opening(rules, settings["seed"], number // 2, tuple(settings["opening_plies"]))
    colours = {"white": "a", "black": "b"} if number % 2 == 0 else {"white": "b", "black": "a"}
    seed = settings["seed"] * 1000 + number
    if scorer is not None:
        team.new_game(scorer)  # a clean engine for every game, as in the team's runner
    agents, trackers = {}, {}
    for colour, side in colours.items():
        if side == "a":
            player, trackers[colour] = _worker["ppo"], NoBelief()
        elif scorer is None:
            player, trackers[colour] = team.RandomAgent(), NoBelief()
        else:
            player = OnePlyBot(scorer)
            trackers[colour] = ParticleTracker(rules, n_particles=settings["particles"], n_hypotheses=settings["guesses"])
        agents[colour] = team.OpeningThenAgent(player, moves)
    config = MatchConfig(time_budget_ms=60_000, max_plies=settings["max_plies"], seed=seed, rules_id=rules.name,
                         engine_id=f"ppo-vs-{settings['opponent']}", leaf_depth=0)
    referee = GameReferee(rules)
    game = {"game": number, "opening": {"id": number // 2, "moves": moves}, "seed": seed, "colours": colours}
    started = time.time()
    try:
        result = play_game(referee, agents, trackers, config)
    except Exception as exc:  # recorded and left out of the score, as in the team's runner
        return {**game, "error": f"{type(exc).__name__}: {exc}", "seconds": round(time.time() - started, 1)}
    ended = referee.result()
    ppo_ms = [p.elapsed_ms for p in result.plies if colours[p.player] == "a" and p.ply >= len(moves)]
    return {**game, "winner": result.winner, "winner_side": colours.get(result.winner),
            "reason": "ply_limit" if result.stopped_at_ply_limit else (ended[1] if ended else None),
            "plies": len(result.plies), "stopped_at_ply_limit": result.stopped_at_ply_limit,
            "moves": [p.move for p in result.plies],
            "ppo_ms_per_move": round(sum(ppo_ms) / len(ppo_ms), 2) if ppo_ms else None,
            "seconds": round(time.time() - started, 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--opponent", required=True, choices=OPPONENTS)
    parser.add_argument("--games", type=int, required=True, help="an even number: each opening is played twice")
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=("sample", "best"), default="sample",
                        help="sample: draw each move from the policy, as in training; best: the most likely move")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-plies", type=int, default=200)
    parser.add_argument("--particles", type=int, default=256)
    parser.add_argument("--guesses", type=int, default=8)
    parser.add_argument("--opening-plies", type=int, nargs=2, default=(2, 8))
    parser.add_argument("--stockfish", default="stockfish")
    args = parser.parse_args()
    if args.games < 2 or args.games % 2:
        parser.error("--games must be even and at least 2")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    checkpoint = Path(args.checkpoint).resolve()
    settings = {**vars(args), "checkpoint": str(checkpoint), "opening_plies": list(args.opening_plies)}

    import play_matches as team  # the team's paired score and intervals
    started = time.time()
    games = []
    with mp.get_context("spawn").Pool(args.jobs, initializer=_start, initargs=(settings,)) as pool, \
            open(out / "games.jsonl", "x") as log:
        for game in pool.imap_unordered(_play, range(args.games)):
            games.append(game)
            log.write(json.dumps(game) + "\n")
            log.flush()
            outcome = game.get("error") or f"{game['winner']} after {game['plies']} plies ({game['reason']})"
            colour = "white" if game["colours"]["white"] == "a" else "black"
            print(f"game {game['game'] + 1}/{args.games}: ppo as {colour}, {outcome}, {game['seconds']} s", flush=True)
        # Leaving the block stops the worker processes; each engine quits when its pipe closes.
    games.sort(key=lambda g: g["game"])
    played = [g for g in games if "error" not in g]
    score = team.paired_score(games)
    summary = {
        "a": "ppo", "b": args.opponent, "mode": args.mode, "games": len(played), "errors": len(games) - len(played),
        "ppo_wins": sum(g["winner_side"] == "a" for g in played), "draws": sum(g["winner"] == "draw" for g in played),
        "ppo_losses": sum(g["winner_side"] == "b" for g in played),
        "score_a": score, "end_reasons": dict(Counter(g["reason"] for g in played)),
        "plies_mean": sum(g["plies"] for g in played) / max(len(played), 1),
        "seconds_per_game_mean": sum(g["seconds"] for g in played) / max(len(played), 1),
        "checkpoint": str(checkpoint.relative_to(HERE)) if checkpoint.is_relative_to(HERE) else checkpoint.name,
        "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "settings": {k: settings[k] for k in ("games", "seed", "max_plies", "particles", "guesses", "opening_plies", "jobs")},
        "rules": "pairb-standin", "team_code": "main 355e5e3 (copied, unchanged)",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": round(time.time() - started, 1),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if score["mean"] is None:
        print(f"ppo against {args.opponent}: no opening finished with both colours -> {out}")
    else:
        low, high = score["wilson95"]
        print(f"ppo ({args.mode}) against {args.opponent}: score {score['mean']:.3f} (Wilson 95% {low:.3f} to {high:.3f}), "
              f"{summary['ppo_wins']} wins, {summary['draws']} draws, {summary['ppo_losses']} losses, "
              f"{summary['errors']} failed, {summary['seconds']:.0f} s -> {out}")


if __name__ == "__main__":
    main()
