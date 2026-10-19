"""Game sessions (Fog Lab): one game between the human at the page and a bot, as the server holds it.

A Session holds the referee (the only holder of the true board), the bot and its tracker, records the game into a
GameRecord and gives the page its view. These tests play real games with the stand-in rules, piece values, 32
particles and 4 guesses. The scorers are spies around piece values, so a test can see every position each of
them was asked about and how often it was closed. Test agents and trackers come in through BOTS entries, the way
Pair A's agent will.
"""
import dataclasses
import json
import random
import re
import threading

import chess
import pytest

from fow_shared.contracts import Decision
from fow_shared.values import standard_fen
from pairb.bot import OnePlyBot
from pairb.lab.record import HIDDEN_KEYS, GameRecord, observation_json, view_state
from pairb.lab.scorers import SCORER_IDS
from pairb.lab.session import BOTS, BotSpec, GameOptions, Session, default_tracker
from pairb.material import MaterialEvaluator
from pairb.rules import StandinRules
from pairb.tracker import ParticleTracker, TrackerLost

COLOURS = ("white", "black")
FAIR_START = "k7/8/1Q6/8/8/8/8/K7 b - - 0 1"  # Black to move, and each of its king's moves walks into the queen
KING_CAPTURE = "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1"  # Re2xe8 takes the king
FIFTY_MOVES = "4k3/8/8/8/8/8/8/R3K3 w - - 99 80"  # any quiet move is the hundredth half-move: a draw
PROMOTION = "7k/P7/8/8/8/8/8/K7 w - - 0 1"
NO_LEGAL_MOVES = {"winner": "draw", "reason": "no_legal_moves"}
FEN_PLACEMENT = re.compile(r"[1-8pnbrqkPNBRQK]+(?:/[1-8pnbrqkPNBRQK]+){7}")  # the board part of any FEN


class Spy:
    """Piece values that remember every evaluate_children call and every close."""

    def __init__(self, device=None):
        self._inner = MaterialEvaluator()
        self.name = self._inner.name
        self.calls = []
        self.closes = 0
        if device is not None:
            self.device = device

    def evaluate_children(self, fen):
        self.calls.append(fen)
        return self._inner.evaluate_children(fen)

    def close(self):
        self.closes += 1


def session_for(rules=None, scorer=None, inspector=None, **options):
    """A session over piece-value spies with 32 particles and 4 guesses; `options` override GameOptions fields."""
    options = {"particles": 32, "guesses": 4, **options}
    return Session(GameOptions(**options), rules or StandinRules(), scorer or Spy(), inspector or Spy())


def play_randomly(session, seed, human_moves):
    """Up to `human_moves` moves for the human, each drawn from their legal moves with random.Random(seed)."""
    rng = random.Random(seed)
    for _ in range(human_moves):
        if session.over:
            return
        session.human_move(rng.choice(session.state()["you"]["legal_moves"]))


def fen_before(record, ply):
    """The true position before move `ply`."""
    return record.start_fen if ply == 0 else record.plies[ply - 1].true_fen


def view_before(record, ply, colour):
    """`colour`'s observation (as JSON) before move `ply`."""
    return (record.start_observations if ply == 0 else record.plies[ply - 1].observations)[colour]


class RandomAgent:
    """An Agent with no explanation: a seeded random legal move, with a uniform policy."""

    name = "random-mover"

    def __init__(self, scorer=None):
        self.rng = None

    def reset(self, player, seed):
        self.rng = random.Random(seed)

    def act(self, turn):
        moves = turn.observation.legal_moves
        return Decision(self.rng.choice(moves), {move: 1 / len(moves) for move in moves})


class NoMovesRules(StandinRules):
    """The stand-in rules, except that `player` has no legal move from ply `from_ply` on, in a position that is not
    over: the open rules case (Review Focus 3)."""

    def __init__(self, player, from_ply=0):
        self.player, self.from_ply = player, from_ply

    def _stuck(self, state):
        return self.current_player(state) == self.player and state.ply >= self.from_ply

    def legal_moves(self, state):
        return () if self._stuck(state) else super().legal_moves(state)

    def observe(self, state, player):
        view = super().observe(state, player)
        return dataclasses.replace(view, legal_moves=()) if self._stuck(state) else view


@pytest.fixture
def register(monkeypatch):
    """Adds a BOTS entry for one test: register(name, make_agent, make_tracker=default_tracker) -> name."""
    def add(name, make_agent, make_tracker=default_tracker):
        monkeypatch.setitem(BOTS, name, BotSpec(name, make_agent, make_tracker))
        return name
    return add


# Catches: plies that do not alternate or are misnumbered, a bot turn recorded at the wrong ply or with another
# move than the one played, a result missing at the end, a record that GameRecord.from_json refuses, and a state
# with keys beyond view_state's plus id, error and device (Ruling R16). Random humans lose their king within a few
# dozen plies, so two games are played (24 and 46 plies when this was written, the second with tracker rebuilds).
@pytest.mark.parametrize("seed", [5, 10])
def test_full_game_with_random_human_moves(seed):
    session = session_for(seed=seed)
    rng = random.Random(seed)
    while not session.over and len(session.record.plies) < 150:
        state = session.state()
        assert (state["to_move"], state["error"], state["ply"]) == ("white", None, len(session.record.plies))
        session.human_move(rng.choice(state["you"]["legal_moves"]))
    record = session.record
    n = len(record.plies)
    assert [ply.ply for ply in record.plies] == list(range(n))
    assert [ply.player for ply in record.plies] == [COLOURS[i % 2] for i in range(n)]
    assert [turn.ply for turn in record.bot_turns] == [ply.ply for ply in record.plies if ply.player == "black"]
    assert all(turn.error is None for turn in record.bot_turns)
    assert all(turn.explanation["chosen"] == record.plies[turn.ply].move for turn in record.bot_turns)
    assert record.plies[-1].true_fen == standard_fen(session.referee.true_board())
    assert record.plies[-1].observations == {c: observation_json(session.referee.observe(c)) for c in COLOURS}
    if session.over:
        assert record.result is not None and session.state()["result"] == record.result
    else:
        assert n == 150 and record.result is None
    assert set(session.state()) == set(view_state(record, reveal=True)) | {"id", "error", "device"}
    assert session.record_json() == record.to_json()
    loaded = GameRecord.from_json(json.loads(json.dumps(session.record_json())))
    for upto in range(n + 1):
        assert view_state(loaded, upto) == view_state(record, upto)


# Catches: a bot that waits for the human when the human plays Black, and a state that is not revealed outside a
# fair game.
def test_human_black_bot_moves_first():
    session = session_for(human="black")
    record = session.record
    assert [(ply.ply, ply.player) for ply in record.plies] == [(0, "white")]
    assert [turn.ply for turn in record.bot_turns] == [0]
    state = session.state()
    assert (state["human"], state["to_move"], state["your_moves"], state["ply"]) == ("black", "black", [], 1)
    assert state["moves"] == [{"ply": 0, "player": "white", "move": record.plies[0].move}]
    assert state["bot"] == record.bot_turns[0].to_json()
    assert re.fullmatch(r"[0-9a-f]{12}", state["id"]) and state["id"] == session.id
    assert set(state) == set(view_state(record, reveal=True)) | {"id", "error", "device"}


# Catches: a move that is not legal (or not text) being played or crashing the session, and a human move accepted
# while the bot is choosing: the probe asks during the bot's own turn, as a second request arriving then would, and
# the lock is re-entrant, so only the turn check can refuse it.
def test_rejects_illegal_and_out_of_turn(register):
    refusals = []

    class Probe(RandomAgent):
        def act(self, turn):
            try:
                session.human_move("d2d4")
            except ValueError as exc:
                refusals.append(str(exc))
            return super().act(turn)

    session = session_for(bot=register("probe", Probe))
    with pytest.raises(ValueError, match="legal"):
        session.human_move("e2e5")
    with pytest.raises(ValueError, match="legal"):
        session.human_move("e7e5")  # Black's move, on White's turn
    for junk in ["", "e2", "e2e4e5", "E2E4", "e2e4 ", 42, None]:
        with pytest.raises(ValueError, match="UCI"):
            session.human_move(junk)
    assert session.record.plies == [] and session.record.bot_turns == [] and session.state()["ply"] == 0
    session.human_move("e2e4")
    assert refusals == ["it is not your turn"]
    assert [ply.player for ply in session.record.plies] == ["white", "black"]
    assert session.record.plies[0].move == "e2e4"  # and d2d4 was never played


# Required test 5. Catches: anything of the bot's side or the true board reaching the page before a fair game ends
# (a key beyond HIDDEN_KEYS, the true position, the bot's move or its guesses anywhere in the state), a "you" that is
# not the referee's own view for the human, a device hidden although it is no secret, and a game that stays hidden
# after it ends.
def test_fair_game_shows_only_human_fields_until_the_end():
    session = session_for(fair=True, start_fen=FAIR_START, human="white", scorer=Spy(device="test-device"))
    hidden = set(HIDDEN_KEYS) | {"id", "error", "device"}
    state = session.state()
    record = session.record
    assert len(record.plies) == 1 and len(record.bot_turns) == 1  # the bot moved first
    while not state["over"]:
        assert set(state) == hidden
        assert state["you"] == observation_json(session.referee.observe("white"))
        assert (state["fair"], state["human"], state["ply"], state["to_move"]) == (True, "white", 1, "white")
        assert (state["your_moves"], state["result"], state["error"]) == ([], None, None)
        assert state["device"] == "test-device"
        text = json.dumps(state)
        assert FEN_PLACEMENT.search(text) is None  # no true position, no guess
        assert record.plies[0].move not in text  # nor the bot's move
        assert all(set(session.state(upto)) == hidden for upto in (0, 1))
        king = next(square for square, piece in state["you"]["visible_pieces"].items() if piece == "k")
        session.human_move(next(move for move in state["you"]["legal_moves"] if move[2:4] == king))
        state = session.state()
    assert state["result"] == {"winner": "white", "reason": "king_capture"}
    assert "bot" in state and "true_fen" in state and state["bot"] == record.bot_turns[0].to_json()
    assert "bot" in session.state(1) and "true_fen" in session.state(0)  # stepping back shows the bot's side too


# Ruling R17. Catches: a fair game that opens up before the bot fails, one that stays hidden after an error stop (the
# record's details would then never be reachable, as no move can follow), and a stopped fair game whose state shows
# less than the whole error or less than what revealing adds at that step.
def test_fair_game_stopped_by_an_error_is_revealed(register):
    class SecondMoveFails(RandomAgent):
        moves = 0

        def act(self, turn):
            self.moves += 1
            if self.moves == 2:
                raise RuntimeError("the bot broke on its second move")
            return super().act(turn)

    session = session_for(bot=register("second-move-fails", SecondMoveFails), fair=True)
    session.human_move("e2e4")  # the bot's first move goes through
    state = session.state()
    assert not session.revealed and set(state) == set(HIDDEN_KEYS) | {"id", "error", "device"}
    assert state["error"] is None
    session.human_move("d2d4")  # always legal here: no Black move reaches d3 or d4; then the bot fails
    record = session.record
    assert session.error.startswith("the bot failed to move: RuntimeError: the bot broke on its second move")
    assert session.revealed and not session.over
    state = session.state()
    assert set(state) == set(view_state(record, reveal=True)) | {"id", "error", "device"}
    assert state["error"] == session.error  # the whole text, not the generic one
    assert state["bot"] == record.bot_turns[0].to_json() and state["true_fen"] == record.plies[-1].true_fen
    assert (state["over"], state["result"]) == (False, None)  # stopped, not over
    assert all("true_fen" in session.state(upto) for upto in range(len(record.plies) + 1))  # every step opens
    with pytest.raises(ValueError) as refused:
        session.human_move("g1f3")
    assert str(refused.value) == f"game stopped: {session.error}"


# Ruling R17. Catches: a `revealed` that is True while a fair game is going on, False once it is over, or ever False
# for a game that is not fair; and one that can be set from outside.
def test_revealed_only_when_a_fair_game_ends():
    for fair in (True, False):
        session = session_for(fair=fair, seed=1)
        rng = random.Random(1)
        while not session.over:
            assert session.revealed is not fair
            session.human_move(rng.choice(session.state()["you"]["legal_moves"]))
        assert session.revealed is True and len(session.record.plies) > 2
        with pytest.raises(AttributeError):
            session.revealed = False


# Review Focus 1. Catches: the inspection made with the bot's own scorer (Stockfish's hash would then carry the true
# board into the bot's later answers), the bot's scorer asked about anything but its guesses, the inspector asked
# about anything but the true board, inspection numbers that are not the inspector's values on the true board, and a
# session that takes one object as both scorers.
def test_inspection_uses_its_own_scorer():
    scorer, inspector = Spy(), Spy()
    session = session_for(scorer=scorer, inspector=inspector, seed=2)
    play_randomly(session, 2, 3)
    record = session.record
    turns = record.bot_turns
    assert len(turns) == 3 and len(turns[0].belief) == 4  # 20 particles at first; later the bot may know more
    assert all(len(turn.belief) == min(4, len(turn.inspection["particles"])) for turn in turns)
    assert scorer.calls == [entry["fen"] for turn in turns for entry in turn.belief]  # one call per guess
    assert inspector.calls == [fen_before(record, turn.ply) for turn in turns]
    for turn in turns:
        values = MaterialEvaluator().evaluate_children(fen_before(record, turn.ply))
        move = record.plies[turn.ply].move
        inspection = turn.inspection
        assert inspection["true_values"] == values and inspection["error"] is None
        assert values[inspection["best_on_true_board"]] == max(values.values())
        assert inspection["lost_by_not_knowing"] == max(values.values()) - values[move]
        assert inspection["truth_in_particles"] == (fen_before(record, turn.ply) in inspection["particles"])
        assert len(inspection["particles"]) <= 32 and isinstance(inspection["rebuilt"], bool)
        assert isinstance(inspection["capped"], bool)
    one = Spy()
    with pytest.raises(ValueError, match="inspector"):
        session_for(scorer=one, inspector=one)
    assert one.closes == 1  # the session owns what it is given, even when it refuses to start


# Review Focus 2. Catches: a bot asked to move after the human has taken its king, and a game going on after it.
def test_human_capturing_the_king_ends_the_game():
    scorer, inspector = Spy(), Spy()
    session = session_for(start_fen=KING_CAPTURE, scorer=scorer, inspector=inspector)
    session.human_move("e2e8")
    assert session.over and session.error is None
    assert session.record.result == {"winner": "white", "reason": "king_capture"}
    assert len(session.record.plies) == 1 and session.record.bot_turns == []
    assert scorer.calls == [] and inspector.calls == []  # nobody was asked to think
    state = session.state()
    assert state["over"] and state["result"] == {"winner": "white", "reason": "king_capture"}
    with pytest.raises(ValueError, match="over"):
        session.human_move("e1e2")


# Review Focus 2. Catches: a draw reached on the human's move that still asks the bot to move.
def test_human_drawing_ends_the_game():
    session = session_for(start_fen=FIFTY_MOVES)
    session.human_move("a1a2")
    assert session.over and session.record.result == {"winner": "draw", "reason": "fifty_move"}
    assert len(session.record.plies) == 1 and session.record.bot_turns == []


# Review Focus 2. Catches: five-character UCI moves refused or played as something else.
def test_promotion_move_is_accepted():
    session = session_for(start_fen=PROMOTION)
    assert {"a7a8q", "a7a8r", "a7a8b", "a7a8n"} <= set(session.state()["you"]["legal_moves"])
    session.human_move("a7a8n")
    first = session.record.plies[0]
    assert (first.move, first.true_fen.split()[0]) == ("a7a8n", "N6k/8/8/8/8/8/8/K7")
    assert len(session.record.plies) == 2 and session.state()["your_moves"] == ["a7a8n"]


# Review Focus 3. Catches: a side to move with no legal move that is asked to move anyway (the bot would raise and the
# human would be stuck), checked only for one side or only after some plies: here after the human's move, after the
# bot's, and at the start with either side to move.
@pytest.mark.parametrize("human, stuck, from_ply, human_moves, plies, bot_turns", [
    ("white", "black", 1, ["e2e4"], 1, 0),  # the bot, after the human's move
    ("white", "white", 2, ["e2e4"], 2, 1),  # the human, after the bot's move
    ("white", "white", 0, [], 0, 0),  # the human, at the start
    ("black", "white", 0, [], 0, 0),  # the bot, at the start
])
def test_no_legal_moves_ends_the_game(human, stuck, from_ply, human_moves, plies, bot_turns):
    scorer, inspector = Spy(), Spy()
    session = session_for(rules=NoMovesRules(stuck, from_ply), human=human, scorer=scorer, inspector=inspector)
    for move in human_moves:
        session.human_move(move)
    assert session.over and session.error is None and session.record.result == NO_LEGAL_MOVES
    assert len(session.record.plies) == plies and len(session.record.bot_turns) == bot_turns
    state = session.state()
    assert state["over"] and state["result"] == NO_LEGAL_MOVES
    assert (scorer.closes, inspector.closes) == (1, 1)  # Ruling R3: closed as soon as the game is over
    with pytest.raises(ValueError, match="over"):
        session.human_move("e2e4")


class FailingTracker(ParticleTracker):
    """Pair B's tracker, except that its `fail_at`-th update raises (the first update is the start's)."""

    def __init__(self, rules, options, fail_at):
        super().__init__(rules, n_particles=options.particles, n_hypotheses=options.guesses,
                         initial_fen=options.start_fen)
        self.fail_at, self.count = fail_at, 0

    def update(self, observation, own_move=None):
        self.count += 1
        if self.count == self.fail_at:
            raise TrackerLost(f"no position fits {observation.player}'s view at ply {observation.ply}")
        return super().update(observation, own_move)


class RaisingAgent(RandomAgent):
    def act(self, turn):
        raise RuntimeError("the bot broke")


class IllegalAgent(RandomAgent):
    def act(self, turn):
        return Decision("a1a8", {move: 1 / len(turn.observation.legal_moves) for move in turn.observation.legal_moves})


# Catches: an exception from the bot or its tracker escaping (the server would answer 500 and the game would hang at
# the bot's turn), a stop without its error in the state and in a stored BotTurn (whose ply must be the number of
# moves, so that no step shows it as played), a game that takes moves after a stop, scorers left open (Ruling R3),
# and a record that cannot be saved and loaded back for the bug report.
@pytest.mark.parametrize("make_agent, fail_at, plies, what", [
    (RaisingAgent, None, 1, "the bot failed to move: RuntimeError: the bot broke"),
    (IllegalAgent, None, 1, "the bot failed to move: ValueError: agent selected an unavailable move"),
    (OnePlyBot, 2, 1, "the bot's tracker failed after the human's move: TrackerLost: no position fits"),
    (OnePlyBot, 3, 2, "the bot's tracker failed after its own move: TrackerLost: no position fits"),
])
def test_bot_error_stops_the_game(register, make_agent, fail_at, plies, what):
    def make_tracker(rules, options):
        return default_tracker(rules, options) if fail_at is None else FailingTracker(rules, options, fail_at)

    scorer, inspector = Spy(), Spy()
    session = session_for(bot=register("failing", make_agent, make_tracker), scorer=scorer, inspector=inspector)
    session.human_move("e2e4")
    record = session.record
    assert session.error.startswith(what) and not session.over and record.result is None
    assert session.state()["error"] == session.error  # not a fair game: the whole message
    failed = record.bot_turns[-1]
    assert (failed.error, failed.ply, len(record.plies)) == (session.error, plies, plies)
    assert [turn.error is None for turn in record.bot_turns] == [True] * (len(record.bot_turns) - 1) + [False]
    if make_agent is not OnePlyBot:
        assert len(failed.belief) == 4  # the belief the bot failed on is kept
    with pytest.raises(ValueError, match="game stopped") as refused:
        session.human_move("d2d4")
    assert str(refused.value) == f"game stopped: {session.error}"
    assert len(record.plies) == plies and (scorer.closes, inspector.closes) == (1, 1)
    loaded = GameRecord.from_json(json.loads(json.dumps(record.to_json())))
    assert loaded.bot_turns[-1].error == session.error
    shown = view_state(loaded)["bot"]
    assert shown is None or shown["error"] is None  # the failed turn is never shown as played


# Ruling R8. Catches: a position reaching the page in an error (a state's repr prints its FEN, a board prints its
# squares), in state(), in the refusal of the next move or in the record. An error stop reveals a fair game too
# (Ruling R17), so both kinds of game show the whole, redacted text.
def test_error_text_never_holds_a_position(register):
    class Leaky(RandomAgent):
        def act(self, turn):
            board = chess.Board(turn.belief.hypotheses[0].fen)
            raise RuntimeError(f"lost at {standard_fen(board)} in {StandinRules().initial_state()!r}\n{board}\n"
                               f"{board.unicode()}")

    name = register("leaky", Leaky)
    for fair in (False, True):
        session = session_for(bot=name, fair=fair, human="black")  # the bot moves first, and fails
        detail = session.record.bot_turns[-1].error
        assert detail == session.error and detail.startswith("the bot failed to move: RuntimeError: lost at <position>")
        assert "StandinState(board=Board('<position>'), ply=0)" in detail and detail.count("<board>") == 2
        assert FEN_PLACEMENT.search(detail) is None and "r n b q" not in detail and "\u265c" not in detail
        state = session.state()
        assert session.revealed and state["error"] == detail and "true_fen" in state
        with pytest.raises(ValueError) as refused:
            session.human_move("e7e5")
        assert str(refused.value) == f"game stopped: {detail}"


# Spec 4.6. Catches: an agent without an explanation leaving the panel empty or crashing the session, an app
# inspection made with the bot's scorer or on something other than the agent's own guesses, and one that is not
# labelled as the app's.
def test_agent_without_explanation_gets_app_inspection(register):
    scorer, inspector = Spy(), Spy()
    session = session_for(bot=register("random", RandomAgent), scorer=scorer, inspector=inspector)
    session.human_move("e2e4")
    record = session.record
    turn = record.bot_turns[-1]
    explanation = turn.explanation
    guesses = [entry["fen"] for entry in turn.belief]
    legal = record.plies[0].observations["black"]["legal_moves"]
    assert explanation["app_inspection"] is True and explanation["error"] is None
    assert (explanation["chosen"], explanation["guesses"]) == (record.plies[1].move, guesses)
    assert explanation["policy"] == pytest.approx({move: 1 / len(legal) for move in legal})
    assert scorer.calls == [] and inspector.calls == guesses + [record.plies[0].true_fen]
    rows = [MaterialEvaluator().evaluate_children(fen) for fen in guesses]
    weights = [entry["weight"] for entry in turn.belief]
    assert explanation["values"] == {move: [row[move] for row in rows] for move in legal}
    for move in legal:
        assert explanation["averages"][move] == pytest.approx(sum(w * row[move] for w, row in zip(weights, rows)))
    assert turn.inspection["true_values"] == MaterialEvaluator().evaluate_children(record.plies[0].true_fen)


# Ruling R18. Catches: a failure of the app's own inspection (an inspector whose engine died) stopping a game in which
# the bot did nothing wrong, or escaping as an exception, for a bot that explains itself and for one that relies on the
# app's inspection; the failure is written under "error" with None for every value the inspector would have given,
# and what needs no inspector (the tracker's side, the agent's policy and guesses) is still filled in.
@pytest.mark.parametrize("explains", [True, False])
def test_inspection_failure_does_not_stop_the_game(register, explains):
    class Broken(Spy):
        def evaluate_children(self, fen):
            raise RuntimeError("engine process died")

    bot = "pairb-one-ply" if explains else register("random", RandomAgent)
    session = session_for(bot=bot, inspector=Broken())
    session.human_move("e2e4")
    record = session.record
    turn = record.bot_turns[-1]
    failed = "the app's inspection failed: RuntimeError: engine process died"
    assert session.error is None and turn.error is None and len(record.plies) == 2
    assert turn.inspection["error"].startswith(failed)
    assert [turn.inspection[key] for key in ("true_values", "best_on_true_board", "lost_by_not_knowing")] == [None] * 3
    assert turn.inspection["truth_in_particles"] is True  # White's 20 first moves, none seen: all are particles
    explanation = turn.explanation
    assert explanation["chosen"] == record.plies[1].move
    if explains:
        assert "app_inspection" not in explanation  # the bot's own explanation, untouched
    else:
        assert explanation["app_inspection"] is True and explanation["error"].startswith(failed)
        assert [explanation[key] for key in ("values", "averages", "min", "max")] == [None] * 4
        assert explanation["guesses"] == [entry["fen"] for entry in turn.belief] and len(explanation["policy"]) == 20
    session.human_move(session.state()["you"]["legal_moves"][0])  # and the game goes on
    assert len(record.plies) == 4


# play_game's order. Catches: a bot or tracker seeded otherwise than play_game seeds them (seed + 0 for White,
# + 1 for Black), a history that is not play_game's private_history (one event per earlier ply: the bot's view
# before it and its own move, if the move was its own), a tracker that misses one of the bot's views or is told the
# human's move, and a time budget other than 60 s.
@pytest.mark.parametrize("human", COLOURS)
def test_bot_gets_what_play_game_gives(register, human):
    agents, trackers = [], []

    class Recording(RandomAgent):
        def __init__(self, scorer=None):
            super().__init__(scorer)
            self.resets, self.turns = [], []
            agents.append(self)

        def reset(self, player, seed):
            self.resets.append((player, seed))
            super().reset(player, seed)

        def act(self, turn):
            self.turns.append(turn)
            return super().act(turn)

    class RecordingTracker(ParticleTracker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.resets, self.updates = [], []
            trackers.append(self)

        def reset(self, player, seed):
            self.resets.append((player, seed))
            super().reset(player, seed)

        def update(self, observation, own_move=None):
            self.updates.append((observation_json(observation), own_move))
            return super().update(observation, own_move)

    def make_tracker(rules, options):
        return RecordingTracker(rules, n_particles=options.particles, n_hypotheses=options.guesses)

    session = session_for(bot=register("recording", Recording, make_tracker), human=human, seed=7)
    play_randomly(session, 7, 4)
    (agent,), (tracker,), record = agents, trackers, session.record
    bot = "black" if human == "white" else "white"
    assert agent.resets == tracker.resets == [(bot, 7 + COLOURS.index(bot))]
    own = [ply.move if ply.player == bot else None for ply in record.plies]
    for turn in agent.turns:
        k = turn.observation.ply
        assert turn.time_budget_ms == 60_000
        assert observation_json(turn.observation) == view_before(record, k, bot)
        assert [(observation_json(event.observation), event.own_move) for event in turn.history] == \
            [(view_before(record, i, bot), own[i]) for i in range(k)]
    assert [turn.observation.ply for turn in agent.turns] == [turn.ply for turn in record.bot_turns]
    shown = len(record.plies) - (1 if session.over else 0)  # the view that ends the game is not shown, as in play_game
    assert tracker.updates == [(record.start_observations[bot], None)] + \
        [(record.plies[i].observations[bot], own[i]) for i in range(shown)]


# Catches: anything in a game left to chance outside the seed (an unseeded draw, set or dict order), so that a game
# chosen for the demo could not be played again. Only the bot's timing may differ.
def test_same_seed_and_moves_give_the_same_game():
    def game():
        session = session_for(seed=4)
        play_randomly(session, 4, 6)
        record = session.record_json()
        for turn in record["bot_turns"]:
            del turn["explanation"]["elapsed_ms"]
        return record

    first = game()
    assert len(first["plies"]) >= 6 and first == game()


# Catches: "random" kept in the record (view_state and from_json need the colour), a colour not drawn from the seed,
# or a draw that always gives the same colour.
def test_random_colour_is_drawn_from_the_seed():
    drawn = set()
    for seed in range(6):
        options = GameOptions(human="random", seed=seed, particles=8, guesses=2)
        session = Session(options, StandinRules(), Spy(), Spy())
        colour = random.Random(seed).choice(COLOURS)
        assert session.human == colour and session.record.options == {**dataclasses.asdict(options), "human": colour}
        assert len(session.record.plies) == (1 if colour == "black" else 0)  # the bot opens when the human is Black
        drawn.add(colour)
    assert drawn == set(COLOURS)


# Ruling R3. Catches: scorers left open after the game, closed twice (a second quit of a Stockfish engine raises),
# kept open when the session cannot start, kept open by a scorer that fails to close, and moves taken by a session
# whose scorers are closed.
def test_scorers_close_once():
    scorer, inspector = Spy(), Spy()
    session = session_for(start_fen=KING_CAPTURE, scorer=scorer, inspector=inspector)
    assert (scorer.closes, inspector.closes) == (0, 0)
    session.human_move("e2e8")
    session.close()
    session.close()
    assert (scorer.closes, inspector.closes) == (1, 1)

    class Dead(Spy):
        def close(self):
            super().close()
            raise RuntimeError("engine event loop dead")

    scorer, inspector = Dead(), Spy()
    session = session_for(scorer=scorer, inspector=inspector)
    session.close()  # never raises, and the inspector is still closed
    session.close()
    assert (scorer.closes, inspector.closes) == (1, 1)
    with pytest.raises(ValueError, match="closed"):
        session.human_move("e2e4")
    assert session.record.plies == []

    scorer, inspector = Spy(), Spy()
    with pytest.raises(ValueError):
        session_for(start_fen="4k3/8/8/8/8/8/8/3KK3 w - - 0 1", scorer=scorer, inspector=inspector)  # two White kings
    assert (scorer.closes, inspector.closes) == (1, 1)


# Ruling R9. Catches: a state(), record_json(), revealed or close() that does not wait for a bot turn in progress,
# which could read a board while python-chess's repetition check is replaying it, or close the engines under the bot.
def test_every_access_waits_for_the_bot_turn(register):
    thinking, go_on = threading.Event(), threading.Event()

    class Slow(RandomAgent):
        def act(self, turn):
            thinking.set()
            go_on.wait(10)
            return super().act(turn)

    scorer, inspector = Spy(), Spy()
    session = session_for(bot=register("slow", Slow), scorer=scorer, inspector=inspector)
    seen = {}
    mover = threading.Thread(target=session.human_move, args=("e2e4",))
    waiting = [threading.Thread(target=lambda: seen.update(state=session.state())),
               threading.Thread(target=lambda: seen.update(record=session.record_json())),
               threading.Thread(target=lambda: seen.update(revealed=session.revealed)),
               threading.Thread(target=session.close)]
    mover.start()
    assert thinking.wait(10)
    for thread in waiting:
        thread.start()
    for thread in waiting:
        thread.join(0.3)
    try:
        assert all(thread.is_alive() for thread in waiting) and scorer.closes == 0
    finally:
        go_on.set()
        for thread in (mover, *waiting):
            thread.join(10)
    assert seen["state"]["ply"] == 2 and len(seen["record"]["plies"]) == 2 and seen["revealed"] is True
    assert (scorer.closes, inspector.closes) == (1, 1)


# Ruling R9, from the other side. Catches: a state() that holds the lock only while it asks `revealed` (which takes
# the lock itself) and lets go of it before it reads the record, so that a move could change the record half-way
# through the view.
def test_state_keeps_the_lock_while_it_reads_the_record(monkeypatch):
    reading, go_on = threading.Event(), threading.Event()

    def slow_view_state(*args, **kwargs):
        reading.set()
        go_on.wait(10)
        return view_state(*args, **kwargs)

    monkeypatch.setattr("pairb.lab.session.view_state", slow_view_state)
    session = session_for()
    seen = {}
    reader = threading.Thread(target=lambda: seen.update(state=session.state()))
    mover = threading.Thread(target=session.human_move, args=("e2e4",))
    reader.start()
    assert reading.wait(10)
    mover.start()
    mover.join(0.3)
    try:
        assert mover.is_alive()  # the move waits until the view has been read
    finally:
        go_on.set()
        for thread in (reader, mover):
            thread.join(10)
    assert seen["state"]["ply"] == 0 and len(session.record.plies) == 2


# Catches: an option out of range or of the wrong kind (from the page's JSON) getting past GameOptions, or refused
# with a message that does not name the field.
@pytest.mark.parametrize("field, value", [
    ("guesses", 0), ("guesses", 33), ("particles", 0), ("particles", 5000), ("seed", -1), ("scorer", "x"),
    ("human", "red"), ("bot", "x"), ("guesses", True), ("guesses", 4.0), ("particles", "32"), ("seed", None),
    ("fair", "yes"), ("fair", 1), ("start_fen", 7), ("start_fen", "not a fen"), ("bot", ["pairb-one-ply"]),
    ("human", None), ("scorer", ["material"]),
])
def test_options_validation(field, value):
    with pytest.raises(ValueError, match=field):
        GameOptions(**{field: value})


# Catches: defaults other than the spec's (256 particles, 8 guesses; Ruling R2), refused edge values, and a default
# bot entry that does not build Pair B's bot and tracker from the options.
def test_options_defaults_and_the_default_bot():
    assert GameOptions() == GameOptions("white", "material", "pairb-one-ply", 8, 256, 0, False, None)
    for edge in [{"guesses": 1}, {"guesses": 32}, {"particles": 1}, {"particles": 4096}, {"seed": 0},
                 {"human": "random"}, {"human": "black"}, {"fair": True}, {"start_fen": PROMOTION},
                 *({"scorer": scorer_id} for scorer_id in SCORER_IDS)]:
        GameOptions(**edge)
    spec = BOTS["pairb-one-ply"]
    assert (spec.label, spec.make_agent) == ("Pair B one-ply belief bot", OnePlyBot)
    tracker = spec.make_tracker(StandinRules(), GameOptions(particles=16, guesses=3, start_fen=PROMOTION))
    assert isinstance(tracker, ParticleTracker)
    assert (tracker.n_particles, tracker.n_hypotheses, tracker.initial_fen) == (16, 3, PROMOTION)
