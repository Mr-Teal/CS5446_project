"""The reproduced paper agent over one-request/one-response JSON lines."""

import argparse
from dataclasses import asdict
import json
import math
import sys
from time import perf_counter

from fow_shared.contracts import Observation
from .agent import PaperAgent
from .config import load
from .engine import EnginePool
from .rule_profile import RULES_ID


def serve(input_stream, output_stream, *, engine, baseline=False, initial_fen=None,
          agent_kwargs=None, pool_factory=EnginePool, agent_factory=PaperAgent):
    pool, agent = None, None
    try:
        for line in input_stream:
            stop = False
            try:
                message = json.loads(line)
                remaining = float(message.get("remaining_seconds", 30))
                if not math.isfinite(remaining) or remaining <= 0:
                    raise ValueError("remaining_seconds must be positive and finite")
                deadline = perf_counter() + remaining
                kind = message["type"]
                if kind == "start":
                    if agent is not None or message.get("schema_version") != 1:
                        raise ValueError("one schema-v1 start is required per process")
                    if message.get("rules_id", RULES_ID) != RULES_ID:
                        raise ValueError("unsupported rules_id")
                    if message.get("player") not in ("white", "black") or type(message.get("seed")) is not int:
                        raise ValueError("start requires player and integer seed")
                    pool = pool_factory(engine)
                    agent = agent_factory(message["player"], message["seed"], pool,
                                          baseline=baseline, initial_fen=initial_fen,
                                          **(agent_kwargs or {}))
                    result = dict(ok=True, agent="zs21-baseline" if baseline else "zs21-paper",
                                  rules_id=RULES_ID, schema_version=1)
                elif kind == "close":
                    result, stop = dict(ok=True), True
                elif agent is None:
                    raise ValueError("send start before observe or act")
                elif kind == "observe":
                    fields = message["observation"]
                    observation = Observation(**{**fields,
                        "visible_squares": tuple(fields["visible_squares"]),
                        "legal_moves": tuple(fields["legal_moves"])})
                    agent.observe(observation, message.get("own_move"), deadline=deadline)
                    result = dict(ok=True)
                elif kind == "act":
                    result = dict(decision=asdict(agent.act(deadline)))
                else:
                    raise ValueError("unknown request type")
            except Exception as exc:
                result, stop = dict(error=f"{type(exc).__name__}: {exc}"), True
            output_stream.write(json.dumps(result, allow_nan=False) + "\n")
            output_stream.flush()
            if stop:
                break
    finally:
        if agent is not None:
            agent.close()
        if pool is not None:
            pool.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--engine")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--variant", choices=("main", "sixfold"), default="main")
    parser.add_argument("--initial-fen", help="only an agreed public starting position, never a hidden current board")
    args = parser.parse_args()
    runtime = load(args.config, args.variant)
    serve(sys.stdin, sys.stdout, engine=args.engine or runtime["engine"], baseline=args.baseline,
          initial_fen=args.initial_fen, agent_kwargs=runtime["agent_kwargs"])


if __name__ == "__main__":
    main()
