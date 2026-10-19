"""The one-ply belief bot, Fog Lab's opponent: it asks its scorer for the value of every legal move on
each guess in its belief, plays the move with the highest weighted average, and keeps an explanation
of exactly those numbers, which the page draws from.

Most tests use a table scorer, so every number in an explanation can be checked by hand. The
two-worlds test (required test 1) plays real games through fow_shared's play_game with the real
tracker, and compares the bot in two worlds that Black cannot tell apart.
"""
import dataclasses
import json
import math
import random
import zlib

import chess
import numpy as np
import pytest

from fow_shared.contracts import AgentInput, Belief, Decision, Hypothesis, Observation
from fow_shared.evaluation import MatchConfig, play_game
from fow_shared.values import fog_legal_moves
from pairb.bot import Explanation, OnePlyBot
from pairb.material import MaterialEvaluator
from pairb.observe import observe
from pairb.rules import GameReferee, StandinRules
from pairb.tracker import ParticleTracker

G1 = chess.STARTING_FEN
G2 = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 2"   # distinct FEN, same moves
BLACK_TO_MOVE = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1"  # Black's moves, not White's
# Eight FENs that differ only in the move number, so all of them have the same 20 legal moves.
FENS = [f"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 {n}" for n in range(1, 9)]
LEGAL = observe(chess.Board(), "white").legal_moves  # White's 20 opening moves, sorted
JSON_KEYS = ["scorer", "guesses", "weights", "values", "averages", "min", "max", "chosen", "elapsed_ms"]


class TableScorer:
    """A scorer that answers from {fen: {move: value}} and remembers what it was asked."""
    name = "table"

    def __init__(self, table):
        self.table, self.calls = table, []

    def evaluate_children(self, fen):
        self.calls.append(fen)
        return dict(self.table[fen])


def uniform(value):
    """The same value for every legal move."""
    return {move: value for move in LEGAL}


def turn(hyps):
    """AgentInput for White at the start position, with the given guesses: (fen, weight) or
    (fen, weight, history_id)."""
    obs = observe(chess.Board(), "white", ply=0)
    return AgentInput(obs, Belief("white", 0, tuple(Hypothesis(*h) for h in hyps)), 1000)


def bot_for(table, seed=0):
    """A bot over a table scorer, reset for a game as White; returns (bot, scorer)."""
    scorer = TableScorer(table)
    bot = OnePlyBot(scorer)
    bot.reset("white", seed)
    return bot, scorer


# Catches: an unweighted mean (e2e4 would win, 0.55 against 0.30), the single best guess or the
# highest value on any guess (e2e4 again), or a weighted average that is not the sum of weight x value.
def test_plays_highest_weighted_average():
    table = {G1: {**uniform(0.0), "e2e4": 0.2, "d2d4": 0.5}, G2: {**uniform(0.0), "e2e4": 0.9, "d2d4": 0.1}}
    bot, _ = bot_for(table)
    d = bot.act(turn([(G1, 0.75), (G2, 0.25)]))
    assert d.move == "d2d4"
    assert bot.last_explanation.averages["d2d4"] == pytest.approx(0.4)
    assert bot.last_explanation.averages["e2e4"] == pytest.approx(0.375)


# Catches: ties broken by the unseeded global random (two runs differ), by dict order or the first
# move (every seed agrees), by anything but the seed, or by a draw other than rng.choice(sorted(ties)).
def test_ties_broken_by_seed_only():
    def move_for(seed):
        bot, _ = bot_for({G1: uniform(0.0)}, seed)
        return bot.act(turn([(G1, 1.0)])).move

    moves = [move_for(seed) for seed in range(20)]
    assert moves == [move_for(seed) for seed in range(20)]  # the same seed, the same move
    assert moves == [random.Random(seed).choice(sorted(LEGAL)) for seed in range(20)]  # the documented draw
    assert len(set(moves)) >= 2  # and the seed does decide


# Catches: a draw that depends on the order in which the rules list the moves (another rules adapter may
# list them differently), so that the same position and seed would give different games.
def test_tie_break_ignores_the_order_the_moves_are_listed_in():
    t = turn([(G1, 1.0)])
    backwards = dataclasses.replace(t, observation=dataclasses.replace(t.observation,
                                                                       legal_moves=LEGAL[::-1]))
    for seed in range(10):
        forward_bot, _ = bot_for({G1: uniform(0.0)}, seed)
        backward_bot, _ = bot_for({G1: uniform(0.0)}, seed)
        assert backward_bot.act(backwards).move == forward_bot.act(t).move == random.Random(seed).choice(sorted(LEGAL))


# Catches: an exact comparison, under which a gap of 5e-13 would pick one move for good, and a
# tolerance so wide that it calls a real difference (1e-9, or 2.5e-12 here) a tie.
def test_ties_are_equal_within_1e_12():
    near = {**uniform(-0.5), "e2e4": 0.3, "d2d4": 0.3 + 5e-13, "c2c4": 0.3 - 2e-12}  # c2c4 is behind
    clear = {**uniform(-0.5), "e2e4": 0.3, "d2d4": 0.3 + 1e-9}                         # d2d4 is ahead

    def chosen_over_seeds(row):
        return {bot_for({G1: row}, seed)[0].act(turn([(G1, 1.0)])).move for seed in range(20)}

    assert chosen_over_seeds(near) == {"e2e4", "d2d4"}
    assert chosen_over_seeds(clear) == {"d2d4"}


# Catches: a decision that is not valid for the observation, a policy that is not one-hot on the move
# chosen, and diagnostics that are not plain floats, that miscount or that time something else than
# the explanation does.
def test_decision_valid_and_one_hot():
    table = {G1: {**uniform(0.0), "e2e4": 0.2}, G2: {**uniform(0.0), "e2e4": 0.4}}
    bot, _ = bot_for(table)
    t = turn([(G1, 0.5), (G2, 0.5)])
    d = bot.act(t)
    d.validate_for(t.observation)
    assert bot.name == "pairb-one-ply" and d.move == "e2e4"
    assert set(d.root_policy) == set(t.observation.legal_moves)
    assert d.root_policy[d.move] == 1.0 and sum(d.root_policy.values()) == 1.0
    assert sorted(d.root_policy.values()) == [0.0] * 19 + [1.0]
    assert d.diagnostics == {"guesses": 2.0, "scorer_calls": 2.0, "elapsed_ms": bot.last_explanation.elapsed_ms,
                             "search_nodes": 2.0}
    assert all(type(value) is float for value in d.diagnostics.values())
    assert d.diagnostics["elapsed_ms"] >= 0.0


# Catches (required test 3, panel equals decision): a move played that is not the highest average in the
# explanation, a second scorer call that makes the explanation say something else, averages that are not
# the weighted means of the values shown, and values that are not the scorer's own answers in belief order.
# 25 random tables with 1 to 8 guesses, checked against a sum worked out here from the table.
@pytest.mark.parametrize("seed", range(25))
def test_explanation_is_what_it_chose_by(seed):
    rng = random.Random(seed)
    fens = FENS[:rng.randint(1, 8)]
    raw = [rng.uniform(0.1, 1.0) for _ in fens]
    weights = [x / sum(raw) for x in raw]
    table = {fen: {move: round(rng.uniform(-1, 1), 3) for move in LEGAL} for fen in fens}
    bot, scorer = bot_for(table, seed)
    d = bot.act(turn(list(zip(fens, weights))))
    e = bot.last_explanation

    assert (e.scorer, e.guesses, e.weights) == ("table", tuple(fens), tuple(weights))
    assert list(e.values) == list(e.averages) == list(LEGAL)
    worked = {move: sum(w * table[fen][move] for fen, w in zip(fens, weights)) for move in LEGAL}
    for move in LEGAL:
        assert e.values[move] == tuple(table[fen][move] for fen in fens)
        assert e.averages[move] == pytest.approx(worked[move], abs=1e-12)
    assert e.chosen == d.move
    assert e.averages[e.chosen] >= max(e.averages.values()) - 1e-12  # the highest average the panel shows
    assert worked[d.move] >= max(worked.values()) - 1e-12            # and the highest there is
    assert len(scorer.calls) == len(fens)


# Catches: keys or their order changed, tuples where the page (and a saved record) needs lists, min and
# max over the wrong axis, a to_json that hands out the explanation's own containers, and an
# explanation that can be changed after the fact.
def test_explanation_json():
    table = {G1: {**uniform(0.0), "e2e4": 0.2, "d2d4": 0.5}, G2: {**uniform(0.0), "e2e4": 0.9, "d2d4": 0.1}}
    bot, _ = bot_for(table)
    bot.act(turn([(G1, 0.75), (G2, 0.25)]))
    e = bot.last_explanation
    j = e.to_json()
    assert isinstance(e, Explanation) and list(j) == JSON_KEYS
    assert (j["scorer"], j["guesses"], j["weights"], j["chosen"]) == ("table", [G1, G2], [0.75, 0.25], "d2d4")
    assert list(j["values"]) == list(LEGAL) and j["values"]["e2e4"] == [0.2, 0.9] and j["values"]["a2a3"] == [0.0, 0.0]
    assert j["averages"]["d2d4"] == pytest.approx(0.4) and j["averages"]["e2e4"] == pytest.approx(0.375)
    assert (j["min"]["e2e4"], j["max"]["e2e4"], j["min"]["d2d4"], j["max"]["d2d4"]) == (0.2, 0.9, 0.1, 0.5)
    assert set(j["min"]) == set(j["max"]) == set(LEGAL)
    assert j["elapsed_ms"] == e.elapsed_ms and e.elapsed_ms >= 0.0
    snapshot = json.loads(json.dumps(j, allow_nan=False))
    assert snapshot == j  # plain JSON: it survives a round trip unchanged
    j["values"]["d2d4"].append(9.0)  # a caller editing what it was given...
    j["averages"]["d2d4"] = -5.0
    j["guesses"].clear()
    assert e.to_json() == snapshot  # ...does not edit the explanation
    assert e.values["d2d4"] == (0.5, 0.1) and e.averages["d2d4"] == pytest.approx(0.4) and len(e.guesses) == 2
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.chosen = "a2a3"


# Catches: a guess that does not have the observation's legal moves being averaged in anyway, whether it
# lacks a move (a stale guess) or has one more (a wrong guess); a message without the guess number; a
# failed turn leaving the previous turn's explanation behind for the panel to show.
@pytest.mark.parametrize("change", ["missing", "extra"])
def test_rejects_guess_with_other_legal_moves(change):
    other = {m: 0.0 for m in LEGAL if m != "e2e4"} if change == "missing" else {**uniform(0.0), "e2e5": 0.0}
    bot, _ = bot_for({G1: uniform(0.0), G2: other})
    bot.act(turn([(G1, 1.0)]))  # a good turn first
    assert bot.last_explanation is not None
    with pytest.raises(ValueError, match="guess 1 has different legal moves from the observation"):
        bot.act(turn([(G1, 0.5), (G2, 0.5)]))
    assert bot.last_explanation is None


# Catches: a guess with the other side to move (Black's moves on White's turn) slipping through to a real
# scorer, which answers with the moves of its own board.
def test_rejects_a_guess_with_the_wrong_side_to_move():
    bot = OnePlyBot(MaterialEvaluator())
    bot.reset("white", 0)
    with pytest.raises(ValueError, match="guess 1 has different legal moves"):
        bot.act(turn([(G1, 0.5), (BLACK_TO_MOVE, 0.5)]))


# Catches: a scorer's NaN or infinity reaching the average, where a comparison with NaN cannot rank
# moves, and a saved record that is not valid JSON.
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_rejects_values_that_are_not_finite(bad):
    bot, _ = bot_for({G1: uniform(0.0), G2: {**uniform(0.0), "e2e4": bad}})
    with pytest.raises(ValueError, match="guess 1 .*finite"):
        bot.act(turn([(G1, 0.5), (G2, 0.5)]))
    assert bot.last_explanation is None


# Catches: a turn without legal moves failing inside max() with a message about empty sequences.
def test_a_turn_without_legal_moves_is_refused():
    obs = Observation(player="white", side_to_move="white", ply=0, visible_squares=(), visible_pieces={},
                      legal_moves=())
    bot, scorer = bot_for({G1: uniform(0.0)})
    with pytest.raises(ValueError, match="no legal move"):
        bot.act(AgentInput(obs, Belief("white", 0, (Hypothesis(G1, 1.0),)), 1000))
    assert scorer.calls == []


# Catches: the scorer asked twice per guess (once to decide, once to explain, and the two could differ), a
# guess skipped, or the guesses asked in another order than the belief's.
def test_one_scorer_call_per_guess():
    bot, scorer = bot_for({G1: uniform(0.0), G2: uniform(0.0)})
    bot.act(turn([(G1, 0.5), (G2, 0.5)]))
    assert scorer.calls == [G1, G2]


# Catches: a board scored once because it appears twice. The tracker gives hypotheses that share a FEN
# distinct history_ids, and each of them is a guess with a weight of its own.
def test_a_repeated_board_is_a_guess_for_each_history():
    table = {G1: {**uniform(0.0), "e2e4": 0.6, "d2d4": 0.2}, G2: {**uniform(0.0), "e2e4": 0.0, "d2d4": 0.5}}
    bot, scorer = bot_for(table)
    d = bot.act(turn([(G1, 0.25, "h1"), (G1, 0.25, "h2"), (G2, 0.5)]))
    e = bot.last_explanation
    assert scorer.calls == [G1, G1, G2]
    assert e.guesses == (G1, G1, G2) and e.weights == (0.25, 0.25, 0.5)
    assert e.values["e2e4"] == (0.6, 0.6, 0.0) and e.averages["e2e4"] == pytest.approx(0.3)
    assert e.averages["d2d4"] == pytest.approx(0.35) and d.move == "d2d4"


# Catches: numpy floats or integers from a scorer being kept as they are (float32 would round the
# average, and none of them can be written as JSON), and an explanation that is not JSON-clean.
def test_values_become_plain_floats():
    class Mixed:
        name = "mixed"

        def evaluate_children(self, fen):
            return {m: 1 if m == "a2a3" else np.float64(0.5) if m == "a2a4" else np.float32(0.25) for m in LEGAL}

    bot = OnePlyBot(Mixed())
    bot.reset("white", 0)
    d = bot.act(turn([(G1, 0.5), (G2, 0.5)]))
    e = bot.last_explanation
    assert all(type(v) is float for vs in e.values.values() for v in vs)
    assert all(type(a) is float for a in e.averages.values()) and type(e.elapsed_ms) is float
    assert d.move == "a2a3" and e.averages["a2a3"] == 1.0 and e.averages["a2a4"] == 0.5 and e.averages["b2b3"] == 0.25
    json.dumps(e.to_json(), allow_nan=False)


# Catches: reset not re-seeding (a second game on the same bot would carry on the first game's draws),
# not clearing the last game's explanation, or the seed being ignored.
def test_reset_starts_a_new_game():
    bot, _ = bot_for({G1: uniform(0.0)}, 7)
    t = turn([(G1, 1.0)])
    first = [bot.act(t).move for _ in range(5)]
    assert bot.last_explanation is not None
    bot.reset("white", 7)
    assert bot.last_explanation is None
    assert [bot.act(t).move for _ in range(5)] == first
    bot.reset("white", 8)
    assert [bot.act(t).move for _ in range(5)] != first


# Catches: a bot that picks a seed for itself when nobody reset it, which hides a game started wrongly.
def test_act_before_reset_is_refused():
    with pytest.raises(RuntimeError, match="reset"):
        OnePlyBot(TableScorer({G1: uniform(0.0)})).act(turn([(G1, 1.0)]))


# ---- Required test 1: two worlds ----
# FEN_A and FEN_B differ only in White's rook, on a1 or on b1. Black has a king and a pawn in the far corner
# (h8, h7), and White a pawn on g6 that Black's pawn can take, so that Black's first decision is not a tie.
# White's king walks up the board, six moves that are legal in both worlds. For Black to see the rook it would
# need five or six of its six moves in a row (the king down the long diagonal to the rook's corner, or a pawn
# running to promote on the first rank), and the games here do not. So Black is shown the same thing in both
# worlds; the test checks that first, and says so if it ever stops being true.
FEN_A = "7k/7p/6P1/8/8/8/8/R3K3 w - - 0 1"
FEN_B = "7k/7p/6P1/8/8/8/8/1R2K3 w - - 0 1"
WHITE_MOVES = ["e1d2", "d2d3", "d3c4", "c4c5", "c5b6", "b6a7"]


class Scripted:
    """White in the two worlds: plays its moves in order, whatever it is shown."""
    name = "scripted"

    def __init__(self, moves):
        self.moves, self.played = list(moves), 0

    def reset(self, player, seed):
        self.played = 0

    def act(self, turn):
        move = self.moves[self.played]
        self.played += 1
        return Decision(move, {m: float(m == move) for m in turn.observation.legal_moves})  # play_game checks it


class Recording:
    """An agent that keeps, for each of its turns, what it was given and what it answered with: the
    observation, the belief, the explanation without its timing, and the move."""

    def __init__(self, agent):
        self.agent, self.name, self.turns = agent, agent.name, []

    def reset(self, player, seed):
        self.agent.reset(player, seed)
        self.turns = []

    def act(self, turn):
        decision = self.agent.act(turn)
        explanation = {k: v for k, v in self.agent.last_explanation.to_json().items() if k != "elapsed_ms"}
        self.turns.append((turn.observation, turn.belief, explanation, decision.move))
        return decision


class RecordingTracker:
    """A tracker that keeps every observation and own move it is given, and every belief it answers with."""

    def __init__(self, tracker):
        self.tracker, self.log = tracker, []

    def reset(self, player, seed):
        self.tracker.reset(player, seed)
        self.log = []

    def update(self, observation, own_move=None):
        belief = self.tracker.update(observation, own_move)
        self.log.append((observation, own_move, belief))
        return belief


class HashScorer:
    """A scorer whose values depend on the position and the move in an arbitrary way, so that every guess
    has numbers of its own and almost no moves tie (Material's differ between guesses only where a king
    can be taken, and its quiet moves tie)."""
    name = "hash"

    def evaluate_children(self, fen):
        return {move.uci(): (zlib.crc32(f"{fen} {move.uci()}".encode()) % 2001 - 1000) / 1000
                for move in fog_legal_moves(chess.Board(fen))}


def play_world(true_fen, scorer, seed):
    """12 plies in the world that really starts at true_fen. White's tracker starts from that world's own
    position; Black's from FEN_A, the public start that Black believes, in both worlds."""
    rules = StandinRules()
    referee = GameReferee(rules, true_fen)
    black_agent = Recording(OnePlyBot(scorer))
    black_tracker = RecordingTracker(ParticleTracker(rules, n_particles=64, initial_fen=FEN_A))
    result = play_game(referee, {"white": Scripted(WHITE_MOVES), "black": black_agent},
                       {"white": ParticleTracker(rules, initial_fen=true_fen), "black": black_tracker},
                       MatchConfig(time_budget_ms=1000, max_plies=12, seed=seed, rules_id=rules.name,
                                   engine_id=scorer.name, leaf_depth=0))
    return result, referee.true_board().fen(), black_agent.turns, black_tracker.log


# Catches: a bot, or a tracker feeding it, that uses anything but the observations and moves it was given
# (the true board, the clock, White's hidden rook, global state or an unseeded random): the same views then
# have to give the same beliefs, explanations and moves, to the last number.
@pytest.mark.parametrize("scorer", [MaterialEvaluator(), HashScorer()], ids=lambda s: s.name)
@pytest.mark.parametrize("seed", [3, 4, 5])
def test_two_worlds_same_observations_same_bot(scorer, seed):
    result_a, truth_a, turns_a, black_a = play_world(FEN_A, scorer, seed)
    result_b, truth_b, turns_b, black_b = play_world(FEN_B, scorer, seed)

    assert truth_a != truth_b  # the worlds really differ (the rook), and both games ran to the limit
    for result in (result_a, result_b):
        assert len(result.plies) == 12 and result.stopped_at_ply_limit
    assert len(turns_a) == len(turns_b) == 6
    # the precondition: Black was shown the same thing at every ply, and made the same moves
    seen_a, seen_b = [(o, m) for o, m, _ in black_a], [(o, m) for o, m, _ in black_b]
    apart = next((i for i, (x, y) in enumerate(zip(seen_a, seen_b)) if x != y), None)
    assert apart is None, f"Black could tell the worlds apart at ply {apart}: the games drifted into the rook's view"
    # and so its tracker made the same beliefs, and the bot the same explanations, decisions and moves
    assert [belief for _, _, belief in black_a] == [belief for _, _, belief in black_b]
    assert turns_a == turns_b
    assert [(p.player, p.move) for p in result_a.plies] == [(p.player, p.move) for p in result_b.plies]
    for _, belief, explanation, move in turns_a:  # and these were real decisions, made on real guesses
        assert explanation["guesses"] == [h.fen for h in belief.hypotheses] and explanation["chosen"] == move
