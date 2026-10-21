"""Bot-against-bot fog-of-war games: two one-ply belief bots, each on its own particle tracker.

    .venv/bin/python scripts/play_matches.py --a network1 --b stockfish-d1 --games 200 --out runs/matches/net1-vs-d1

Each side is a scorer by its Fog Lab id (material, stockfish-d1, stockfish-d11, network1, belief),
or `linear` (the linear correction, checkpoints/linear-v1), inside pairb.bot.OnePlyBot, or `random`,
a seeded uniform random legal move. Both sides are honest: fow_shared.evaluation.play_game gives each
one only its observations and its own tracker's belief. --rules picks the rules as Fog Lab does:
`auto` is Teal's adapter when this checkout has it, else Pair B's stand-in; pin `teal` or `standin`
so that every machine of a batch plays by the same rules.

Openings: opening i is k plies, k from 2 to 8, of random legal moves drawn from
random.Random(seed * 1000 + i), never one that ends the game. Each opening is played twice, a as
White and then a as Black, and its plies go through the runner (each bot plays its colour's opening
moves first), so both trackers see every ply from the start position.

Value lost by not knowing, for each move a bot chooses: the best value on the true board minus the
true-board value of the move it played, both from a second copy of that bot's scorer, so the
runner's look at the true board never reaches the bot (a Stockfish scorer keeps its hash between
calls). It is 0 when the bot played what it would have played had it seen the board; `random` has
no scorer and no value lost.

Every scorer and second copy starts each game with a clean Stockfish (ucinewgame), so a game does
not depend on the games before it; within a game the hash is kept, as inside a search.

Writes games.jsonl, one game per line as each one ends, and summary.json into --out, which must not
exist yet: games, wins, draws and losses per side, a's score (wins plus half the draws) over the
openings whose two games both finished, with a 95% interval that resamples those complete colour
pairs 2,000 times with seed 0 (none with fewer than two pairs), the count of incomplete pairs,
mean value lost per side, plies, time per move, the device each network ran on, and the settings,
checkpoints and commit, with a record of uncommitted changes, the SHA-256 of every source file that
plays (fow_shared, pairb, this script, Pair A's rules), of the Stockfish binary, and the library
versions. A game
that raises is recorded with its error and left out of the score, and the run goes on. A value-lost
measurement that fails after a game finished keeps the game and its result; the move records the
measurement's error under diagnostic_error. The summary is written even when the run is
interrupted, and the exit status is 1 if any game or measurement failed.
"""
import argparse
import contextlib
import datetime
import importlib.metadata
import json
import random
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from fow_shared.contracts import Decision
from fow_shared.evaluation import MatchConfig, play_game
from fow_shared.values import standard_fen
from pairb.bot import OnePlyBot
from pairb.lab.paths import ensure_repo_on_path
from pairb.lab.scorers import CHECKPOINTS, SCORER_IDS, ScorerOptions, open_scorer
from pairb.provenance import git_commit, git_status, portable, runtime, sha256_of
from pairb.rules import GameReferee, pick_rules
from pairb.stockfish import StockfishEvaluator
from pairb.tracker import ParticleTracker

ROOT = Path(__file__).resolve().parents[1]
LINEAR = "linear-v1/best.npz"  # the linear correction, inside the checkpoints folder
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
        # standard_fen keeps the en passant square of a capture only fog rules allow; python-chess's
        # default FEN drops it, and the second scorer would then miss a move the referee allows.
        self.before.append(standard_fen(self._referee.true_board()))
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


def new_game(scorer) -> None:
    """Clear the Stockfish a scorer holds (itself, or the one under a network or the linear correction)."""
    for engine in (scorer, getattr(scorer, "stockfish", None)):
        if isinstance(engine, StockfishEvaluator):
            engine.new_game()


def play_one(rules, number: int, moves: list[str], colours: dict, scorers: dict, judges: dict, args) -> dict:
    """One game, colours {"white": side, "black": side}; the record of the game."""
    started = time.time()
    for scorer in (*scorers.values(), *judges.values()):
        if scorer is not None:
            new_game(scorer)
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
    except Exception as exc:  # TrackerLost, a bot or scorer that raises: recorded, not scored
        return {**game, "error": f"{type(exc).__name__}: {exc}", "plies_played": len(referee.before),
                "seconds": round(time.time() - started, 1)}
    record, failed = [], 0
    for ply in result.plies:
        side = colours[ply.player]
        entry = {"ply": ply.ply, "player": ply.player, "side": side, "move": ply.move,
                 "opening": ply.ply < len(moves), "elapsed_ms": round(ply.elapsed_ms, 3),
                 "guesses": int(ply.search_nodes), "tracker": trackers[ply.player].log[ply.ply],
                 "best": None, "played": None, "value_lost": None}
        if not entry["opening"] and judges[side] is not None:
            try:
                entry.update(value_lost(judges[side], referee.before[ply.ply], ply.move))
            except Exception as exc:  # the measurement failed, not the game: keep the game
                entry["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
                failed += 1
        record.append(entry)
    ended = referee.result()
    winner_side = colours.get(result.winner)
    return {**game, "winner": result.winner, "winner_side": winner_side, "reason": ended[1] if ended else None,
            "plies": len(result.plies), "stopped_at_ply_limit": result.stopped_at_ply_limit,
            "diagnostic_errors": failed, "moves": record,
            "trackers": {c: trackers[c].log for c in ("white", "black")}, "seconds": round(time.time() - started, 1)}


def paired_score(games: list[dict]) -> dict:
    """a's score over the complete colour pairs (openings whose two games, one with each colour, both
    finished), with a 95% interval that resamples those pairs; no interval with fewer than two pairs."""
    by_opening = {}
    for g in games:
        by_opening.setdefault(g["opening"]["id"], []).append(g)
    pairs = []
    for pair in by_opening.values():
        done = [g for g in pair if "error" not in g]
        if len(pair) == len(done) == 2 and {g["colours"]["white"] for g in done} == {"a", "b"}:
            pairs.append(sum(1.0 if g["winner_side"] == "a" else 0.5 if g["winner"] == "draw" else 0.0
                             for g in done) / 2)
    points = np.array(pairs, dtype=np.float64)
    interval = None
    if len(points) >= 2:
        boots = points[np.random.default_rng(BOOT_SEED).integers(0, len(points), size=(N_BOOT, len(points)))].mean(axis=1)
        interval = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]
    return {"mean": float(points.mean()) if len(points) else None, "ci95": interval,
            "complete_pairs": len(pairs), "incomplete_pairs": len(by_opening) - len(pairs),
            "resamples": N_BOOT, "seed": BOOT_SEED, "unit": "complete colour pairs (both games of an opening)"}


def open_side(sid: str, opts: ScorerOptions):
    """A new scorer for a side: Fog Lab's open_scorer for its five, and the linear correction, which
    Fog Lab does not offer, opened the same way (no new game before each call, as inside a search)."""
    if sid != "linear":
        return open_scorer(sid, opts)
    from pairb.linear_evaluator import LinearEvaluator
    return LinearEvaluator.from_checkpoint(opts.checkpoints / LINEAR, stockfish_path=opts.stockfish,
                                           new_game_each_call=False)


def run_record(stockfish: str, repo: Path) -> dict:
    """What a run's results can be traced to, read once before the first game: the commit, uncommitted
    changes, the SHA-256 of each source file that plays (from where pairb, fow_shared and this script
    were imported, and Pair A's rules under `repo`, the root put on the path for them), of the Stockfish
    binary, and the library versions (torch's without importing it)."""
    import fow_shared
    import pairb
    files = sorted({*Path(fow_shared.__file__).resolve().parent.glob("*.py"),
                    *Path(pairb.__file__).resolve().parent.glob("**/*.py"), Path(__file__).resolve(),
                    *repo.resolve().glob("pair_a_prep/*.py")})
    root = repo.resolve()

    def name(path):
        return path.relative_to(root).as_posix() if path.is_relative_to(root) else portable(str(path))
    engine = shutil.which(stockfish)
    try:
        torch_version = importlib.metadata.version("torch")
    except importlib.metadata.PackageNotFoundError:
        torch_version = None
    now = runtime()
    versions = {k: v for k, v in now.items() if k in ("python", "platform", "numpy", "python_chess")}
    return {"git_commit": git_commit(), "runtime": now, "git_status": git_status(),
            "source_sha256": {name(p): sha256_of(p) for p in files},
            "stockfish": {"path": portable(engine) if engine else None, "sha256": sha256_of(engine) if engine else None},
            "packages": {**versions, "torch": torch_version}}


def summarise(games: list[dict], args, names: dict, checkpoints: dict, seconds: float, rules,
              devices: dict | None = None, record: dict | None = None) -> dict:
    played = [g for g in games if "error" not in g]
    sides = {}
    for side in ("a", "b"):
        mine = [m for g in played for m in g["moves"] if m["side"] == side and not m["opening"]]
        lost = [m["value_lost"] for m in mine if m["value_lost"] is not None]
        ms = np.array([m["elapsed_ms"] for m in mine], dtype=np.float64)
        sides[side] = {
            "scorer": getattr(args, side), "name": names[side], "checkpoint_sha256": checkpoints[side],
            "device": (devices or {}).get(side),
            "wins": sum(g["winner_side"] == side for g in played), "draws": sum(g["winner"] == "draw" for g in played),
            "losses": sum(g["winner_side"] not in (side, None) for g in played),
            "as_white": sum(g["colours"]["white"] == side for g in played), "moves": len(mine),
            "value_lost_mean": float(np.mean(lost)) if lost else None,
            "ms_per_move_mean": float(ms.mean()) if len(ms) else None,
            "ms_per_move_p95": float(np.percentile(ms, 95)) if len(ms) else None,
        }
    return {
        "a": args.a, "b": args.b, "games": len(played), "openings": len({g["opening"]["id"] for g in played}),
        "errors": len(games) - len(played),
        "diagnostic_errors": sum(g.get("diagnostic_errors", 0) for g in played),
        "score_a": paired_score(games),
        "sides": sides,
        "plies_mean": float(np.mean([g["plies"] for g in played])) if played else None,
        "stopped_at_ply_limit": sum(g["stopped_at_ply_limit"] for g in played),
        "seconds_per_game_mean": float(np.mean([g["seconds"] for g in played])) if played else None,
        "rules": rules.name,
        "settings": {k: getattr(args, k) for k in ("games", "max_plies", "seed", "particles", "guesses", "device",
                                                   "rules")} | {"stockfish": portable(args.stockfish),
                                                                "time_budget_ms": TIME_BUDGET_MS},
        "openings_rule": "opening i: k = randint(2, 8), then k random legal plies that do not end the game, both "
                         "from random.Random(seed * 1000 + i); game n has match seed seed * 1000 + n",
        "git_commit": (record or {}).get("git_commit"), "runtime": (record or {}).get("runtime"), "record": record,
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "seconds": round(seconds, 1),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    choices = (*SCORER_IDS, "linear", "random")
    ap.add_argument("--a", required=True, choices=choices, help="the first-named side, whose score is reported")
    ap.add_argument("--b", required=True, choices=choices)
    ap.add_argument("--games", type=int, required=True, help="an even number: each opening is played twice")
    ap.add_argument("--max-plies", type=int, default=200, help="a game still going after this many plies is a draw")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--particles", type=int, default=256, help="each tracker's particle cap")
    ap.add_argument("--guesses", type=int, default=8, help="the most guesses a belief gives a bot")
    ap.add_argument("--device", default="auto", help="for the networks: auto, mps, cuda or cpu")
    ap.add_argument("--stockfish", default="stockfish")
    ap.add_argument("--rules", choices=("auto", "teal", "standin"), default="auto",
                    help="auto is Teal's adapter when this checkout has it, else Pair B's stand-in; pin one for a batch")
    ap.add_argument("--checkpoints", default=str(ROOT / "checkpoints"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.games < 2 or args.games % 2:
        ap.error("--games must be even (each opening is played with both colours) and at least 2")
    out = Path(args.out)
    if out.exists():
        sys.exit(f"{out} exists; choose a new folder")

    repo = ensure_repo_on_path()  # before the rules are chosen: Teal's adapter is imported from the repo root
    try:
        rules = pick_rules(args.rules)
    except ValueError as error:
        ap.error(str(error))
    print(f"rules: {rules.name}", flush=True)
    opts = ScorerOptions(Path(args.checkpoints), args.stockfish, None if args.device == "auto" else args.device)
    started = time.time()
    with contextlib.ExitStack() as stack:
        scorers, judges, names, checkpoints, devices = {}, {}, {}, {}, {}
        for side in ("a", "b"):
            sid = getattr(args, side)
            if sid == "random":
                scorers[side] = judges[side] = None
                names[side], checkpoints[side], devices[side] = RandomAgent.name, None, None
                continue
            scorers[side] = stack.enter_context(open_side(sid, opts))
            judges[side] = stack.enter_context(open_side(sid, opts))
            names[side] = scorers[side].name
            checkpoint = LINEAR if sid == "linear" else CHECKPOINTS.get(sid)
            checkpoints[side] = sha256_of(opts.checkpoints / checkpoint) if checkpoint else None
            devices[side] = str(scorers[side].device) if hasattr(scorers[side], "device") else None
        record = run_record(args.stockfish, repo)
        out.mkdir(parents=True)
        games = []
        try:
            with open(out / "games.jsonl", "x") as log:
                for number in range(args.games):
                    moves = opening(rules, args.seed, number // 2)
                    colours = {"white": "a", "black": "b"} if number % 2 == 0 else {"white": "b", "black": "a"}
                    game = play_one(rules, number, moves, colours, scorers, judges, args)
                    games.append(game)
                    log.write(json.dumps(game) + "\n")
                    log.flush()
                    outcome = game.get("error") or f"{game['winner']} after {game['plies']} plies"
                    side = "white" if colours["white"] == "a" else "black"
                    print(f"game {number + 1}/{args.games}: {args.a} as {side}, {outcome}, {game['seconds']} s", flush=True)
        finally:  # the games finished so far are summarised even if the run is interrupted
            summary = summarise(games, args, names, checkpoints, time.time() - started, rules, devices, record)
            (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    s = summary["score_a"]
    if s["mean"] is None:
        print(f"{args.a} against {args.b}: no opening finished with both colours -> {out}")
    else:
        spread = (f"95% CI {s['ci95'][0]:.3f} to {s['ci95'][1]:.3f}" if s["ci95"]
                  else "no interval: fewer than two complete pairs")
        print(f"{args.a} against {args.b}: score {s['mean']:.3f} ({spread}) over {s['complete_pairs']} complete "
              f"colour pairs, {s['incomplete_pairs']} incomplete -> {out}")
    if summary["errors"]:
        print(f"{summary['errors']} game(s) failed; their errors are in games.jsonl", file=sys.stderr)
    if summary["diagnostic_errors"]:
        print(f"{summary['diagnostic_errors']} value-lost measurement(s) failed; see diagnostic_error in games.jsonl",
              file=sys.stderr)
    if summary["errors"] or summary["diagnostic_errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
