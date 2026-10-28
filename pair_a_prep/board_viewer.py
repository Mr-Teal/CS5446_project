"""Local chessboard viewer backed by RulesAdapter; no engine or tracker required."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import RLock
from urllib.parse import parse_qs, urlparse

import chess

from .rules_adapter import RulesAdapter


DEMOS = {
    "king_capture": {"name": "Opening to king capture", "fen": None,
                     "moves": ["e2e4", "f7f6", "d1h5", "g7g5", "h5e8"]},
    "castling": {"name": "Castle out of check", "fen": "8/8/8/8/8/4k3/4q3/4K2R w K - 0 1",
                 "moves": ["e1g1", "e3d3"]},
    "en_passant": {"name": "En passant capture", "fen": "7k/8/8/4Pp2/8/8/8/K7 w - f6 0 2",
                   "moves": ["e5f6", "h8g8"]},
    "promotion": {"name": "Pawn promotion", "fen": "7k/P7/8/8/8/8/8/7K w - - 0 1",
                  "moves": ["a7a8n", "h8g8"]},
    "repetition": {"name": "Threefold repetition", "fen": None,
                   "moves": ["g1f3", "g8f6", "f3g1", "f6g8"] * 2},
}


class BoardSession:
    """One local inspection session, with history and a revision for stale tabs."""

    def __init__(self):
        self.rules = RulesAdapter()
        self.lock = RLock()
        self.revision = 0
        self.states = [self.rules.initial_state()]
        self.moves = []
        self.cursor = 0

    def snapshot(self, view="full"):
        if view not in ("full", "white", "black"):
            raise ValueError("unknown board view")
        state = self.states[self.cursor]
        side = self.rules.current_player(state)
        ended = self.rules.terminal(state)
        if view == "full":
            board = state.board_copy()
            visible = [chess.square_name(sq) for sq in chess.SQUARES]
            pieces = {sq: (piece.symbol() if piece else None) for sq in visible
                      for piece in [board.piece_at(chess.parse_square(sq))]}
            legal = self.rules.legal_moves(state)
            captured = state.captured_square
        else:
            obs = self.rules.observe(state, view)
            visible, pieces, legal = obs.visible_squares, dict(obs.visible_pieces), obs.legal_moves
            captured = obs.captured_own_piece_at
        last = None
        if self.cursor:
            mover = self.rules.current_player(self.states[self.cursor - 1])
            if view == "full" or view == mover:
                last = self.moves[self.cursor - 1]
        history = []
        for i, move in enumerate(self.moves):
            mover = self.rules.current_player(self.states[i])
            history.append({"ply": i + 1, "player": mover,
                            "move": move if view == "full" or view == mover else None})
        return {"revision": self.revision, "view": view, "ply": state.ply, "side_to_move": side,
                "visible_squares": visible, "pieces": pieces, "legal_moves": legal,
                "captured_square": captured, "last_move": last,
                "terminal": ended is not None, "winner": ended.winner if ended else None,
                "reason": ended.reason if ended else None, "fen": state.fen if view == "full" else None,
                "cursor": self.cursor, "total_plies": len(self.moves), "history": history,
                "demos": {key: demo["name"] for key, demo in DEMOS.items()}}

    def mutate(self, action, payload):
        with self.lock:
            if type(payload.get("revision")) is not int or payload["revision"] != self.revision:
                raise StaleRevision("The board changed. Refresh and try again.")
            view = payload.get("view", "full")
            if view not in ("full", "white", "black"):
                raise ValueError("unknown board view")
            if action == "move":
                state = self.states[self.cursor]
                if view != "full" and view != self.rules.current_player(state):
                    raise ValueError("Switch to the acting player's view to move.")
                successor = self.rules.apply_move(state, payload.get("move"))
                # A move from a past position starts a new branch, after validation.
                self.states = self.states[:self.cursor + 1] + [successor]
                self.moves = self.moves[:self.cursor] + [payload["move"]]
                self.cursor += 1
            elif action == "navigate":
                index = payload.get("index")
                if type(index) is not int or not 0 <= index <= len(self.moves):
                    raise ValueError("invalid replay position")
                self.cursor = index
            elif action in ("reset", "demo"):
                if action == "demo":
                    key = payload.get("demo")
                    if not isinstance(key, str) or key not in DEMOS:
                        raise ValueError("unknown demo")
                    fen, moves = DEMOS[key]["fen"], DEMOS[key]["moves"]
                else:
                    fen = payload.get("fen")
                    if fen is not None and not isinstance(fen, str):
                        raise ValueError("FEN must be text")
                    fen, moves = (fen.strip() or None) if fen is not None else None, []
                states = [self.rules.initial_state(fen)]
                for move in moves:
                    states.append(self.rules.apply_move(states[-1], move))
                self.states, self.moves, self.cursor = states, list(moves), 0
            else:
                raise ValueError("unknown action")
            self.revision += 1
            return self.snapshot(view)


class StaleRevision(ValueError):
    pass


def make_server(port=8766):
    session = BoardSession()
    assets = Path(__file__).with_name("board_viewer_assets")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, content_type="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, allow_nan=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            route = urlparse(self.path)
            if route.path == "/api/state":
                try:
                    with session.lock:
                        self.send(200, session.snapshot(parse_qs(route.query).get("view", ["full"])[0]))
                except ValueError as exc:
                    self.send(400, {"error": str(exc)})
                return
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/style.css": ("style.css", "text/css; charset=utf-8")}
            if route.path not in files:
                self.send(404, {"error": "not found"})
                return
            name, content_type = files[route.path]
            self.send(200, (assets / name).read_bytes(), content_type)

        def do_POST(self):
            # Same-origin JSON requests only; this server controls a local session.
            if self.headers.get("Origin") not in (None, "http://" + self.headers.get("Host", "")):
                self.send(403, {"error": "cross-origin request rejected"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8192:
                    raise ValueError("invalid request size")
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("expected a JSON object")
                path = urlparse(self.path).path
                if path not in ("/api/move", "/api/navigate", "/api/reset", "/api/demo"):
                    self.send(404, {"error": "not found"})
                    return
                self.send(200, session.mutate(path.rsplit("/", 1)[1], payload))
            except StaleRevision as exc:
                self.send(409, {"error": str(exc)})
            except (ValueError, TypeError, UnicodeError) as exc:
                self.send(400, {"error": str(exc)})

    # Always bind to loopback. No network service or external account is needed.
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    try:
        server = make_server(args.port)
    except OSError as exc:
        parser.exit(1, "Cannot start viewer: {}. Try --port 8767.\n".format(exc))
    print("Chessboard viewer: http://127.0.0.1:{}/".format(server.server_port), flush=True)
    print("Press Ctrl+C to stop. This is a local rules inspector, not an Obscuro agent.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
