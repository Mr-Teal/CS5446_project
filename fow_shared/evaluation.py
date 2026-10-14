"""Common settings and match loop, independent of the two paper agents."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Mapping, Tuple

from .interfaces import Agent, BeliefTracker, Referee
from .contracts import AgentInput, HistoryEvent


@dataclass(frozen=True)
class MatchConfig:
    time_budget_ms: int
    max_plies: int
    seed: int
    rules_id: str
    engine_id: str
    leaf_depth: int

    def __post_init__(self) -> None:
        if self.time_budget_ms <= 0 or self.max_plies <= 0 or self.leaf_depth < 0:
            raise ValueError("invalid match limits")
        if not self.rules_id or not self.engine_id:
            raise ValueError("rules and engine versions must be identified")


@dataclass(frozen=True)
class PlyResult:
    ply: int
    player: str
    agent_name: str
    move: str
    elapsed_ms: float
    over_budget: bool
    search_nodes: float


@dataclass(frozen=True)
class MatchResult:
    winner: str  # 'white', 'black', or 'draw'.
    plies: Tuple[PlyResult, ...]
    config: MatchConfig
    stopped_at_ply_limit: bool


def play_game(referee: Referee, agents: Mapping[str, Agent],
              trackers: Mapping[str, BeliefTracker], config: MatchConfig) -> MatchResult:
    """Run one game. Supply fresh agents/trackers for every game in a match set."""
    if set(agents) != {"white", "black"} or set(trackers) != {"white", "black"}:
        raise ValueError("one agent and tracker are required per colour")
    referee.reset(config.seed)
    for index, player in enumerate(("white", "black")):
        agents[player].reset(player, config.seed + index)
        trackers[player].reset(player, config.seed + index)
    history = []
    private_history = {"white": [], "black": []}
    observations = {player: referee.observe(player) for player in ("white", "black")}
    beliefs = {player: trackers[player].update(observations[player])
               for player in ("white", "black")}
    while not referee.is_terminal() and len(history) < config.max_plies:
        player = referee.current_player()
        if player not in ("white", "black"):
            raise ValueError("referee returned invalid player")
        observation = observations[player]
        if observation.player != player or observation.ply != len(history):
            raise ValueError("referee observation has wrong player or ply")
        turn = AgentInput(observation, beliefs[player], config.time_budget_ms,
                          tuple(private_history[player]))
        started = perf_counter()
        decision = agents[player].act(turn)
        elapsed_ms = (perf_counter() - started) * 1000
        decision.validate_for(observation)
        history.append(PlyResult(len(history), player, agents[player].name,
                                 decision.move, elapsed_ms,
                                 elapsed_ms > config.time_budget_ms,
                                 decision.diagnostics.get("search_nodes", 0.0)))
        for viewer in ("white", "black"):
            private_history[viewer].append(HistoryEvent(
                observations[viewer], decision.move if viewer == player else None))
        referee.apply(decision.move)
        if not referee.is_terminal():
            observations = {viewer: referee.observe(viewer) for viewer in ("white", "black")}
            beliefs = {viewer: trackers[viewer].update(observations[viewer])
                       for viewer in ("white", "black")}
    capped = not referee.is_terminal()
    winner = "draw" if capped else referee.winner()
    if winner not in ("white", "black", "draw"):
        raise ValueError("referee returned invalid winner")
    return MatchResult(winner, tuple(history), config, capped)
