"""Fog Lab's server: a small JSON API over one live game and loaded replays, and the page's files.

It is the standard library's ThreadingHTTPServer on 127.0.0.1 only, with no framework. Chess stays on the server: the
page draws what it is sent and sends clicks. Routes (an error is {"error": message} with 400, 403, 404 or 500):

    GET  /                          the page, static/index.html
    GET  /static/<name>             a file directly inside static/, else 404
    GET  /api/config                {rules: {name, label}, scorers: [{id, label, available, reason}], default_scorer,
                                    torch, machine}
    POST /api/games                 GameOptions fields (scorer: default_scorer when absent) -> {id, state}
    GET  /api/games/<id>[?ply=n]    Session.state(n)
    POST /api/games/<id>/move       {move} -> the state after the move and the bot's reply
    GET  /api/games/<id>/record     the record as JSON; 403 for a fair game that is still going
    POST /api/games/<id>/save       writes it to <home>/games/<YYYYMMDD-HHMMSS>-<id>.json -> {name}; 403 likewise
    GET  /api/saved                 [{name, modified}], newest first
    POST /api/replays               a record, or {name} of a saved game -> {id, plies}
    GET  /api/replays/<id>[?ply=n]  view_state(record, n, reveal=True), plus "error" as a live state has it

One game is live at a time: a new game closes the old one. Replays are kept in memory, the newest few. LabApp holds
both behind one lock that guards only its own fields: it is never held while a Session works, since a bot's turn can
take long, and a Session holds its own lock for every use. The app calls a Session through its public methods alone.

The server decides nothing about what a fair game may show. Session.state() does, and Session.revealed says when the
record may go out: the record and save routes answer 403 until it is True (Rulings R16 and R17). A replay always
reveals: it is a record that has already been given out. The text of an unexpected exception never reaches the page,
since it may hold a position: it goes to the window that started the app.

A scorer that fails to open (an engine that will not start, a checkpoint that will not load) is a 400 with the error's
message, and is listed as unavailable with that message until the server restarts (Ruling R14).

Safety. The server answers only requests addressed to the machine itself (a Host of 127.0.0.1, localhost or ::1) and
only from a page of its own (an Origin, when the request has one, equal to its Host), so a web page on another site
cannot use a visitor's browser to start games or write files, nor can DNS rebinding bring one in. A file name from the
page is checked before any file is read: a static file's against a short list of safe characters, and then resolved;
a saved game's for folders, drives and NUL. The server writes only into <home>/games, under names it makes itself.

Routes are the entries of ROUTES: a method, a pattern for the path and the name of the LabApp method that answers it.
"""
import contextlib
import dataclasses
import json
import os
import platform
import re
import sys
import tempfile
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
from .paths import lab_home
from .record import GameRecord, view_state
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
_STATIC_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")  # one name, no folders, no dot files, no drives
_PLY = re.compile(r"-?[0-9]{1,9}")  # ASCII digits only: int() also reads others


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
)
_ROUTES = tuple((method, re.compile(pattern), name) for method, pattern, name in ROUTES)


class LabApp:
    """What the server serves: the live game, the loaded replays, the scorers and where games are saved.

    `repo` is the team repository's root; `scorer_opts` says where Stockfish and the checkpoints are; `rules` is the
    rules implementation every game uses; `runs` is the manager of background test runs, for the routes that start and
    report them, or None; `home` is where games are saved, by default lab_home(repo): tests give a folder of their
    own, so nothing is written into the checkout. Request methods are called from many threads at once.
    """

    def __init__(self, repo: Path, scorer_opts: ScorerOptions, rules: Rules, runs=None, home: Path | None = None):
        self.repo = Path(repo)
        self.scorer_opts = scorer_opts
        self.rules = rules
        self.runs = runs
        self.home = lab_home(self.repo) if home is None else Path(home)
        self._lock = threading.Lock()  # guards the three fields below, and nothing else
        self._session: Session | None = None
        self._replays: dict[str, GameRecord] = {}  # oldest first
        self._failed: dict[str, str] = {}  # scorer id -> why it failed to open

    def close(self) -> None:
        """Close the live game (its scorers, so no engine is left running). Calling it again does nothing."""
        with self._lock:
            session, self._session = self._session, None
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
        that the rules refuse."""
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
            previous, self._session = self._session, session
        if previous is not None:
            previous.close()
        return {"id": session.id, "state": session.state()}

    def game_state(self, request: Request) -> dict:
        return _state(self._game(request.args["id"]), request.ply())

    def move(self, request: Request) -> dict:
        session = self._game(request.args["id"])
        try:
            session.human_move(request.read_object().get("move"))
        except ValueError as error:
            raise ApiError(400, str(error)) from error
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
            _write_atomically(folder / name, json.dumps(record, ensure_ascii=False, indent=1))
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
        try:
            entries = list((self.home / "games").iterdir())
        except FileNotFoundError:
            return []
        found = []
        for path in entries:
            with contextlib.suppress(OSError):  # a file that was removed since the listing is not listed
                if path.suffix == ".json" and path.is_file():
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
        if not isinstance(name, str) or not name or name in (".", "..") or re.search(r"[/\\:\x00]", name):
            raise ApiError(400, "name must be the name of a saved game, with no folders")
        path = self.home / "games" / name
        if not path.is_file():
            raise ApiError(404, f"there is no saved game called {name}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError) as error:  # ValueError holds bad UTF-8 and bad JSON
            raise ApiError(400, f"{name} could not be read as a saved game") from error


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


def _write_atomically(path: Path, text: str) -> None:
    """Write `text` to `path` as UTF-8 so that a reader sees the whole file or none: into a temporary file in the same
    folder (which the games listing skips), then renamed over the name."""
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".saving-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


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
            self._check_origin()
            reply = self.server.app.handle("GET" if self.command == "HEAD" else self.command, self.path, body)
        except ApiError as error:
            reply = error_reply(error.status, error.message)
        except ConnectionError:
            raise  # the client left: nobody to answer, and handle_error says nothing of it
        except Exception:
            print(f"Fog Lab: {self.command} {self.path!r} failed:", file=sys.stderr)
            traceback.print_exc()
            reply = error_reply(500, "internal error: the window that started Fog Lab has the details")
        self._send(reply)

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
        self.send_response(reply.status)
        self.send_header("Content-Type", reply.content_type)
        self.send_header("Content-Length", str(len(reply.body)))
        self.send_header("Cache-Control", "no-store")
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
