"""Small public contract for evaluation tracker factories."""

from __future__ import annotations

from importlib import import_module
from typing import Mapping


def load_tracker_factory(factory_path: str, settings: Mapping[str, str]):
    """Load one player's factory, whose create_tracker returns a fresh tracker per game."""
    module_name, separator, class_name = factory_path.partition(":")
    if not separator or not module_name or not class_name:
        raise ValueError("tracker_factory must use the form 'python.module:FactoryClass'")

    factory = getattr(import_module(module_name), class_name, None)
    if not isinstance(factory, type):
        raise ValueError(f"Tracker factory must be a class: {factory_path}")

    instance = factory(settings)
    if not callable(getattr(instance, "create_tracker", None)):
        raise TypeError(f"Tracker factory must define create_tracker(rules, initial_fen): {factory_path}")
    return instance
