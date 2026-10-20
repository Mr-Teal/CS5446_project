"""Fog Lab's server: a small JSON API over one live game, loaded replays and the test runs, and the page's files.

It is the standard library's ThreadingHTTPServer on 127.0.0.1 only, with no framework. Chess stays on the server: the
page draws what it is sent and sends clicks. Routes (an error is {"error": message} with 400, 403, 404, 409 or 500):

    GET  /                          the page, static/index.html
    GET  /static/<name>             a file directly inside static/, else 404
    GET  /api/config                {rules: {name, label}, scorers: [{id, label, available, reason}], default_scorer,
                                    torch, machine}
    POST /api/games                 GameOptions fields (scorer: default_scorer when absent) -> {id, state}; 409 once
                                    the app is closing
    GET  /api/games/<id>[?ply=n]    Session.state(n)
    POST /api/games/<id>/move       {move} -> the state after the move and the bot's reply
    GET  /api/games/<id>/record     the record as JSON; 403 for a fair game that is still going
    POST /api/games/<id>/save       writes it to <home>/games/<YYYYMMDD-HHMMSS>-<id>.json -> {name}; 403 likewise
    GET  /api/saved                 [{name, modified}], newest first
    POST /api/replays               a record, or {name} of a saved game -> {id, plies}
    GET  /api/replays/<id>[?ply=n]  view_state(record, n, reveal=True), plus "error": the failed turn's, at the last ply
    POST /api/tests/run             {fetch} (true when absent) -> 202 {id}; 409 while a run is going or when closing
    GET  /api/tests/status          RunManager.status(): {running, id, started, progress, stages, error}
    GET  /api/tests/latest          the newest saved run's summary (runs.py); 404 when there is none
    GET  /api/tests/runs/<id>/logs/<name>   that run's log, as text/plain; 404 for anything but a file in its logs/

The test routes are 404 in an app made without a run manager (`runs`).

One game is live at a time: a new game closes the old one. Replays are kept in memory, the newest few. LabApp holds
both behind one lock that guards only its own fields: it is never held while a Session works, since a bot's turn can
take long, and a Session holds its own lock for every use. The app calls a Session through its public methods alone.
Once the app is closed (close(), on the way out), no game goes live: one that was still opening its scorers is closed
and answered 409 (R19). The test runs are the RunManager's (runs.py): one at a time, in a thread of its own, saved under
<home>/runs, and stopped when the app closes (R29).

The server decides nothing about what a fair game may show. Session.state() does, and Session.revealed says when the
record may go out: the record and save routes answer 403 until it is True (Rulings R16 and R17). A replay always
reveals: it is a record that has already been given out. The text of an unexpected exception never reaches the page,
since it may hold a position: it goes to the window that started the app.

A scorer that fails to open (an engine that will not start, a checkpoint that will not load) is a 400 with the error's
message, and is listed as unavailable with that message until the server restarts (Ruling R14).

Safety. The server answers only requests addressed to the machine itself (a Host of 127.0.0.1, localhost or ::1) and
only from a page of its own (an Origin, when the request has one, equal to its Host), so a web page on another site
cannot use a visitor's browser to start games, start runs or write files, nor can DNS rebinding bring one in. A file
name from the page is checked before any file is read: a static file's against a short list of safe characters, and
then resolved; a saved game's for folders, drives and NUL; a log's and its run id by the RunManager. Each is at most 128
characters, so no name is too long for the file system (Python 3.12's Path.is_file raises for one: R19). The server
writes only into <home>/games, under names it makes itself, and its RunManager only into <home>/runs. Every answer
forbids type sniffing (X-Content-Type-Options) and framing by any page (X-Frame-Options and the CSP frame-ancestors).

Routes are the entries of ROUTES: a method, a pattern for the path and the name of the LabApp method that answers it.
"""
import contextlib
import dataclasses
import json
import os
import platform
import re
import sys
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePath
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from ..rules import Rules
from .paths import lab_home, write_atomically
from .record import GameRecord, view_state
from .runs import RunBusy, RunManager
from .scorers import ScorerInfo, ScorerOptions, available_scorers, default_scorer, open_scorer, torch_available
from .session import GameOptions, Session

LOOPBACK = "127.0.0.1"
LOCAL_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})
STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY = 64 * 1024 * 1024  # the most a request may carry: a record of a long game is a few megabytes
MAX_REPLAYS = 8  # loaded replays kept in memory, the newest
JSON_TYPE = "application/json; charset=utf-8"
# Content types are listed here and not looked up with the mimetypes module, which reads the Windows registry, where
# a script may be registered as text/plain, and a browser refuses to load an ES module sent that way.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": JSON_TYPE,
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}
_STATIC_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")  # one name: no folders, dot files or drives, 128 at most
MAX_SAVED_NAME = 128  # characters in the name of a saved game the page may load
_PLY = re.compile(r"-?[0-9]{1,9}")  # ASCII digits only: int() also reads others
_CLOSING = "Fog Lab is shutting down, so no game can start"


class ApiError(Exception):
    """An answer that is an error: the HTTP status and the message the page gets."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass(frozen=True)
class Reply:
    """What a route answers with: the body's bytes, their content type and the status."""

    body: bytes
    content_type: str = JSON_TYPE
    status: int = 200


def json_reply(value: Any, status: int = 200) -> Reply:
    return Reply(json.dumps(value).encode("utf-8"), JSON_TYPE, status)


def error_reply(status: int, message: str) -> Reply:
    return json_reply({"error": message}, status)


@dataclass
class Request:
    """One request, as a route sees it: the path with its query parsed, the body's bytes, and the named parts of the
    route's pattern (such as the game's id), unquoted."""

    method: str
    path: str
    query: dict[str, list[str]]
    body: bytes
    args: dict[str, str] = field(default_factory=dict)

    def read_json(self) -> Any:
        """The body as JSON; an empty body is {}. ApiError (400) for anything that is not valid JSON."""
        if not self.body.strip():
            return {}
        try:
            return json.loads(self.body)
        except (ValueError, RecursionError):  # ValueError holds bad UTF-8 and bad JSON; the other is nesting too deep
            raise ApiError(400, "the request body is not valid JSON") from None

    def read_object(self) -> dict:
        """The body as a JSON object. ApiError (400) for another kind of JSON."""
        data = self.read_json()
        if not isinstance(data, dict):
            raise ApiError(400, "the request body must be a JSON object")
        return data

    def ply(self) -> int | None:
        """The ?ply= step: None when there is none, else a whole number (its range is for the caller to check).
        ApiError (400) when it is not one whole number."""
        values = self.query.get("ply")
        if values is None:
            return None
        if len(values) != 1 or not _PLY.fullmatch(values[0]):
            raise ApiError(400, "ply must be one whole number")
        return int(values[0])


ROUTES = (
    ("GET", r"/", "index"),
    ("GET", r"/static/(?P<name>.*)", "static"),
    ("GET", r"/api/config", "config"),
    ("POST", r"/api/games", "new_game"),
    ("GET", r"/api/games/(?P<id>[^/]+)", "game_state"),
    ("POST", r"/api/games/(?P<id>[^/]+)/move", "move"),
    ("GET", r"/api/games/(?P<id>[^/]+)/record", "record"),
    ("POST", r"/api/games/(?P<id>[^/]+)/save", "save"),
    ("GET", r"/api/saved", "saved"),
    ("POST", r"/api/replays", "new_replay"),
    ("GET", r"/api/replays/(?P<id>[^/]+)", "replay_state"),
    ("POST", r"/api/tests/run", "start_run"),
    ("GET", r"/api/tests/status", "run_status"),
    ("GET", r"/api/tests/latest", "latest_run"),
    ("GET", r"/api/tests/runs/(?P<id>[^/]+)/logs/(?P<name>[^/]+)", "run_log"),
)
_ROUTES = tuple((method, re.compile(pattern), name) for method, pattern, name in ROUTES)


class LabApp:
    """What the server serves: the live game, the loaded replays, the scorers and where games are saved.

    `repo` is the team repository's root; `scorer_opts` says where Stockfish and the checkpoints are; `rules` is the
    rules implementation every game uses; `runs` is the RunManager of the background test runs, for the routes that
    start and report them, or None; `home` is where games are saved, by default lab_home(repo): tests give a folder of
    their own, so nothing is written into the checkout. Request methods are called from many threads at once.
    """

    def __init__(self, repo: Path, scorer_opts: ScorerOptions, rules: Rules, runs: RunManager | None = None,
                 home: Path | None = None):
        self.repo = Path(repo)
        self.scorer_opts = scorer_opts
        self.rules = rules
        self.runs = runs
        self.home = lab_home(self.repo) if home is None else Path(home)
        self._lock = threading.Lock()  # guards the four fields below, and nothing else
        self._closed = False  # set by close(): no game goes live after it (R19)
        self._session: Session | None = None
        self._replays: dict[str, GameRecord] = {}  # oldest first
        self._failed: dict[str, str] = {}  # scorer id -> why it failed to open

    def close(self) -> None:
        """Stop the test run that is going (R29), waiting a little for it to be saved, then close the live game (its
        scorers, so no engine is left running). No game goes live and no run starts afterwards. The runs come first:
        closing a game waits for a bot's turn in progress, and a run asked for meanwhile would still have started.
        Calling it again does nothing."""
        with self._lock:
            self._closed = True
            session, self._session = self._session, None
        if self.runs is not None:
            self.runs.close()
        if session is not None:
            session.close()

    def handle(self, method: str, target: str, body: bytes) -> Reply:
        """The answer to a request: `target` is the request line's path with its query. ApiError for an error."""
        path, _, query = target.partition("?")
        request = Request(method, path, parse_qs(query, keep_blank_values=True), body)
        for verb, pattern, name in _ROUTES:
            match = pattern.fullmatch(path) if verb == method else None
            if match:
                request.args = {key: unquote(value) for key, value in match.groupdict().items()}
                answer = getattr(self, name)(request)
                return answer if isinstance(answer, Reply) else json_reply(answer)
        raise ApiError(404, f"there is no {method} route for {path}")

    # ---- the page ----

    def index(self, request: Request) -> Reply:
        return _static_file("index.html")

    def static(self, request: Request) -> Reply:
        return _static_file(request.args["name"])

    # ---- configuration ----

    def config(self, request: Request) -> dict:
        infos = self._scorers()
        return {"rules": {"name": self.rules.name, "label": self.rules.label},
                "scorers": [dataclasses.asdict(info) for info in infos],
                "default_scorer": default_scorer(infos),
                "torch": torch_available(),
                "machine": _machine()}

    def _scorers(self) -> list[ScorerInfo]:
        """The registry's listing, with each scorer that has failed to open since the server started marked as
        unavailable with the error's text. A scorer the registry itself holds back keeps the registry's reason, which
        is found afresh on every call: it comes first because it is the one the user can act on."""
        with self._lock:
            failed = dict(self._failed)
        return [dataclasses.replace(info, available=False, reason=failed[info.id])
                if info.available and info.id in failed else info
                for info in available_scorers(self.scorer_opts)]

    # ---- the live game ----

    def new_game(self, request: Request) -> dict:
        """Start a game and make it the live one, closing the old one. The old game is left alone if the new one
        cannot be started: 400 for options that are wrong, a scorer that is unavailable or will not open, and a start
        that the rules refuse. 409 once the app is closing, even for a game that was opening its scorers when it
        closed: that one is closed at once (R19)."""
        with self._lock:
            if self._closed:
                raise ApiError(409, _CLOSING)
        fields = request.read_object()
        if "scorer" not in fields:
            fields = {**fields, "scorer": default_scorer(self._scorers())}
        unknown = sorted(set(fields) - {option.name for option in dataclasses.fields(GameOptions)})
        if unknown:
            raise ApiError(400, f"unknown option: {', '.join(unknown)}")
        try:
            options = GameOptions(**fields)
        except (TypeError, ValueError) as error:
            raise ApiError(400, str(error)) from error
        bot, inspector = self._open_scorers(options.scorer)
        try:
            session = Session(options, self.rules, bot, inspector)  # owns both scorers: closes them if it raises
        except ValueError as error:
            raise ApiError(400, str(error)) from error
        with self._lock:
            closed = self._closed
            if not closed:
                previous, self._session = self._session, session
        if closed:  # the app closed while the scorers opened: nobody would close this game
            session.close()
            raise ApiError(409, _CLOSING)
        if previous is not None:
            previous.close()
        return {"id": session.id, "state": session.state()}

    def game_state(self, request: Request) -> dict:
        return _state(self._game(request.args["id"]), request.ply())

    def move(self, request: Request) -> dict:
        session = self._game(request.args["id"])
        fields = request.read_object()
        intermediate = fields.get("include_after_human", False)
        if not isinstance(intermediate, bool):
            raise ApiError(400, "include_after_human must be a boolean")
        try:
            after_human = session.human_move(fields.get("move"), include_after_human=intermediate)
        except ValueError as error:
            raise ApiError(400, str(error)) from error
        if intermediate:
            return {"after_human": after_human, "state": session.state()}
        return session.state()

    def record(self, request: Request) -> dict:
        session = self._game(request.args["id"])
        if not session.revealed:
            raise ApiError(403, "a fair game's record stays closed until the game is over")
        return session.record_json()

    def save(self, request: Request) -> dict:
        session = self._game(request.args["id"])
        if not session.revealed:
            raise ApiError(403, "a fair game cannot be saved until the game is over")
        record = session.record_json()
        name = f"{datetime.now():%Y%m%d-%H%M%S}-{session.id}.json"
        folder = self.home / "games"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            write_atomically(folder / name, json.dumps(record, ensure_ascii=False, indent=1))
        except OSError as error:
            raise ApiError(500, f"could not save the game: {error}") from error
        return {"name": name}

    def _game(self, game_id: str) -> Session:
        with self._lock:
            session = self._session
        if session is None or session.id != game_id:
            raise ApiError(404, f"there is no game {game_id}: only the newest game is kept")
        return session

    def _open_scorers(self, scorer_id: str) -> tuple:
        """The bot's scorer and the inspector's, two objects opened separately (the bot must never share an engine's
        memory with the app's look at the true board). ApiError (400) when the scorer has failed before, or fails now;
        the first is closed if the second fails."""
        with self._lock:
            known = self._failed.get(scorer_id)
        if known is not None:
            raise ApiError(400, known)
        bot = self._open_scorer(scorer_id)
        try:
            return bot, self._open_scorer(scorer_id)
        except BaseException:
            with contextlib.suppress(Exception):
                bot.close()
            raise

    def _open_scorer(self, scorer_id: str):
        try:
            return open_scorer(scorer_id, self.scorer_opts)
        except Exception as error:  # not only ValueError: an engine or a checkpoint can fail in any way
            reason = str(error) or type(error).__name__
            if next(info for info in self._scorers() if info.id == scorer_id).available:  # else the registry knows why
                with self._lock:
                    self._failed[scorer_id] = reason
            raise ApiError(400, reason) from error

    # ---- saved games and replays ----

    def saved(self, request: Request) -> list[dict]:
        """The saved games the page may load. 500 with the reason when the games folder cannot be listed (R19)."""
        try:
            entries = list((self.home / "games").iterdir())
        except FileNotFoundError:
            return []
        except OSError as error:  # the games path is a file, or may not be read
            raise ApiError(500, f"could not list the saved games: {error}") from error
        found = []
        for path in entries:
            with contextlib.suppress(OSError):  # a file that was removed since the listing is not listed
                if path.suffix == ".json" and _saved_name_ok(path.name) and path.is_file():
                    found.append((path.stat().st_mtime_ns, path.name))
        found.sort(reverse=True)
        return [{"name": name, "modified": _local_time(stamp)} for stamp, name in found]

    def new_replay(self, request: Request) -> dict:
        body = request.read_json()
        data = self._saved_json(body["name"]) if isinstance(body, dict) and set(body) == {"name"} else body
        try:
            record = GameRecord.from_json(data)
        except ValueError as error:
            raise ApiError(400, str(error)) from error
        replay_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._replays[replay_id] = record
            while len(self._replays) > MAX_REPLAYS:
                del self._replays[next(iter(self._replays))]
        return {"id": replay_id, "plies": len(record.plies)}

    def replay_state(self, request: Request) -> dict:
        replay_id = request.args["id"]
        with self._lock:
            record = self._replays.get(replay_id)
        if record is None:
            raise ApiError(404, f"there is no replay {replay_id}: only the newest {MAX_REPLAYS} are kept")
        try:
            state = view_state(record, request.ply(), reveal=True)
        except ValueError as error:
            raise ApiError(400, str(error)) from error
        # A turn that failed is the last bot turn, with the ply after the last move, and live play shows its error
        # exactly at that step.
        failed = record.bot_turns[-1] if record.bot_turns else None
        stopped = failed is not None and failed.ply == len(record.plies) and state["ply"] == len(record.plies)
        state["error"] = failed.error if stopped else None
        return state

    def _saved_json(self, name: Any) -> Any:
        """The JSON in the saved game called `name`, a file directly inside the games folder."""
        if not _saved_name_ok(name):
            raise ApiError(400, f"name must be the name of a saved game: no folders, {MAX_SAVED_NAME} characters at "
                                "most")
        path = self.home / "games" / name
        try:
            found = path.is_file()
        except OSError:  # Python 3.12 raises for a name the file system cannot hold (too many bytes); 3.14 says False
            found = False
        if not found:
            raise ApiError(404, f"there is no saved game called {name}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError) as error:  # ValueError holds bad UTF-8 and bad JSON
            raise ApiError(400, f"{name} could not be read as a saved game") from error

    # ---- test runs (the Tests tab) ----

    def start_run(self, request: Request) -> Reply:
        """Start a test run: 202 {id}. 400 for a body other than {"fetch": true or false} (fetch is true when absent:
        the page never sends a ref); 409 while a run is going or when the app is closing."""
        runs = self._runs()
        fields = request.read_object()
        unknown = sorted(set(fields) - {"fetch"})
        if unknown:
            raise ApiError(400, f"unknown option: {', '.join(unknown)}")
        fetch = fields.get("fetch", True)
        if not isinstance(fetch, bool):
            raise ApiError(400, "fetch must be true or false")
        try:
            run_id = runs.start(fetch)
        except RunBusy as error:
            raise ApiError(409, str(error)) from error
        except OSError as error:  # its folder could not be made
            raise ApiError(500, f"could not start the test run: {error}") from error
        return json_reply({"id": run_id}, 202)

    def run_status(self, request: Request) -> dict:
        return self._runs().status()

    def latest_run(self, request: Request) -> dict:
        summary = self._runs().latest()
        if summary is None:
            raise ApiError(404, "no test run has been saved yet")
        return summary

    def run_log(self, request: Request) -> Reply:
        """A log of a run, as text: only a file directly inside that run's logs folder (RunManager.log_path)."""
        runs = self._runs()
        try:
            path = runs.log_path(request.args["id"], request.args["name"])
            body = path.read_bytes() if path.is_file() else None
        except (ValueError, OSError):
            body = None
        if body is None:
            raise ApiError(404, "there is no such log")
        return Reply(body, CONTENT_TYPES[".txt"])

    def _runs(self) -> RunManager:
        if self.runs is None:
            raise ApiError(404, "this Fog Lab was started without test runs")
        return self.runs


def _saved_name_ok(name: Any) -> bool:
    """Whether `name` may be the name of a saved game to load: text of 1 to MAX_SAVED_NAME characters, not "." or
    "..", with no folder, drive or NUL in it. The listing offers only such names."""
    return (isinstance(name, str) and 0 < len(name) <= MAX_SAVED_NAME and name not in (".", "..")
            and not re.search(r"[/\\:\x00]", name))


def _state(session: Session, upto: int | None) -> dict:
    try:
        return session.state(upto)
    except ValueError as error:
        raise ApiError(400, str(error)) from error


def _static_file(name: str) -> Reply:
    """The file called `name` directly inside STATIC_DIR, as bytes with its content type. ApiError (404) for anything
    else: a folder, a path, a dot file, a name outside the safe characters, or a link that leads out of the folder."""
    folder = STATIC_DIR.resolve()
    if _STATIC_NAME.fullmatch(name):
        path = (folder / name).resolve()
        if path.parent == folder and path.is_file():
            try:
                body = path.read_bytes()
            except OSError:
                raise ApiError(404, "there is no such file") from None
            return Reply(body, CONTENT_TYPES.get(PurePath(name).suffix.lower(), "application/octet-stream"))
    raise ApiError(404, "there is no such file")


def _local_time(nanoseconds: int) -> str:
    """A file's modification time (st_mtime_ns) as local time with its UTC offset, such as 2026-10-19T15:20:01+08:00."""
    return datetime.fromtimestamp(nanoseconds / 1e9).astimezone().isoformat(timespec="seconds")


def _machine() -> str:
    """The operating system and processor, such as "macOS arm64" or "Windows AMD64": it tells why there is no torch."""
    system = platform.system()
    return f"{'macOS' if system == 'Darwin' else system} {platform.machine()}".strip()


def _hostname(host: str) -> str | None:
    """The host name in a Host header, without its port, or None if there is none to be read."""
    try:
        return urlsplit("//" + host).hostname
    except ValueError:
        return None


class _Handler(BaseHTTPRequestHandler):
    """Reads a request, has the app answer it, and writes the answer. Every answer is complete (Content-Length) and the
    connection closes after it (HTTP/1.0), so nothing is left half-read between requests."""

    timeout = 60  # seconds a client may stay silent before its connection is dropped

    def do_GET(self) -> None:
        self._serve()

    do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_GET  # only GET and POST have routes

    def _serve(self) -> None:
        try:
            body = self._read_body()  # first, so that a refusal does not leave a body unread on the connection
        except ConnectionError:
            raise  # the client left mid-upload: nobody is there to answer, and handle_error says nothing of it
        except Exception as error:
            self._send(self._failure(error))
            return
        try:
            self._check_origin()
            reply = self.server.app.handle("GET" if self.command == "HEAD" else self.command, self.path, body)
        except Exception as error:  # a ConnectionError from a route too: a failure like any other (R19)
            reply = self._failure(error)
        self._send(reply)

    def _failure(self, error: Exception) -> Reply:
        """The answer for an exception: an ApiError's own, or else a 500 whose details (they may hold a position) go
        to the window that started the app and never to the page."""
        if isinstance(error, ApiError):
            return error_reply(error.status, error.message)
        print(f"Fog Lab: {self.command} {self.path!r} failed:", file=sys.stderr)
        traceback.print_exception(error)
        return error_reply(500, "internal error: the window that started Fog Lab has the details")

    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if length is None:
            return b""
        if not re.fullmatch(r"[0-9]{1,12}", length.strip()):
            raise ApiError(400, "Content-Length must be a number of bytes")
        if int(length) > MAX_BODY:
            raise ApiError(400, f"the request body is too large: the limit is {MAX_BODY // 2 ** 20} MB")
        try:
            body = self.rfile.read(int(length))
        except TimeoutError:
            raise ApiError(400, "timed out waiting for the request body") from None
        if len(body) < int(length):
            raise ApiError(400, "the request body ended before its Content-Length")
        return body

    def _check_origin(self) -> None:
        host = self.headers.get("Host")
        if host is not None and _hostname(host) not in LOCAL_NAMES:
            raise ApiError(403, "Fog Lab answers only requests addressed to 127.0.0.1 or localhost")
        origin = self.headers.get("Origin")
        if origin is not None and (host is None or origin.lower() != f"http://{host}".lower()):
            raise ApiError(403, "Fog Lab answers only its own page, not a page from another site")

    def _send(self, reply: Reply) -> None:
        """Write `reply`. Every answer, an error too, says that its type is not to be guessed and that no page may
        frame it (so another site cannot trick a click on Fog Lab's page into starting a run or a game)."""
        self.send_response(reply.status)
        self.send_header("Content-Type", reply.content_type)
        self.send_header("Content-Length", str(len(reply.body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(reply.body)

    def send_error(self, code, message=None, explain=None) -> None:
        """The library calls this for a request it cannot read (a bad request line, a version it does not know, a line
        that is too long): the answer is JSON, like every other."""
        self.close_connection = True
        self._send(error_reply(code, message or self.responses.get(code, ("error",))[0]))

    def log_message(self, format, *args) -> None:
        pass  # the page makes many requests; failures are printed where they happen


class _LabServer(ThreadingHTTPServer):
    """A ThreadingHTTPServer that knows its app."""

    # On Windows SO_REUSEADDR lets a second server bind a port that is in use, and then neither is sure of its
    # requests; there a taken port should be an error. Elsewhere it only allows an immediate restart.
    allow_reuse_address = os.name != "nt"
    app: LabApp

    def handle_error(self, request, client_address) -> None:
        if not isinstance(sys.exc_info()[1], ConnectionError):  # a browser that leaves mid-answer is no news
            super().handle_error(request, client_address)


def make_server(app: LabApp, port: int = 8765) -> ThreadingHTTPServer:
    """A server for `app` on 127.0.0.1 at `port`; 0 takes any free port, which server_address[1] then says. It is
    not serving yet: run serve_forever() (in a thread, in a test), then shutdown() from another thread and
    server_close(). OSError when the port is taken."""
    httpd = _LabServer((LOOPBACK, port), _Handler)
    httpd.app = app
    return httpd
