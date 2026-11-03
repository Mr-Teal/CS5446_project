"""Pair A's search agent as a Fog Lab bot: the sampled subgame PCFR+ agent of pair_a_prep, with its exact history
tracker.

The agent is pair_a_prep.chess_subgame_agent.ChessSubgameAgent in the arms' full-effort configuration (1,024 solver
rounds, 16,384 nodes, 4,096 evaluator calls, depth 1 growing to 2, one-sided growth). Its leaf evaluator is the bot's
scorer that Fog Lab has already opened: every Fog Lab scorer has the evaluate_children(fen) it needs. Fog Lab owns
that scorer and closes it; the agent never does.

Two limits are added here, and each answers a number. Fog Lab gives a bot 60 s per move (session.TIME_BUDGET_MS),
which is right for Pair B's one-ply bot, which answers long before it, but Pair A's agent searches until its budget
runs out: the page would wait a minute on every move. Pair A's runs give it 5 s per move (label_run.py's default),
so the agent is handed the smaller of the two. The tracker is Pair A's exact one, which keeps every board the
opponent's moves could have led to. That set is small on almost every turn (a median of 188 states) and enormous on
a few: it passes a million states on one turn in two hundred, and reached 2.2 million (tail_guard.py's measurements).
pair_a_prep.tail_guard prunes it back once it holds more than 96,000 states, the threshold Pair A sized for a 4.5 GB
container, and leaves it exact below that.

The agent and the tracker play by Teal's rules: they replay histories with Teal's RulesAdapter, so the bot is offered
only when the server plays by those rules. Fog Lab's Guesses option is the tracker's hypothesis sample size, the
boards the agent searches over; Particles is Pair B's alone and is not used. pair_a_prep is imported only when the
bot is made or asked about, so the app starts on a checkout without it.
"""
import dataclasses

from ..rules import Rules

NAME = "pair-a-subgame"
TEAL_RULES = "teal-rules-adapter"
BUDGET_MS = 5_000  # the agent's time per move, as Pair A's runs give it
MAX_STATES = 96_000  # the tail guard's threshold (pair_a_prep.tail_guard)


def unavailable_reason(rules: Rules) -> str | None:
    """Why Pair A's bot cannot play under `rules`, or None when it can: pair_a_prep cannot be imported, or the rules
    are not Teal's."""
    try:
        import pair_a_prep.chess_subgame_agent  # noqa: F401
        import pair_a_prep.tail_guard  # noqa: F401
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
    """Pair A's agent in its full-effort configuration, with `scorer` as its leaf evaluator, taking at most
    `budget_ms` per move. It plays from the standard start (make_pair_a_tracker refuses any other)."""
    from pair_a_prep.anytime_agent import AnytimeConfig
    from pair_a_prep.chess_subgame_agent import ChessSubgameAgent

    config = AnytimeConfig(rounds=1024, max_nodes=16384, schedule="alternating", stop_on_time=True,
                           growth="one_sided", initial_depth=1, max_depth=2, rounds_per_stage=2, final_rounds=2,
                           max_evaluator_calls=4096)
    return PairAAgent(ChessSubgameAgent(scorer, config), budget_ms)


def make_pair_a_tracker(rules: Rules, options):
    """Pair A's exact history tracker, tail-guarded at 96,000 states, sampling `options.guesses` hypotheses.
    ValueError when the bot cannot play under `rules` (unavailable_reason), and for a start other than the standard
    one: the agent is made from the scorer alone, so it could not be told the start it replays histories from."""
    reason = unavailable_reason(rules)
    if reason is not None:
        raise ValueError(reason)
    if options.start_fen is not None:
        raise ValueError("Pair A's agent plays from the standard start only")
    from pair_a_prep.tail_guard import Factory

    settings = {"tracker_policy": "exact", "max_candidates": "none", "sample_size": str(options.guesses),
                "tracker_backend": "auto", "max_states": str(MAX_STATES)}
    return Factory(settings).create_tracker(rules)
