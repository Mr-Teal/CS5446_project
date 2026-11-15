"""The PPO self-play network as a player for the team's match runner (pair_c).

    [player_a]
    name = PPO self-play network
    factory = ppo_player:PpoFactory
    checkpoint_path = checkpoints/ppo-selfplay-12h/final.pt
    move_choice = sample            ; sample (as in training) or best (the most likely move)
    leaf_depth = 0
    tracker_factory = ppo_player:NoBeliefFactory

`checkpoint_path` may be absolute. A relative path is read from the package folder (the folder that
holds `player/`), so the configurations work from any current folder.

The player is fowppo.agent.PpoAgent. It reads only its own observations and keeps its own memory of
them. It uses no belief, so its tracker is a placeholder that returns one start-position board and
cannot fail.
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from fowppo.agent import NoBelief, PpoAgent

PACKAGE = Path(__file__).resolve().parents[1]
MOVE_CHOICES = ("sample", "best")


class PpoFactory:
    """pair_c agent factory: one PpoAgent per player section."""

    def __init__(self, settings: Mapping[str, str]):
        self.settings = settings

    def load_model(self) -> PpoAgent:
        path = Path(self.settings["checkpoint_path"].strip()).expanduser()
        if not path.is_absolute():
            path = PACKAGE / path
        if not path.is_file():
            raise FileNotFoundError(f"no PPO checkpoint at {path}")
        choice = self.settings.get("move_choice", "sample").strip()
        if choice not in MOVE_CHOICES:
            raise ValueError(f"move_choice must be one of {MOVE_CHOICES}, not {choice!r}")
        agent = PpoAgent.from_checkpoint(path, sample=choice == "sample", name=f"ppo-{choice}")
        agent.provenance_checkpoint_path = path.resolve()  # the runner hashes this file
        return agent

    def reset_game(self) -> None:
        """Nothing carries over between games: the agent rebuilds its memory from the history."""


class NoBeliefFactory:
    """pair_c tracker factory for a player that does not use a belief."""

    def __init__(self, settings: Mapping[str, str]):
        self.settings = settings

    def create_tracker(self, rules, initial_fen: str | None = None) -> NoBelief:
        if initial_fen:
            raise ValueError("the PPO player's memory assumes the standard start position")
        return NoBelief()
