"""Observation-only JSON-lines process adapter and a clearly named demo agent."""

import argparse
from dataclasses import asdict
import importlib
import json
import os
from pathlib import Path
from queue import Queue, Empty
from random import Random
import subprocess
import sys
from threading import Thread
from time import perf_counter

from fow_shared.contracts import Decision, Observation
from .model import BudgetError
from .rule_profile import RULES_ID


class ProcessAgent:
    def __init__(self, spec, player, seed):
        path = Path(spec).resolve()
        settings = json.loads(path.read_text(encoding="utf-8"))
        command = settings["command"]
        if not isinstance(command, list) or not command or not all(isinstance(s, str) for s in command):
            raise ValueError("process command must be a nonempty argument list")
        if Path(command[0]).stem.lower() in ("python", "python3", "py", "pythonw"):
            raise ValueError("Python process agents must start through pixi run")
        self.errors = path.with_suffix(".stderr.log").open("a", encoding="utf-8")
        cwd = Path(settings.get("cwd", "."))
        if not cwd.is_absolute():
            cwd = path.parent / cwd
        self.process = subprocess.Popen(command, cwd=cwd.resolve(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors,
            text=True, encoding="utf-8", bufsize=1, shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.answers, self.previous = Queue(), None
        def reader():
            for line in self.process.stdout:
                self.answers.put(line)
            self.answers.put(None)
        self.reader = Thread(target=reader, daemon=True)
        self.reader.start()
        try:
            self.request(dict(type="start", schema_version=1, player=player, seed=seed,
                              rules_id=RULES_ID), perf_counter()+30)
        except BaseException:
            self.close()
            raise

    def request(self, message, deadline):
        remaining = deadline-perf_counter()
        if remaining <= 0:
            raise BudgetError("external agent deadline exhausted")
        message["remaining_seconds"] = remaining
        self.process.stdin.write(json.dumps(message, allow_nan=False)+"\n")
        self.process.stdin.flush()
        try:
            line = self.answers.get(timeout=max(.001, deadline-perf_counter()))
        except Empty as exc:
            self.close()
            raise BudgetError("external agent response timed out") from exc
        if line is None:
            raise RuntimeError("external agent exited before replying")
        result = json.loads(line)
        if result.get("error"):
            raise RuntimeError("external agent: " + str(result["error"]))
        return result

    def observe(self, observation, own_move=None, deadline=None):
        self.request(dict(type="observe", observation=asdict(observation), own_move=own_move),
                     deadline if deadline is not None else perf_counter()+30)
        self.previous = observation

    def act(self, deadline):
        result = self.request(dict(type="act"), deadline)
        decision = Decision(**result["decision"])
        decision.validate_for(self.previous)
        return decision

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW, check=False)
                else:
                    self.process.kill()
                self.process.wait(timeout=2)
        self.errors.close()


def create_agent(kind, player, seed, pool):
    if kind in ("paper", "baseline"):
        from .agent import PaperAgent
        return PaperAgent(player, seed, pool, baseline=kind=="baseline")
    if kind.startswith("process:"):
        return ProcessAgent(kind[len("process:"):], player, seed)
    module, separator, factory = kind.partition(":")
    if not separator:
        raise ValueError("agent must be paper, baseline, process:spec.json, or module:factory")
    return getattr(importlib.import_module(module), factory)(player=player, seed=seed, pool=pool)


def random_example():
    """Interface demonstration only; this is never used by the paper benchmark."""
    rng, previous = None, None
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if message["type"] == "start":
                rng = Random(message["seed"])
                result = dict(ok=True, agent="random_protocol_example_not_paper_agent")
            elif message["type"] == "observe":
                previous = Observation(**message["observation"])
                result = dict(ok=True)
            elif message["type"] == "act":
                actions = previous.legal_moves
                result = dict(decision=asdict(Decision(rng.choice(actions), dict.fromkeys(actions,1/len(actions)))))
            else:
                raise ValueError("unknown request type")
        except Exception as exc:
            result = dict(error=f"{type(exc).__name__}: {exc}")
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--random-example", action="store_true", required=True)
    parser.parse_args()
    random_example()
