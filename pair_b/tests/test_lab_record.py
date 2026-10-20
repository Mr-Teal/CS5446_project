"""Game records (Fog Lab): everything one game produces, saved as JSON and loaded back, and the dictionary the
page draws from a record, in live play and when stepping through a saved game.

The records are built by hand from real StandinRules positions: a scripted game is played through the
referee, and the true FEN and both players' observations are taken after every move. Every expected value
is a literal, or is worked out from those positions here, never produced by pairb.lab.record.
"""
import copy
import dataclasses
import json
import re
from types import MappingProxyType

import pytest

from fow_shared.values import standard_fen
from pairb.bot import Explanation
from pairb.lab.record import HIDDEN_KEYS, BotTurn, GameRecord, PlyRecord, observation_json, view_state
from pairb.rules import GameReferee, StandinRules

COLOURS = ("white", "black")
MOVES = ["e2e4", "e7e5", "g1f3"]  # White, Black, White
KING_CAPTURE = "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1"  # Re2xe8 takes the king
FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"  # a true position, which no message may hold
SPOILED = "SPOILED-BY-THE-TEST"
NINE_KEYS = {"player", "side_to_move", "ply", "visible_squares", "visible_pieces", "legal_moves",
             "captured_own_piece_at", "terminal", "outcome"}

# Worked out by hand for MOVES. After k moves, by the human's colour: White played moves 0 and 2, Black move 1.
TO_MOVE = ["white", "black", "white", "black"]
YOUR_MOVES = {"white": [[], ["e2e4"], ["e2e4"], ["e2e4", "g1f3"]], "black": [[], [], ["e7e5"], ["e7e5"]]}
MOVE_LIST = [{"ply": 0, "player": "white", "move": "e2e4"}, {"ply": 1, "player": "black", "move": "e7e5"},
             {"ply": 2, "player": "white", "move": "g1f3"}]
# The ply of the bot turn that a view after k moves shows: the bot's latest move so far. The bot is Black (it
# moved at ply 1) when the human is White, and White (plies 0 and 2) when the human is Black.
BOT_TURN_SHOWN = {"white": [None, None, 1, 1], "black": [None, 0, 0, 2]}


def other(colour):
    return "black" if colour == "white" else "white"


def play(moves, fen=None):
    """A scripted game as the stand-in referee holds it. Returns (positions, movers): positions[k] is the true
    FEN and both players' Observations after k moves, and movers[k] is who played move k."""
    referee = GameReferee(StandinRules(), fen)
    positions = [(standard_fen(referee.true_board()), {c: referee.observe(c) for c in COLOURS})]
    movers = []
    for move in moves:
        movers.append(referee.current_player())
        referee.apply(move)
        positions.append((standard_fen(referee.true_board()), {c: referee.observe(c) for c in COLOURS}))
    return positions, movers


POSITIONS, _ = play(MOVES)


def both(views):
    return {c: observation_json(views[c]) for c in COLOURS}


def next_move_number(fen):
    """The same position with the next move number: another FEN, with the same legal moves."""
    placement, number = fen.rsplit(" ", 1)
    return f"{placement} {int(number) + 1}"


def bot_turn(k, positions, move, bot):
    """The turn of the bot (the colour `bot`) after k moves, as a session would record it: it guessed the true
    position and a twin of it, and played `move`. The explanation is a real Explanation.to_json()."""
    fen = positions[k][0]
    guesses = (fen, next_move_number(fen))
    rival = next(m for m in positions[k][1][bot].legal_moves if m != move)
    explanation = Explanation("material", guesses, (0.75, 0.25), {move: (0.5, 0.25), rival: (-0.5, 0.0)},
                              {move: 0.4375, rival: -0.375}, move, 12.5)
    inspection = {"true_values": {move: 0.5, rival: -0.5}, "best_on_true_board": move, "lost_by_not_knowing": 0.0,
                  "particles": list(guesses), "truth_in_particles": True, "rebuilt": False, "capped": False}
    return BotTurn(ply=k, belief=[{"fen": guesses[0], "weight": 0.75}, {"fen": guesses[1], "weight": 0.25}],
                   population_size=12, explanation=explanation.to_json(), inspection=inspection)


def make_record(human="white", moves=MOVES, fen=None, fair=False):
    """The scripted game as a session would have recorded it, not finished (result None)."""
    positions, movers = play(moves, fen)
    plies = [PlyRecord(ply=k, player=movers[k], move=moves[k], true_fen=positions[k + 1][0],
                       observations=both(positions[k + 1][1])) for k in range(len(moves))]
    turns = [bot_turn(k, positions, moves[k], other(human)) for k in range(len(moves)) if movers[k] != human]
    options = {"human": human, "scorer": "material", "bot": "pairb-one-ply", "guesses": 2, "particles": 16,
               "seed": 7, "fair": fair, "start_fen": fen}
    return GameRecord(options=options, rules="pairb-standin", scorer="material", bot="pairb-one-ply",
                      start_fen=positions[0][0], start_observations=both(positions[0][1]), plies=plies,
                      bot_turns=turns, result=None)


def finished_record():
    record = make_record("white", ["e2e8"], KING_CAPTURE)
    record.result = {"winner": "white", "reason": "king_capture"}
    return record


def app_inspected_record():
    """The bot's first turn comes from an agent with no explanation of its own, and no known population."""
    record = make_record("black")
    explanation = {"policy": {"e2e4": 1.0, "d2d4": 0.0}, "values": {"e2e4": [0.5], "d2d4": [0.25]},
                   "averages": {"e2e4": 0.5, "d2d4": 0.25}, "app_inspection": True}
    record.bot_turns[0] = dataclasses.replace(record.bot_turns[0], population_size=None, explanation=explanation)
    return record


def tracker_failed_record():
    """A finished game whose bot's tracker failed on the view that ended it: the result stands."""
    record = finished_record()
    record.tracker_error = "the bot's tracker failed on the view that ended the game: TrackerLost: no position fits"
    return record


def failed_record():
    """The bot raised on its turn at ply 4: its turn is in the record, with the error, and no move follows."""
    record = make_record("black", MOVES + ["b8c6"])
    record.bot_turns.append(BotTurn(ply=4, belief=[], population_size=None, explanation={}, inspection={},
                                    error="the bot stopped"))
    return record


KINDS = {"plain, human White": lambda: make_record("white"), "plain, human Black": lambda: make_record("black"),
         "finished": finished_record, "tracker failed at the end": tracker_failed_record,
         "no explanation from the agent": app_inspected_record,
         "bot error": failed_record, "new game": lambda: make_record("white", [])}


@pytest.fixture(params=COLOURS)
def rec(request):
    """The three-move game, once with the human as White and once as Black."""
    return make_record(request.param)


@pytest.fixture(params=KINDS)
def kind(request):
    """Every kind of record a session can produce."""
    return KINDS[request.param]()


# Catches: a hidden view that quietly grows. A key added to HIDDEN_KEYS is a field a player is not entitled to
# in a fair game; the keys are the contract, so they are written out here as agreed.
def test_hidden_keys_are_what_a_player_may_know():
    assert HIDDEN_KEYS == ("fair", "human", "over", "ply", "result", "to_move", "you", "your_moves")


# Catches: a missing, renamed or extra key (halfmove_clock and schema_version stay out), tuples where JSON has
# lists (a record loaded back would differ from the one saved), and a view other than the one observed.
def test_observation_json_has_the_page_fields():
    view = observation_json(POSITIONS[0][1]["white"])
    squares = sorted(f + r for f in "abcdefgh" for r in "1234")  # White sees its ranks and where its pawns can go
    assert set(view) == NINE_KEYS
    assert (view["player"], view["side_to_move"], view["ply"]) == ("white", "white", 0)
    assert view["visible_squares"] == squares
    assert set(view["visible_pieces"]) == set(squares)
    pieces = view["visible_pieces"]
    assert (pieces["e1"], pieces["a2"], pieces["e4"]) == ("K", "P", None)
    assert len(view["legal_moves"]) == 20 and "e2e4" in view["legal_moves"]
    assert (view["captured_own_piece_at"], view["terminal"], view["outcome"]) == (None, False, None)
    assert type(view["visible_squares"]) is list and type(view["legal_moves"]) is list
    assert json.loads(json.dumps(view)) == view


# Catches: a finished game's terminal flag and outcome dropped or taken from the wrong player, and a captured
# own piece lost (the stand-in rules never fill that field, so one is set by hand).
def test_observation_json_carries_game_over_and_captures():
    positions, _ = play(["e2e8"], KING_CAPTURE)
    won, lost = (observation_json(positions[1][1][c]) for c in COLOURS)
    assert (won["player"], won["terminal"], won["outcome"]) == ("white", True, 1.0)
    assert (lost["player"], lost["terminal"], lost["outcome"], lost["legal_moves"]) == ("black", True, -1.0, [])
    assert (won["side_to_move"], won["ply"], lost["side_to_move"], lost["ply"]) == ("black", 1, "black", 1)
    assert lost["visible_squares"] == [] and lost["visible_pieces"] == {}  # Black has no pieces left to see with
    taken = dataclasses.replace(positions[1][1]["black"], captured_own_piece_at="e4")
    assert observation_json(taken)["captured_own_piece_at"] == "e4"


# Catches: a mapping that is not a dict left as it is (the contract only promises a Mapping, and json.dumps fails
# on one that is not a dict), so that the page could not be sent the view.
def test_observation_json_turns_any_mapping_into_a_dict():
    observation = POSITIONS[0][1]["white"]
    frozen = dataclasses.replace(observation, visible_pieces=MappingProxyType(dict(observation.visible_pieces)))
    view = observation_json(frozen)
    assert type(view["visible_pieces"]) is dict
    assert view == observation_json(observation)
    json.dumps(view)


# Catches: fields in another order than the agreed one (anything that builds a record by position would swap
# values without an error), and defaults that differ: a version 1 record, a turn with no error.
def test_records_have_the_agreed_fields_in_the_agreed_order():
    def fields(cls):
        return [(f.name, f.default) for f in dataclasses.fields(cls)]

    missing = dataclasses.MISSING
    assert fields(PlyRecord) == [("ply", missing), ("player", missing), ("move", missing), ("true_fen", missing),
                                 ("observations", missing)]
    assert fields(BotTurn) == [("ply", missing), ("belief", missing), ("population_size", missing),
                               ("explanation", missing), ("inspection", missing), ("error", None)]
    assert fields(GameRecord) == [("options", missing), ("rules", missing), ("scorer", missing), ("bot", missing),
                                  ("start_fen", missing), ("start_observations", missing), ("plies", missing),
                                  ("bot_turns", missing), ("result", missing), ("tracker_error", None),
                                  ("version", 1)]


# Catches: a saved file whose key names drift from the agreed ones, which would orphan the games already saved.
def test_the_saved_json_has_the_agreed_keys(rec):
    data = rec.to_json()
    assert set(data) == {"version", "options", "rules", "scorer", "bot", "start_fen", "start_observations", "plies",
                         "bot_turns", "result", "tracker_error"}
    assert data["version"] == 1
    assert set(data["plies"][0]) == {"ply", "player", "move", "true_fen", "observations"}
    assert set(data["bot_turns"][0]) == {"ply", "belief", "population_size", "explanation", "inspection", "error"}
    assert set(data["plies"][0]["observations"]) == set(COLOURS)


# Catches: a field that does not survive a trip through a JSON file (a tuple for a list, a lost key, a value
# changed), for every kind of record: finished, with an agent that has no explanation, with a bot error.
def test_round_trip_json(kind):
    data = kind.to_json()
    again = GameRecord.from_json(json.loads(json.dumps(data)))
    assert again.to_json() == data
    assert again == kind


def scribble(data):
    """Empty every list and dict inside `data`, itself included: what a caller that kept using what it was given
    could do to it."""
    pending, containers = [data], []
    while pending:
        node = pending.pop()
        if isinstance(node, (dict, list)):
            containers.append(node)
            pending.extend(node.values() if isinstance(node, dict) else node)
    for node in containers:
        node.clear()


def snapshot(record):
    """The record's JSON as a copy that shares nothing with it, made by dumping and loading."""
    return json.loads(json.dumps(record.to_json()))


# Catches: a to_json that hands out one of the record's own lists or dicts, at any depth, so that whoever holds the
# JSON (a file writer, the server) could change the game.
def test_to_json_copies(kind):
    before = snapshot(kind)
    scribble(kind.to_json())
    assert kind.to_json() == before


# Catches: a from_json that keeps a list or dict of the data it was given, at any depth.
def test_from_json_copies(kind):
    before = snapshot(kind)
    data = json.loads(json.dumps(before))
    loaded = GameRecord.from_json(data)
    scribble(data)
    assert loaded.to_json() == before


# Catches: a stray key in a saved game, which from_json would otherwise keep and pass on to the page (in `you`,
# for one): the record that comes back is the record that was written.
def test_unknown_keys_are_dropped(rec):
    data = rec.to_json()
    for place in (data, data["plies"][0], data["start_observations"]["white"],
                  data["plies"][1]["observations"]["black"], data["bot_turns"][0]):
        place["notes"] = FEN
    assert GameRecord.from_json(data).to_json() == rec.to_json()


# Catches: another version read as this one, and a version that is not a whole number (True equals 1 in
# Python, and 1.0 is not what this app writes).
@pytest.mark.parametrize("version", [2, 0, -1, "1", 1.0, True, None])
def test_rejects_other_version(rec, version):
    data = rec.to_json()
    data["version"] = version
    with pytest.raises(ValueError, match="version"):
        GameRecord.from_json(data)


# Catches: a record with no version read as the current one.
def test_rejects_a_missing_version(rec):
    data = rec.to_json()
    del data["version"]
    with pytest.raises(ValueError, match="version"):
        GameRecord.from_json(data)


# Catches: a message that leaves out which version the file has or which one this app reads.
def test_the_message_for_another_version_names_both_versions(rec):
    data = rec.to_json()
    data["version"] = 2
    with pytest.raises(ValueError) as caught:
        GameRecord.from_json(data)
    assert re.search(r"\b2\b", str(caught.value)) and re.search(r"\b1\b", str(caught.value))


class _Missing:
    def __repr__(self):
        return "<missing>"


MISSING = _Missing()


def broken(data, path, value):
    """A deep copy of the JSON `data` with the node at `path` (keys and indexes) replaced by `value`, or removed
    when `value` is MISSING. An empty path replaces everything."""
    if not path:
        return copy.deepcopy(value)
    result = copy.deepcopy(data)
    parent = result
    for step in path[:-1]:
        parent = parent[step]
    if value is MISSING:
        del parent[path[-1]]
    else:
        parent[path[-1]] = copy.deepcopy(value)
    return result


# (where to break the record's JSON, what to put there or MISSING to remove it, a word the message must hold)
BAD_SHAPES = [
    ((), ["a list"], "object"),
    ((), None, "object"),
    (("options",), MISSING, "options"),
    (("options",), [], "options"),
    (("options", "human"), MISSING, "human"),
    (("options", "human"), "random", "human"),  # the colour must be the resolved one
    (("options", "fair"), "yes", "fair"),
    (("rules",), MISSING, "rules"),
    (("rules",), 5, "rules"),
    (("scorer",), None, "scorer"),
    (("bot",), MISSING, "bot"),
    (("start_fen",), 5, "start_fen"),
    (("start_observations",), MISSING, "start_observations"),
    (("start_observations",), [], "start_observations"),
    (("start_observations", "black"), MISSING, "black"),
    (("start_observations", "white", "legal_moves"), MISSING, "legal_moves"),
    (("start_observations", "white", "legal_moves"), "e2e4", "legal_moves"),
    (("start_observations", "white", "visible_squares"), [5], "visible_squares"),
    (("start_observations", "white", "visible_pieces"), ["e1"], "visible_pieces"),
    (("start_observations", "white", "visible_pieces"), {"e1": 5}, "visible_pieces"),
    (("start_observations", "white", "terminal"), "no", "terminal"),
    (("start_observations", "white", "outcome"), "win", "outcome"),
    (("start_observations", "white", "outcome"), True, "outcome"),
    (("start_observations", "white", "ply"), "0", "ply"),
    (("start_observations", "white", "side_to_move"), "red", "side_to_move"),
    (("start_observations", "white", "player"), "black", "player"),  # the other player's view, filed under White
    (("plies",), MISSING, "plies"),
    (("plies",), "none", "plies"),
    (("plies", 0), 5, "plies[0]"),
    (("plies", 1, "move"), MISSING, "move"),
    (("plies", 1, "move"), 5, "move"),
    (("plies", 1, "player"), "red", "player"),
    (("plies", 1, "true_fen"), None, "true_fen"),
    (("plies", 1, "ply"), 5, "ply"),  # plies are numbered by their place in the list
    (("plies", 2, "observations"), MISSING, "observations"),
    (("plies", 2, "observations", "white"), MISSING, "white"),
    (("bot_turns",), "none", "bot_turns"),
    (("bot_turns", 0), [], "bot_turns[0]"),
    (("bot_turns", 0, "ply"), "1", "ply"),
    (("bot_turns", 0, "belief"), MISSING, "belief"),
    (("bot_turns", 0, "belief"), [{"weight": 1.0}], "belief"),
    (("bot_turns", 0, "belief"), [{"fen": "x", "weight": "heavy"}], "belief"),
    (("bot_turns", 0, "belief"), [{"fen": "x", "weight": True}], "belief"),
    (("bot_turns", 0, "population_size"), MISSING, "population_size"),
    (("bot_turns", 0, "population_size"), "many", "population_size"),
    (("bot_turns", 0, "explanation"), [], "explanation"),
    (("bot_turns", 0, "inspection"), None, "inspection"),
    (("bot_turns", 0, "error"), 5, "error"),
    (("result",), MISSING, "result"),
    (("result",), "white", "result"),
    (("result",), {"winner": "white"}, "result"),
    (("tracker_error",), 5, "tracker_error"),
    (("tracker_error",), ["x"], "tracker_error"),
]


# Catches: a shape that is not a record getting through, an error that is not a ValueError (the server turns
# only ValueError into a 400), and a message that does not say where the fault is.
@pytest.mark.parametrize("path, value, word", BAD_SHAPES,
                         ids=[f"{'.'.join(map(str, path)) or 'root'}={value!r}" for path, value, _ in BAD_SHAPES])
def test_rejects_a_malformed_shape(path, value, word):
    data = broken(make_record("black").to_json(), path, value)
    with pytest.raises(ValueError, match=re.escape(word)):
        GameRecord.from_json(data)


# Catches (review focus 4): a value nested deeper than a copy can follow, in one of the parts that are kept as they
# are. json.loads reads 600 levels (it reads 1,000 and more), and copying them raised a RecursionError, which
# a server would not turn into a 400.
@pytest.mark.parametrize("path", [("options", "deep"), ("bot_turns", 0, "explanation", "deep"),
                                  ("bot_turns", 0, "inspection", "deep"), ("bot_turns", 0, "belief", 0, "deep")])
def test_a_value_nested_too_deeply_is_a_value_error(path):
    nest = json.loads("[" * 600 + "]" * 600)
    data = make_record("black").to_json()
    parent = data
    for step in path[:-1]:
        parent = parent[step]
    parent[path[-1]] = nest
    with pytest.raises(ValueError, match="deeply"):
        GameRecord.from_json(data)


def nodes(data, path=()):
    """Every place in a JSON value as a path of keys and indexes, the root left out."""
    if isinstance(data, dict):
        children = data.items()
    elif isinstance(data, list):
        children = enumerate(data)
    else:
        return
    for key, child in children:
        yield path + (key,)
        yield from nodes(child, path + (key,))


# Catches (review focus 4: a malformed request never gets a 500): any damage to a record, at any place in it,
# that gets past from_json as something other than a ValueError, a message that holds a position (the damage
# plants a true FEN everywhere, in three shapes), and a record that from_json accepts but the page cannot be drawn
# from, at some step, hidden or not.
def test_any_damage_is_a_value_error_without_a_position_or_a_record_that_can_be_viewed():
    record = make_record("black", MOVES[:2])
    record.result = {"winner": "draw", "reason": "no_legal_moves"}  # so that the result's own parts get damaged too
    good = record.to_json()
    places = list(nodes(good))
    planted = [MISSING, None, True, 7, -1.5, "text", [], {}, FEN, [FEN], {"fen": FEN}]
    rejected = accepted = 0
    for path in places:
        for value in planted:
            data = broken(good, path, value)
            where = f"{'.'.join(map(str, path))} <- {value!r}"
            try:
                loaded = GameRecord.from_json(data)
            except ValueError as error:
                assert FEN.split()[0] not in str(error) and "/" not in str(error), where
                rejected += 1
                continue
            except Exception as error:
                raise AssertionError(f"{where} escaped as {error!r}") from error
            accepted += 1
            try:
                for upto in range(len(loaded.plies) + 1):
                    for reveal in (False, True):
                        view_state(loaded, upto, reveal=reveal)
                json.dumps(loaded.to_json())
            except Exception as error:
                raise AssertionError(f"{where} was accepted, then {error!r}") from error
    assert len(places) > 500 and rejected and accepted  # the sweep covered the record, and met both outcomes


# Catches (fail-closed): a call that leaves out `reveal` getting the revealed view, the bot's side and the true board
# included, of a fair game that is still going; and a `reveal` passed by position, where it reads like a step. Every
# caller says which view it wants, by name.
def test_reveal_has_no_default_and_is_given_by_name(rec):
    for args in ((), (3,), (3, True), (3, False), (None, True)):
        with pytest.raises(TypeError):
            view_state(rec, *args)
    assert view_state(rec, 3, reveal=False) == view_state(rec, reveal=False)
    assert view_state(rec, upto=3, reveal=True) == view_state(rec, reveal=True)


# Catches (brief): a hidden view with a key more or fewer than HIDDEN_KEYS, and a `you` that is not the human's
# own observation after the last move.
def test_hidden_view_has_only_human_fields(rec):
    s = view_state(rec, reveal=False)
    assert set(s) == set(HIDDEN_KEYS)
    assert s["you"] == rec.plies[-1].observations[rec.options["human"]]


# Catches: any hidden-view value that is not the human's own, wrong at some step: the whole view, for every k.
@pytest.mark.parametrize("k", range(4))
def test_hidden_view_values(rec, k):
    human = rec.options["human"]
    s = view_state(rec, k, reveal=False)
    assert s == {"fair": False, "human": human, "over": False, "ply": k, "result": None, "to_move": TO_MOVE[k],
                 "you": observation_json(POSITIONS[k][1][human]), "your_moves": YOUR_MOVES[human][k]}
    assert json.loads(json.dumps(s)) == s  # plain JSON values, as the page receives them


# Catches (fair game): a hidden view that reads the bot's side, the true FEN, the bot's observation or its turns,
# such as a to_move taken from the true FEN or an `over` from the bot's observation. Everything on the bot's side is
# spoiled, and the hidden view must not change; the revealed view must show the spoiling, or the check proves nothing.
# Once with the game going and once with a result, because the end is worked out from other fields.
@pytest.mark.parametrize("result", [None, {"winner": "draw", "reason": "no_legal_moves"}], ids=["going", "over"])
def test_hidden_view_reads_nothing_on_the_bots_side(rec, result):
    rec.result = result
    bot = other(rec.options["human"])
    spoiled = copy.deepcopy(rec)
    spoiled.rules = spoiled.scorer = spoiled.bot = spoiled.start_fen = spoiled.tracker_error = SPOILED
    spoiled.start_observations[bot] = {SPOILED: SPOILED}
    for ply in spoiled.plies:
        ply.true_fen = SPOILED
        ply.observations[bot] = {SPOILED: SPOILED}
    spoiled.bot_turns = [BotTurn(ply=0, belief=[{"fen": SPOILED, "weight": 1.0}], population_size=None,
                                 explanation={SPOILED: SPOILED}, inspection={SPOILED: SPOILED}, error=SPOILED)]
    for k in range(4):
        hidden = view_state(spoiled, k, reveal=False)
        assert hidden == view_state(rec, k, reveal=False)
        assert SPOILED not in json.dumps(hidden)
    assert SPOILED in json.dumps(view_state(spoiled, 3, reveal=True))


# Catches: a fair flag that is not the record's option, that defaults to true, or that holds at some steps and
# not at others, in either view.
def test_fair_comes_from_the_options():
    unmarked = make_record()
    del unmarked.options["fair"]
    for upto in range(4):
        for reveal in (False, True):
            assert view_state(make_record(fair=True), upto, reveal=reveal)["fair"] is True
            assert view_state(make_record(fair=False), upto, reveal=reveal)["fair"] is False
            assert view_state(unmarked, upto, reveal=reveal)["fair"] is False


# Catches: a game-over banner on a position the game had not ended in (a saved game stepped back would show it
# at every move), a result shown while the game goes on, and an end read from the observation: a game that stops
# for lack of legal moves is not terminal for the rules, but it is over.
def test_over_and_result_only_at_the_end(rec):
    rec.result = {"winner": "draw", "reason": "no_legal_moves"}
    for reveal in (False, True):
        for k in range(3):
            s = view_state(rec, k, reveal=reveal)
            assert (s["over"], s["result"]) == (False, None)
        for s in (view_state(rec, 3, reveal=reveal), view_state(rec, reveal=reveal)):
            assert (s["over"], s["result"]) == (True, {"winner": "draw", "reason": "no_legal_moves"})
            assert s["you"]["terminal"] is False


# Catches: the end of a real finished game not showing in the human's own view: the king taken, the result, the
# outcome in the observation, and no end at the start.
def test_a_finished_game():
    record = finished_record()
    s = view_state(record, reveal=False)
    assert s["over"] is True and s["result"] == {"winner": "white", "reason": "king_capture"}
    assert (s["you"]["terminal"], s["you"]["outcome"], s["to_move"], s["your_moves"]) == (True, 1.0, "black", ["e2e8"])
    start = view_state(record, 0, reveal=False)
    assert (start["over"], start["result"], start["your_moves"]) == (False, None, [])


# Catches (brief): a revealed view without the bot's turn, the true position or the bot's view, or one that changes
# what the player already has; and values that are not the record's own.
def test_revealed_view_adds_bot_and_truth(rec):
    human = rec.options["human"]
    s = view_state(rec, reveal=True)
    assert set(s) == set(HIDDEN_KEYS) | {"moves", "bot", "true_fen", "bot_view", "rules", "scorer", "bot_name",
                                         "tracker_error"}
    assert s["tracker_error"] is None
    assert s["moves"] == MOVE_LIST
    assert s["true_fen"] == "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"
    assert s["bot_view"] == observation_json(POSITIONS[3][1][other(human)]) and s["bot_view"] != s["you"]
    assert (s["rules"], s["scorer"], s["bot_name"]) == ("pairb-standin", "material", "pairb-one-ply")
    assert s["bot"] == rec.bot_turns[-1].to_json() and s["bot"]["error"] is None
    assert {key: s[key] for key in HIDDEN_KEYS} == view_state(rec, reveal=False)
    assert json.loads(json.dumps(s)) == s


# Catches (brief): a step that shows the wrong moment: `you` for the start or after the first move.
def test_step_back(rec):
    human = rec.options["human"]
    assert view_state(rec, upto=1, reveal=True)["you"] == rec.plies[0].observations[human]
    assert view_state(rec, upto=0, reveal=True)["you"] == rec.start_observations[human]


# Catches: every field of the view at every step: an off-by-one in the index of the position (after k moves is
# plies[k - 1], and at the start plies[-1] is the LAST move, not the start), the bot's turn chosen with <= instead
# of <, the first turn instead of the latest, and your_moves or moves cut at the wrong place.
@pytest.mark.parametrize("k", range(4))
def test_every_step_shows_that_moment(rec, k):
    human = rec.options["human"]
    s = view_state(rec, k, reveal=True)
    shown = BOT_TURN_SHOWN[human][k]
    assert s["ply"] == k and s["to_move"] == TO_MOVE[k]
    assert s["you"] == observation_json(POSITIONS[k][1][human])
    assert s["bot_view"] == observation_json(POSITIONS[k][1][other(human)])
    assert s["true_fen"] == POSITIONS[k][0]
    assert s["moves"] == MOVE_LIST[:k] and s["your_moves"] == YOUR_MOVES[human][k]
    assert s["bot"] == (None if shown is None else {t.ply: t for t in rec.bot_turns}[shown].to_json())


# Catches: a step outside the record read as the end, or wrapped round by a negative index, or a step that is not
# a whole number accepted.
@pytest.mark.parametrize("upto", [-1, 4, 99, 1.0, "1"])
def test_a_step_outside_the_record_is_a_value_error(rec, upto):
    for reveal in (False, True):
        with pytest.raises(ValueError, match="ply"):
            view_state(rec, upto, reveal=reveal)


# Catches: a new game (no move yet) breaking the view: the first step is the start itself, and no turn is shown.
def test_a_new_game():
    record = make_record("black", [])
    s = view_state(record, reveal=True)
    assert s["ply"] == 0 and s["you"] == record.start_observations["black"] and s["your_moves"] == []
    assert (s["moves"], s["bot"], s["over"], s["result"]) == ([], None, False, None)
    assert s["true_fen"] == record.start_fen == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    with pytest.raises(ValueError):
        view_state(record, 1, reveal=True)


# Catches: the failure of the bot's tracker on the view that ended the game shown before the end (it happened after
# the last move), lost from the end, shown in a hidden view, or a saved game from before this field refused: it loads
# with None. The game is over all the same, with its result.
def test_a_tracker_failure_at_the_end_is_shown_at_the_end_only():
    record = tracker_failed_record()
    end = view_state(record, reveal=True)
    assert (end["over"], end["result"]) == (True, {"winner": "white", "reason": "king_capture"})
    assert end["tracker_error"] == record.tracker_error
    assert view_state(record, 0, reveal=True)["tracker_error"] is None
    assert set(view_state(record, reveal=False)) == set(HIDDEN_KEYS)
    going = make_record("white")
    going.tracker_error = "the bot's tracker failed"  # never so before the end: a damaged file shows nothing early
    assert all(view_state(going, upto, reveal=True)["tracker_error"] is None for upto in range(4))
    data = finished_record().to_json()
    del data["tracker_error"]
    assert GameRecord.from_json(data).tracker_error is None


# Catches: the turn that failed shown as one that was played (it has no move after it), or lost from the saved game
# (it is what the bug report is made from).
def test_a_failed_turn_is_saved_but_is_not_a_played_one():
    record = failed_record()
    assert view_state(record, reveal=True)["bot"]["ply"] == 2
    assert view_state(record, reveal=True)["bot"]["error"] is None
    again = GameRecord.from_json(json.loads(json.dumps(record.to_json())))
    assert (again.bot_turns[-1].ply, again.bot_turns[-1].error) == (4, "the bot stopped")


# Catches (live and replay views come from this one function): a loaded record that draws a different screen from the
# one it was saved from, at any step, hidden or revealed.
def test_a_loaded_record_gives_the_same_views(kind):
    loaded = GameRecord.from_json(json.loads(json.dumps(kind.to_json())))
    for upto in range(len(kind.plies) + 1):
        for reveal in (False, True):
            assert view_state(loaded, upto, reveal=reveal) == view_state(kind, upto, reveal=reveal)


# Catches: a view that hands the page one of the record's own lists or dicts, at any depth, so that a change to the
# state (the session adds keys to it) or to what the page was given changes the saved game.
def test_views_are_copies(kind):
    before = snapshot(kind)
    for upto in range(len(kind.plies) + 1):
        for reveal in (False, True):
            scribble(view_state(kind, upto, reveal=reveal))
    assert kind.to_json() == before


# Catches: a human colour that is not a colour (the options hold "random" until a session resolves it) turning into
# a KeyError deep inside the view.
def test_the_view_needs_the_humans_colour(rec):
    rec.options["human"] = "random"
    with pytest.raises(ValueError, match="human"):
        view_state(rec, reveal=True)
