"""Many fog-of-war chess games at once, for self-play.

Rules: fow_shared.values (this folder holds an unchanged copy from team main 355e5e3): a game ends
when a king is captured, by the fifty-move rule, by threefold repetition, or when the side to move
has no move; all but the first are draws. A game that reaches MAX_PLIES is also a draw, as in the
team's matches.

What a player is shown (25 planes of 8 x 8, own side at the bottom, Black mirrored):
   0- 5  own pieces by type (pawn, knight, bishop, rook, queen, king)
   6-11  enemy pieces by type on the squares this player sees now
  12     the squares this player sees now (the team rule: own squares, and where own pieces can move)
  13-18  enemy pieces by type as last seen, on squares not seen now (a memory, so it can be stale)
  19     how long ago each unseen square was last seen (0 = now, 248 = 31 plies or more)
  20     where the opponent's last move captured one of this player's pieces
  21-22  own castling rights, kingside and queenside
  23     plies played, out of MAX_PLIES
  24     1 if this player is White

Nothing here comes from the hidden part of the board: the memory holds only what the player saw
earlier, and both players know the start position. The piece-count potential (`phi`) does use the
true board, but it is a training reward and the player never sees it.
"""
import random

import chess
import numpy as np

from fow_shared.values import _available_fog_moves, terminal_score

from .moves import N_ACTIONS, TYPE_OF

MAX_PLIES = 200
N_PLANES = 25
P_OWN, P_SEEN_ENEMY, P_SEEN, P_MEMORY, P_AGE, P_LOSS, P_CASTLE, P_PLY, P_WHITE = 0, 6, 12, 13, 19, 20, 21, 23, 24
SCALED_PLANES = (P_AGE, P_PLY)  # stored as 0..255; every other plane is 0 or 1

_PIECE_VALUES = (1, 3, 3, 5, 9, 0)  # pawn, knight, bishop, rook, queen, king
_VICTIM_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
_MEMORY_LIMITS = (8, 2, 2, 2, 1, 1)  # most pieces of each type to remember (promotions aside)
_ALL = chess.BB_ALL
_NOT_A, _NOT_H = ~chess.BB_FILE_A & _ALL, ~chess.BB_FILE_H & _ALL


def seen_bb(board: chess.Board, color: chess.Color) -> int:
    """The squares `color` sees, as a bitboard: its own squares and the squares its pieces could
    move to, check ignored. A pawn sees a diagonal only when it can capture there. An en passant
    capture, open to the side to move only, also shows the pawn it would take."""
    own = board.occupied_co[color]
    occupied = board.occupied
    pawns = board.pawns & own
    seen = own
    for square in chess.scan_forward(own & ~pawns):
        seen |= board.attacks_mask(square)
    if color == chess.WHITE:
        single = (pawns << 8) & ~occupied & _ALL
        double = ((single & chess.BB_RANK_3) << 8) & ~occupied
        attacks = (((pawns & _NOT_A) << 7) | ((pawns & _NOT_H) << 9)) & _ALL
    else:
        single = (pawns >> 8) & ~occupied
        double = ((single & chess.BB_RANK_6) >> 8) & ~occupied
        attacks = ((pawns & _NOT_A) >> 9) | ((pawns & _NOT_H) >> 7)
    seen |= single | double | (attacks & board.occupied_co[not color])
    if board.turn == color and board.ep_square is not None:
        target = chess.BB_SQUARES[board.ep_square]
        if attacks & target and not occupied & target:
            seen |= target | (target >> 8 if color == chess.WHITE else target << 8)
    return seen


def material_balance(board: chess.Board, color: chess.Color) -> int:
    """Piece values of `color` minus the opponent's (pawn 1, knight 3, bishop 3, rook 5, queen 9)."""
    own, other = board.occupied_co[color], board.occupied_co[not color]
    kinds = (board.pawns, board.knights, board.bishops, board.rooks, board.queens)
    return sum(v * ((k & own).bit_count() - (k & other).bit_count()) for v, k in zip(_PIECE_VALUES, kinds))


def _cells(bitboards) -> np.ndarray:
    """Bitboards as (len, 64) uint8, one cell per square a1..h8."""
    raw = np.array(bitboards, dtype="<u8").view(np.uint8)
    return np.unpackbits(raw, bitorder="little").reshape(len(bitboards), 64)


def remember(memory: list, age: np.ndarray, seen: int, enemy_now) -> None:
    """Update one player's memory after a ply, in place. `seen` is what the player sees now and
    `enemy_now` the enemy pieces in view by type (six bitboards). Squares in view are known
    exactly; other squares keep what was last seen there and grow one ply older."""
    age += age < 255
    age[_cells((seen,))[0].view(np.bool_)] = 0
    for k in range(6):
        now = enemy_now[k]
        kept = memory[k] & ~seen
        # A piece seen somewhere new replaces the oldest memory of that type.
        while kept and (kept | now).bit_count() > _MEMORY_LIMITS[k]:
            oldest = max(chess.scan_forward(kept), key=age.__getitem__)
            kept &= ~chess.BB_SQUARES[oldest]
        memory[k] = kept | now


def write_planes(out: np.ndarray, color: chess.Color, own, enemy_seen, seen: int, memory, age: np.ndarray,
                 loss: int, kingside: bool, queenside: bool, ply: int) -> None:
    """Write one player's 25 planes into `out`, shape (25, 64) uint8. `own` and `enemy_seen` are six
    bitboards each, by piece type; the rest is that player's view, memory and counters."""
    boards = list(own) + list(enemy_seen) + [seen] + [m & ~seen for m in memory] + [loss]
    scaled_age = np.minimum(age, 31) * 8
    if color == chess.BLACK:
        boards = [chess.flip_vertical(b) for b in boards]
        scaled_age = scaled_age.reshape(8, 8)[::-1].reshape(64)
    cells = _cells(boards)
    out[0:19] = cells[0:19]
    out[P_AGE] = scaled_age
    out[P_LOSS] = cells[19]
    out[P_CASTLE] = kingside
    out[P_CASTLE + 1] = queenside
    out[P_PLY] = min(ply, MAX_PLIES) * 255 // MAX_PLIES
    out[P_WHITE] = color == chess.WHITE


class Game:
    """One game: the true board, and for each player what it sees and remembers."""

    __slots__ = ("board", "ply", "seen", "memory", "age", "loss")

    def __init__(self):
        board = self.board = chess.Board()
        self.ply = 0
        # Indexed by colour as an int: 0 = Black, 1 = White.
        self.seen = [seen_bb(board, chess.BLACK), seen_bb(board, chess.WHITE)]
        # Both players know the start position, so each starts by remembering the other's set-up.
        self.memory = [[board.pieces_mask(kind, not color) for kind in chess.PIECE_TYPES]
                       for color in (chess.BLACK, chess.WHITE)]
        self.age = [np.zeros(64, dtype=np.uint8), np.zeros(64, dtype=np.uint8)]
        self.loss = [0, 0]

    def after_move(self, mover: chess.Color, captured_square):
        """Refresh both players' views and memories once `mover`'s move is on the board."""
        board = self.board
        kinds = (board.pawns, board.knights, board.bishops, board.rooks, board.queens, board.kings)
        for color in (chess.BLACK, chess.WHITE):
            seen = self.seen[color] = seen_bb(board, color)
            enemy_seen = board.occupied_co[not color] & seen
            remember(self.memory[color], self.age[color], seen, [k & enemy_seen for k in kinds])
        self.loss[mover] = 0
        self.loss[not mover] = 0 if captured_square is None else chess.BB_SQUARES[captured_square]

    def play(self, move: chess.Move):
        """Play `move` for the side to move. Returns None while the game goes on, with both views
        refreshed, or (reason, score for the player who would move next) when the move ended it."""
        board = self.board
        mover = board.turn
        captured = None
        if board.is_en_passant(move):
            captured = move.to_square + (-8 if mover == chess.WHITE else 8)
        elif board.occupied_co[not mover] & chess.BB_SQUARES[move.to_square]:
            captured = move.to_square
        board.push(move)
        self.ply += 1
        ended = terminal_score(board)
        if ended is None and self.ply >= MAX_PLIES:
            ended = ("ply_limit", 0.0)
        if ended is None:
            self.after_move(mover, captured)
        return ended


def encode(game: Game, color: chess.Color, out: np.ndarray) -> None:
    """Write `color`'s 25 planes into `out`, shape (25, 64) uint8."""
    board = game.board
    own, seen = board.occupied_co[color], game.seen[color]
    enemy_seen = board.occupied_co[not color] & seen
    kinds = (board.pawns, board.knights, board.bishops, board.rooks, board.queens, board.kings)
    write_planes(out, color, [k & own for k in kinds], [k & enemy_seen for k in kinds], seen, game.memory[color],
                 game.age[color], game.loss[color], board.has_kingside_castling_rights(color),
                 board.has_queenside_castling_rights(color), game.ply)


def legal_actions(board: chess.Board) -> dict:
    """{action: move} for the side to move. Under-promotions are left out: a pawn always queens."""
    black = board.turn == chess.BLACK
    table = {}
    for move in _available_fog_moves(board):
        if move.promotion is not None and move.promotion != chess.QUEEN:
            continue
        start, end = move.from_square, move.to_square
        if black:
            start, end = start ^ 56, end ^ 56
        table[TYPE_OF[start][end] * 64 + start] = move
    return table


RIVALS = ("self", "random", "greedy", "past")  # who the learner can meet in a game
LEARNER, SCRIPTED, PAST = 0, 1, 2  # who decides the next move (the `control` array)


def array_fields(n: int) -> dict:
    """{name: (dtype, shape)} of the arrays a VecFow of `n` games fills."""
    return {"obs": (np.uint8, (n, N_PLANES, 64)), "mask": (np.bool_, (n, N_ACTIONS)), "phi": (np.float32, (n,)),
            "seat": (np.int8, (n,)), "control": (np.int8, (n,))}


class VecFow:
    """`n` games side by side. After every step the arrays describe the player to move in each game:

      obs      (n, 25, 64) uint8   what that player is shown
      mask     (n, 4096) bool      its legal actions
      phi      (n,) float32        its piece balance times `shaping` (a training reward only)
      seat     (n,) int8           1 = White, 0 = Black
      control  (n,) int8           who decides this move: LEARNER, SCRIPTED or PAST

    step(actions) plays one move in every game (or in the games listed in `only`) and returns, for
    the player who moved, `term_r` (+1 if the move captured the king, else 0) and `done`. With
    auto_reset a finished game starts again at once; without it the game stays finished and its
    result is in `results`. `finished` lists (plies, winner, reason) with winner 1 White, 0 Black,
    -1 draw; the caller may clear it.

    `rivals` maps names in RIVALS to the chance that a new game is played against them; "self"
    means the learner plays both colours (the default for every game). In any other game one
    colour, chosen at random, belongs to the rival: a SCRIPTED rival's move is chosen here and
    played whatever action the caller passes, and a PAST rival's move must come from the caller
    (an earlier copy of the network). `arrays` lets a caller supply the storage (shared memory).
    `opening` = (low, high) starts every game with that many random plies; (0, 0) is the standard start.
    """

    def __init__(self, n: int, shaping: float = 0.0, auto_reset: bool = True, rivals=None, seed: int = 0,
                 arrays=None, opening=(0, 0)):
        self.n, self.shaping, self.auto_reset, self.opening = n, shaping, auto_reset, tuple(opening)
        rivals = rivals or {"self": 1.0}
        if set(rivals) - set(RIVALS) or min(rivals.values()) < 0 or sum(rivals.values()) <= 0:
            raise ValueError(f"rivals must give chances for names in {RIVALS}")
        self._rival_kinds = [RIVALS.index(name) for name in rivals]
        self._rival_weights = list(rivals.values())
        self._rng = random.Random(seed)
        if arrays is None:
            arrays = {name: np.zeros(shape, dtype=dtype) for name, (dtype, shape) in array_fields(n).items()}
        self.obs, self.mask, self.phi = arrays["obs"], arrays["mask"], arrays["phi"]
        self.seat, self.control = arrays["seat"], arrays["control"]
        self.scripted = [0] * n
        self.games = [self._new_game() for _ in range(n)]
        self.rival = [self._draw_rival() for _ in range(n)]
        self.tables = [None] * n
        self.alive = np.ones(n, dtype=np.bool_)
        self.results = [None] * n
        self.finished = []
        for i in range(n):
            self._prepare(i)

    def _new_game(self) -> Game:
        """A new game after a random opening: a number of plies drawn evenly from `opening`, each a
        random legal move, as in the team's matches (2 to 8 plies there). Both players watch the
        opening, so their memories are right. An opening that would end the game is drawn again."""
        low, high = self.opening
        while True:
            game = Game()
            for _ in range(self._rng.randint(low, high)):
                if game.play(self._rng.choice(_available_fog_moves(game.board))) is not None:
                    break
            else:
                return game

    def _draw_rival(self):
        """(kind, colour) of a new game's rival; kind 0 is "self", with no rival colour."""
        kind = self._rng.choices(self._rival_kinds, self._rival_weights)[0]
        return kind, self._rng.random() < 0.5

    def _prepare(self, i: int) -> None:
        game = self.games[i]
        color = game.board.turn
        table = self.tables[i] = legal_actions(game.board)
        row = self.mask[i]
        row[:] = False
        row[list(table)] = True
        encode(game, color, self.obs[i])
        self.phi[i] = self.shaping * material_balance(game.board, color)
        self.seat[i] = color
        kind, rival_color = self.rival[i]
        if kind == 0 or color != rival_color:
            self.control[i] = LEARNER
        elif RIVALS[kind] == "past":
            self.control[i] = PAST
        else:
            self.control[i] = SCRIPTED
            self.scripted[i] = scripted_action(self, i, RIVALS[kind], self._rng)

    def step(self, actions, only=None):
        term_r = np.zeros(self.n, dtype=np.float32)
        done = np.zeros(self.n, dtype=np.bool_)
        for i in (range(self.n) if only is None else only):
            game = self.games[i]
            board = game.board
            mover = board.turn
            move = self.tables[i][self.scripted[i] if self.control[i] == SCRIPTED else int(actions[i])]
            ended = game.play(move)
            if ended is not None:
                reason, score = ended
                reward = -score + 0.0  # the score speaks for the side to move, the mover's opponent
                term_r[i], done[i] = reward, True
                result = (game.ply, int(mover) if reward > 0 else -1, reason)
                self.finished.append(result)
                if not self.auto_reset:
                    self.alive[i], self.results[i] = False, result
                    continue
                self.games[i] = self._new_game()
                self.rival[i] = self._draw_rival()
            self._prepare(i)
        return term_r, done


def scripted_action(vec: VecFow, i: int, kind: str, rng) -> int:
    """A hand-made opponent's action in game `i`.

    "random": any legal move. "greedy": the capture of the most valuable piece, the king first, and
    any legal move when nothing can be captured. Both are honest: a move's target square is always
    in the mover's view, so the greedy player uses only what it sees.
    """
    table = vec.tables[i]
    actions = sorted(table)
    if kind == "random":
        return rng.choice(actions)
    if kind != "greedy":
        raise ValueError(f"unknown scripted player {kind!r}")
    board = vec.games[i].board
    best, best_value = [], 0
    for action in actions:
        move = table[action]
        victim = board.piece_type_at(move.to_square)
        value = _VICTIM_VALUES[victim] if victim else (1 if board.is_en_passant(move) else 0)
        if value > best_value:
            best, best_value = [action], value
        elif value == best_value and value > 0:
            best.append(action)
    return rng.choice(best) if best else rng.choice(actions)
