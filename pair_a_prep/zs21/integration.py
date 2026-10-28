"""Adapter to fow_shared.Agent.reset/act using only the seat's observation history."""

from time import perf_counter

from .agent import PaperAgent
from .model import view_signature


class SharedAgent:
    def __init__(self, pool, *, baseline=False, initial_fen=None, **agent_kwargs):
        self.pool, self.baseline, self.initial_fen = pool, baseline, initial_fen
        self.agent_kwargs = agent_kwargs
        self.name = "zs21-baseline" if baseline else "zs21-paper"
        self.core = None
        self.accepted_history = ()

    def reset(self, player, seed):
        self.close()
        self.core = PaperAgent(player, seed, self.pool, baseline=self.baseline,
                               initial_fen=self.initial_fen, **self.agent_kwargs)
        self.accepted_history = ()

    def act(self, turn):
        deadline = perf_counter() + turn.time_budget_ms / 1000.
        if self.core is None:
            raise ValueError("reset(player, seed) is required before act")
        current, history = turn.observation, turn.history
        if current.player != self.core.player or current.side_to_move != current.player or current.terminal:
            raise ValueError("not an active own turn")
        if len(history) != current.ply or any(
                event.observation.ply != index or event.observation.player != current.player
                for index, event in enumerate(history)):
            raise ValueError("complete private history from ply 0 is required")
        signatures = tuple((view_signature(event.observation), event.own_move) for event in history)
        if signatures[:len(self.accepted_history)] != self.accepted_history:
            raise ValueError("previously supplied private history changed")
        previous = self.core.tracker.previous
        if previous is not None:
            if current.ply <= previous.ply:
                raise ValueError("duplicate or stale act request")
            if view_signature(history[previous.ply].observation) != view_signature(previous):
                raise ValueError("previous decision observation changed")
            if history[previous.ply].own_move != self.last_move:
                raise ValueError("history does not contain the previously chosen own move")
        observations = [event.observation for event in history] + [current]
        first = 0 if previous is None else previous.ply + 1
        for observation in observations[first:]:
            own_move = history[observation.ply - 1].own_move if observation.ply else None
            self.core.observe(observation, own_move, deadline=deadline)
        decision = self.core.act(deadline)
        self.accepted_history, self.last_move = signatures, decision.move
        return decision

    def close(self):
        if self.core is not None:
            self.core.close()
            self.core = None
