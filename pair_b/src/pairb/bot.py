"""The one-ply belief bot: the opponent in Fog Lab's Play tab, and a baseline for Pair A's agent.

It implements fow_shared's Agent, and it is honest: it acts only on the AgentInput it is given (the
observation, the belief its tracker made from the observations, the history) and on the scorer it was
built with, so it never sees a referee, a true board or the other side's hidden pieces. For each guess
in the belief it asks the scorer for the value of every legal move, then plays the move with the
highest weighted average over the guesses: the sum of weight times value (a Belief's weights sum to one).

- One scorer call (LeafEvaluator.evaluate_children) per hypothesis, as the belief gives them: a board
  that appears twice, as two histories that reach the same FEN, is scored twice.
- The scorer's answer must have exactly the observation's legal moves and only finite values, or
  ValueError. A guess that disagrees with the observation (the other side to move, a stale position)
  is not a position this player could be in, and it is better to stop than to average it in. The
  message names the guess by its index in the belief, counting from 0 as explanation.guesses does,
  and never holds a position.
- Values are from the bot's view: evaluate_children scores for the side to move, which on the bot's
  own turn is the bot.
- Ties, averages equal within 1e-12, are broken by one random.Random that reset seeds, drawing from
  the sorted tied moves. A draw is made on every turn, tied or not, so a turn's draw depends on the
  seed and the number of turns since reset, and on nothing else.
- Decision.root_policy is one-hot on the move chosen. Decision.diagnostics are plain floats: guesses,
  scorer_calls, elapsed_ms and search_nodes (one expanded node per scorer call).
- time_budget_ms and the history are not used. The bot makes one scorer call per guess, and the
  tracker has already folded the history into the belief.

last_explanation keeps the numbers of the latest turn: the guesses and their weights, every move's
value on every guess, every move's average and the move chosen. The decision is made from that
explanation, and the page draws only from it, so what it shows is what the bot chose by. A turn that
raises leaves no explanation behind.
"""
import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter

from fow_shared.contracts import AgentInput, Decision
from fow_shared.interfaces import LeafEvaluator

TIE_TOLERANCE = 1e-12  # an average this close to the best one is tied with it


@dataclass(frozen=True)
class Explanation:
    """What the bot chose by on one turn: the numbers behind its Decision, all in the bot's view."""

    scorer: str
    guesses: tuple[str, ...]  # hypothesis FENs, belief order
    weights: tuple[float, ...]
    values: Mapping[str, tuple[float, ...]]  # move -> value on each guess, bot's view
    averages: Mapping[str, float]  # move -> weighted average (the decision uses these)
    chosen: str
    elapsed_ms: float

    def to_json(self) -> dict:
        """Plain JSON values: lists and dicts, not tuples, and a fresh copy on every call. min and max
        are each move's lowest and highest value over the guesses."""
        return {
            "scorer": self.scorer,
            "guesses": list(self.guesses),
            "weights": list(self.weights),
            "values": {move: list(vs) for move, vs in self.values.items()},
            "averages": dict(self.averages),
            "min": {move: min(vs) for move, vs in self.values.items()},
            "max": {move: max(vs) for move, vs in self.values.items()},
            "chosen": self.chosen,
            "elapsed_ms": self.elapsed_ms,
        }


class OnePlyBot:
    """fow_shared's Agent. `scorer` is any LeafEvaluator; the bot uses only its name and evaluate_children."""

    name = "pairb-one-ply"

    def __init__(self, scorer: LeafEvaluator):
        self.scorer = scorer
        self.last_explanation: Explanation | None = None
        self._rng: random.Random | None = None

    def reset(self, player: str, seed: int) -> None:
        """Start a new game: seed the tie-break and forget the last explanation. The bot keeps no colour
        of its own; every observation names its player."""
        self._rng = random.Random(seed)
        self.last_explanation = None

    def act(self, turn: AgentInput) -> Decision:
        """The legal move with the highest weighted average value over the belief's guesses.

        ValueError, with last_explanation None, for a turn without legal moves and for a guess whose
        scores do not fit the observation; RuntimeError before the first reset.
        """
        if self._rng is None:
            raise RuntimeError("call reset(player, seed) before act")
        self.last_explanation = None  # nothing stale is left if this turn raises
        started = perf_counter()
        moves = turn.observation.legal_moves
        if not moves:
            raise ValueError("the observation has no legal move to choose from")
        hypotheses = turn.belief.hypotheses
        rows = [self._score(index, hypothesis.fen, moves) for index, hypothesis in enumerate(hypotheses)]
        weights = tuple(hypothesis.weight for hypothesis in hypotheses)
        values = {move: tuple(row[move] for row in rows) for move in moves}
        averages = {move: sum(w * v for w, v in zip(weights, vs)) for move, vs in values.items()}
        best = max(averages.values())
        tied = sorted(move for move, average in averages.items() if best - average <= TIE_TOLERANCE)
        chosen = self._rng.choice(tied)
        elapsed_ms = (perf_counter() - started) * 1000
        explanation = Explanation(self.scorer.name, tuple(h.fen for h in hypotheses), weights, values, averages,
                                  chosen, elapsed_ms)
        policy = {move: float(move == explanation.chosen) for move in explanation.averages}
        calls = float(len(rows))
        diagnostics = {"guesses": float(len(explanation.guesses)), "scorer_calls": calls,
                       "elapsed_ms": explanation.elapsed_ms, "search_nodes": calls}
        decision = Decision(explanation.chosen, policy, diagnostics)
        self.last_explanation = explanation
        return decision

    def _score(self, index: int, fen: str, moves: tuple[str, ...]) -> dict[str, float]:
        """The scorer's value of each move on the guess `fen`, as plain floats."""
        children = self.scorer.evaluate_children(fen)
        if set(children) != set(moves):
            raise ValueError(f"guess {index} has different legal moves from the observation")
        row = {move: float(children[move]) for move in moves}
        if not all(map(math.isfinite, row.values())):
            raise ValueError(f"guess {index} has a value that is not a finite number")
        return row
