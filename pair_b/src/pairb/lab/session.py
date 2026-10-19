"""Game sessions for Fog Lab: one game between the human at the page and a bot, as the server holds it.

A Session holds what spec 4.2 lists: the referee, the only holder of the true board; the human's side, whose moves
arrive from the page as UCI text; the bot, a fow_shared Agent; and the bot's BeliefTracker. It records the game into a
GameRecord (pairb.lab.record) and gives the page its view of it. The game follows fow_shared.evaluation.play_game,
one ply at a time:

- The bot and its tracker are reset with the bot's colour and the game's seed, plus 0 for White and 1 for Black.
- The tracker is shown every view of the bot's from the start on, with own_move set right after the bot's own move
  and None after the human's. As in play_game, it is not shown the view that ends the game.
- On its turn the bot gets AgentInput(observation, belief, 60 000 ms, history) and nothing else. The history is
  built as play_game builds private_history: one HistoryEvent per earlier ply, holding the bot's view before that ply
  and the move if it was the bot's own. Its Decision is checked with Decision.validate_for before it is played.
- The bot replies at once to the human's move, unless the game is over. A position that no rule has ended but whose
  side to move has no legal move ends the game as {"winner": "draw", "reason": "no_legal_moves"}; this is checked at
  the start and after every move.

Honesty: nothing from the referee or from the human's side reaches the bot or its tracker. The app's inspection of a
bot turn (every move's value on the true board, what not knowing cost, whether the true position is among the
tracker's particles) is made with the inspector, a second scorer object that the bot never uses, because one scorer
could carry the true board into the bot's later answers: Stockfish keeps a hash between calls. The inspection is
recorded and never fed back. An agent that gives no explanation gets the app's inspection of its own belief instead,
made with the inspector and marked "app_inspection". A failure of the app's own inspection does not stop the game: it
is written into the inspection, under "error".

Fair game: until a fair game is revealed, state() is view_state(reveal=False), only what the human is entitled to,
plus the game's id, the scorer's device and the error (None). Session.revealed decides it, and nothing else does: it is
always True outside a fair game, and in a fair game once the game is over or has been stopped by an error, since no
move can follow either. A server sends a fair game's record only while revealed is True.

Errors: an exception from the bot or its tracker stops the game. `error` says what failed, a BotTurn holding the same
text is stored (its ply is the number of moves so far, so no step shows it as played), and every later move is
refused. A stop reveals a fair game, so the page gets the whole error text. That text never holds a position: a FEN or
a printed board in an exception's message is replaced, since a rules state's repr prints its FEN.

The session owns both scorers from the moment it is created. It closes them as soon as the game is over or stopped, on
close(), and before raising when it cannot start. One re-entrant lock guards every use of the referee, the tracker and
the record, reads included, because python-chess's repetition check pops and re-pushes moves on the stored board: a
server calls the session only through its methods.
"""
import contextlib
import dataclasses
import random
import re
import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chess

from fow_shared.contracts import AgentInput, Belief, Decision, HistoryEvent, Observation
from fow_shared.interfaces import Agent, BeliefTracker
from fow_shared.values import standard_fen

from ..bot import OnePlyBot
from ..rules import GameReferee, Rules
from ..tracker import ParticleTracker
from .record import BotTurn, GameRecord, PlyRecord, observation_json, view_state
from .scorers import SCORER_IDS

COLOURS = ("white", "black")
HUMAN_CHOICES = ("white", "black", "random")
TIME_BUDGET_MS = 60_000
# What a fair game that is not revealed would show for an error (Ruling R8). An error stop reveals the game (R17), so
# this text is never shown now; it stays as the fail-closed answer should `revealed` ever be narrowed.
FAIR_ERROR = "the bot stopped with an error; details are in the record"

_UCI = re.compile(r"[a-h][1-8][a-h][1-8][qrbn]?")
# A FEN, or the board part of one, and a board printed by python-chess (str(board) or board.unicode()): 8 rows of 8.
_RANK = r"[pnbrqkPNBRQK1-8]{1,8}"
_FEN = re.compile(rf"{_RANK}(?:/{_RANK}){{7}}"
                  r"(?: [wb](?: (?:-|[KQkqA-Ha-h]{1,4}))?(?: (?:-|[a-h][1-8]))?(?: \d+){0,2})?")
_SQUARE = "[.pnbrqkPNBRQK\u2654-\u265f\u2b58\u00b7]"
_ROW = rf"{_SQUARE}(?: {_SQUARE}){{7}}"
_DIAGRAM = re.compile(rf"{_ROW}(?:\n{_ROW}){{7}}")


@dataclass(frozen=True)
class GameOptions:
    """How a new game is set up, as the New game panel sends it. Every field is checked when the options are made:
    ValueError, naming the field, for a value of the wrong kind or out of range."""

    human: str = "white"  # "white", "black" or "random", which is drawn with random.Random(seed)
    scorer: str = "material"  # one of pairb.lab.scorers.SCORER_IDS
    bot: str = "pairb-one-ply"  # a key of BOTS
    guesses: int = 8  # 1..32: the most guesses a belief of the bot's holds
    particles: int = 256  # 1..4096: the tracker's cap
    seed: int = 0  # 0 or more
    fair: bool = False
    start_fen: str | None = None  # a public start other than the standard one, for tests

    def __post_init__(self) -> None:
        if not isinstance(self.human, str) or self.human not in HUMAN_CHOICES:
            raise ValueError('human must be "white", "black" or "random"')
        if not isinstance(self.scorer, str) or self.scorer not in SCORER_IDS:
            raise ValueError(f"scorer must be one of: {', '.join(SCORER_IDS)}")
        if not isinstance(self.bot, str) or self.bot not in BOTS:
            raise ValueError(f"bot must be one of: {', '.join(BOTS)}")
        _check_whole(self.guesses, "guesses", 1, 32)
        _check_whole(self.particles, "particles", 1, 4096)
        _check_whole(self.seed, "seed", 0)
        if not isinstance(self.fair, bool):
            raise ValueError("fair must be true or false")
        if self.start_fen is not None:
            if not isinstance(self.start_fen, str):
                raise ValueError("start_fen must be a FEN, or null for the standard start")
            try:
                chess.Board(self.start_fen)
            except ValueError:
                raise ValueError("start_fen is not a FEN that python-chess can read") from None


def _check_whole(value, name: str, low: int, high: int | None = None) -> None:
    """ValueError unless `value` is a whole number (not a bool) from `low` to `high` (no upper bound when None)."""
    if not isinstance(value, int) or isinstance(value, bool) or value < low or (high is not None and value > high):
        span = f"from {low} to {high}" if high is not None else f"of {low} or more"
        raise ValueError(f"{name} must be a whole number {span}")


@dataclass(frozen=True)
class BotSpec:
    """A bot the app offers: how to make the Agent from the bot's scorer, and the BeliefTracker it plays with."""

    label: str
    make_agent: Callable[[Any], Agent]  # takes the bot's scorer
    make_tracker: Callable[[Rules, GameOptions], BeliefTracker]


def default_tracker(rules: Rules, options: GameOptions) -> ParticleTracker:
    """Pair B's particle tracker from the game's public start, with the game's particles and guesses."""
    return ParticleTracker(rules, n_particles=options.particles, n_hypotheses=options.guesses,
                           initial_fen=options.start_fen)


# Adding Pair A's agent is one more entry: a factory for their agent and one for their tracker.
BOTS: dict[str, BotSpec] = {"pairb-one-ply": BotSpec("Pair B one-ply belief bot", OnePlyBot, default_tracker)}


class Session:
    """One game between the human and a bot. Use it through its methods; its attributes are for reading only.

    id is uuid4().hex[:12]. options are the GameOptions it was made with; human is the human's colour, "random"
    resolved, and bot_colour the other one. referee is for the app's inspection and for tests. record is the game so
    far. over is True once the game has a result; error is set when the bot or its tracker stopped the game, which is
    then not over and takes no more moves. revealed says whether the page may see the bot's side.
    """

    def __init__(self, options: GameOptions, rules: Rules, scorer, inspector):
        """Start the game: `scorer` is the bot's and `inspector` the app's, two separately opened objects of the same
        scorer id. The bot moves at once if it is to move. If the game cannot start, both scorers are closed and the
        exception (ValueError for a start the rules refuse, or the same object given twice) is raised."""
        self._lock = threading.RLock()
        self._scorer, self._inspector = scorer, inspector
        self._closed = False
        try:
            with self._lock:
                self._start(options, rules)
        except BaseException:
            self._close_scorers()
            raise

    def _start(self, options: GameOptions, rules: Rules) -> None:
        if self._inspector is self._scorer:
            raise ValueError("the inspector must be a scorer object of its own, not the bot's")
        self.options = options
        self.id = uuid.uuid4().hex[:12]
        self.human = random.Random(options.seed).choice(COLOURS) if options.human == "random" else options.human
        self.bot_colour = "black" if self.human == "white" else "white"
        self.over = False
        self.error: str | None = None
        device = getattr(self._scorer, "device", None)
        self._device = None if device is None else str(device)
        self.referee = GameReferee(rules, options.start_fen)
        self.referee.reset(options.seed)
        spec = BOTS[options.bot]
        self._agent = spec.make_agent(self._scorer)
        self._tracker = spec.make_tracker(rules, options)
        seed = options.seed + COLOURS.index(self.bot_colour)  # as play_game seeds each colour
        self._agent.reset(self.bot_colour, seed)
        self._tracker.reset(self.bot_colour, seed)
        views = self._views()
        self.record = GameRecord(options={**dataclasses.asdict(options), "human": self.human}, rules=rules.name,
                                 scorer=self._scorer.name, bot=self._agent.name,
                                 start_fen=standard_fen(self.referee.true_board()),
                                 start_observations=_views_json(views), plies=[], bot_turns=[], result=None)
        self._bot_view = views[self.bot_colour]  # the bot's latest observation
        self._history: list[HistoryEvent] = []  # play_game's private_history for the bot
        self._belief: Belief | None = None
        if self._ended(views):
            return
        try:
            self._belief = self._tracker.update(self._bot_view)
        except Exception as exc:
            self._stop("the bot's tracker failed on its first view", exc)
            return
        if self.referee.current_player() == self.bot_colour:
            self._bot_turn()

    def human_move(self, move: str) -> None:
        """Play the human's move, then the bot's reply unless the game is over.

        ValueError, with the game unchanged, when the game is over, stopped or closed, when it is not the human's
        turn, and when `move` is not UCI text or not one of the human's legal moves.
        """
        with self._lock:
            if self.over:
                raise ValueError("the game is over")
            if self.error is not None:
                raise ValueError(f"game stopped: {self._error_text(self.revealed)}")
            if self._closed:
                raise ValueError("the game has been closed")
            if self.referee.current_player() != self.human:
                raise ValueError("it is not your turn")
            if not isinstance(move, str) or not _UCI.fullmatch(move):
                raise ValueError("a move must be UCI text, such as e2e4 or a7a8q")
            if move not in self.referee.observe(self.human).legal_moves:
                raise ValueError(f"{move} is not one of your legal moves")
            before = self._bot_view
            self.referee.apply(move)
            self._moved(self.human, move, before, own=False)
            if not self.over and self.error is None:
                self._bot_turn()

    @property
    def revealed(self) -> bool:
        """Whether the page may see the bot's side and the true board, in state() and in the record: always outside a
        fair game, and in a fair game once it is over or has been stopped by an error. Read under the session's lock.
        This is the only place that decides it."""
        with self._lock:
            return not self.options.fair or self.over or self.error is not None

    def state(self, upto: int | None = None) -> dict:
        """The page's view after `upto` moves (default: all of them): view_state, with the bot's side and the true
        board when `revealed`, plus "id", "error" (why the game stopped, or None) and "device" (the bot's scorer's
        device, or None; no secret, so shown in a fair game too). ValueError when `upto` is not a whole number from 0
        to the number of moves."""
        with self._lock:
            reveal = self.revealed
            view = view_state(self.record, upto, reveal=reveal)
            view.update(id=self.id, error=self._error_text(reveal), device=self._device)
            return view

    def record_json(self) -> dict:
        """The game record as plain JSON values (GameRecord.to_json), read under the session's lock. It holds the
        bot's side and the true board: a server sends it only while `revealed` is True, which it checks itself."""
        with self._lock:
            return self.record.to_json()

    def close(self) -> None:
        """Close the bot's scorer and the inspector unless the game has closed them already. Calling it again does
        nothing, and it never raises: a scorer that fails to close (an engine that has died) does not keep the other
        open. A game that is not over takes no more moves after this."""
        with self._lock:
            self._close_scorers()

    def _bot_turn(self) -> None:
        """The bot's move, in play_game's order: act and check the decision, keep the explanation, inspect with the
        inspector, play the move, then show the tracker the bot's new view. Anything raised before the move is played
        stops the game with nothing played."""
        view, belief = self._bot_view, self._belief
        try:
            decision = self._agent.act(AgentInput(view, belief, TIME_BUDGET_MS, tuple(self._history)))
            decision.validate_for(view)
            made = getattr(self._agent, "last_explanation", None)
            explanation = made.to_json() if made is not None else self._app_explanation(view, belief, decision)
            inspection = self._inspection(decision.move)
            self.referee.apply(decision.move)
        except Exception as exc:
            self._stop("the bot failed to move", exc, belief)
            return
        self.record.bot_turns.append(BotTurn(len(self.record.plies), _belief_json(belief), belief.population_size,
                                             explanation, inspection))
        self._moved(self.bot_colour, decision.move, view, own=True)

    def _moved(self, mover: str, move: str, before: Observation, own: bool) -> None:
        """After `mover` played `move` (the bot's own move when `own`): extend the bot's history from its view
        `before` the move, record the ply, end the game if it is over, and otherwise show the tracker the new view."""
        self._history.append(HistoryEvent(before, move if own else None))
        views = self._views()
        self.record.plies.append(PlyRecord(len(self.record.plies), mover, move,
                                           standard_fen(self.referee.true_board()), _views_json(views)))
        self._bot_view = views[self.bot_colour]
        if self._ended(views):
            return
        try:
            self._belief = self._tracker.update(self._bot_view, own_move=move if own else None)
        except Exception as exc:
            after = "its own move" if own else "the human's move"
            self._stop(f"the bot's tracker failed after {after}", exc)

    def _ended(self, views: dict[str, Observation]) -> bool:
        """Whether the game is over: a rule has ended it, or its side to move has no legal move (a draw,
        "no_legal_moves"). If it is, the result is recorded and the scorers are closed."""
        ended = self.referee.result()
        if ended is None:
            if views[self.referee.current_player()].legal_moves:
                return False
            ended = ("draw", "no_legal_moves")
        self.record.result = {"winner": ended[0], "reason": ended[1]}
        self.over = True
        self._close_scorers()
        return True

    def _stop(self, what: str, exc: Exception, belief: Belief | None = None) -> None:
        """Stop the game after an exception from the bot or its tracker: keep the error, and the belief the bot had,
        in a BotTurn that was never played, and close the scorers."""
        self.error = f"{what}: {_describe(exc)}"
        self.record.bot_turns.append(BotTurn(len(self.record.plies), [] if belief is None else _belief_json(belief),
                                             None if belief is None else belief.population_size, {}, {},
                                             error=self.error))
        self._close_scorers()

    def _app_explanation(self, view: Observation, belief: Belief, decision: Decision) -> dict:
        """For an agent that gives no explanation: its policy and its move, and the inspector's value of every legal
        move on each of the agent's own guesses, with each move's weighted average, minimum and maximum, marked as the
        app's inspection. A failure leaves the values None and is written into it, under "error"."""
        moves = view.legal_moves
        guesses = [hypothesis.fen for hypothesis in belief.hypotheses]
        weights = [float(hypothesis.weight) for hypothesis in belief.hypotheses]
        explanation = {"app_inspection": True, "scorer": self._inspector.name, "chosen": decision.move,
                       "policy": {move: float(decision.root_policy[move]) for move in moves},
                       "guesses": guesses, "weights": weights, "values": None, "averages": None, "min": None,
                       "max": None, "error": None}
        try:
            rows = []
            for index, fen in enumerate(guesses):
                children = self._inspector.evaluate_children(fen)
                if set(children) != set(moves):
                    raise ValueError(f"guess {index} has different legal moves from the observation")
                rows.append({move: float(children[move]) for move in moves})
            values = {move: [row[move] for row in rows] for move in moves}
            explanation.update(values=values,
                               averages={move: sum(w * v for w, v in zip(weights, vs)) for move, vs in values.items()},
                               min={move: min(vs) for move, vs in values.items()},
                               max={move: max(vs) for move, vs in values.items()})
        except Exception as exc:
            explanation["error"] = f"the app's inspection failed: {_describe(exc)}"
        return explanation

    def _inspection(self, move: str) -> dict:
        """The app's look at the bot's turn before `move` is played, which the bot never sees: the inspector's value of
        every move on the true board, the best of them (the bot's move when it is one of the best) and
        lost_by_not_knowing, the best value minus the bot's move's; and the tracker's particles (FENs), whether the true
        position is one of them, and whether the tracker rebuilt or capped them. A tracker that cannot say leaves None.
        A failure is written into it, under "error"."""
        true_fen = standard_fen(self.referee.true_board())
        inspection = {"true_values": None, "best_on_true_board": None, "lost_by_not_knowing": None,
                      "particles": None, "truth_in_particles": None, "rebuilt": None, "capped": None, "error": None}
        try:
            particle_fens = getattr(self._tracker, "particle_fens", None)
            if callable(particle_fens):
                particles = list(particle_fens())
                inspection.update(particles=particles, truth_in_particles=true_fen in particles)
            for flag in ("rebuilt", "capped"):
                value = getattr(self._tracker, flag, None)
                inspection[flag] = None if value is None else bool(value)
            values = {child: float(value) for child, value in self._inspector.evaluate_children(true_fen).items()}
            if move not in values:
                raise ValueError("the scorer gave no value for the bot's move on the true board")
            best = max(values.values())
            tied = sorted(child for child, value in values.items() if value == best)
            inspection.update(true_values=values, best_on_true_board=move if move in tied else tied[0],
                              lost_by_not_knowing=best - values[move])
        except Exception as exc:
            inspection["error"] = f"the app's inspection failed: {_describe(exc)}"
        return inspection

    def _views(self) -> dict[str, Observation]:
        return {colour: self.referee.observe(colour) for colour in COLOURS}

    def _error_text(self, reveal: bool) -> str | None:
        """The error as the page may see it, given `revealed`: the whole text when revealed, FAIR_ERROR otherwise."""
        if self.error is None:
            return None
        return self.error if reveal else FAIR_ERROR

    def _close_scorers(self) -> None:
        if self._closed:
            return
        self._closed = True
        for scorer in (self._scorer,) if self._inspector is self._scorer else (self._scorer, self._inspector):
            with contextlib.suppress(Exception):  # an engine that has died cannot be closed; the other still is
                scorer.close()


def _views_json(views: dict[str, Observation]) -> dict:
    return {colour: observation_json(views[colour]) for colour in COLOURS}


def _belief_json(belief: Belief) -> list[dict]:
    return [{"fen": hypothesis.fen, "weight": float(hypothesis.weight)} for hypothesis in belief.hypotheses]


def _describe(exc: BaseException) -> str:
    """An exception as text for the record and the page: its type, its message with every FEN replaced by <position>
    and every printed board by <board>, and the file, line and function that raised it."""
    message = _DIAGRAM.sub("<board>", _FEN.sub("<position>", str(exc)))
    text = f"{type(exc).__name__}: {message}" if message else type(exc).__name__
    frames = traceback.extract_tb(exc.__traceback__)
    if frames:
        text += f" (at {Path(frames[-1].filename).name}:{frames[-1].lineno} in {frames[-1].name})"
    return text
