"""Bounded Pair A factories for Pair C's optional evaluation interface.

This module does not import pair_c. The same player settings must identify the
public start used by the match; the tracker factory validates that invariant.
"""

from typing import Mapping
from pathlib import Path
from hashlib import sha256
from math import isfinite
import json
import shutil

from .anytime_agent import AnytimeConfig, AnytimePCFRAgent
from .belief_tracker import BeliefTracker
from .cross_turn import RetainedPCFRAgent
from .chess_subgame_agent import ChessSubgameAgent
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


class _ManagedLeaf:
    @property
    def config_id(self):
        base = super().config_id
        identity = getattr(self.evaluator, "handoff_identity", None)
        if identity is None:
            return base
        digest = sha256(json.dumps(identity, sort_keys=True, allow_nan=False).encode()).hexdigest()[:16]
        return base+":leaf-"+digest

    def close(self):
        self.evaluator.close()


class _ManagedAnytime(_ManagedLeaf, AnytimePCFRAgent):
    pass


class _ManagedFixed(_ManagedLeaf, FixedDepthPCFRAgent):
    pass


class _ManagedRetained(_ManagedLeaf, RetainedPCFRAgent):
    pass


class _ManagedSubgame(_ManagedLeaf, ChessSubgameAgent):
    pass


def _boolean(settings, key, default):
    value = settings.get(key, str(default)).strip().lower()
    if value not in ("true", "false"):
        raise ValueError(key+" must be true or false")
    return value == "true"


def _engine_path(setting):
    path = Path(setting).expanduser()
    candidate = path if path.is_absolute() else Path(__file__).resolve().parents[1]/path
    if candidate.is_file():
        return candidate.resolve()
    if not path.is_absolute() and path.parent == Path("."):
        found = shutil.which(setting)
        if found:
            return Path(found).resolve()
    raise FileNotFoundError("Stockfish executable not found: "+setting)


def _load_leaf(settings):
    kind = settings.get("leaf_evaluator", "material").strip().lower()
    if kind == "material":
        if int(settings.get("leaf_depth", "0")) != 0:
            raise ValueError("the Material handoff requires leaf_depth=0; search depth is separate")
        from pairb.material import MaterialEvaluator
        return MaterialEvaluator()
    if kind != "stockfish":
        raise ValueError("leaf_evaluator must be material or stockfish")
    depth = _positive(settings, "leaf_depth", 1)
    hash_mb = _positive(settings, "stockfish_hash_mb", 16)
    per_call = _boolean(settings, "stockfish_new_game_each_call", True)
    timeout = float(settings.get("stockfish_call_timeout_s", "2"))
    if not isfinite(timeout) or timeout <= 0:
        raise ValueError("stockfish_call_timeout_s must be finite and positive")
    path = _engine_path(settings.get("stockfish_path", "stockfish").strip())
    hasher = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    expected_hash = settings.get("stockfish_sha256", "").strip().lower()
    if expected_hash and expected_hash != digest:
        raise ValueError("stockfish_sha256 does not match the executable")
    from pairb.stockfish import StockfishEvaluator
    class OwnedStockfish(StockfishEvaluator):
        def __init__(self, **kwargs):
            try:
                super().__init__(**kwargs)
            except Exception:
                if getattr(self, "engine", None) is not None:
                    self.close()
                raise
    leaf = OwnedStockfish(depth=depth, path=str(path), hash_mb=hash_mb,
                         new_game_each_call=per_call, call_timeout_s=timeout)
    try:
        expected_name = settings.get("stockfish_expected_name", "").strip()
        actual = leaf.engine.id.get("name", "")
        if expected_name and expected_name != actual:
            raise ValueError("stockfish_expected_name does not match running UCI identity: "+actual)
        leaf.provenance_executable_path = str(path)
        leaf.handoff_identity = dict(kind="stockfish", depth=depth, threads=1, hash_mb=hash_mb,
            new_game_each_call=per_call, call_timeout_s=timeout,
            engine_name=actual, engine_author=leaf.engine.id.get("author"), executable_sha256=digest)
        return leaf
    except Exception:
        leaf.close()
        raise


class SearchFactory:
    """Create bounded Material or explicit Stockfish search with owned resources."""

    def __init__(self, settings: Mapping[str, str]):
        self.settings = settings
        self._agent = None

    def load_leaf(self):
        """Override only the evaluator while preserving search validation/lifecycle."""
        return _load_leaf(self.settings)

    def load_model(self):
        if self._agent is not None:
            raise RuntimeError("a factory loads exactly one owned agent")
        mode = self.settings.get("search_mode", "anytime").strip()
        if mode != "subgame" and any(key in self.settings for key in ("purify", "submission_reserve_fraction")):
            raise ValueError("purify and submission_reserve_fraction require search_mode=subgame")
        common = dict(rounds=_positive(self.settings, "solver_rounds", 8),
                      max_nodes=_positive(self.settings, "max_nodes", 1024 if mode == "subgame" else 512),
                      schedule="alternating", stop_on_time=_clock(self.settings))
        mode = self.settings.get("search_mode", "anytime").strip()
        if mode in ("anytime", "retained", "subgame"):
            config = AnytimeConfig(**common,
                growth=self.settings.get("growth", "one_sided" if mode == "subgame" else "uniform").strip(),
                initial_depth=_positive(self.settings, "initial_depth", 1),
                max_depth=_positive(self.settings, "max_depth", 3 if mode == "retained" else 2),
                rounds_per_stage=_positive(self.settings, "rounds_per_stage", 2),
                final_rounds=_positive(self.settings, "final_rounds", 2),
                max_evaluator_calls=_positive(self.settings, "max_evaluator_calls", 48 if mode == "subgame" else 16))
            if mode == "retained" and config.max_depth < 3:
                raise ValueError("retained mode requires max_depth >= 3 for cross-turn reuse")
            agent_type = (_ManagedSubgame if mode == "subgame" else
                          _ManagedRetained if mode == "retained" else _ManagedAnytime)
        elif mode == "fixed":
            config = SearchConfig(**common, depth=_positive(self.settings, "search_depth", 1))
            agent_type = _ManagedFixed
        else:
            raise ValueError("search_mode must be anytime, retained, subgame or fixed")
        extra = {}
        if mode == "subgame":
            purify = self.settings.get("purify", "true").strip().lower()
            if purify not in ("true", "false"):
                raise ValueError("purify must be true or false")
            extra = dict(purify=purify == "true", submission_reserve_fraction=float(
                self.settings.get("submission_reserve_fraction", "0.1")))
        leaf = self.load_leaf()
        try:
            self._agent = agent_type(leaf, config, _initial_fen(self.settings), **extra)
        except Exception:
            leaf.close()
            raise
        return self._agent

    def reset_game(self):
        if self._agent is not None:
            reset = getattr(self._agent.evaluator, "new_game", None)
            if callable(reset):
                reset()


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
        from .evaluation_tracking import BudgetedExactTracker

        policy = self.settings.get("tracker_policy", "exact").strip()
        if policy == "bounded-history":
            from .bounded_tracking import BoundedHistoryTracker
            if any(key in self.settings for key in ("tracker_slice_ms", "tracker_memory_mb",
                                                    "tracker_max_resumes")):
                raise ValueError("bounded-history uses tracker_total_ms and history/rebuild caps only")
            return BoundedHistoryTracker(initial_fen,
                sample_size=_positive(self.settings, "sample_size", 4),
                max_histories=_positive(self.settings, "tracker_max_histories", 8192),
                backend=self.settings.get("tracker_backend", "native").strip(),
                total_ms=float(self.settings.get("tracker_total_ms", "16000")),
                rebuild_attempts=int(self.settings.get("tracker_rebuild_attempts", "4")))
        if policy not in ("exact", "budgeted-exact"):
            raise ValueError("tracker_policy must be exact or budgeted-exact")
        budget_keys = ("tracker_slice_ms", "tracker_total_ms", "tracker_memory_mb", "tracker_max_resumes")
        if policy == "exact" and any(key in self.settings for key in budget_keys):
            raise ValueError("tracker budget settings require tracker_policy=budgeted-exact")
        cap = self.settings.get("max_candidates", "2000" if policy == "exact" else "none").strip().lower()
        maximum = None if cap == "none" else _positive({"max_candidates": cap}, "max_candidates", 2000)
        tracker = BeliefTracker(initial_fen,
            sample_size=_positive(self.settings, "sample_size", 4), max_candidates=maximum,
            backend=self.settings.get("tracker_backend", "auto").strip())
        if policy == "exact":
            tracker.evaluation_policy = "exact"
            return tracker

        def number(key, default, *, zero=False):
            value = float(self.settings.get(key, str(default)))
            if not isfinite(value) or value < 0 or (not zero and value == 0):
                raise ValueError(key + " must be finite and " + ("nonnegative" if zero else "positive"))
            return value

        resumes = int(self.settings.get("tracker_max_resumes", "16"))
        if resumes < 0:
            raise ValueError("tracker_max_resumes must be nonnegative")
        return BudgetedExactTracker(tracker,
            slice_ms=number("tracker_slice_ms", 100, zero=True),
            total_ms=number("tracker_total_ms", 2000),
            memory_mb=(None if self.settings.get("tracker_memory_mb", "64").strip().lower() == "none"
                       else number("tracker_memory_mb", 64, zero=True)), max_resumes=resumes)
