"""The belief-input PPO network as a player for the team's match runner (pair_c).

    [player_a]
    name = PPO self-play network with belief input
    factory = ppo_belief_player:PpoBeliefFactory
    checkpoint_path = checkpoints/ppo-belief-5h/final.pt
    move_choice = sample            ; sample (as in training) or best (the most likely move)
    leaf_depth = 0
    tracker_factory = ppo_belief_player:NoBeliefFactory

`checkpoint_path` may be absolute. A relative path is read from the package folder (the folder that
holds `player/`), so the configurations work from any current folder.

The player is fowppo_belief.agent.PpoAgent. It reads only its own observations and its own moves, and
keeps its own belief sampler (kernel/belief_sampler.cpp, at most 1,024 positions), the one it was
trained with. So the runner's tracker for it is a placeholder that returns one start-position board
and cannot fail. The sampler is a compiled library: build it once with `python player/kernel/build.py`.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Mapping

PACKAGE = Path(__file__).resolve().parents[1]
MOVE_CHOICES = ("sample", "best")


def belief_package(module: str):
    """A module of the fowppo_belief package, e.g. belief_package("agent")."""
    return importlib.import_module(f"fowppo_belief.{module}")


class PpoBeliefFactory:
    """pair_c agent factory: one PpoAgent (belief input) per player section."""

    def __init__(self, settings: Mapping[str, str]):
        self.settings = settings

    def load_model(self):
        path = Path(self.settings["checkpoint_path"].strip()).expanduser()
        if not path.is_absolute():
            path = PACKAGE / path
        if not path.is_file():
            raise FileNotFoundError(f"no PPO checkpoint at {path}")
        choice = self.settings.get("move_choice", "sample").strip()
        if choice not in MOVE_CHOICES:
            raise ValueError(f"move_choice must be one of {MOVE_CHOICES}, not {choice!r}")
        agent = belief_package("agent").PpoAgent.from_checkpoint(path, sample=choice == "sample", name=f"ppo-belief-{choice}")
        agent.provenance_checkpoint_path = path.resolve()  # the runner hashes this file
        return agent

    def reset_game(self) -> None:
        """Nothing carries over between games: the agent's reset() starts a new belief sampler."""


class NoBeliefFactory:
    """pair_c tracker factory for a player that keeps its own belief."""

    def __init__(self, settings: Mapping[str, str]):
        self.settings = settings

    def create_tracker(self, rules, initial_fen: str | None = None):
        if initial_fen:
            raise ValueError("the PPO player's belief sampler assumes the standard start position")
        return belief_package("agent").NoBelief()
