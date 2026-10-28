"""Bot-against-bot fog-of-war games: two one-ply belief bots, each on its own particle tracker.

    .venv/bin/python scripts/play_matches.py --a network1 --b stockfish-d1 --games 200 --rules standin --out runs/matches/net1-vs-d1

Each side is a scorer by its Fog Lab id (material, stockfish-d1, stockfish-d11, network1, belief),
or `linear` (the linear correction, checkpoints/linear-v1), inside pairb.bot.OnePlyBot, or `random`,
a seeded uniform random legal move. Both sides are honest: fow_shared.evaluation.play_game gives each
one only its observations and its own tracker's belief. --rules picks the rules as Fog Lab does:
`auto` is Teal's adapter when this checkout has it, else Pair B's stand-in; pin `teal` or `standin`
so that every machine of a batch plays by the same rules.

Openings: opening i is k plies, k from 2 to 8 (--opening-plies; 0 0 is the standard start), of random
legal moves drawn from random.Random(seed * 1000 + i), never one that ends the game. Each opening is
played twice, a as White and then a as Black, and its plies go through the runner (each bot plays its
colour's opening moves first), so both trackers see every ply from the start position.

A run of more than two games must pin --rules (standin or teal): what auto picks depends on whether
the checkout has Teal's adapter, and one table must be played by one set of rules. Each ply records over_budget against
--time-budget-ms (60 s by default); the one-ply bots do not read the budget, so the flag measures
overruns and never cuts a move short.

A side with no fog-legal move: the draw decided on #17 arrives with Teal's #28, and --rules does not
pin it; only the commit does. So each run tries BLOCKED_FEN at the start and records what its rules
do there as no_move_rule: "draw", or "unresolved" until the draw rule lands; see no_move_rule. While it
is unresolved, such a game fails with "ValueError: the observation has no legal move to choose from"
(the same text for a bot side and a random side) and is counted in errors_no_legal_move.

A Stockfish that dies (a crash), or stops answering (no reply within StockfishEvaluator's
call_timeout_s, 60 s by default), is reopened, scorer and second copy, after the game or measurement
that found it dead, and the game records which side was reopened; a run stops after 5 failed games
in a row.

Value lost by not knowing, for each move a bot chooses: the best value on the true board minus the
true-board value of the move it played, both from a second copy of that bot's scorer, so the
runner's look at the true board never reaches the bot (a Stockfish scorer keeps its hash between
calls). It is 0 when the bot played what it would have played had it seen the board; `random` has
no scorer and no value lost.

Every scorer and second copy starts each game with a clean Stockfish (ucinewgame), so a game does
not depend on the games before it; within a game the hash is kept, as inside a search.

Writes games.jsonl, one game per line as each one ends, and summary.json into --out, which must not
exist yet: games, wins, draws and losses per side, a's score (wins plus half the draws) over the
openings whose two games both finished, with Wilson's 95% interval on that pair-level proportion
and, when there are at least 20 complete pairs that do not all score the same, a 95% interval that
resamples those pairs 2,000 times with seed 0 (fewer pairs are too few to resample meaningfully and
identical pairs collapse to a point, so the bootstrap is then withheld and `degenerate` is true), the
count of incomplete pairs, how the finished games ended (end_reasons: king_capture, fifty_move,
threefold_repetition, no_legal_moves, ply_limit, and any other reason by its own name), mean value
lost per side, plies, time per move (mean, median and 95th percentile), over-budget plies and the
tracker's capped and rebuilt updates per side, the device each network ran on, the rules and
no_move_rule, the command (home folder as ~), and the settings (engine policy and call_timeout_s
included), checkpoints and commit, with a record of uncommitted changes, the SHA-256 of every source
file that plays (fow_shared, pairb, this script, pair_a_prep), of the Stockfish binary, and the
library versions. A game that raises is recorded with its error and left out of the score, and the
run goes on; errors counts these games and errors_no_legal_move the ones that failed for want of a
move. A value-lost measurement that fails after a game finished keeps the game and its result; the
move records the measurement's error under diagnostic_error. The summary is written even when the
run is interrupted or the runner itself fails: completed is true only when every planned game has a
record and nothing stopped the run early, and stopped_early says why it stopped ("interrupted" after
Ctrl-C, which still ends the process with a non-zero status). The exit status is 1 if any game or
measurement failed.
"""
import argparse
import contextlib
import datetime
import importlib.metadata
import inspect
import json
import math
import random
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from fow_shared.contracts import Decision
from fow_shared.evaluation import MatchConfig, play_game
from fow_shared.values import standard_fen
from pairb.bot import NO_LEGAL_MOVE, OnePlyBot
from pairb.lab.paths import ensure_repo_on_path
from pairb.lab.scorers import CHECKPOINTS, SCORER_IDS, ScorerOptions, open_scorer
from pairb.provenance import git_commit, git_status, portable, runtime, sha256_of
from pairb.rules import GameReferee, pick_rules
from pairb.stockfish import StockfishEvaluator
from pairb.tracker import ParticleTracker

ROOT = Path(__file__).resolve().parents[1]
LINEAR = "linear-v1/best.npz"  # the linear correction, inside the checkpoints folder
TIME_BUDGET_MS = 60_000  # the default --time-budget-ms: each ply records over_budget against it; the one-ply
# bots do not read the budget, so the flag only measures overruns, it never cuts a move short
CALL_TIMEOUT_S = inspect.signature(StockfishEvaluator).parameters["call_timeout_s"].default  # per Stockfish call
ENGINE_POLICY = {"threads": 1, "hash_mb": 16, "new_game": "before every game",
                 "within_game": "hash kept between calls",
                 "call_timeout_s": CALL_TIMEOUT_S}  # StockfishEvaluator's settings and this runner's use
BLOCKED_FEN = "7k/8/8/8/1p6/pPp5/PRP5/KB6 w - - 0 1"  # White to move, and no fog-legal move
END_REASONS = ("king_capture", "fifty_move", "threefold_repetition", "no_legal_moves", "ply_limit")  # always listed
N_BOOT, BOOT_SEED = 2000, 0
MIN_PAIRS = 20  # fewer complete colour pairs than this get no bootstrap interval, only Wilson's
MAX_CONSECUTIVE_ERRORS = 5  # a run stops after this many failed games in a row


class RandomAgent:
    """fow_shared's Agent: a uniform random legal move, seeded by reset."""

    name = "random"

    def __init__(self):
        self.rng = None

    def reset(self, player, seed):
        self.rng = random.Random(seed)

    def act(self, turn):
        moves = turn.observation.legal_moves
        if not moves:  # the bots' error, so a table counts every no-move failure the same way
            raise ValueError(NO_LEGAL_MOVE)
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


def no_move_rule(rules) -> str:
    """What `rules` do when the side to move has no fog-legal move, tried on BLOCKED_FEN: "draw" once the
    draw rule decided on #17 is in this code (it arrives with Teal's #28), "unresolved" before that, when
    such a game fails with the bots' no-legal-move error. --rules does not pin this; only the commit does."""
    try:
        ended = rules.terminal(rules.initial_state(BLOCKED_FEN))
    except Exception as exc:  # rules that refuse the position: say so, and let the run go on
        return f"unknown ({type(exc).__name__}: {exc})"
    if ended is None:
        return "unresolved"
    return "draw" if ended[0] == "draw" else f"{ended[0]} wins ({ended[1]})"


def opening(rules, seed: int, index: int, plies: tuple[int, int] = (2, 8)) -> list[str]:
    """Opening `index`: k random legal plies, k drawn from plies[0]..plies[1], none of which ends the
    game; (0, 0) is the standard start, for runs that compare with a public-start protocol."""
    rng = random.Random(seed * 1000 + index)
    state, moves = rules.initial_state(), []
    for _ in range(rng.randint(*plies)):
        options = [m for m in sorted(rules.legal_moves(state)) if rules.terminal(rules.apply_move(state, m)) is None]
        if not options:  # every move would end the game: the opening stops here
            break
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


def engines_of(scorer) -> list:
    """The Stockfish a scorer holds: itself, or the one under a network or the linear correction."""
    return [e for e in (scorer, getattr(scorer, "stockfish", None)) if isinstance(e, StockfishEvaluator)]


def new_game(scorer) -> None:
    """Clear the Stockfish a scorer holds, so the next game starts with an empty hash."""
    for engine in engines_of(scorer):
        engine.new_game()


def reopen_dead(stack, scorers: dict, judges: dict, args, opts: ScorerOptions) -> list[str]:
    """After a failed game or measurement: any side whose scorer or second copy has a dead Stockfish
    (a crash) gets both reopened, so one crash does not fail every later game. Returns the sides."""
    reopened = []
    for side in ("a", "b"):
        holders = [h for h in (scorers.get(side), judges.get(side)) if h is not None]
        if holders and not all(e.alive() for h in holders for e in engines_of(h)):
            for h in holders:
                h.close()
            scorers[side] = stack.enter_context(open_side(getattr(args, side), opts))
            judges[side] = stack.enter_context(open_side(getattr(args, side), opts))
            reopened.append(side)
    return reopened


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
    config = MatchConfig(time_budget_ms=getattr(args, "time_budget_ms", TIME_BUDGET_MS), max_plies=args.max_plies,
                         seed=seed, rules_id=rules.name, engine_id=f"{args.a}-vs-{args.b}", leaf_depth=0)
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
                 "over_budget": bool(ply.over_budget),
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


def wilson95(p: float, n: int, z: float = 1.959964) -> list[float]:
    """Wilson's 95% score interval for a proportion p seen in n trials; here the pair-level score over
    n complete pairs, treated as a proportion. An approximation: a pair's score is 0, 0.25, 0.5, 0.75 or
    1 (a draw in either game gives a quarter point), not a 0-or-1 outcome."""
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [0.0 if p <= 0 else max(0.0, centre - half), 1.0 if p >= 1 else min(1.0, centre + half)]


def paired_score(games: list[dict]) -> dict:
    """a's score over the complete colour pairs (openings whose two games, one with each colour, both
    finished), the Wilson interval on that pair-level proportion, and a 95% bootstrap interval that
    resamples the pairs, given only when there are at least MIN_PAIRS of them and they are not all
    equal: fewer pairs are too few to resample meaningfully, and identical pairs collapse the percentile
    bootstrap to a point. `degenerate` is true whenever no bootstrap interval is given; `note` says why."""
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
    mean = float(points.mean()) if len(points) else None
    interval, note = None, None
    if not len(points):
        note = "no complete colour pair"
    elif len(points) < MIN_PAIRS:
        note = f"fewer than {MIN_PAIRS} complete pairs"
    elif len(set(points.tolist())) == 1:
        note = "every pair scored the same, so the bootstrap would collapse to a point"
    else:
        boots = points[np.random.default_rng(BOOT_SEED).integers(0, len(points), size=(N_BOOT, len(points)))].mean(axis=1)
        interval = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]
    return {"mean": mean, "ci95": interval, "degenerate": interval is None, "note": note,
            "wilson95": wilson95(mean, len(points)) if mean is not None else None,
            "complete_pairs": len(pairs), "incomplete_pairs": len(by_opening) - len(pairs),
            "resamples": N_BOOT, "seed": BOOT_SEED, "min_pairs": MIN_PAIRS,
            "unit": "complete colour pairs (both games of an opening)"}


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


def engine_policy(scorers: dict, judges: dict) -> dict:
    """The engine settings the run actually used, read from the opened engines where they differ from the constant."""
    engines = [e for h in (*scorers.values(), *judges.values()) if h is not None for e in engines_of(h)]
    policy = dict(ENGINE_POLICY)
    if any(e.new_game_each_call for e in engines):
        policy["within_game"] = "hash cleared before every call"
    timeouts = sorted({e.call_timeout_s for e in engines})
    if timeouts:
        policy["call_timeout_s"] = timeouts[0] if len(timeouts) == 1 else timeouts
    return policy


def end_reasons(played: list[dict]) -> dict:
    """How the finished games ended: END_REASONS always (ply_limit for a game stopped at --max-plies),
    and any other reason the rules give, by its own name."""
    counts = dict.fromkeys(END_REASONS, 0)
    for g in played:
        reason = "ply_limit" if g["stopped_at_ply_limit"] else g.get("reason") or "unknown"
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def summarise(games: list[dict], args, names: dict, checkpoints: dict, seconds: float, rules,
              devices: dict | None = None, record: dict | None = None, stopped_early: str | None = None,
              policy: dict | None = None, no_move: str | None = None, command: list[str] | None = None) -> dict:
    played = [g for g in games if "error" not in g]
    sides = {}
    for side in ("a", "b"):
        mine = [m for g in played for m in g["moves"] if m["side"] == side and not m["opening"]]
        lost = [m["value_lost"] for m in mine if m["value_lost"] is not None]
        ms = np.array([m["elapsed_ms"] for m in mine], dtype=np.float64)
        updates = [u for g in played for colour, s in g["colours"].items() if s == side
                   for u in g.get("trackers", {}).get(colour, [])]  # this side's own tracker, every update
        sides[side] = {
            "scorer": getattr(args, side), "name": names[side], "checkpoint_sha256": checkpoints[side],
            "device": (devices or {}).get(side),
            "wins": sum(g["winner_side"] == side for g in played), "draws": sum(g["winner"] == "draw" for g in played),
            "losses": sum(g["winner_side"] not in (side, None) for g in played),
            "as_white": sum(g["colours"]["white"] == side for g in played), "moves": len(mine),
            "value_lost_mean": float(np.mean(lost)) if lost else None,
            "ms_per_move_mean": float(ms.mean()) if len(ms) else None,
            "ms_per_move_median": float(np.median(ms)) if len(ms) else None,
            "ms_per_move_p95": float(np.percentile(ms, 95)) if len(ms) else None,
            "over_budget_plies": sum(bool(m["over_budget"]) for m in mine),
            "tracker_capped": sum(bool(u["capped"]) for u in updates),
            "tracker_rebuilt": sum(bool(u["rebuilt"]) for u in updates),
        }
    return {
        "a": args.a, "b": args.b, "games": len(played), "openings": len({g["opening"]["id"] for g in played}),
        "errors": len(games) - len(played),
        "errors_no_legal_move": sum(NO_LEGAL_MOVE in g["error"] for g in games if "error" in g),
        "diagnostic_errors": sum(g.get("diagnostic_errors", 0) for g in played),
        "reopened": sum(len(g.get("reopened", [])) for g in games),
        "stopped_early": stopped_early,
        "completed": len(games) == args.games and stopped_early is None,
        "score_a": paired_score(games),
        "sides": sides,
        "plies_mean": float(np.mean([g["plies"] for g in played])) if played else None,
        "stopped_at_ply_limit": sum(g["stopped_at_ply_limit"] for g in played),
        "end_reasons": end_reasons(played),
        "seconds_per_game_mean": float(np.mean([g["seconds"] for g in played])) if played else None,
        "rules": rules.name,
        "no_move_rule": no_move,
        "command": command,
        "settings": {k: getattr(args, k) for k in ("games", "max_plies", "seed", "particles", "guesses", "device",
                                                   "rules", "time_budget_ms")}
        | {"opening_plies": list(args.opening_plies), "stockfish": portable(args.stockfish),
           "engine": policy or ENGINE_POLICY,
           "out": portable(str(Path(args.out).resolve()))},
        "openings_rule": f"opening i: k = randint({args.opening_plies[0]}, {args.opening_plies[1]}), then k random "
                         "legal plies that do not end the game, both from random.Random(seed * 1000 + i); game n has "
                         "match seed seed * 1000 + n",
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
                    help="auto is Teal's adapter when this checkout has it, else Pair B's stand-in; a run of more than "
                         "two games must pin teal or standin")
    ap.add_argument("--opening-plies", nargs=2, type=int, default=[2, 8], metavar=("MIN", "MAX"),
                    help="each opening is MIN to MAX random plies; 0 0 plays every pair from the standard start")
    ap.add_argument("--time-budget-ms", type=int, default=TIME_BUDGET_MS,
                    help="the budget each ply's over_budget flag is measured against; the bots do not read it")
    ap.add_argument("--checkpoints", default=str(ROOT / "checkpoints"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.games < 2 or args.games % 2:
        ap.error("--games must be even (each opening is played with both colours) and at least 2")
    if args.rules == "auto" and args.games > 2:
        ap.error("pin --rules standin or teal for a batch: auto is Teal's adapter only where the checkout has it, "
                 "so a batch across machines or days could mix rules")
    if not 0 <= args.opening_plies[0] <= args.opening_plies[1]:
        ap.error("--opening-plies needs 0 <= MIN <= MAX")
    if args.time_budget_ms <= 0:
        ap.error("--time-budget-ms must be positive")
    out = Path(args.out)
    if out.exists():
        sys.exit(f"{out} exists; choose a new folder")

    repo = ensure_repo_on_path()  # before the rules are chosen: Teal's adapter is imported from the repo root
    try:
        rules = pick_rules(args.rules)
    except ValueError as error:
        ap.error(str(error))
    no_move = no_move_rule(rules)
    print(f"rules: {rules.name}; no_move_rule: {no_move}", flush=True)
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
        games, failed_in_a_row, stopped_early = [], 0, None
        try:
            with open(out / "games.jsonl", "x") as log:
                for number in range(args.games):
                    moves = opening(rules, args.seed, number // 2, tuple(args.opening_plies))
                    colours = {"white": "a", "black": "b"} if number % 2 == 0 else {"white": "b", "black": "a"}
                    game = play_one(rules, number, moves, colours, scorers, judges, args)
                    if "error" in game or game.get("diagnostic_errors"):
                        try:
                            reopened = reopen_dead(stack, scorers, judges, args, opts)
                            if reopened:
                                game["reopened"] = reopened
                        except Exception as exc:  # the game is still recorded; the run cannot go on
                            game["reopen_error"] = f"{type(exc).__name__}: {exc}"
                            stopped_early = f"could not reopen a dead engine: {game['reopen_error']}"
                    games.append(game)
                    log.write(json.dumps(game) + "\n")
                    log.flush()
                    outcome = game.get("error") or f"{game['winner']} after {game['plies']} plies"
                    side = "white" if colours["white"] == "a" else "black"
                    print(f"game {number + 1}/{args.games}: {args.a} as {side}, {outcome}, {game['seconds']} s", flush=True)
                    if stopped_early:
                        print(f"stopping: {stopped_early}", file=sys.stderr)
                        break
                    failed_in_a_row = failed_in_a_row + 1 if "error" in game else 0
                    if failed_in_a_row >= MAX_CONSECUTIVE_ERRORS:
                        stopped_early = f"{failed_in_a_row} consecutive games failed"
                        print(f"stopping: {stopped_early}; see games.jsonl", file=sys.stderr)
                        break
        except KeyboardInterrupt:  # Ctrl-C: summarised below as not completed, and still raised (exit status not 0)
            stopped_early = "interrupted"
            print(f"interrupted after {len(games)} of {args.games} games; summary.json says so", file=sys.stderr)
            raise
        except Exception as exc:  # the runner itself failed (a failing game is caught in play_one)
            stopped_early = f"the run failed: {type(exc).__name__}: {exc}"
            raise
        finally:  # the games finished so far are summarised even if the run is interrupted
            summary = summarise(games, args, names, checkpoints, time.time() - started, rules, devices, record,
                                stopped_early, engine_policy(scorers, judges), no_move, portable(sys.argv))
            (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    s = summary["score_a"]
    if s["mean"] is None:
        print(f"{args.a} against {args.b}: no opening finished with both colours -> {out}")
    else:
        w = s["wilson95"]
        spread = (f"bootstrap 95% CI {s['ci95'][0]:.3f} to {s['ci95'][1]:.3f}; Wilson 95% {w[0]:.3f} to {w[1]:.3f}"
                  if s["ci95"] else f"no bootstrap interval ({s['note']}); Wilson 95% {w[0]:.3f} to {w[1]:.3f}")
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
