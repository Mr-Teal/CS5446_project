"""The reviewed main-branch Pair A search as a Fog Lab bot.

Fog Lab owns the selected scorer. The agent receives at most a 5-second search
allowance; tracking and inspection are separate, so this is not a whole-turn
deadline. Guesses controls the number of sampled histories; Particles belongs
to Pair B's bot. Only Teal rules and the standard public start are supported.

The browser-only tracker below uses main's public state_count/prune interface.
It retains complete support until its first prune and is approximate afterward.
Pruning before an update is a heuristic to reduce retained history, not a hard
memory or update-time bound. A subsequent update may fail explicitly if pruning
discarded the true history. No solver-label, packed-state or PR65-67 code is
required, and no full-game strength result is attributed to this adapter.
"""
import dataclasses

from ..rules import Rules

NAME = "pair-a-subgame"
TEAL_RULES = "teal-rules-adapter"
BUDGET_MS = 5_000  # the agent's time per move, as Pair A's runs give it
MAX_STATES = 96_000  # retained-state trigger, not a hard peak-memory limit


def unavailable_reason(rules: Rules) -> str | None:
    """Why Pair A's bot cannot play under `rules`, or None when it can: pair_a_prep cannot be imported, or the rules
    are not Teal's."""
    try:
        import pair_a_prep.chess_subgame_agent  # noqa: F401
        import pair_a_prep.evaluation_factories  # noqa: F401
    except ImportError as error:
        return f"Pair A's agent is not in this checkout (pair_a_prep cannot be imported: {error})"
    if getattr(rules, "name", None) != TEAL_RULES:
        return ("Pair A's agent plays by Teal's rules; start Fog Lab with --rules teal "
                "(auto picks them when pair_a_prep is importable)")
    return None


class PairAAgent:
    """Pair A's ChessSubgameAgent (`inner`) with every turn's time budget cut to at most `budget_ms`."""

    name = NAME

    def __init__(self, inner, budget_ms: int):
        self.inner = inner
        self.budget_ms = budget_ms

    def reset(self, player: str, seed: int) -> None:
        self.inner.reset(player, seed)

    def act(self, turn):
        return self.inner.act(dataclasses.replace(turn, time_budget_ms=min(turn.time_budget_ms, self.budget_ms)))


def make_pair_a_agent(scorer, *, budget_ms: int = BUDGET_MS) -> PairAAgent:
    """Main's search with `scorer` as its leaf and a `budget_ms` search allowance.
    It plays from the standard start (make_pair_a_tracker refuses any other)."""
    from pair_a_prep.anytime_agent import AnytimeConfig
    from pair_a_prep.chess_subgame_agent import ChessSubgameAgent

    config = AnytimeConfig(rounds=1024, max_nodes=16384, schedule="alternating", stop_on_time=True,
                           growth="one_sided", initial_depth=1, max_depth=2, rounds_per_stage=2, final_rounds=2,
                           max_evaluator_calls=4096)
    return PairAAgent(ChessSubgameAgent(scorer, config), budget_ms)


def make_pair_a_tracker(rules: Rules, options):
    """Pair A history tracker with an explicit approximate browser pruning policy.
    ValueError when the bot cannot play under `rules` (unavailable_reason), and for a start other than the standard
    one: the agent is made from the scorer alone, so it could not be told the start it replays histories from."""
    reason = unavailable_reason(rules)
    if reason is not None:
        raise ValueError(reason)
    if options.start_fen is not None:
        raise ValueError("Pair A's agent plays from the standard start only")
    from pair_a_prep.evaluation_factories import HistoryTrackerFactory

    settings = {"tracker_policy": "exact", "max_candidates": "none", "sample_size": str(options.guesses),
                "tracker_backend": "auto"}
    return BrowserHistoryTracker(HistoryTrackerFactory(settings).create_tracker(rules), MAX_STATES)


class BrowserHistoryTracker:
    """Prune represented histories before a large update; never recover from the referee."""

    def __init__(self, inner, max_states):
        if max_states < 1:
            raise ValueError("max_states must be positive")
        self.inner = inner
        self.max_states = max_states
        self.prunes = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def reset(self, player, seed):
        self.inner.reset(player, seed)
        self.prunes = 0

    def update(self, observation, own_move=None):
        if self.inner.state_count > self.max_states:
            self.inner.prune(self.max_states)
            self.prunes += 1
        return self.inner.update(observation, own_move)

