"""Fog Lab's server: its JSON API over game sessions and saved replays, its static files, its start command and the
paths it works out.

The server tests start the real thing on a free port (make_server(app, port=0)) in a thread and talk to it with
http.client, so what they check is what the page gets. Games use piece values, 16 particles and 2 guesses. A LabApp
always gets a home under tmp_path, so nothing is written into the checkout, and opening scorers is faked wherever a
test needs to count what was opened and closed.
"""
import dataclasses
import errno
import http.client
import json
import os
import queue
import random
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from fow_shared.contracts import Decision
from no_torch import PAIR_B, run_without_torch
from pairb.lab import __main__ as start_command
from pairb.lab import server
from pairb.lab.paths import ensure_repo_on_path, lab_home, repo_root, venv_python
from pairb.lab.record import HIDDEN_KEYS, GameRecord, view_state
from pairb.lab.scorers import SCORER_IDS, ScorerOptions, available_scorers, default_scorer, torch_available
from pairb.lab.server import LabApp, make_server
from pairb.lab.session import BOTS, BotSpec, default_tracker
from pairb.material import MaterialEvaluator
from pairb.rules import StandinRules

REPO = PAIR_B.parent
GAME = {"scorer": "material", "particles": 16, "guesses": 2}
KING_CAPTURE = "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1"  # Re2xe8 takes the king
FEN_PLACEMENT = re.compile(r"[1-8pnbrqkPNBRQK]+(?:/[1-8pnbrqkPNBRQK]+){7}")  # the board part of any FEN
HIDDEN = set(HIDDEN_KEYS) | {"id", "error", "device"}  # all a fair game in progress may serve (Ruling R16)
UNKNOWN_ID = "0123456789ab"


# ---- a running server, and a way to talk to it ----

@dataclasses.dataclass
class Answer:
    status: int
    body: bytes
    headers: http.client.HTTPMessage

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")

    def header(self, name, default=None):
        return self.headers.get(name, default)

    def data(self):
        return json.loads(self.body)


class Lab:
    """A running server and its app. Every request opens its own connection, so threads can share one Lab."""

    def __init__(self, app, httpd, home, scorer_opts):
        self.app, self.httpd, self.home, self.scorer_opts = app, httpd, home, scorer_opts
        self.port = httpd.server_address[1]

    def send(self, method, path, body=None, headers=None) -> Answer:
        """A dict or list body goes as JSON; text and bytes go as they are."""
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return Answer(response.status, response.read(), response.headers)
        finally:
            connection.close()

    def get(self, path, headers=None):
        """(status, the JSON the server sent, or its text when it did not send JSON)."""
        return self._parsed(self.send("GET", path, headers=headers))

    def post(self, path, body=None, headers=None):
        return self._parsed(self.send("POST", path, body, headers))

    @staticmethod
    def _parsed(answer):
        is_json = answer.header("Content-Type", "").startswith("application/json")
        return answer.status, answer.data() if is_json else answer.text


@pytest.fixture
def start_lab(tmp_path):
    """start_lab(**scorer_options) -> a Lab on a free port; every one started is stopped at the end of the test."""
    started = []

    def start(**scorer_options):
        scorer_opts = ScorerOptions(checkpoints=tmp_path / "no-checkpoints", **scorer_options)
        home = tmp_path / "fog_lab"
        app = LabApp(REPO, scorer_opts, StandinRules(), home=home)
        httpd = make_server(app, port=0)
        thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        started.append((app, httpd, thread))
        return Lab(app, httpd, home, scorer_opts)

    yield start
    for app, httpd, thread in started:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=30)
        app.close()


@pytest.fixture
def lab(start_lab):
    return start_lab()


@pytest.fixture
def engine_file(tmp_path):
    """Listing only looks, so an empty file at the engine's path is enough to make the Stockfish scorers available."""
    path = tmp_path / "engine"
    path.write_bytes(b"")
    return path


class Spy:
    """Piece values that count their closes."""

    def __init__(self):
        self._inner = MaterialEvaluator()
        self.name = self._inner.name
        self.closes = 0

    def evaluate_children(self, fen):
        return self._inner.evaluate_children(fen)

    def close(self):
        self.closes += 1


class ScriptedBot:
    """An Agent that plays seeded random legal moves, and raises on its fail_on-th move when it has one. Its name is
    not ASCII, which a saved file must keep."""

    name = "bot-\u265f\ufe0e"
    fail_on = None

    def __init__(self, scorer=None):
        self.rng, self.moves = None, 0

    def reset(self, player, seed):
        self.rng, self.moves = random.Random(seed), 0

    def act(self, turn):
        self.moves += 1
        if self.moves == self.fail_on:
            raise RuntimeError(f"the bot broke on move {self.moves}")
        moves = turn.observation.legal_moves
        return Decision(self.rng.choice(moves), {move: 1 / len(moves) for move in moves})


class FailsSecond(ScriptedBot):
    fail_on = 2


@pytest.fixture
def scripted_bots(monkeypatch):
    """Adds the BOTS entries "scripted" and "fails-second" for one test."""
    for name, agent in (("scripted", ScriptedBot), ("fails-second", FailsSecond)):
        monkeypatch.setitem(BOTS, name, BotSpec(name, agent, default_tracker))


def new_game(lab, **options) -> str:
    status, created = lab.post("/api/games", {**GAME, **options})
    assert status == 200, created
    return created["id"]


def play(lab, *moves, **options) -> str:
    """Start a game and play the human's `moves` in it. Returns the game's id."""
    game = new_game(lab, **options)
    for move in moves:
        status, state = lab.post(f"/api/games/{game}/move", {"move": move})
        assert status == 200, state
    return game


def expect_error(answer: Answer, status: int) -> str:
    """The message of an {"error": ...} answer with this status."""
    assert answer.status == status, answer.body
    assert answer.header("Content-Type") == "application/json; charset=utf-8"
    data = answer.data()
    assert set(data) == {"error"} and isinstance(data["error"], str) and data["error"]
    return data["error"]


# ---- the API ----

# Catches: a server bound to all interfaces (or to "localhost", which may be IPv6 too), which would put a game's true
# board on the network.
def test_binds_loopback_only(lab):
    assert lab.httpd.server_address[0] == "127.0.0.1"


# Catches: a listing that leaves a scorer out or reorders them, rows that differ from the registry's own, a default
# that is not one the page can start, and a missing machine or torch flag.
def test_config_lists_rules_and_scorers(lab):
    status, config = lab.get("/api/config")
    assert status == 200
    assert set(config) == {"rules", "scorers", "default_scorer", "bots", "default_bot", "torch", "machine"}
    assert config["rules"] == {"name": "pairb-standin", "label": StandinRules.label}
    assert config["rules"]["name"] in {"pairb-standin", "teal-rules-adapter"}
    assert [row["id"] for row in config["scorers"]] == list(SCORER_IDS) and len(config["scorers"]) == len(SCORER_IDS)
    assert all(set(row) == {"id", "label", "available", "reason"} for row in config["scorers"])
    infos = available_scorers(lab.scorer_opts)
    assert config["scorers"] == [dataclasses.asdict(info) for info in infos]
    assert config["default_scorer"] == default_scorer(infos)
    assert config["torch"] is torch_available()
    assert isinstance(config["machine"], str) and config["machine"]


# Catches: a state that differs between the answer that made it and a later read, a move that does not reach the
# bot, a ply query that returns the wrong step, and a record that is not served for a game that is not fair.
def test_game_round_trip(lab):
    status, created = lab.post("/api/games", GAME)
    assert status == 200 and set(created) == {"id", "state"}
    game, state = created["id"], created["state"]
    assert state["id"] == game
    assert (state["human"], state["ply"], state["over"], state["error"]) == ("white", 0, False, None)
    assert "e2e4" in state["you"]["legal_moves"]
    assert lab.get(f"/api/games/{game}") == (200, state)
    status, after = lab.post(f"/api/games/{game}/move", {"move": "e2e4"})
    assert status == 200 and after["ply"] == 2 and after["your_moves"] == ["e2e4"] and after["to_move"] == "white"
    assert [(m["ply"], m["player"]) for m in after["moves"]] == [(0, "white"), (1, "black")]
    assert after["moves"][0]["move"] == "e2e4" and after["bot"]["ply"] == 1
    assert lab.get(f"/api/games/{game}") == (200, after)
    status, step = lab.get(f"/api/games/{game}?ply=1")
    assert status == 200 and (step["ply"], step["to_move"], step["bot"], step["id"]) == (1, "black", None, game)
    assert lab.get(f"/api/games/{game}?ply=0")[1]["moves"] == []
    status, record = lab.get(f"/api/games/{game}/record")  # not fair: open at any time
    assert status == 200 and record == GameRecord.from_json(record).to_json() and len(record["plies"]) == 2


# Catches: a bad request that crashes the handler (500), that gets an HTML page or no body, or whose message does
# not say what is wrong; and a refused move that changes the game.
def test_bad_requests_get_messages(lab):
    assert "JSON" in expect_error(lab.send("POST", "/api/games", b"{not json"), 400)
    assert "guesses" in expect_error(lab.send("POST", "/api/games", {**GAME, "guesses": 0}), 400)
    expect_error(lab.send("GET", f"/api/games/{UNKNOWN_ID}"), 404)
    game = new_game(lab)
    assert "e2e5" in expect_error(lab.send("POST", f"/api/games/{game}/move", {"move": "e2e5"}), 400)
    assert lab.get(f"/api/games/{game}")[1]["ply"] == 0


# Catches: any of these answering 500 or HTML, a wrong method on a real path being served, and unknown options
# being ignored or crashing (GameOptions raises TypeError for them).
@pytest.mark.parametrize("method, path, body, status", [
    ("GET", "/no/such/page", None, 404),
    ("GET", "/api/games", None, 404),
    ("GET", "/api/games/", None, 404),
    ("POST", "/api/config", {}, 404),
    ("PUT", "/api/games", {}, 404),
    ("DELETE", f"/api/games/{UNKNOWN_ID}", None, 404),
    ("PATCH", "/api/config", {}, 404),
    ("OPTIONS", "/api/games", None, 404),
    ("GET", f"/api/games/{UNKNOWN_ID}/record", None, 404),
    ("POST", f"/api/games/{UNKNOWN_ID}/move", {"move": "e2e4"}, 404),
    ("POST", f"/api/games/{UNKNOWN_ID}/save", {}, 404),
    ("GET", f"/api/games/{UNKNOWN_ID}?ply=abc", None, 404),
    ("GET", f"/api/replays/{UNKNOWN_ID}", None, 404),
    ("GET", "/api/games/a%2Fb", None, 404),
    ("POST", "/api/games", b"[1, 2]", 400),
    ("POST", "/api/games", b'"text"', 400),
    ("POST", "/api/games", b"null", 400),
    ("POST", "/api/games", b"\xff\xfe", 400),
    ("POST", "/api/games", b"[" * 100_000, 400),
    ("POST", "/api/games", {**GAME, "bogus": 1}, 400),
    ("POST", "/api/games", {**GAME, "scorer": "nonsense"}, 400),
    ("POST", "/api/games", {**GAME, "scorer": None}, 400),
    ("POST", "/api/games", {**GAME, "guesses": True}, 400),
    ("POST", "/api/games", {**GAME, "particles": "many"}, 400),
    ("POST", "/api/games", {**GAME, "human": "green"}, 400),
    ("POST", "/api/games", {**GAME, "fair": "yes"}, 400),
    ("POST", "/api/games", {**GAME, "start_fen": "garbage"}, 400),
    ("POST", "/api/games", {**GAME, "start_fen": 7}, 400),
    ("POST", "/api/games", {**GAME, "bot": "no-such-bot"}, 400),
    ("POST", "/api/replays", b"{", 400),
    ("POST", "/api/replays", [], 400),
    ("POST", "/api/replays", {}, 400),
    ("POST", "/api/replays", {"version": 2}, 400),
    ("POST", "/api/replays", {"version": 1, "plies": "no"}, 400),
    ("POST", "/api/replays", b"[" * 100_000, 400),
    ("POST", "/api/replays", {"name": "missing.json"}, 404),
    ("POST", "/api/replays", {"name": "a", "extra": 1}, 400),
])
def test_every_unusable_request_gets_a_json_message(lab, method, path, body, status):
    expect_error(lab.send(method, path, body), status)


# Catches: the move reply losing the observation between the two moves, or leaking hidden fields in a fair game.
@pytest.mark.parametrize("fair", [False, True])
def test_move_can_return_two_distinct_observations(lab, fair):
    game = new_game(lab, fair=fair)
    status, reply = lab.post(f"/api/games/{game}/move", {"move": "e2e4", "include_after_human": True})
    assert status == 200
    assert reply["after_human"]["ply"] == 1
    assert reply["state"]["ply"] == 2
    if fair:
        assert set(reply["after_human"]) == HIDDEN
        assert set(reply["state"]) == HIDDEN
    status, current = lab.get(f"/api/games/{game}")
    assert status == 200 and current == reply["state"]


# Catches: a non-boolean include_after_human being accepted, or a move being played before the flag is refused.
def test_invalid_intermediate_flag_does_not_play_a_move(lab):
    game = new_game(lab)
    status, error = lab.post(f"/api/games/{game}/move", {"move": "e2e4", "include_after_human": "yes"})
    assert status == 400 and "boolean" in error["error"]
    assert lab.get(f"/api/games/{game}")[1]["ply"] == 0


# Catches: a bad move or ply being played, crashing, or answered with a message that is not the session's own, and a
# ply parsed so loosely that "٣" (Arabic-Indic three, which int() reads) or "1.5" gets through.
def test_bad_moves_and_plies_are_refused_with_messages(lab):
    game = new_game(lab)
    for body in [{"move": 5}, {"move": None}, {}, {"move": "e2e4e5"}, {"move": "E2E4"}, {"move": "e7e5"},
                 {"move": "a1a2"}, [1], b"nope"]:
        expect_error(lab.send("POST", f"/api/games/{game}/move", body), 400)
    assert "UCI" in expect_error(lab.send("POST", f"/api/games/{game}/move", {"move": 5}), 400)
    for query in ["abc", "1.5", "-1", "1", "", "%D9%A3", "1&ply=1", "99999999999999999999999"]:
        message = expect_error(lab.send("GET", f"/api/games/{game}?ply={query}"), 400)
        assert "ply" in message
    assert "from 0 to 0" in expect_error(lab.send("GET", f"/api/games/{game}?ply=1"), 400)
    assert lab.get(f"/api/games/{game}?ply=0")[0] == 200
    assert lab.get(f"/api/games/{game}")[1]["ply"] == 0  # nothing was played


# Catches: a draw or a win that the server does not report, and a move after the game is over being played.
def test_a_finished_game_takes_no_more_moves(lab):
    game = play(lab, "e2e8", start_fen=KING_CAPTURE)
    status, state = lab.get(f"/api/games/{game}")
    assert state["over"] and state["result"] == {"winner": "white", "reason": "king_capture"}
    assert "over" in expect_error(lab.send("POST", f"/api/games/{game}/move", {"move": "e1e2"}), 400)


# ---- fair games ----

# Required test 5, Ruling R17. Catches: a record or a save that opens a fair game before it ends (the bot's side and
# the true board are in it), one that stays closed after, and a save that writes the file before it refuses.
def test_record_forbidden_for_unfinished_fair_game(lab):
    game = new_game(lab, fair=True, start_fen=KING_CAPTURE)
    for answer in (lab.send("GET", f"/api/games/{game}/record"), lab.send("POST", f"/api/games/{game}/save")):
        assert "fair" in expect_error(answer, 403)
    assert not (lab.home / "games").exists()
    status, state = lab.post(f"/api/games/{game}/move", {"move": "e2e8"})
    assert state["over"] and state["result"] == {"winner": "white", "reason": "king_capture"}
    status, record = lab.get(f"/api/games/{game}/record")
    assert status == 200 and GameRecord.from_json(record).result == {"winner": "white", "reason": "king_capture"}
    status, saved = lab.post(f"/api/games/{game}/save")
    assert status == 200 and (lab.home / "games" / saved["name"]).is_file()
    replay = lab.post("/api/replays", record)[1]["id"]  # stepping back through the ended game shows the bot's side
    start = lab.get(f"/api/replays/{replay}?ply=0")[1]
    assert start["fair"] is True and "true_fen" in start and "bot_view" in start


# Required test 5, Ruling R16. Catches: any key beyond the human's own in a fair game's state, on any route and at any
# step (the bot's move or guesses, the true board), a board position anywhere in the text, and a state that has lost
# the human's own fields.
def test_fair_game_in_progress_serves_only_the_humans_fields(lab):
    status, created = lab.post("/api/games", {**GAME, "fair": True})
    game = created["id"]
    status, moved = lab.post(f"/api/games/{game}/move", {"move": "e2e4"})
    served = [created["state"], moved, lab.get(f"/api/games/{game}")[1]]
    served += [lab.get(f"/api/games/{game}?ply={ply}")[1] for ply in (0, 1, 2)]
    for state in served:
        assert set(state) == HIDDEN
        assert FEN_PLACEMENT.search(json.dumps(state)) is None
        assert (state["fair"], state["human"], state["error"]) == (True, "white", None)
    assert (moved["ply"], moved["your_moves"], moved["to_move"], moved["over"]) == (2, ["e2e4"], "white", False)
    assert [state["ply"] for state in served[3:]] == [0, 1, 2]


# Ruling R17, and "stepping matches live play". Catches: a fair game stopped by the bot's error staying closed
# (no move can follow, so the record would never be reachable), a record whose failed turn is not the last, and a
# replay that does not show the error at the step where live play showed it, or shows it earlier.
def test_a_game_stopped_by_an_error_can_be_saved_and_replayed(lab, scripted_bots):
    game = new_game(lab, bot="fails-second", fair=True)
    assert lab.post(f"/api/games/{game}/move", {"move": "e2e4"})[0] == 200
    assert "fair" in expect_error(lab.send("GET", f"/api/games/{game}/record"), 403)
    status, stopped = lab.post(f"/api/games/{game}/move", {"move": "d2d4"})
    assert status == 200 and "broke on move 2" in stopped["error"] and not stopped["over"]
    status, record = lab.get(f"/api/games/{game}/record")
    assert status == 200 and lab.post(f"/api/games/{game}/save")[0] == 200
    last = len(record["plies"])
    assert record["bot_turns"][-1]["ply"] == last and record["bot_turns"][-1]["error"] == stopped["error"]
    replay = lab.post("/api/replays", record)[1]["id"]

    def same(state):  # a live state holds the game's error at every step; a replay, at the last one only
        return {key: value for key, value in state.items() if key not in ("id", "device", "error")}

    for ply in range(last + 1):
        live = lab.get(f"/api/games/{game}?ply={ply}")[1]
        stepped = lab.get(f"/api/replays/{replay}?ply={ply}")[1]
        assert same(stepped) == same(live)
        assert stepped["error"] == (stopped["error"] if ply == last else None)  # live play had none until then
    assert lab.get(f"/api/replays/{replay}")[1]["error"] == stopped["error"]
    assert lab.get(f"/api/games/{game}")[1]["error"] == stopped["error"]


# ---- replays, saving and loading ----

# Catches: a replay that differs from live play at any step (it is the same screen), a default step that is not
# the last, and a state built without revealing.
def test_replay_round_trip(lab):
    game = play(lab, "e2e4")
    record = lab.get(f"/api/games/{game}/record")[1]
    status, loaded = lab.post("/api/replays", record)
    assert status == 200 and set(loaded) == {"id", "plies"} and loaded["plies"] == 2
    assert re.fullmatch(r"[0-9a-f]{12}", loaded["id"])
    replay = loaded["id"]
    for ply in (0, 1, 2):
        live = lab.get(f"/api/games/{game}?ply={ply}")[1]
        stepped = lab.get(f"/api/replays/{replay}?ply={ply}")[1]
        assert stepped == {key: value for key, value in live.items() if key not in ("id", "device")}
    assert lab.get(f"/api/replays/{replay}") == (200, stepped)
    expected = {**view_state(GameRecord.from_json(record), 1, reveal=True), "error": None}
    assert lab.get(f"/api/replays/{replay}?ply=1") == (200, expected)


# Catches: a replay step outside the record, or one that is not a whole number, being served or crashing, and a
# replay id that answers for a game.
def test_replay_plies_must_be_in_range(lab):
    record = lab.get(f"/api/games/{play(lab, 'e2e4')}/record")[1]
    replay = lab.post("/api/replays", record)[1]["id"]
    for query in ["abc", "1.5", "-1", "3", "", "%D9%A3", "1&ply=1", "99999999999999999999999"]:
        assert "ply" in expect_error(lab.send("GET", f"/api/replays/{replay}?ply={query}"), 400)
    assert "from 0 to 2" in expect_error(lab.send("GET", f"/api/replays/{replay}?ply=3"), 400)
    assert lab.get(f"/api/games/{replay}")[0] == 404


# Catches: only the newest replays being kept without anything saying so, or all of them being kept for as long as the
# server runs (a record is megabytes).
def test_only_the_newest_replays_are_kept(lab):
    record = lab.get(f"/api/games/{play(lab, 'e2e4')}/record")[1]
    ids = [lab.post("/api/replays", record)[1]["id"] for _ in range(server.MAX_REPLAYS + 2)]
    statuses = [lab.get(f"/api/replays/{replay}")[0] for replay in ids]
    assert statuses == [404] * 2 + [200] * server.MAX_REPLAYS


# Catches: a save that is not in the games folder under the name the page is told, a file that is not the record,
# a half-written file left behind, a listing without the saved game, and a loaded game that differs from the record.
def test_save_list_and_load(lab):
    game = play(lab, "e2e4")
    status, saved = lab.post(f"/api/games/{game}/save")
    assert status == 200 and set(saved) == {"name"}
    name = saved["name"]
    assert re.fullmatch(rf"\d{{8}}-\d{{6}}-{game}\.json", name)
    path = lab.home / "games" / name
    assert json.loads(path.read_text(encoding="utf-8")) == lab.get(f"/api/games/{game}/record")[1]
    assert [item.name for item in path.parent.iterdir()] == [name]
    status, listing = lab.get("/api/saved")
    assert status == 200 and [row["name"] for row in listing] == [name] and set(listing[0]) == {"name", "modified"}
    assert abs(datetime.fromisoformat(listing[0]["modified"]).timestamp() - time.time()) < 120
    status, loaded = lab.post("/api/replays", {"name": name})
    assert (status, loaded["plies"]) == (200, 2)
    again = lab.post("/api/replays", lab.get(f"/api/games/{game}/record")[1])[1]["id"]
    for ply in (0, 1, 2):
        assert lab.get(f"/api/replays/{loaded['id']}?ply={ply}") == lab.get(f"/api/replays/{again}?ply={ply}")


# Catches: a missing games folder being an error, files that are not saved games (a note, a half-written
# temporary file, a folder with a .json name) listed, and the oldest game coming first.
def test_saved_games_are_listed_newest_first(lab):
    assert lab.get("/api/saved") == (200, [])
    games = lab.home / "games"
    games.mkdir(parents=True)
    for name, age in [("old.json", 300), ("new.json", 100), ("middle.json", 200)]:
        (games / name).write_text("{}", encoding="utf-8")
        stamp = time.time() - age
        os.utime(games / name, (stamp, stamp))
    (games / "notes.txt").write_text("not a game", encoding="utf-8")
    (games / ".saving-1.tmp").write_text("{", encoding="utf-8")
    (games / "folder.json").mkdir()
    assert [row["name"] for row in lab.get("/api/saved")[1]] == ["new.json", "middle.json", "old.json"]


# Catches: a name that reaches a file outside the games folder (the secret is a real, loadable record sitting one
# folder up, so a guard that only worked by the file not being there would show), and a name of the wrong kind.
@pytest.mark.parametrize("name", ["../secret.json", "..\\secret.json", "sub/x.json", "/etc/passwd", "C:x.json",
                                  "x.json:stream", "", ".", "..", "x\x00.json", 5, None, ["a"], True])
def test_saved_names_cannot_leave_the_games_folder(lab, name):
    game = play(lab, "e2e4")
    (lab.home / "games").mkdir(parents=True)
    (lab.home / "secret.json").write_text(json.dumps(lab.get(f"/api/games/{game}/record")[1]), encoding="utf-8")
    assert "name" in expect_error(lab.send("POST", "/api/replays", {"name": name}), 400)


# Catches: a saved file that is not JSON, not text, not a record or not a file answered with a crash.
def test_saved_files_that_cannot_be_loaded_are_refused_with_a_message(lab):
    games = lab.home / "games"
    games.mkdir(parents=True)
    (games / "broken.json").write_text("{not json", encoding="utf-8")
    (games / "binary.json").write_bytes(b"\xff\xfe\x00\x01")
    (games / "other.json").write_text('{"version": 2}', encoding="utf-8")
    (games / "folder.json").mkdir()
    for name in ("broken.json", "binary.json"):
        assert name in expect_error(lab.send("POST", "/api/replays", {"name": name}), 400)
    assert "version" in expect_error(lab.send("POST", "/api/replays", {"name": "other.json"}), 400)
    expect_error(lab.send("POST", "/api/replays", {"name": "folder.json"}), 404)


# Catches: a text file written in the machine's own encoding (Windows: cp1252, which cannot hold a bot's name
# like this), a name that comes back changed, and escapes where readable text was meant.
def test_saved_files_are_utf_8(lab, scripted_bots):
    game = play(lab, "e2e4", bot="scripted")
    name = lab.post(f"/api/games/{game}/save")[1]["name"]
    raw = (lab.home / "games" / name).read_bytes()
    assert ScriptedBot.name.encode("utf-8") in raw
    assert json.loads(raw.decode("utf-8"))["bot"] == ScriptedBot.name
    replay = lab.post("/api/replays", {"name": name})[1]["id"]
    assert lab.get(f"/api/replays/{replay}")[1]["bot_name"] == ScriptedBot.name


# Catches: a save that fails with a crash when the games folder cannot be made.
def test_a_save_that_cannot_write_says_so(lab):
    game = play(lab, "e2e4")
    lab.home.mkdir(parents=True)
    (lab.home / "games").write_text("a file where the folder should be", encoding="utf-8")
    assert "could not save" in expect_error(lab.send("POST", f"/api/games/{game}/save"), 500)


# Ruling R19 (a). Catches: a listing that crashes with no message when the games path cannot be listed (here it is a
# file).
def test_the_saved_games_listing_says_when_it_cannot_list(lab):
    lab.home.mkdir(parents=True)
    (lab.home / "games").write_text("a file where the folder should be", encoding="utf-8")
    assert "could not list the saved games" in expect_error(lab.send("GET", "/api/saved"), 500)


@pytest.fixture
def is_file_as_on_python_3_12(monkeypatch):
    """Path.is_file as Python 3.12 has it: for a name longer than the file system allows (255 bytes here) it raises
    OSError, where 3.14 says False. So the tests below show the guard on any version."""
    real = Path.is_file

    def is_file(self, *args, **kwargs):
        if any(len(part.encode("utf-8")) > 255 for part in self.parts):
            raise OSError(errno.ENAMETOOLONG, "File name too long", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", is_file)


# Ruling R19 (a). Catches: a name too long for the file system answered with a 500 (a teammate's Python 3.12 raises
# for one), for a static file and for a saved game; names of a length the file system can hold but that are refused
# (or offered by the listing and then refused); and the longest names allowed not being served.
def test_names_too_long_for_the_file_system_get_messages(lab, static_dir, is_file_as_on_python_3_12):
    for name in ["a" * 300, "a" * 300 + ".js", "a" * 129]:
        expect_error(lab.send("GET", f"/static/{name}"), 404)
    (static_dir / ("b" * 128)).write_text("the longest name", encoding="utf-8")
    assert lab.send("GET", "/static/" + "b" * 128).text == "the longest name"
    for name in ["a" * 300 + ".json", "\u00e9" * 200 + ".json"]:
        assert "name" in expect_error(lab.send("POST", "/api/replays", {"name": name}), 400)
    # 125 characters but 365 bytes: within the length allowed, and still too long for the file system
    expect_error(lab.send("POST", "/api/replays", {"name": "\u265f" * 120 + ".json"}), 404)
    games = lab.home / "games"
    games.mkdir(parents=True)
    longest = "c" * 123 + ".json"  # 128 characters, the most a saved game's name may have
    (games / longest).write_text(json.dumps(lab.get(f"/api/games/{play(lab, 'e2e4')}/record")[1]), encoding="utf-8")
    (games / ("d" * 200 + ".json")).write_text("{}", encoding="utf-8")  # too long a name to load: not offered
    assert [row["name"] for row in lab.get("/api/saved")[1]] == [longest]
    assert lab.post("/api/replays", {"name": longest})[0] == 200


# ---- scorers: availability, opening, failing ----

# Catches: an unavailable scorer starting a game, a 400 that does not carry the reason the page lists, and the
# listing changing because someone asked. On an Intel Mac the torch reason comes first, so the test compares with the
# listing's own reason.
def test_unavailable_scorer_is_400(lab):
    before = lab.get("/api/config")[1]
    for scorer_id in ("network1", "belief"):
        row = next(row for row in before["scorers"] if row["id"] == scorer_id)
        assert row["available"] is False and row["reason"]
        assert row["reason"] in expect_error(lab.send("POST", "/api/games", {**GAME, "scorer": scorer_id}), 400)
    assert lab.get("/api/config")[1] == before


# Catches: a game started with another scorer than the one the page lists as the default, and a scorer opened once
# where the bot and the inspector each need their own.
def test_the_default_scorer_is_used_when_none_is_given(start_lab, engine_file, monkeypatch):
    lab = start_lab(stockfish=str(engine_file))
    wanted = lab.get("/api/config")[1]["default_scorer"]
    assert wanted == "stockfish-d1"  # the belief network is held back by its missing checkpoint (or by no torch)
    opened = []
    monkeypatch.setattr(server, "open_scorer", lambda scorer_id, opts: opened.append(scorer_id) or Spy())
    status, created = lab.post("/api/games", {"particles": 16, "guesses": 2})
    assert status == 200 and opened == [wanted, wanted]
    assert lab.get(f"/api/games/{created['id']}/record")[1]["options"]["scorer"] == wanted


# Catches: a new game that leaves the old session open (an engine process each), one that closes it without being
# replaced, a scorer opened once for the bot and the inspector, and a closed game still answering.
def test_a_new_game_closes_the_old_one(lab, monkeypatch):
    opened = []

    def fake_open(scorer_id, opts):
        opened.append((scorer_id, Spy()))
        return opened[-1][1]

    monkeypatch.setattr(server, "open_scorer", fake_open)
    first = new_game(lab)
    assert [scorer_id for scorer_id, _ in opened] == ["material", "material"] and opened[0][1] is not opened[1][1]
    second = new_game(lab)
    assert second != first and [spy.closes for _, spy in opened] == [1, 1, 0, 0]
    assert lab.get(f"/api/games/{first}")[0] == 404 and lab.get(f"/api/games/{second}")[0] == 200
    lab.app.close()
    assert [spy.closes for _, spy in opened] == [1, 1, 1, 1]
    assert lab.get(f"/api/games/{second}")[0] == 404


# Ruling R19 (b). Catches: a new game that finishes opening its scorers after the app has closed (Ctrl+C while it
# opens) going live anyway, with its engines left running after the server has stopped; and a game started after close.
def test_no_game_goes_live_after_close(lab, monkeypatch):
    entered, release, spies = threading.Event(), threading.Event(), []

    def slow_open(scorer_id, opts):
        spies.append(Spy())
        entered.set()
        release.wait(60)
        return spies[-1]

    monkeypatch.setattr(server, "open_scorer", slow_open)
    answers = []
    opening = threading.Thread(target=lambda: answers.append(lab.send("POST", "/api/games", GAME)))
    opening.start()
    assert entered.wait(60)
    lab.app.close()
    release.set()
    opening.join(timeout=120)
    assert "shutting down" in expect_error(answers[0], 409)
    assert [spy.closes for spy in spies] == [1, 1]
    assert "shutting down" in expect_error(lab.send("POST", "/api/games", GAME), 409)
    assert len(spies) == 2, "nothing is opened after close"


# Catches: a refused new game (bad options, an unavailable scorer, a start the rules refuse) ending the game in
# progress, and the scorers of a start that was refused being left open.
def test_a_refused_new_game_leaves_the_current_one_alone(lab, monkeypatch):
    game = play(lab, "e2e4")
    for body in [{**GAME, "guesses": 0}, {**GAME, "scorer": "network1"}, {**GAME, "bogus": 1}]:
        assert lab.post("/api/games", body)[0] == 400
    spies = []
    monkeypatch.setattr(server, "open_scorer", lambda scorer_id, opts: spies.append(Spy()) or spies[-1])
    message = expect_error(lab.send("POST", "/api/games", {**GAME, "start_fen": "8/8/8/8/8/8/8/8 w - - 0 1"}), 400)
    assert "king" in message and [spy.closes for spy in spies] == [1, 1]
    assert lab.get(f"/api/games/{game}")[1]["ply"] == 2
    assert lab.post(f"/api/games/{game}/move", {"move": "d2d4"})[0] == 200


# Ruling R14. Catches: an exception other than ValueError from opening a scorer (an engine that will not run, a
# checkpoint that will not load) becoming a 500, a failure that is forgotten (the page would offer the scorer again),
# a reason that is not the error's own message, a listing that changes for any other scorer, and a retry of
# something the listing calls unavailable.
def test_a_scorer_that_fails_to_open_is_refused_and_listed_as_unavailable(start_lab, engine_file, monkeypatch):
    lab = start_lab(stockfish=str(engine_file))
    before = lab.get("/api/config")[1]
    assert {row["id"]: row for row in before["scorers"]}["stockfish-d1"]["available"] is True
    assert before["default_scorer"] == "stockfish-d1"
    real_open, calls = server.open_scorer, []

    def will_not_start(scorer_id, opts):
        calls.append(scorer_id)
        if scorer_id == "stockfish-d1":
            raise PermissionError(13, "Permission denied", opts.stockfish)  # not a ValueError
        return real_open(scorer_id, opts)

    monkeypatch.setattr(server, "open_scorer", will_not_start)
    message = expect_error(lab.send("POST", "/api/games", {**GAME, "scorer": "stockfish-d1"}), 400)
    assert "Permission denied" in message
    after = lab.get("/api/config")[1]
    rows = {row["id"]: row for row in after["scorers"]}
    assert rows["stockfish-d1"] == {"id": "stockfish-d1", "label": "Quick Stockfish", "available": False,
                                    "reason": message}
    assert [row for row in after["scorers"] if row["id"] != "stockfish-d1"] == \
           [row for row in before["scorers"] if row["id"] != "stockfish-d1"]
    assert after["default_scorer"] == "material"  # the failed scorer is no longer the default
    assert expect_error(lab.send("POST", "/api/games", {**GAME, "scorer": "stockfish-d1"}), 400) == message
    assert calls == ["stockfish-d1"]  # remembered: not tried again until the server restarts
    assert lab.post("/api/games", GAME)[0] == 200  # and the other scorers are not affected


# Ruling R14. Catches: a first scorer left open (an engine process) when the second fails to open, and an exception
# with no message leaving a blank reason.
def test_when_the_second_open_fails_the_first_is_closed(lab, monkeypatch):
    spies = []

    def second_fails(scorer_id, opts):
        if spies:
            raise RuntimeError()
        spies.append(Spy())
        return spies[0]

    monkeypatch.setattr(server, "open_scorer", second_fails)
    message = expect_error(lab.send("POST", "/api/games", GAME), 400)
    assert message == "RuntimeError" and [spy.closes for spy in spies] == [1]
    row = {row["id"]: row for row in lab.get("/api/config")[1]["scorers"]}["material"]
    assert (row["available"], row["reason"]) == (False, "RuntimeError")


# Catches: games that are started at once leaving a scorer open (the swap and the close are not one step), a
# session closed twice, or two games both answering.
def test_concurrent_new_games_leave_one_live_game_and_nothing_open_behind(lab, monkeypatch):
    spies, lock = [], threading.Lock()

    def fake_open(scorer_id, opts):
        spy = Spy()
        with lock:
            spies.append(spy)
        return spy

    monkeypatch.setattr(server, "open_scorer", fake_open)
    results = []
    threads = [threading.Thread(target=lambda: results.append(lab.post("/api/games", GAME))) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert [status for status, _ in results] == [200] * 4 and len(spies) == 8
    assert sum(spy.closes == 0 for spy in spies) == 2 and all(spy.closes <= 1 for spy in spies)
    assert sum(lab.get(f"/api/games/{created['id']}")[0] == 200 for _, created in results) == 1
    lab.app.close()
    assert all(spy.closes == 1 for spy in spies)


# ---- static files ----

@pytest.fixture
def static_dir(tmp_path, monkeypatch):
    """A static/ folder of the tests' own, next to a secret.txt that must never be served."""
    site = tmp_path / "site"
    folder = site / "static"
    (folder / "sub").mkdir(parents=True)
    files = {"index.html": '<div id="app"></div>\n', "app.js": 'export const piece = "\u265f\ufe0e";\n',
             "style.css": "body { margin: 0 }\n", "data.json": "{}", "notes.xyz": "x",
             "sub/x": "inside a folder", ".hidden": "a dot file", "../secret.txt": "outside static"}
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    monkeypatch.setattr(server, "STATIC_DIR", folder)
    return folder


# Catches: a script served as text/plain (Windows can map .js that way through its registry, and a page that loads
# ES modules refuses it), a missing charset, and a file read back as other bytes than it holds.
@pytest.mark.parametrize("name, content_type", [
    ("index.html", "text/html; charset=utf-8"), ("app.js", "text/javascript; charset=utf-8"),
    ("style.css", "text/css; charset=utf-8"), ("data.json", "application/json; charset=utf-8"),
    ("notes.xyz", "application/octet-stream")])
def test_static_files_are_served_with_their_content_types(lab, static_dir, name, content_type):
    answer = lab.send("GET", f"/static/{name}")
    assert answer.status == 200 and answer.header("Content-Type") == content_type
    assert answer.body == (static_dir / name).read_bytes() and answer.header("Content-Length") == str(len(answer.body))
    assert lab.send("GET", f"/static/{name}?v=3").body == answer.body


# Catches: a file outside static/ reachable through dots, encoded dots or slashes, backslashes or a drive, a folder or
# a dot file served, a name with a trailing slash or a NUL byte served as the file before it, and a missing file
# crashing. The secret exists, so a 404 shows the guard and not an absent file.
@pytest.mark.parametrize("path", [
    "/static/../secret.txt", "/static/%2e%2e/secret.txt", "/static/..%2fsecret.txt", "/static/%2e%2e%2fsecret.txt",
    "/static/..%5csecret.txt", "/static//secret.txt", "/static/sub/x", "/static/sub", "/static/sub/", "/static/.hidden",
    "/static/", "/static", "/static/..", "/static/.", "/static/index.html/", "/static/index.html%00.js",
    "/static/C:/x", "/static/missing.js", "/../secret.txt", "/%2e%2e/secret.txt"])
def test_static_blocks_traversal(lab, static_dir, path):
    answer = lab.send("GET", path)
    assert answer.status == 404 and "outside static" not in answer.text and "inside a folder" not in answer.text
    expect_error(answer, 404)


# Catches: the same, in the package's own static/ folder, where the files above it are the server's source.
def test_static_blocks_traversal_in_the_real_folder(lab):
    for path in ["/static/../server.py", "/static/%2e%2e/server.py", "/static/sub/x", "/static/..%2f__init__.py"]:
        answer = lab.send("GET", path)
        expect_error(answer, 404)
        assert "LabApp" not in answer.text


# Catches: a link inside static/ that leads out of it being followed.
def test_static_does_not_follow_a_link_out_of_the_folder(lab, static_dir):
    try:
        (static_dir / "link.txt").symlink_to(static_dir.parent / "secret.txt")
    except (OSError, NotImplementedError):
        pytest.skip("this machine cannot make symbolic links")
    expect_error(lab.send("GET", "/static/link.txt"), 404)


# Catches: HEAD answered with a body (bytes after the headers that no client expects) or not answered like GET. The
# bytes are read off the socket: http.client never reads a body for HEAD, so it could not tell.
def test_head_answers_like_get_without_the_body(lab, static_dir):
    got = lab.send("GET", "/static/app.js")
    head, body = raw_exchange(lab.port, b"HEAD /static/app.js HTTP/1.0\r\n\r\n")
    assert head.startswith(b"HTTP/1.0 200") and body == b""
    assert f"Content-Length: {len(got.body)}".encode() in head
    assert b"Content-Type: text/javascript; charset=utf-8" in head


# Ruling R4. Catches: a page that has no root element for the app to fill, and an index that is not the file.
def test_index_served(lab):
    answer = lab.send("GET", "/")
    assert answer.status == 200 and answer.header("Content-Type") == "text/html; charset=utf-8"
    assert 'id="app"' in answer.text and answer.header("Cache-Control") == "no-store"
    assert answer.body == (Path(server.__file__).parent / "static" / "index.html").read_bytes()
    assert lab.send("GET", "/static/index.html").body == answer.body and lab.send("GET", "/?x=1").body == answer.body


# ---- the server on the network ----

# Catches: a page on another site (or another host name, as in DNS rebinding) driving the app through the visitor's
# browser: starting games, saving files. Names for the machine itself, on any port, are fine, and so are requests
# that carry no Origin (every client but a browser).
def test_other_pages_and_other_host_names_are_refused(lab):
    game = new_game(lab)
    port = lab.port
    refused = [{"Host": "evil.example"}, {"Host": f"evil.example:{port}"}, {"Origin": "http://evil.example"},
               {"Origin": "null"}, {"Origin": f"http://evil.example:{port}"}, {"Origin": f"http://localhost:{port}"}]
    for headers in refused:
        expect_error(lab.send("POST", "/api/games", GAME, headers), 403)
        expect_error(lab.send("GET", "/api/config", headers=headers), 403)
    assert lab.get(f"/api/games/{game}")[0] == 200  # none of the refused starts replaced it
    for headers in [{"Host": f"localhost:{port}"}, {"Host": "localhost"}, {"Origin": f"http://127.0.0.1:{port}"},
                    {"Host": f"localhost:{port}", "Origin": f"http://localhost:{port}"}]:
        assert lab.get("/api/config", headers)[0] == 200


SAFE_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                "Content-Security-Policy": "frame-ancestors 'none'"}


# Defence in depth. Catches: an answer that a browser may sniff as another type than the one sent, or that a page on
# another site may frame (a click it tricks the user into could start a run or replace the live game): an API answer,
# a static file, the page itself, an error, and the library's own refusal of a request it cannot read.
def test_every_answer_forbids_sniffing_and_framing(lab):
    answers = [lab.send("GET", "/api/config"), lab.send("GET", "/static/app.js"), lab.send("GET", "/"),
               lab.send("GET", f"/api/games/{UNKNOWN_ID}"), lab.send("POST", "/api/games", b"{not json")]
    assert [answer.status for answer in answers] == [200, 200, 200, 404, 400]
    for answer in answers:
        assert {name: answer.header(name) for name in SAFE_HEADERS} == SAFE_HEADERS
    head, _ = raw_exchange(lab.port, b"FETCH / HTTP/1.0\r\n\r\n")  # answered by send_error
    assert head.startswith(b"HTTP/1.0 501")
    for name, value in SAFE_HEADERS.items():
        assert f"\r\n{name}: {value}\r\n".encode() in head + b"\r\n"


# Catches: a request the library cannot read or serve (a bad Content-Length, a body that stops short, a request line
# that is too long, a method it does not know) answered with its HTML error page or a dropped connection.
@pytest.mark.parametrize("request_bytes, status", [
    (b"POST /api/games HTTP/1.0\r\nContent-Length: abc\r\n\r\n", 400),
    (b"POST /api/games HTTP/1.0\r\nContent-Length: -5\r\n\r\n", 400),
    (b"POST /api/games HTTP/1.0\r\nContent-Length: 99999999999\r\n\r\n", 400),
    (b'POST /api/games HTTP/1.0\r\nContent-Length: 50\r\n\r\n{"scorer"', 400),
    (b"GET /" + b"a" * (65_537 - 5), 414),  # exactly what the library reads of a request line: nothing is left unread
    (b"FETCH / HTTP/1.0\r\n\r\n", 501),  # a method nobody has heard of: the library's own refusal, in JSON
])
def test_protocol_errors_are_json_too(lab, request_bytes, status):
    head, body = raw_exchange(lab.port, request_bytes)
    assert int(head.split(b" ", 2)[1]) == status and b"application/json" in head
    assert list(json.loads(body)) == ["error"]


# Catches: a request line that is not HTTP at all (no version, or one that does not exist) answered with the library's
# HTML page. The library answers such a request in HTTP/0.9, which has no status line or headers, so the JSON error
# is all there is.
@pytest.mark.parametrize("request_bytes", [b"NONSENSE\r\n\r\n", b"GET / HTTP/9.9\r\n\r\n"])
def test_garbage_requests_get_a_bare_json_error(lab, request_bytes):
    head, body = raw_exchange(lab.port, request_bytes)
    assert head == b"" and list(json.loads(body)) == ["error"]


def raw_exchange(port, request_bytes) -> tuple[bytes, bytes]:
    """Send these bytes as they are and read until the server closes: (the head, the body); the head is empty for an
    answer with no status line."""
    with socket.create_connection(("127.0.0.1", port), timeout=60) as connection:
        connection.sendall(request_bytes)
        connection.shutdown(socket.SHUT_WR)
        chunks = []
        while chunk := connection.recv(65536):
            chunks.append(chunk)
    answer = b"".join(chunks)
    if answer.startswith(b"HTTP/"):
        head, _, body = answer.partition(b"\r\n\r\n")
        return head, body
    return b"", answer


# Catches: a refusal that answers before it has read the request's body (the connection then closes on unread bytes, and
# the client is reset instead of told why). The body is far larger than the sockets' buffers.
def test_a_refused_request_with_a_big_body_still_gets_its_answer(lab):
    body = b"x" * 3_000_000
    request = b"POST /api/replays HTTP/1.0\r\nOrigin: http://evil.example\r\nContent-Length: %d\r\n\r\n" % len(body)
    head, answer = raw_exchange(lab.port, request + body)
    assert head.startswith(b"HTTP/1.0 403") and list(json.loads(answer)) == ["error"]


# Catches: a client that drops its connection in the middle of an upload (a browser tab closed; on Windows the library
# prints a traceback for each) leaving noise in the window that started the app, or a server that stops answering.
def test_a_dropped_connection_is_not_news(lab, capsys):
    connection = socket.create_connection(("127.0.0.1", lab.port), timeout=60)
    connection.sendall(b"POST /api/replays HTTP/1.0\r\nContent-Length: 1000\r\n\r\n{")
    connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    connection.close()  # with a linger time of 0 the close is a reset, not a goodbye
    time.sleep(0.3)  # long enough for the handler's thread to find out
    assert lab.get("/api/config")[0] == 200
    assert capsys.readouterr().err == ""


# Catches: an exception that nobody foresaw reaching the page with its text (it may hold a position, and a fair game's
# true board must not), no trace for whoever started the app, and a server that stops answering after it.
def test_an_unexpected_error_is_a_500_that_keeps_its_details_off_the_page(lab, monkeypatch, capsys):
    def broken(self, request):
        raise RuntimeError("SECRET 8/8/8/8/8/8/8/8 w - - 0 1")

    monkeypatch.setattr(LabApp, "config", broken)
    answer = lab.send("GET", "/api/config")
    assert "SECRET" not in answer.text and expect_error(answer, 500)
    assert "RuntimeError" in capsys.readouterr().err
    monkeypatch.undo()
    assert lab.get("/api/config")[0] == 200


# Ruling R19 (c). Catches: a ConnectionError raised inside a route (a BrokenPipeError from a pipe to an engine or a
# check, say) taken for a client that left: the page then gets no answer at all, and the window no trace.
def test_a_connection_error_inside_a_route_is_a_500(lab, monkeypatch, capsys):
    def broken(self, request):
        raise BrokenPipeError(errno.EPIPE, "Broken pipe")

    monkeypatch.setattr(LabApp, "config", broken)
    assert "internal error" in expect_error(lab.send("GET", "/api/config"), 500)
    assert "BrokenPipeError" in capsys.readouterr().err


# Catches: the Tests tab's routes crashing, or answering as if there were runs, in an app made without a run manager.
@pytest.mark.parametrize("method, path", [("POST", "/api/tests/run"), ("GET", "/api/tests/status"),
                                          ("GET", "/api/tests/latest"),
                                          ("GET", "/api/tests/runs/20261019-120000-000000/logs/0-pair_b.txt")])
def test_the_test_routes_need_a_run_manager(lab, method, path):
    assert "test runs" in expect_error(lab.send(method, path, {} if method == "POST" else None), 404)


# ---- the start command ----

def first_line(stream, timeout) -> str:
    """The first line a process prints, or queue.Empty when it prints none in time."""
    lines = queue.Queue()
    threading.Thread(target=lambda: lines.put(stream.readline()), daemon=True).start()
    return lines.get(timeout=timeout)


# Catches: a start command that prints another URL than the one it listens on (--port 0 asks for any free port, so the
# line must say which), a flag that is not passed on, and a process that does not serve the page it announces.
def test_start_command_prints_its_url_and_serves(tmp_path):
    no_engine = tmp_path / "no-engine"
    process = subprocess.Popen(
        [sys.executable, "-m", "pairb.lab", "--port", "0", "--rules", "standin", "--stockfish", str(no_engine)],
        cwd=PAIR_B, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
    try:
        line = first_line(process.stdout, timeout=120)
        match = re.fullmatch(r"Fog Lab: http://127\.0\.0\.1:(\d+)  \(Ctrl\+C to stop\)", line.rstrip("\r\n"))
        assert match, (line, process.poll())
        port = int(match.group(1))
        assert port > 0
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        connection.request("GET", "/api/config")
        config = json.loads(connection.getresponse().read())
        connection.close()
        rows = {row["id"]: row for row in config["scorers"]}
        assert config["rules"]["name"] == "pairb-standin"
        assert rows["stockfish-d1"]["reason"] == f"no Stockfish found at '{no_engine}'"
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        connection.request("GET", "/")
        assert 'id="app"' in connection.getresponse().read().decode("utf-8")
        connection.close()
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        connection.request("GET", "/api/tests/status")  # the app has its run manager; nothing is started here
        response = connection.getresponse()
        assert response.status == 200 and json.loads(response.read())["running"] is False
        connection.close()
    finally:
        process.terminate()
        try:
            process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


class FakeServer:
    """make_server's server for the start command's tests: it serves until a Ctrl+C at once."""

    server_address = ("127.0.0.1", 4321)  # not the port that was asked for

    def __init__(self, calls):
        self.calls = calls

    def serve_forever(self):
        self.calls.append("serve")
        raise KeyboardInterrupt

    def server_close(self):
        self.calls.append("server_close")


def fake_start(monkeypatch, running=False) -> list:
    """Replace what the start command builds with fakes that note, in the list returned, what they were made with and
    what was done to them. The run manager says `running` when asked."""
    calls = []

    class FakeRuns:
        def __init__(self, checkout, home, stages_file, **options):
            calls.append(("runs", checkout, home, stages_file, options))

        def status(self):
            return {"running": running}

    class FakeApp:
        def __init__(self, repo, scorer_opts, rules, **more):
            calls.append(("app", repo, scorer_opts, rules, more))

        def close(self):
            calls.append("app.close")

    monkeypatch.setattr(start_command, "ensure_repo_on_path", lambda: calls.append("on_path") or REPO)
    monkeypatch.setattr(start_command, "pick_rules", lambda choice: calls.append(("rules", choice)) or "RULES")
    monkeypatch.setattr(start_command, "RunManager", FakeRuns)
    monkeypatch.setattr(start_command, "LabApp", FakeApp)
    monkeypatch.setattr(start_command, "make_server",
                        lambda app, port: calls.append(("server", port)) or FakeServer(calls))
    return calls


# Ruling R10, and "closes the session on exit". Catches: the repo root put on the path after the rules are picked
# (Teal's adapter would never be found), a flag that is dropped, the printed port being the requested one, a Ctrl+C
# that leaves the server's socket or the live game open, and test runs that are not wired to this checkout, its home,
# its stages file, the engine and device asked for, and whether torch is here (Task 16; here it is not, as on an Intel
# Mac, whatever this machine has).
def test_start_command_wires_its_flags_and_cleans_up_on_ctrl_c(monkeypatch, capsys):
    calls = fake_start(monkeypatch)
    monkeypatch.setattr(start_command, "torch_available", lambda: False)
    code = start_command.main(["--port", "0", "--stockfish", "sf", "--device", "cpu", "--rules", "teal"])
    assert code == 0
    options = ScorerOptions(REPO / "pair_b" / "checkpoints", stockfish="sf", device="cpu")
    assert calls[:2] == ["on_path", ("rules", "teal")]
    assert calls[2] == ("runs", REPO, lab_home(REPO), REPO / "pair_b" / "fog_lab_stages.json",
                        {"torch": False, "stockfish": "sf", "device": "cpu"})
    assert calls[3][:4] == ("app", REPO, options, "RULES")
    assert list(calls[3][4]) == ["runs"] and type(calls[3][4]["runs"]).__name__ == "FakeRuns"
    assert calls[4:] == [("server", 0), "serve", "server_close", "app.close"]
    assert capsys.readouterr() == ("Fog Lab: http://127.0.0.1:4321  (Ctrl+C to stop)\n", "")


# Catches: --open opening the page before the server listens (the browser would get a refused connection), at the
# port asked for rather than the one the server got (0 asks for any free one), or without being asked.
def test_start_command_opens_the_page_only_with_open(monkeypatch, capsys):
    calls = fake_start(monkeypatch)
    monkeypatch.setattr(start_command.webbrowser, "open", lambda url: calls.append(("open", url)) or True)
    assert start_command.main(["--port", "0"]) == 0
    assert not [c for c in calls if c[0] == "open"]
    calls.clear()
    assert start_command.main(["--port", "0", "--open"]) == 0
    assert calls[-5:] == [("server", 0), ("open", "http://127.0.0.1:4321"), "serve", "server_close", "app.close"]
    assert capsys.readouterr().err == ""


# Catches: a machine with no browser to open (a remote shell, say) stopping Fog Lab, or failing silently.
def test_start_command_still_serves_when_no_browser_opens(monkeypatch, capsys):
    calls = fake_start(monkeypatch)
    monkeypatch.setattr(start_command.webbrowser, "open", lambda url: False)
    assert start_command.main(["--open"]) == 0
    assert "serve" in calls
    assert capsys.readouterr().err == "Fog Lab: no browser opened; open the address above yourself\n"


# Catches: a relative --stockfish path handed on as it is. The Play tab would find the engine, but the Tests tab's
# harness and history checks run in a stage's worktree, where the path points nowhere. The scorers and the test runs
# get the same absolute path.
def test_start_command_makes_a_relative_stockfish_path_absolute(tmp_path, monkeypatch):
    (tmp_path / "engines").mkdir()
    (tmp_path / "engines" / "stockfish-x").write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    calls = fake_start(monkeypatch)
    assert start_command.main(["--port", "0", "--rules", "standin", "--stockfish", "engines/stockfish-x"]) == 0
    absolute = str(Path.cwd() / "engines" / "stockfish-x")
    assert (calls[2][4]["stockfish"], calls[3][2].stockfish) == (absolute, absolute)


# Catches: a path-like --stockfish value (with a folder separator in it, or naming a file that is there, as Windows
# finds stockfish.exe in the folder it starts from) left relative, and a bare command name made into a path, which
# would stop the PATH lookup that finds it.
def test_which_stockfish_values_are_paths(tmp_path, monkeypatch):
    (tmp_path / "engines").mkdir()
    (tmp_path / "engines" / "stockfish-x").write_bytes(b"")
    (tmp_path / "stockfish.exe").write_bytes(b"")
    (tmp_path / "a folder").mkdir()
    monkeypatch.chdir(tmp_path)
    here, engine = Path.cwd(), start_command.engine_path
    assert engine(str(Path("engines", "stockfish-x"))) == str(here / "engines" / "stockfish-x")
    assert engine("engines/not-there-yet") == str(here / "engines" / "not-there-yet")  # a path all the same
    assert engine("stockfish.exe") == str(here / "stockfish.exe")  # a file that is there
    assert engine(str(here / "engines" / "stockfish-x")) == str(here / "engines" / "stockfish-x")  # absolute already
    for name in ("stockfish", "stockfish.exe-elsewhere", "a folder"):  # no file of that name here: the PATH decides
        assert engine(name) == name


# R29. Catches: a Ctrl+C during a test run that leaves its window silent for the seconds the run takes to stop.
def test_start_command_says_it_is_stopping_a_run(monkeypatch, capsys):
    calls = fake_start(monkeypatch, running=True)
    assert start_command.main(["--port", "0", "--rules", "standin"]) == 0
    assert calls[-3:] == ["serve", "server_close", "app.close"]
    assert "stopping the test run" in capsys.readouterr().err


# Catches: a stack trace for a mistake in a flag, a port outside 0..65535 reaching the socket, and Teal's adapter
# being asked for where it is not.
@pytest.mark.parametrize("argv", [["--port", "70000"], ["--port", "-1"], ["--port", "http"], ["--rules", "bogus"],
                                  ["--no-such-flag"]])
def test_start_command_refuses_bad_flags(argv, capsys):
    with pytest.raises(SystemExit) as stopped:
        start_command.main(argv)
    assert stopped.value.code == 2 and "usage" in capsys.readouterr().err


def test_start_command_says_when_teal_is_not_here(monkeypatch, capsys):
    def missing(choice):
        raise ValueError("Teal's rules adapter is not in this checkout")

    monkeypatch.setattr(start_command, "pick_rules", missing)
    with pytest.raises(SystemExit) as stopped:
        start_command.main(["--rules", "teal"])
    assert stopped.value.code == 2 and "Teal's rules adapter is not in this checkout" in capsys.readouterr().err


# Catches: a port that is taken ending in a stack trace, or with nothing said about what to do.
def test_start_command_says_when_the_port_is_taken(capsys):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        assert start_command.main(["--port", str(port), "--rules", "standin"]) == 1
    error = capsys.readouterr().err
    assert f"127.0.0.1:{port}" in error and "--port" in error


# ---- no torch (required test 6, the Play part) ----

# Catches: an import of torch on the way to a running server, a networks row that is not greyed out with the reason,
# a Play tab that does not work with piece values, and a refusal of a network that comes out as a crash.
def test_app_starts_without_torch():
    code = '''
import http.client, json, tempfile, threading
from pathlib import Path
from pairb.lab.paths import repo_root
from pairb.lab.scorers import ScorerOptions
from pairb.lab.server import LabApp, make_server
from pairb.rules import StandinRules

repo = repo_root()
with tempfile.TemporaryDirectory() as home:
    app = LabApp(repo, ScorerOptions(repo / "pair_b" / "checkpoints"), StandinRules(), home=Path(home))
    server = make_server(app, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def call(method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
        connection.request(method, path, None if body is None else json.dumps(body))
        response = connection.getresponse()
        data = json.loads(response.read())
        connection.close()
        return response.status, data

    try:
        status, config = call("GET", "/api/config")
        assert status == 200 and config["torch"] is False, config
        rows = {row["id"]: row for row in config["scorers"]}
        for scorer_id in ("network1", "belief"):
            assert rows[scorer_id]["available"] is False and "torch" in rows[scorer_id]["reason"], rows[scorer_id]
        assert rows["material"]["available"] is True and config["default_scorer"] in ("stockfish-d1", "material")
        status, created = call("POST", "/api/games", {"scorer": "material", "particles": 16, "guesses": 2})
        assert status == 200, created
        status, state = call("POST", "/api/games/" + created["id"] + "/move", {"move": "e2e4"})
        assert status == 200 and state["ply"] == 2 and state["error"] is None, state
        status, refused = call("POST", "/api/games", {"scorer": "network1"})
        assert status == 400 and "torch" in refused["error"], refused
        print("ok")
    finally:
        server.shutdown()
        server.server_close()
        app.close()
'''
    r = run_without_torch(code, PAIR_B)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == "ok"


# ---- paths ----

# Catches: a root found by the working directory (the app is started from pair_b/, but also from elsewhere), a
# folder that holds only one of the two, the outer of two nested checkouts, and no root being a crash with no message.
def test_repo_root_is_the_nearest_folder_holding_fow_shared_and_pair_b(tmp_path):
    (tmp_path / "fow_shared").mkdir()
    deep = tmp_path / "pair_b" / "src" / "pairb" / "lab"
    deep.mkdir(parents=True)
    assert repo_root(deep) == tmp_path.resolve() and repo_root(tmp_path) == tmp_path.resolve()
    assert repo_root(deep / "paths.py") == tmp_path.resolve()  # a file that need not exist
    inner = tmp_path / "pair_b" / "vendor" / "inner"
    (inner / "fow_shared").mkdir(parents=True)
    (inner / "pair_b").mkdir()
    assert repo_root(inner / "pair_b" / "deep") == inner.resolve()
    lonely = tmp_path / "elsewhere"
    lonely.mkdir()
    (lonely / "pair_b").mkdir()
    assert repo_root(lonely / "pair_b") == tmp_path.resolve()  # only one of the two there: keep looking upwards
    with pytest.raises(FileNotFoundError, match="fow_shared"):
        repo_root(tmp_path.parent / "no-such-checkout")


def test_repo_root_defaults_to_the_checkout_this_code_is_in():
    assert repo_root() == REPO.resolve()


# Ruling R10. Catches: a start command that cannot find Teal's package because nothing put the repo root on the path (in
# a fresh interpreter started in pair_b/ it is not there: the editable install of fow_shared adds only fow_shared).
def test_ensure_repo_on_path_makes_the_teams_packages_importable_in_a_fresh_interpreter():
    code = ("import importlib.util as u\n"
            "if u.find_spec('pair_a_prep') is not None: raise SystemExit('already importable')\n"
            "from pairb.lab.paths import ensure_repo_on_path\n"
            "ensure_repo_on_path()\n"
            "assert u.find_spec('pair_a_prep') is not None\n"
            "print('ok')\n")
    r = subprocess.run([sys.executable, "-E", "-c", code], cwd=PAIR_B, capture_output=True, encoding="utf-8",
                       errors="replace", timeout=300)
    if "already importable" in r.stderr:
        pytest.skip("the repo root is on this environment's import path already")
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stdout + r.stderr


# Catches: a path inserted twice, appended where the working directory would still win, or not returned.
def test_ensure_repo_on_path_inserts_the_root_once(monkeypatch):
    root = repo_root()
    monkeypatch.setattr(sys, "path", [item for item in sys.path if item != str(root)])
    assert ensure_repo_on_path() == root and sys.path[0] == str(root)
    assert ensure_repo_on_path() == root and sys.path.count(str(root)) == 1


# Required test 7, in part. Catches: an interpreter path built with the wrong separator or folder for the platform,
# a path with spaces split or quoted (it is passed as one argument), and windows=None not following the machine.
def test_venv_python_for_each_platform():
    unix = venv_python(Path("/work/Pair B/pair_b"), windows=False)
    assert unix.parts[-3:] == (".venv", "bin", "python") and unix == Path("/work/Pair B/pair_b/.venv/bin/python")
    windows = venv_python(Path("C:/Users/Teal Lee/pair_b"), windows=True)
    assert windows.parts[-3:] == (".venv", "Scripts", "python.exe")
    assert str(windows).startswith(str(Path("C:/Users/Teal Lee/pair_b"))) and "Teal Lee" in str(windows)
    assert venv_python(Path("p")) == venv_python(Path("p"), windows=os.name == "nt")


def test_lab_home_is_inside_pair_b():
    assert lab_home(Path("/some/repo")) == Path("/some/repo/pair_b/.fog_lab")


# Ruling R5, and R6. Catches: an app whose home is not the lab's folder unless it is told otherwise, one that cannot be
# told, and a games folder that git would see (a saved game is megabytes and nobody's to commit).
def test_home_defaults_to_the_labs_folder_and_that_folder_is_ignored_by_git(tmp_path):
    options = ScorerOptions(tmp_path)
    assert LabApp(tmp_path, options, StandinRules()).home == lab_home(tmp_path)
    assert LabApp(tmp_path, options, StandinRules(), home=tmp_path / "elsewhere").home == tmp_path / "elsewhere"
    assert ".fog_lab/" in (PAIR_B / ".gitignore").read_text(encoding="utf-8").split()
