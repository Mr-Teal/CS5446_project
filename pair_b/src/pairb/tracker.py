"""An honest belief tracker for Fog Lab: a set of possible true positions, called particles.

It implements fow_shared's BeliefTracker and, as that protocol requires, uses only the
observations it is given, its own player's moves and its own past state: nothing here sees a
referee or a true board. A particle is a state of the rules in use (pairb.rules) that would have
shown the player exactly the latest observation: the same squares, the same pieces on them, the
same legal moves and the same result.

- The first update starts from the public start position.
- After the player's own move, the move is applied to every particle.
- After a move the player did not see, each particle is replaced by every position one move away.
- Only the states that show the player exactly the observation are kept, one per standard_fen.
- Cap: if more than n_particles are left, a seeded random sample of n_particles is kept.
- Rebuild, when none is left (a cap dropped the true position earlier, or the start was wrong):
  up to rebuild_tries times, a previous particle has one to three of the opponent's pieces on
  squares the player did not see moved to other such squares, and is stepped forward again;
  failing that, up to rebuild_tries times, the opponent's pieces of a previous particle are placed
  at random on the squares the player cannot see now. The first try that fits ends the rebuild.
  TrackerLost if nothing fits.
- Output: a Belief of up to n_hypotheses particles, sampled, with uniform weights.
  population_size is the number of particles while the set is exact (never capped or rebuilt
  since reset), and None after that.

Particles keep their move history, because threefold repetition needs it. A rebuilt particle is
made from a FEN, so its history starts there; the rules start such a state at ply 0, and it is
given the ply it stands for with dataclasses.replace, which Pair B's StandinState and Teal's
RuleState both allow. One random.Random, seeded by reset, makes every choice, so the same rules,
start, seed, observations and own moves always give the same particles and beliefs.
"""
import dataclasses
import random
from collections import Counter
from collections.abc import Iterable
from typing import Any

import chess

from fow_shared.contracts import Belief, Hypothesis, Observation
from fow_shared.values import standard_fen

from .rules import Rules

_BACK_RANKS = (0, 7)  # no pawn may stand on the first or last rank


class TrackerLost(RuntimeError):
    """No position fits the player's observation, and a rebuild found none either."""


class ParticleTracker:
    """fow_shared's BeliefTracker: particles of `rules` states, each fitting the player's last view.

    n_particles caps the set (None: no cap), n_hypotheses is the most guesses a Belief carries,
    initial_fen is the public start (None: the standard start), and rebuild_tries bounds each of
    the two stages of a rebuild. After every update, capped says whether it sampled down to
    n_particles, rebuilt whether it had to rebuild, and exact whether neither has happened since
    reset.
    """

    def __init__(self, rules: Rules, n_particles: int | None = 256, n_hypotheses: int = 8,
                 initial_fen: str | None = None, rebuild_tries: int = 2000):
        if n_particles is not None and n_particles < 1:
            raise ValueError("n_particles must be at least 1, or None for no cap")
        if n_hypotheses < 1:
            raise ValueError("n_hypotheses must be at least 1")
        if rebuild_tries < 0:
            raise ValueError("rebuild_tries cannot be negative")
        self.rules = rules
        self.n_particles = n_particles
        self.n_hypotheses = n_hypotheses
        self.initial_fen = initial_fen
        self.rebuild_tries = rebuild_tries
        self._start = rules.initial_state(initial_fen)  # a start the rules refuse fails here
        self._player: str | None = None
        self._clear(random.Random(0))

    def _clear(self, rng: random.Random) -> None:
        self._rng = rng
        self._particles: list = []
        self._fens: list[str] = []
        self._last: Observation | None = None  # the observation the particles fit
        self.capped = False
        self.rebuilt = False
        self.exact = True

    def reset(self, player: str, seed: int) -> None:
        """Start a new game as `player` ("white" or "black"), every random choice drawn from `seed`."""
        if player not in ("white", "black"):
            raise ValueError(f"player must be 'white' or 'black', not {player!r}")
        self._player = player
        self._clear(random.Random(seed))

    def update(self, observation: Observation, own_move: str | None = None) -> Belief:
        """The belief after `observation`, the view that ends the game included.

        own_move is the player's own move that led to it: None at the start and after a move the
        player did not see. ValueError for a view of the other player or an own move that was not
        legal; TrackerLost, with the particles left as they were, when no position fits.
        """
        if self._player is None:
            raise RuntimeError("call reset(player, seed) before update")
        if observation.player != self._player:
            raise ValueError(f"this tracker follows {self._player}, not {observation.player}")
        if self._last is None:
            if own_move is not None:
                raise ValueError("the first update comes before any move, so own_move must be None")
            previous, candidates = [], [self._start]
        else:
            if own_move is not None and own_move not in self._last.legal_moves:
                raise ValueError(f"{own_move!r} was not among {self._player}'s legal moves")
            previous = self._particles
            candidates = (child for state in previous for child in self._successors(state, own_move))
        found = self._consistent(candidates, observation)
        rebuilt = not found
        if rebuilt:
            if not previous:
                raise TrackerLost(f"the start position does not fit {self._player}'s first view")
            found = self._rebuild(previous, observation, own_move)
        fens = list(found)
        capped = self.n_particles is not None and len(fens) > self.n_particles
        if capped:
            fens = [fens[i] for i in sorted(self._rng.sample(range(len(fens)), self.n_particles))]
        self._fens = fens
        self._particles = [found[fen] for fen in fens]
        self._last = observation
        self.capped, self.rebuilt = capped, rebuilt
        self.exact = self.exact and not (capped or rebuilt)
        return self._belief(observation)

    def particles(self) -> list:
        """The current particles: states of the rules, for read-only use."""
        return list(self._particles)

    def particle_fens(self) -> list[str]:
        """standard_fen of each particle, in the same order."""
        return list(self._fens)

    def _belief(self, observation: Observation) -> Belief:
        k = min(self.n_hypotheses, len(self._fens))
        picked = sorted(self._rng.sample(range(len(self._fens)), k))
        return Belief(self._player, observation.ply, tuple(Hypothesis(self._fens[i], 1 / k) for i in picked),
                      population_size=len(self._fens) if self.exact else None, weighting="uniform")

    def _successors(self, state: Any, own_move: str | None) -> list:
        """The states one ply after `state`: after the player's own move, or after each move the side
        to move could have made, when the player did not see it."""
        moves = self.rules.legal_moves(state)
        if own_move is not None:
            return [self.rules.apply_move(state, own_move)] if own_move in moves else []
        return [self.rules.apply_move(state, move) for move in moves]

    def _consistent(self, states: Iterable, observation: Observation) -> dict[str, Any]:
        """The states that would have shown the player exactly `observation`, by standard_fen; the
        first state met is kept for each FEN, in the order met."""
        kept = {}
        for state in states:
            if self.rules.observe(state, self._player) == observation:
                kept.setdefault(standard_fen(self.rules.board(state)), state)
        return kept

    def _rebuild(self, previous: list, observation: Observation, own_move: str | None) -> dict[str, Any]:
        """Positions that fit `observation` when no particle does, made from `previous` particles."""
        before = self._last
        seen = set(before.visible_squares)
        unseen = [square for square in chess.SQUARES if chess.square_name(square) not in seen]
        for _ in range(self.rebuild_tries):
            moved = self._move_unseen(self._rng.choice(previous), unseen, before.ply)
            if moved is not None:
                found = self._consistent(self._successors(moved, own_move), observation)
                if found:
                    return found
        for _ in range(self.rebuild_tries):
            placed = self._place_unseen(self._rng.choice(previous), observation, own_move)
            if placed is not None:
                found = self._consistent([placed], observation)
                if found:
                    return found
        raise TrackerLost(f"no position fits {self._player}'s view at ply {observation.ply}")

    def _move_unseen(self, state: Any, unseen: list[int], ply: int) -> Any:
        """`state` with one to three of the opponent's pieces on `unseen` squares moved to other empty
        unseen squares, as a new state at `ply`; None if there is nothing to move."""
        board = self.rules.board(state)
        them = not _color(self._player)
        hidden = [square for square in unseen if board.color_at(square) == them]
        free = [square for square in unseen if board.piece_at(square) is None]
        if not hidden or not free:
            return None
        for square in self._rng.sample(hidden, self._rng.randint(1, min(3, len(hidden)))):
            piece = board.piece_at(square)
            spots = [to for to in free if piece.piece_type != chess.PAWN or chess.square_rank(to) not in _BACK_RANKS]
            if spots:
                to = self._rng.choice(spots)
                board.remove_piece_at(square)
                board.set_piece_at(to, piece)
                free.remove(to)
                free.append(square)
        return self._state_from(board, ply)

    def _place_unseen(self, state: Any, observation: Observation, own_move: str | None) -> Any:
        """The pieces `observation` shows where it shows them, and the opponent's other pieces of
        `state` (a previous particle) at random on the squares it does not show, as a new state; None
        if they do not fit."""
        me = _color(self._player)
        if own_move is not None:
            board = self.rules.board(self.rules.apply_move(state, own_move))
        else:
            board = self.rules.board(state)
            mine_before = len(chess.SquareSet(board.occupied_co[me]))
            board.push(chess.Move.null())  # the unseen move: the turn passes and the clocks run on
            mine_now = sum(1 for symbol in observation.visible_pieces.values()
                           if symbol is not None and chess.Piece.from_symbol(symbol).color == me)
            if mine_now < mine_before:
                board.halfmove_clock = 0  # the opponent took one of the player's pieces
            board.ep_square = _en_passant_square(observation)
        theirs = Counter(board.piece_at(square).symbol() for square in chess.scan_forward(board.occupied_co[not me]))
        shown = sorted((name, symbol) for name, symbol in observation.visible_pieces.items() if symbol is not None)
        for _, symbol in shown:
            if chess.Piece.from_symbol(symbol).color == me:
                continue
            pawn = "P" if symbol.isupper() else "p"
            if theirs[symbol] > 0:
                theirs[symbol] -= 1
            elif symbol not in (pawn, "K", "k") and theirs[pawn] > 0:
                theirs[pawn] -= 1  # a pawn that was promoted
        board.clear_board()
        for name, symbol in shown:
            board.set_piece_at(chess.parse_square(name), chess.Piece.from_symbol(symbol))
        free = [square for square in chess.SQUARES
                if chess.square_name(square) not in observation.visible_pieces and square != board.ep_square]
        for symbol in sorted(theirs.elements()):
            piece = chess.Piece.from_symbol(symbol)
            spots = [to for to in free if piece.piece_type != chess.PAWN or chess.square_rank(to) not in _BACK_RANKS]
            if not spots:
                return None
            to = self._rng.choice(spots)
            board.set_piece_at(to, piece)
            free.remove(to)
        return self._state_from(board, observation.ply)

    def _state_from(self, board: chess.Board, ply: int) -> Any:
        """A state of the rules for a board changed by hand, at `ply`; None if the rules refuse it.

        The rules build it from the FEN, which has no move history, and start it at ply 0, so it is
        given its ply with dataclasses.replace when its state type has a ply field.
        """
        board.castling_rights = board.clean_castling_rights()
        _drop_stale_en_passant(board)
        try:
            state = self.rules.initial_state(standard_fen(board))
        except ValueError:
            return None
        if dataclasses.is_dataclass(state) and "ply" in {field.name for field in dataclasses.fields(state)}:
            state = dataclasses.replace(state, ply=ply)
        return state


def _color(player: str) -> chess.Color:
    return chess.WHITE if player == "white" else chess.BLACK


def _en_passant_square(observation: Observation) -> int | None:
    """The en passant square when the player's legal moves include an en passant capture, a pawn's
    diagonal move onto a square the player sees empty; None otherwise."""
    pieces = observation.visible_pieces
    for move in observation.legal_moves:
        start, end = move[:2], move[2:4]
        if pieces.get(start) in ("P", "p") and start[0] != end[0] and end in pieces and pieces[end] is None:
            return chess.parse_square(end)
    return None


def _drop_stale_en_passant(board: chess.Board) -> None:
    """Keep the en passant square only while it and the square behind it are empty and the pawn that
    moved two squares stands in front of it."""
    ep = board.ep_square
    if ep is None:
        return
    step = -8 if board.turn == chess.WHITE else 8  # from the en passant square towards that pawn
    rank = 5 if board.turn == chess.WHITE else 2
    if (chess.square_rank(ep) != rank or board.piece_at(ep) is not None or board.piece_at(ep - step) is not None
            or board.piece_at(ep + step) != chess.Piece(chess.PAWN, not board.turn)):
        board.ep_square = None
