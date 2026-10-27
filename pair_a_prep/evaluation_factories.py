"""Bounded Pair A factories for Pair C's optional evaluation interface.

This module does not import pair_c. The same player settings must identify the
public start used by the match; the tracker factory validates that invariant.
"""

from typing import Mapping

from .anytime_agent import AnytimeConfig, AnytimePCFRAgent
from .belief_tracker import BeliefTracker
from .cross_turn import RetainedPCFRAgent
from .rules_adapter import RulesAdapter
from .search_agent import FixedDepthPCFRAgent, SearchConfig


def _positive(settings, key, default):
    value = int(settings.get(key, str(default)))
    if value < 1:
        raise ValueError(key + " must be positive")
    return value


def _clock(settings):
    value = settings.get("stop_on_time", "false").strip().lower()
    if value not in ("true", "false"):
        raise ValueError("stop_on_time must be true or false")
    return value == "true"


def _initial_fen(settings):
    return settings.get("public_initial_fen", "").strip() or None


class _ManagedAnytime(AnytimePCFRAgent):
    def close(self):
        self.evaluator.close()


class _ManagedFixed(FixedDepthPCFRAgent):
    def close(self):
        self.evaluator.close()


class _ManagedRetained(RetainedPCFRAgent):
    def close(self):
        self.evaluator.close()


class SearchFactory:
    """Create a Material-only search baseline with independent owned resources."""

    def __init__(self, settings: Mapping[str, str]):
        self.settings = settings

    def load_model(self):
        from pairb.material import MaterialEvaluator
        if int(self.settings.get("leaf_depth", "0")) != 0:
            raise ValueError("the Material handoff requires leaf_depth=0; search depth is separate")
        common = dict(rounds=_positive(self.settings, "solver_rounds", 8),
                      max_nodes=_positive(self.settings, "max_nodes", 512),
                      schedule="alternating", stop_on_time=_clock(self.settings))
        mode = self.settings.get("search_mode", "anytime").strip()
        if mode in ("anytime", "retained"):
            config = AnytimeConfig(**common,
                growth=self.settings.get("growth", "uniform").strip(),
                initial_depth=_positive(self.settings, "initial_depth", 1),
                max_depth=_positive(self.settings, "max_depth", 2),
                rounds_per_stage=_positive(self.settings, "rounds_per_stage", 2),
                final_rounds=_positive(self.settings, "final_rounds", 2),
                max_evaluator_calls=_positive(self.settings, "max_evaluator_calls", 16))
            agent_type = _ManagedRetained if mode == "retained" else _ManagedAnytime
        elif mode == "fixed":
            config = SearchConfig(**common, depth=_positive(self.settings, "search_depth", 1))
            agent_type = _ManagedFixed
        else:
            raise ValueError("search_mode must be anytime, retained or fixed")
        self._agent = agent_type(MaterialEvaluator(), config, _initial_fen(self.settings))
        return self._agent

    def reset_game(self):
        # Material has no engine/cache to reset. The shared loop resets the agent.
        pass


class HistoryTrackerFactory:
    """Fresh exact path tracker; fail explicitly if referee/start semantics differ."""

    def __init__(self, settings: Mapping[str, str]):
        self.settings = settings

    def create_tracker(self, rules, initial_fen=None):
        if getattr(rules, "name", None) != "teal-rules-adapter":
            raise ValueError("Pair A exact tracking requires rules=teal, including capture notices")
        adapter = RulesAdapter()
        if adapter.initial_state(_initial_fen(self.settings)).fen != adapter.initial_state(initial_fen).fen:
            raise ValueError("public_initial_fen must match the runner's public initial_fen")
        return BeliefTracker(initial_fen,
            sample_size=_positive(self.settings, "sample_size", 4),
            max_candidates=_positive(self.settings, "max_candidates", 2000))
