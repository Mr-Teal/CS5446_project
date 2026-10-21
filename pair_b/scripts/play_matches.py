"""Bot-against-bot fog-of-war games: two one-ply belief bots, each on its own particle tracker.

    .venv/bin/python scripts/play_matches.py --a network1 --b stockfish-d1 --games 200 --out runs/matches/net1-vs-d1

Each side is a scorer by its Fog Lab id (material, stockfish-d1, stockfish-d11, network1, belief)
inside pairb.bot.OnePlyBot, or `random`, a seeded uniform random legal move. Both sides are honest:
fow_shared.evaluation.play_game gives each one only its observations and its own tracker's belief.

Openings: opening i is k plies, k from 2 to 8, of random legal moves drawn from
random.Random(seed * 1000 + i), never one that ends the game. Each opening is played twice, a as
White and then a as Black, and its plies go through the runner (each bot plays its colour's opening
moves first), so both trackers see every ply from the start position.

Value lost by not knowing, for each move a bot chooses: the best value on the true board minus the
true-board value of the move it played, both from a second copy of that bot's scorer, so the
runner's look at the true board never reaches the bot (a Stockfish scorer keeps its hash between
calls). It is 0 when the bot played what it would have played had it seen the board; `random` has
no scorer and no value lost.

Writes games.jsonl, one game per line as each one ends, and summary.json into --out, which must not
exist yet: games, wins, draws and losses per side, a's score (wins plus half the draws, over the
games) with a 95% interval that resamples openings, both colours together, 2,000 times with seed 0,
mean value lost per side, plies, time per move, and the settings, checkpoints and commit.
"""
import argparse
import contextlib
import datetime
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

from fow_shared.contracts import Decision
from fow_shared.evaluation import MatchConfig, play_game
from pairb.bot import OnePlyBot
from pairb.lab.scorers import CHECKPOINTS, SCORER_IDS, ScorerOptions, open_scorer
from pairb.provenance import git_commit, runtime, sha256_of
from pairb.rules import GameReferee, pick_rules
from pairb.tracker import ParticleTracker, TrackerLost

ROOT = Path(__file__).resolve().parents[1]
TIME_BUDGET_MS = 60_000  # recorded with each ply as over_budget; the one-ply bots do not use it
N_BOOT, BOOT_SEED = 2000, 0


class RandomAgent:
    """fow_shared's Agent: a uniform random legal move, seeded by reset."""

    name = "random"

    def __init__(self):
        self.rng = None

    def reset(self, player, seed):
        self.rng = random.Random(seed)

    def act(self, turn):
        moves = turn.observation.legal_moves
        return Decision(self.rng.choice(sorted(moves)), {move: 1 / len(moves) for move in moves})


class OpeningThenAgent:
    """fow_shared's Agent: plays its colour's moves of a fixed opening, then hands over to `agent`."""

    def __init__(self, agent, opening):
        self.agent, self.opening, self.name = agent, tuple(opening), agent.name

    def reset(self, player, seed):
        self.agent.reset(player, seed)

    def act(self, turn):
        ply = turn.observation.ply
        if ply >= len(self.opening):
            return self.agent.act(turn)
        move = self.opening[ply]
        return Decision(move, {m: float(m == move) for m in turn.observation.legal_moves}, {"opening": 1.0})


class WatchedTracker:
    """A tracker that notes its state after every update, for the record only."""

    def __init__(self, tracker):
        self.tracker, self.log = tracker, []

    def reset(self, player, seed):
        self.tracker.reset(player, seed)
        self.log = []

    def update(self, observation, own_move=None):
        belief = self.tracker.update(observation, own_move)
        t = self.tracker
        self.log.append({"ply": observation.ply, "exact": t.exact, "capped": t.capped, "rebuilt": t.rebuilt,
                         "particles": len(t.particle_fens())})
        return belief


class WatchedReferee:
    """The referee, noting the true position before every move. Only the runner reads the notes."""

    def __init__(self, referee):
        self._referee, self.before = referee, []

    def reset(self, seed):
        self._referee.reset(seed)
        self.before = []

    def apply(self, move):
        self.before.append(self._referee.true_board().fen())
        self._referee.apply(move)

    def __getattr__(self, name):  # current_player, is_terminal, winner, observe, result
        return getattr(self._referee, name)


def opening(rules, seed: int, index: int) -> list[str]:
    """Opening `index`: k in 2..8 random legal plies, none of which ends the game."""
    rng = random.Random(seed * 1000 + index)
    state, moves = rules.initial_state(), []
    for _ in range(rng.randint(2, 8)):
        options = [m for m in sorted(rules.legal_moves(state)) if rules.terminal(rules.apply_move(state, m)) is None]
        moves.append(rng.choice(options))
        state = rules.apply_move(state, moves[-1])
    return moves


def value_lost(judge, true_fen: str, move: str) -> dict:
    """The best value on the true board, the played move's value there, and their difference, all from the
    mover's view, by `judge`."""
    values = judge.evaluate_children(true_fen)
    if move not in values:
        raise ValueError(f"{move} is not a legal move on the true board {true_fen}")
    best = max(values.values())
    return {"best": best, "played": values[move], "value_lost": best - values[move]}


def play_one(rules, number: int, moves: list[str], colours: dict, scorers: dict, judges: dict, args) -> dict:
    """One game, colours {"white": side, "black": side}; the record of the game."""
    started = time.time()
    seed = args.seed * 1000 + number
    referee = WatchedReferee(GameReferee(rules))
    trackers = {c: WatchedTracker(ParticleTracker(rules, n_particles=args.particles, n_hypotheses=args.guesses))
                for c in ("white", "black")}
    agents = {c: OpeningThenAgent(RandomAgent() if scorers[s] is None else OnePlyBot(scorers[s]), moves)
              for c, s in colours.items()}
    config = MatchConfig(time_budget_ms=TIME_BUDGET_MS, max_plies=args.max_plies, seed=seed, rules_id=rules.name,
                         engine_id=f"{args.a}-vs-{args.b}", leaf_depth=0)
    game = {"game": number, "opening": {"id": number // 2, "moves": moves}, "seed": seed, "colours": colours,
            "scorers": {c: getattr(args, s) for c, s in colours.items()}}
    try:
        result = play_game(referee, agents, trackers, config)
    except TrackerLost as exc:
        return {**game, "error": str(exc), "seconds": round(time.time() - started, 1)}
    record = []
    for ply in result.plies:
        side = colours[ply.player]
        entry = {"ply": ply.ply, "player": ply.player, "side": side, "move": ply.move,
                 "opening": ply.ply < len(moves), "elapsed_ms": round(ply.elapsed_ms, 3),
                 "guesses": int(ply.search_nodes), "tracker": trackers[ply.player].log[ply.ply],
                 "best": None, "played": None, "value_lost": None}
        if not entry["opening"] and judges[side] is not None:
            entry.update(value_lost(judges[side], referee.before[ply.ply], ply.move))
        record.append(entry)
    ended = referee.result()
    winner_side = colours.get(result.winner)
    return {**game, "winner": result.winner, "winner_side": winner_side, "reason": ended[1] if ended else None,
            "plies": len(result.plies), "stopped_at_ply_limit": result.stopped_at_ply_limit, "moves": record,
            "trackers": {c: trackers[c].log for c in ("white", "black")}, "seconds": round(time.time() - started, 1)}


def score_interval(games: list[dict]) -> list[float]:
    """95% interval of a's score, resampling openings with both of their games together."""
    by_opening = {}
    for g in games:
        points = 1.0 if g["winner_side"] == "a" else 0.5 if g["winner"] == "draw" else 0.0
        total = by_opening.setdefault(g["opening"]["id"], [0.0, 0])
        total[0] += points
        total[1] += 1
    points, counts = (np.array(v, dtype=np.float64) for v in zip(*by_opening.values()))
    pick = np.random.default_rng(BOOT_SEED).integers(0, len(points), size=(N_BOOT, len(points)))
    boots = points[pick].sum(axis=1) / counts[pick].sum(axis=1)
    return [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]


def summarise(games: list[dict], args, names: dict, checkpoints: dict, seconds: float, rules) -> dict:
    played = [g for g in games if "error" not in g]
    sides = {}
    for side in ("a", "b"):
        mine = [m for g in played for m in g["moves"] if m["side"] == side and not m["opening"]]
        lost = [m["value_lost"] for m in mine if m["value_lost"] is not None]
        ms = np.array([m["elapsed_ms"] for m in mine], dtype=np.float64)
        sides[side] = {
            "scorer": getattr(args, side), "name": names[side], "checkpoint_sha256": checkpoints[side],
            "wins": sum(g["winner_side"] == side for g in played), "draws": sum(g["winner"] == "draw" for g in played),
            "losses": sum(g["winner_side"] not in (side, None) for g in played),
            "as_white": sum(g["colours"]["white"] == side for g in played), "moves": len(mine),
            "value_lost_mean": float(np.mean(lost)) if lost else None,
            "ms_per_move_mean": float(ms.mean()) if len(ms) else None,
            "ms_per_move_p95": float(np.percentile(ms, 95)) if len(ms) else None,
        }
    a = sides["a"]
    score = (a["wins"] + 0.5 * a["draws"]) / len(played) if played else None
    return {
        "a": args.a, "b": args.b, "games": len(played), "openings": len({g["opening"]["id"] for g in played}),
        "errors": len(games) - len(played),
        "score_a": {"mean": score, "ci95": score_interval(played) if played else None, "resamples": N_BOOT,
                    "seed": BOOT_SEED, "unit": "openings, both colours together"},
        "sides": sides,
        "plies_mean": float(np.mean([g["plies"] for g in played])) if played else None,
        "stopped_at_ply_limit": sum(g["stopped_at_ply_limit"] for g in played),
        "seconds_per_game_mean": float(np.mean([g["seconds"] for g in played])) if played else None,
        "rules": rules.name,
        "settings": {k: getattr(args, k) for k in ("games", "max_plies", "seed", "particles", "guesses", "device",
                                                   "stockfish")} | {"time_budget_ms": TIME_BUDGET_MS},
        "openings_rule": "opening i: k = randint(2, 8), then k random legal plies that do not end the game, both "
                         "from random.Random(seed * 1000 + i); game n has match seed seed * 1000 + n",
        "git_commit": git_commit(), "runtime": runtime(),
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "seconds": round(seconds, 1),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    choices = (*SCORER_IDS, "random")
    ap.add_argument("--a", required=True, choices=choices, help="the first-named side, whose score is reported")
    ap.add_argument("--b", required=True, choices=choices)
    ap.add_argument("--games", type=int, required=True, help="an even number: each opening is played twice")
    ap.add_argument("--max-plies", type=int, default=200, help="a game still going after this many plies is a draw")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--particles", type=int, default=256, help="each tracker's particle cap")
    ap.add_argument("--guesses", type=int, default=8, help="the most guesses a belief gives a bot")
    ap.add_argument("--device", default="auto", help="for the networks: auto, mps, cuda or cpu")
    ap.add_argument("--stockfish", default="stockfish")
    ap.add_argument("--checkpoints", default=str(ROOT / "checkpoints"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.games < 2 or args.games % 2:
        ap.error("--games must be even (each opening is played with both colours) and at least 2")
    out = Path(args.out)
    if out.exists():
        sys.exit(f"{out} exists; choose a new folder")

    rules = pick_rules("auto")
    opts = ScorerOptions(Path(args.checkpoints), args.stockfish, None if args.device == "auto" else args.device)
    started = time.time()
    with contextlib.ExitStack() as stack:
        scorers, judges, names, checkpoints = {}, {}, {}, {}
        for side in ("a", "b"):
            sid = getattr(args, side)
            if sid == "random":
                scorers[side] = judges[side] = None
                names[side], checkpoints[side] = RandomAgent.name, None
                continue
            scorers[side] = stack.enter_context(open_scorer(sid, opts))
            judges[side] = stack.enter_context(open_scorer(sid, opts))
            names[side] = scorers[side].name
            checkpoints[side] = sha256_of(opts.checkpoints / CHECKPOINTS[sid]) if sid in CHECKPOINTS else None
        out.mkdir(parents=True)
        games = []
        with open(out / "games.jsonl", "x") as log:
            for number in range(args.games):
                moves = opening(rules, args.seed, number // 2)
                colours = {"white": "a", "black": "b"} if number % 2 == 0 else {"white": "b", "black": "a"}
                game = play_one(rules, number, moves, colours, scorers, judges, args)
                games.append(game)
                log.write(json.dumps(game) + "\n")
                log.flush()
                outcome = game.get("error") or f"{game['winner']} after {game['plies']} plies"
                print(f"game {number + 1}/{args.games}: {args.a} as {'white' if colours['white'] == 'a' else 'black'}, "
                      f"{outcome}, {game['seconds']} s", flush=True)
    summary = summarise(games, args, names, checkpoints, time.time() - started, rules)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    s = summary["score_a"]
    print(f"{args.a} against {args.b}: score {s['mean']:.3f} (95% CI {s['ci95'][0]:.3f} to {s['ci95'][1]:.3f}) "
          f"over {summary['games']} games -> {out}")


if __name__ == "__main__":
    main()
