"""An honest belief tracker for Fog Lab: a set of possible true positions, called particles.

It implements fow_shared's BeliefTracker and, as that protocol requires, uses only the
observations it is given, its own player's moves and its own past state: nothing here sees a
referee or a true board. A particle is a state of the rules in use (pairb.rules) that would have
shown the player exactly the latest observation: the same squares, the same pieces on them, the
same legal moves and the same result.

- The first update starts from the public start position.
- After the player's own move, the move is applied to every particle.
- After a move the player did not see, each particle is replaced by every position one move away.
- Only the states that show the player exactly the observation are kept. Two of them are merged
  only when they have the same standard_fen and the same positions since the last irreversible
  move (the positions python-chess's threefold-repetition check counts), so merging never changes
  what the rules can decide later, a repetition draw included.
- Cap: if more than n_particles are left, a seeded random sample of n_particles is kept.
- Rebuild, when none is left (a cap dropped the true position earlier, or the start was wrong):
  up to rebuild_tries times, a previous particle has one to three of the opponent's pieces on
  squares the player did not see moved to other such squares, and is stepped forward again;
  failing that, up to rebuild_tries times, the opponent's pieces of a previous particle are placed
  at random on the squares the player cannot see now. Each stage collects distinct positions that
  fit until it has n_hypotheses of them (n_particles if that is smaller) or its tries run out, so
  that a rebuilt belief is not a single guess. TrackerLost if nothing fits.
- A view that ends the game never raises. If nothing fits it even after a rebuild, the positions
  one step on that show the player the same squares and pieces are kept (all of them if none does),
  and the update counts as a rebuild.
- Output: a Belief of up to n_hypotheses particles, sampled, with uniform weights. Hypotheses that
  share a FEN get distinct history_ids, a short hash of their positions since the last
  irreversible move; a FEN that is unique in the belief keeps "". population_size is the number of
  particles while the set is exact (never capped or rebuilt since reset), and None after that.

Particles keep their move history, because threefold repetition needs it. Keeping histories apart
makes an uncapped set grow with every path the opponent could have walked unseen: in a quiet
ending with a rook or a king wandering out of view, tens of thousands of particles within a dozen
plies. A rebuilt particle is made from a FEN, so its history starts there; the rules start such a
state at ply 0, and it is given the ply it stands for with dataclasses.replace, which Pair B's
StandinState and Teal's RuleState both allow, and, where the state keeps one (Teal's RuleState), the
view's capture notice. One random.Random, seeded by reset, makes every
choice, so the same rules, start, seed, observations and own moves always give the same particles
and beliefs.
"""
import dataclasses
import hashlib
import random
from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

import chess

from fow_shared.contracts import Belief, Hypothesis, Observation
from fow_shared.values import standard_fen

from .rules import Rules

_BACK_RANKS = (0, 7)  # no pawn may stand on the first or last rank
# A particle's positions since the last irreversible move, as python-chess's repetition check
# compares them (Board.epd: the en passant square only when a legal capture exists), sorted.
Window = tuple[str, ...]


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
        self._windows: list[Window] = []
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
        legal; TrackerLost, with the particles left as they were, when no position fits a view that
        does not end the game.
        """
        if self._player is None:
            raise RuntimeError("call reset(player, seed) before update")
        if observation.player != self._player:
            raise ValueError(f"this tracker follows {self._player}, not {observation.player}")
        if self._last is None:
            if own_move is not None:
                raise ValueError("the first update comes before any move, so own_move must be None")
            previous, candidates = [], [(self._start, ())]
        else:
            if own_move is not None and own_move not in self._last.legal_moves:
                raise ValueError(f"{own_move!r} was not among {self._player}'s legal moves")
            previous = list(zip(self._particles, self._windows))
            candidates = (child for state, window in previous for child in self._successors(state, window, own_move))
        found = self._keep(candidates, lambda view: view == observation)
        rebuilt = not found
        if rebuilt:
            if previous:
                found = self._rebuild(previous, observation, own_move)
            if not found and observation.terminal:
                found = self._lookalikes(previous, observation, own_move)
            if not found:
                raise TrackerLost(f"no position fits {self._player}'s view at ply {observation.ply}" if previous
                                  else f"the start position does not fit {self._player}'s first view")
        keys = list(found)
        capped = self.n_particles is not None and len(keys) > self.n_particles
        if capped:
            keys = [keys[i] for i in sorted(self._rng.sample(range(len(keys)), self.n_particles))]
        self._particles = [found[key] for key in keys]
        self._fens = [fen for fen, _ in keys]
        self._windows = [window for _, window in keys]
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
        shared = Counter(self._fens[i] for i in picked)
        hypotheses = tuple(Hypothesis(self._fens[i], 1 / k,
                                      _history_id(self._windows[i]) if shared[self._fens[i]] > 1 else "")
                           for i in picked)
        return Belief(self._player, observation.ply, hypotheses,
                      population_size=len(self._fens) if self.exact else None, weighting="uniform")

    def _successors(self, state: Any, window: Window, own_move: str | None) -> list[tuple[Any, Window]]:
        """The (state, window) pairs one ply after `state`: after the player's own move, or after each
        move the side to move could have made, when the player did not see it.

        A move python-chess calls irreversible (a capture, a pawn move, a lost castling right, or any
        move while an en passant capture is open) empties the window; any other move adds the
        position it leaves, as python-chess's repetition check walks back through them.
        """
        moves = self.rules.legal_moves(state)
        if own_move is not None:
            moves = (own_move,) if own_move in moves else ()
        if not moves:
            return []
        board = self.rules.board(state)
        longer = tuple(sorted((*window, board.epd())))
        return [(self.rules.apply_move(state, move), () if board.is_irreversible(chess.Move.from_uci(move)) else longer)
                for move in moves]

    def _keep(self, pairs: Iterable[tuple[Any, Window]], fits: Callable[[Observation], bool],
              kept: dict[tuple[str, Window], Any] | None = None) -> dict[tuple[str, Window], Any]:
        """The (state, window) pairs whose view for the player passes `fits`, by (standard_fen, window),
        added to `kept` if given; the first state met is kept for each key, in the order met."""
        kept = {} if kept is None else kept
        for state, window in pairs:
            if fits(self.rules.observe(state, self._player)):
                kept.setdefault((standard_fen(self.rules.board(state)), window), state)
        return kept

    def _rebuild(self, previous: list[tuple[Any, Window]], observation: Observation,
                 own_move: str | None) -> dict[tuple[str, Window], Any]:
        """Positions that fit `observation` when no particle does, made from `previous` particles;
        empty if none is found. A rebuilt position is made from a FEN, so its window starts empty.

        Each stage collects distinct positions until it has n_hypotheses of them (n_particles if
        that is smaller) or its rebuild_tries tries run out; the second runs only if the first found
        none.
        """
        want = self.n_hypotheses if self.n_particles is None else min(self.n_hypotheses, self.n_particles)
        before = self._last
        seen = set(before.visible_squares)
        unseen = [square for square in chess.SQUARES if chess.square_name(square) not in seen]
        found: dict[tuple[str, Window], Any] = {}
        for _ in range(self.rebuild_tries):
            if len(found) >= want:
                break
            moved = self._move_unseen(self._rng.choice(previous)[0], unseen, before.ply)
            if moved is not None:
                self._keep(self._successors(moved, (), own_move), lambda view: view == observation, found)
        for _ in range(0 if found else self.rebuild_tries):
            if len(found) >= want:
                break
            placed = self._place_unseen(self._rng.choice(previous)[0], observation, own_move)
            if placed is not None:
                self._keep([(placed, ())], lambda view: view == observation, found)
        return found

    def _lookalikes(self, previous: list[tuple[Any, Window]], observation: Observation,
                    own_move: str | None) -> dict[tuple[str, Window], Any]:
        """For a view that ends the game and that nothing fits: the positions one step on that show the
        player the same squares and pieces, whatever the result and legal moves, or all of them if
        none does, so that the end of a game never raises. With nothing to step to (the particles had
        already ended the game), the particles themselves."""
        if not previous:
            candidates = [(self._start, ())]
        else:
            candidates = [child for state, window in previous for child in self._successors(state, window, own_move)]
        candidates = candidates or previous
        shown = (observation.visible_squares, dict(observation.visible_pieces))
        return (self._keep(candidates, lambda view: (view.visible_squares, dict(view.visible_pieces)) == shown)
                or self._keep(candidates, lambda view: True))

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
        return self._state_from(board, observation.ply, observation.captured_own_piece_at)

    def _state_from(self, board: chess.Board, ply: int, captured_at: str | None = None) -> Any:
        """A state of the rules for a board changed by hand, at `ply`; None if the rules refuse it.

        The rules build it from the FEN, which has no move history, and start it at ply 0, so it is
        given its ply with dataclasses.replace when its state type has a ply field. A FEN has no
        capture notice either. Where the state type keeps one (Teal's RuleState: captured_player and
        captured_square), a state that must fit a view is given the view's, `captured_at`, the square
        where the player lost a piece, or it could never show the player that view. Pair B's
        StandinState keeps none. (A state that is stepped forward before it is compared, as a first
        rebuild stage's is, gets its notice from the move.)
        """
        board.castling_rights = board.clean_castling_rights()
        _drop_stale_en_passant(board)
        try:
            state = self.rules.initial_state(standard_fen(board))
        except ValueError:
            return None
        if dataclasses.is_dataclass(state):
            names = {field.name for field in dataclasses.fields(state)}
            changes = {"ply": ply} if "ply" in names else {}
            if captured_at is not None and {"captured_player", "captured_square"} <= names:
                changes.update(captured_player=self._player, captured_square=captured_at)
            if changes:
                state = dataclasses.replace(state, **changes)
        return state


def _color(player: str) -> chess.Color:
    return chess.WHITE if player == "white" else chess.BLACK


def _history_id(window: Window) -> str:
    """A short, reproducible name for a particle's positions since the last irreversible move."""
    return hashlib.sha1("\n".join(window).encode("utf-8")).hexdigest()[:16]


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
