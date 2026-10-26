"""Small public contract for evaluation player factories."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]


def project_path(value: str) -> Path:
    """Resolve a configured filesystem path against the repository root."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def load_player(factory_path: str, settings: Mapping[str, str], resources):
    """Return the Agent and its factory's per-game reset callback.

    The runner calls reset_game once before each game, then passes the Agent
    to play_game. The factory owns the scorer state it needs to clear.
    """
    module_name, separator, class_name = factory_path.partition(":")
    if not separator or not module_name or not class_name:
        raise ValueError("factory must use the form 'python.module:FactoryClass'")

    factory = getattr(import_module(module_name), class_name, None)
    if not isinstance(factory, type):
        raise ValueError(f"Player factory must be a class: {factory_path}")

    instance = factory(settings)
    reset_game = getattr(instance, "reset_game", None)
    if not callable(reset_game):
        raise TypeError(f"Player factory must define reset_game(): {factory_path}")
    agent = instance.load_model()

    # Some Agents own external resources such as a Stockfish subprocess. The
    # shared play_game() contract does not close them, so Pair C registers an
    # optional close() method with its own ExitStack. Agents without close()
    # remain fully supported.
    close = getattr(agent, "close", None)
    if not callable(close):
        # Pair B's OnePlyBot keeps its scorer as ``agent.scorer``; network and
        # Stockfish scorers expose close() for their owned engine processes.
        close = getattr(getattr(agent, "scorer", None), "close", None)
    if callable(close):
        resources.callback(close)
    return agent, reset_game
