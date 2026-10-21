"""Exact, history-preserving inference from one player's private observations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from random import Random
from typing import Optional, Tuple

from fow_shared.contracts import Belief, Hypothesis, Observation
from .interface_draft import Player
from .rules_adapter import RuleState, RulesAdapter


class BeliefCapacityError(RuntimeError):
    """An exact update exceeded its explicit budget; no update was committed."""


@dataclass(frozen=True)
class _Candidate:
    state: RuleState
    moves: Tuple[str, ...]
    history_id: str

    def advance(self, rules: RulesAdapter, move: str) -> _Candidate:
        identity = sha256((self.history_id + ":" + move).encode("ascii")).hexdigest()
        return _Candidate(rules.apply_move(self.state, move), self.moves + (move,), identity)


class BeliefTracker:
    """Retain all consistent histories; optionally sample only the returned belief.

    Uniform means equal weight per surviving history, not a Bayesian posterior
    under a uniform-move opponent. Equal FENs with different paths stay distinct.
    No referee, true board, or opponent action is accepted by this interface.

    ``initial_fen`` is a publicly agreed starting position, also used when the
    shared match runner calls reset(player, seed). A reset-time FEN overrides it
    for that game only. A custom FEN starts fresh repetition history at ply zero.
    ``sample_size=None`` returns all candidates. ``max_candidates`` is an optional
    fail-fast limit on retained histories, never a truncation or particle filter.
    """

    def __init__(
        self,
        initial_fen: Optional[str] = None,
        *,
        sample_size: Optional[int] = None,
        max_candidates: Optional[int] = None,
    ) -> None:
        for name, value in (("sample_size", sample_size), ("max_candidates", max_candidates)):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{name} must be a positive integer or None")
        self._rules = RulesAdapter()
        self._initial_fen = initial_fen
        self._sample_size = sample_size
        self._max_candidates = max_candidates
        self._player: Optional[Player] = None
        self._previous: Optional[Observation] = None
        self._candidates: Tuple[_Candidate, ...] = ()
        self._rng = Random()

    @property
    def population_size(self) -> int:
        """Exact retained history count (zero before reset, one public root after)."""
        return len(self._candidates)

    def reset(
        self, player: Player, seed: int, initial_fen: Optional[str] = None
    ) -> None:
        """Clear prior inference and sampling state; wait for the ply-zero view."""
        if player not in ("white", "black"):
            raise ValueError("player must be white or black")
        if type(seed) is not int:
            raise ValueError("seed must be an integer")
        state = self._rules.initial_state(
            self._initial_fen if initial_fen is None else initial_fen
        )
        identity = sha256(state.fen.encode("ascii")).hexdigest()
        self._candidates = (_Candidate(state, (), identity),)
        self._player = player
        self._previous = None
        self._rng = Random(seed)

    def update(self, observation: Observation, own_move: Optional[str] = None) -> Belief:
        """Consume exactly the next snapshot, atomically or with an explicit error.

        own_move leads to this snapshot; it is required after our move and must
        be None at initialization and after an unknown opponent move. Invalid
        input, an empty result, or a capacity failure leaves the last accepted
        population, snapshot and sampling stream unchanged, allowing a retry.
        """
        if self._player is None:
            raise ValueError("reset must be called before update")
        if not isinstance(observation, Observation):
            raise ValueError("observation must be a shared Observation")
        # Reconstruct to validate and detach the caller-owned mapping.
        observation = replace(observation, visible_pieces=dict(observation.visible_pieces))
        if observation.player != self._player:
            raise ValueError("observation belongs to another player")
        expected_ply = 0 if self._previous is None else self._previous.ply + 1
        if type(observation.ply) is not int or observation.ply != expected_ply:
            raise ValueError(f"expected ply {expected_ply}, got {observation.ply}")

        if self._previous is None:
            if own_move is not None:
                raise ValueError("initial observation cannot have an own_move")
            candidates = [c for c in self._candidates if self._matches(c.state, observation)]
        else:
            if self._previous.terminal:
                raise ValueError("cannot advance a terminal belief; reset for a new game")
            next_player = "black" if self._previous.side_to_move == "white" else "white"
            if observation.side_to_move != next_player:
                raise ValueError("side_to_move must alternate after each ply")
            our_turn = self._previous.side_to_move == self._player
            if our_turn:
                if own_move is None or own_move not in self._previous.legal_moves:
                    raise ValueError("own_move must name an available action from the previous view")
            elif own_move is not None:
                raise ValueError("opponent moves must remain unknown; own_move must be None")

            candidates = []
            for parent in self._candidates:
                moves = (own_move,) if our_turn else self._rules.legal_moves(parent.state)
                for move in moves:
                    child = parent.advance(self._rules, move)
                    if self._matches(child.state, observation):
                        candidates.append(child)
                        if (self._max_candidates is not None
                                and len(candidates) > self._max_candidates):
                            raise BeliefCapacityError(
                                f"ply {observation.ply}: more than {self._max_candidates} "
                                "consistent histories; exact update was not committed"
                            )

        if not candidates:
            raise ValueError(
                f"ply {observation.ply}: no candidate history matches the observation"
            )
        belief = self._make_belief(candidates, observation.ply)
        self._candidates = tuple(candidates)
        self._previous = observation
        return belief

    def _matches(self, state: RuleState, observed: Observation) -> bool:
        predicted = self._rules.observe(state, observed.player)
        # Ordering of square/move sets has no information content. An explicitly
        # revealed clock constrains candidates; None provides no clock evidence.
        return (
            predicted.player == observed.player
            and predicted.side_to_move == observed.side_to_move
            and predicted.ply == observed.ply
            and set(predicted.visible_squares) == set(observed.visible_squares)
            and predicted.visible_pieces == observed.visible_pieces
            and set(predicted.legal_moves) == set(observed.legal_moves)
            and predicted.captured_own_piece_at == observed.captured_own_piece_at
            and predicted.terminal == observed.terminal
            and predicted.outcome == observed.outcome
            and (observed.halfmove_clock is None
                 or state.board_copy().halfmove_clock == observed.halfmove_clock)
        )

    def _make_belief(self, candidates: list[_Candidate], ply: int) -> Belief:
        count = len(candidates)
        if self._sample_size is not None and count > self._sample_size:
            indices = sorted(self._rng.sample(range(count), self._sample_size))
            selected = [candidates[i] for i in indices]
        else:
            selected = candidates
        weight = 1.0 / len(selected)
        return Belief(
            player=self._player,
            ply=ply,
            hypotheses=tuple(
                Hypothesis(c.state.fen, weight, c.history_id, c.moves) for c in selected
            ),
            population_size=count,
            weighting="uniform",
        )
