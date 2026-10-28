"""Human/agent play and a separate three-board spectator using Pair A assets."""

import argparse
from contextlib import nullcontext
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from queue import Queue, Empty
from secrets import token_urlsafe
from threading import Thread
from time import perf_counter
from urllib.parse import urlparse, parse_qs

from ..board_viewer import BoardSession, StaleRevision
from .agent import PaperAgent
from .engine import EnginePool
from .model import RefereeRules, BudgetError
from .protocol import create_agent
from .config import load
from .rule_profile import RULES_ID


class PlaySession(BoardSession):
    def __init__(self, pool, white="human", black="paper", seed=2106, seconds=None, output=None):
        super().__init__()
        self.rules = RefereeRules()
        self.pool, self.seed = pool, seed
        self.seconds = load()["data"]["experiment"]["seconds_per_move"] if seconds is None else seconds
        self.roles = {"white": white, "black": black}
        self.tokens = {token_urlsafe(24): role for role in ("white", "black", "spectator")}
        self.commands = Queue()
        self.error = None
        self.thinking = None
        self.stopping = False
        self.output = Path(output) if output else None
        self.thread = Thread(target=self.run, daemon=True)

    def payload(self, role):
        with self.lock:
            views = ("white", "full", "black") if role == "spectator" else (role,)
            return dict(role=role, roles=self.roles, boards=[self.snapshot(v) for v in views],
                        thinking=self.thinking, error=self.error,
                        can_move=role != "spectator" and self.roles[role] == "human"
                        and self.rules.current_player(self.states[-1]) == role
                        and self.rules.terminal(self.states[-1]) is None,
                        revision=self.revision, rules_id=RULES_ID)

    def submit(self, role, payload):
        with self.lock:
            if role == "spectator" or self.roles[role] != "human":
                raise ValueError("this capability cannot submit a move")
            if payload.get("revision") != self.revision:
                raise StaleRevision("stale position")
            if self.rules.current_player(self.states[-1]) != role or self.error:
                raise ValueError("not an active human turn")
            move = payload.get("move")
            if move not in self.rules.legal_moves(self.states[-1]):
                raise ValueError("unavailable move")
            self.commands.put((self.revision, move))

    def restart(self, role):
        if role == "spectator" or self.roles[role] != "human":
            raise ValueError("only a human seat may start a new game")
        with self.lock:
            if self.thinking is not None:
                raise ValueError("wait for the current agent decision before restarting")
            self.stopping = True
        if self.thread.is_alive():
            self.thread.join(timeout=1.)
        if self.thread.is_alive():
            raise ValueError("previous game is still stopping")
        with self.lock:
            self.states, self.moves, self.cursor = [self.rules.initial_state()], [], 0
            self.revision += 1
            self.commands = Queue()
            self.error = None
            self.stopping = False
            self.thread = Thread(target=self.run, daemon=True)
            self.thread.start()

    def run(self):
        agents = {}
        try:
            for i, (p, kind) in enumerate(self.roles.items()):
                if kind != "human":
                    agents[p] = create_agent(kind, p, self.seed+i, self.pool)
            start = perf_counter()
            for p, agent in agents.items():
                agent.observe(self.rules.observe(self.states[-1], p))
            while not self.stopping:
                state = self.states[-1]
                if self.rules.terminal(state):
                    return
                player = self.rules.current_player(state)
                if player in agents:
                    self.thinking = player
                    decision = agents[player].act(start+self.seconds)
                    if perf_counter() > start+self.seconds:
                        raise BudgetError("late UI agent submission")
                    decision.validate_for(self.rules.observe(state, player))
                    move = decision.move
                else:
                    self.thinking = None
                    while not self.stopping:
                        try:
                            revision, move = self.commands.get(timeout=.25)
                        except Empty:
                            continue
                        if revision == self.revision:
                            break
                    if self.stopping:
                        return
                with self.lock:
                    self.states.append(self.rules.apply_move(state, move))
                    self.moves.append(move)
                    self.cursor += 1
                    self.revision += 1
                    start = perf_counter()
                    self.thinking = None
                # Notify the previous mover first, as in the match runner.
                for p in (player, "black" if player == "white" else "white"):
                    if p in agents:
                        agents[p].observe(self.rules.observe(self.states[-1], p), move if p == player else None,
                                          deadline=start+self.seconds if p != player else None)
                if self.output:
                    self.output.parent.mkdir(parents=True, exist_ok=True)
                    with self.output.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(dict(ply=self.cursor, move=move, fen=self.states[-1].fen, rules_id=RULES_ID,
                            observations={p: asdict(self.rules.observe(self.states[-1], p)) for p in self.roles}))+"\n")
        except Exception as exc:
            self.error = f"Game stopped: {type(exc).__name__}: {exc}"
        finally:
            self.thinking = None
            for agent in agents.values():
                agent.close()


def make_server(session, port=8767):
    assets = Path(__file__).with_name("ui_assets")
    shared_css = Path(__file__).parents[1] / "board_viewer_assets/style.css"
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, data, content_type="application/json; charset=utf-8"):
            data = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)

        def role(self):
            query = parse_qs(urlparse(self.path).query)
            return session.tokens.get(query.get("token", [""])[0])

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/style.css", "/app.js"):
                file = shared_css if path == "/style.css" else assets / "app.js"
                return self.send(200, file.read_bytes(), "text/css" if path == "/style.css" else "text/javascript")
            role = self.role()
            if role is None:
                return self.send(403, {"error": "unknown session capability"})
            if path == "/api/state":
                return self.send(200, session.payload(role))
            if path == "/":
                return self.send(200, (assets / "index.html").read_bytes(), "text/html; charset=utf-8")
            self.send(404, {"error": "not found"})

        def do_POST(self):
            if self.headers.get("Origin") not in (None, "http://"+self.headers.get("Host", "")):
                return self.send(403, {"error": "cross-origin request rejected"})
            role = self.role()
            if role is None:
                return self.send(403, {"error": "unknown session capability"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                path = urlparse(self.path).path
                if not 0 < size <= 4096 or path not in ("/api/move", "/api/reset"):
                    raise ValueError("invalid request")
                payload = json.loads(self.rfile.read(size))
                if path == "/api/reset":
                    session.restart(role)
                else:
                    session.submit(role, payload)
                self.send(200, {"accepted": True})
            except StaleRevision as exc:
                self.send(409, {"error": str(exc)})
            except (ValueError, TypeError, AttributeError) as exc:
                self.send(400, {"error": str(exc)})
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine")
    parser.add_argument("--white", default="human", help="human, paper, baseline, process:JSON, module:factory")
    parser.add_argument("--black", default="paper", help="human, paper, baseline, process:JSON, module:factory")
    parser.add_argument("--seed", type=int, default=2106)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--seconds", type=float, help="agent turn budget; defaults to runtime.toml")
    parser.add_argument("--output")
    args = parser.parse_args()
    needs_engine = args.white in ("paper", "baseline") or args.black in ("paper", "baseline")
    if needs_engine and not args.engine:
        parser.error("--engine is required when either seat uses an agent")
    with EnginePool(args.engine) if needs_engine else nullcontext(None) as pool:
        session = PlaySession(pool, args.white, args.black, args.seed, seconds=args.seconds, output=args.output)
        server = make_server(session, args.port)
        for token, role in session.tokens.items():
            print(f"{role}: http://127.0.0.1:{server.server_port}/?token={token}", flush=True)
        session.thread.start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            session.stopping = True
            session.thread.join(timeout=10.)
            server.server_close()


if __name__ == "__main__":
    main()
