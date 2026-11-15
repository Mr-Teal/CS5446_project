"""Many fog-of-war chess games at once, for self-play. Belief-input version.

This file is the first PPO agent's fowppo/env.py (pair_b/experiments/ppo_selfplay/player/fowppo)
with one change: what a player is shown. The rules,
the rewards, the opponents and the action table are the same lines as before.

Rules: fow_shared.values (the team's shared rules): a game ends
when a king is captured, by the fifty-move rule, by threefold repetition, or when the side to move
has no move; all but the first are draws. A game that reaches MAX_PLIES is also a draw, as in the
team's matches.

What a player is shown (32 planes of 8 x 8, own side at the bottom, Black mirrored): the team's
belief input, fow_shared.features.PLANE_NAMES, as one "fuzzy board" (see belief.py):
   0- 5  own pieces by type (pawn, knight, bishop, rook, queen, king)
   6-11  enemy pieces by type on the squares this player sees now
  12     the squares this player sees now
  13     enemy pieces in view, any type
  14-19  how likely each square holds an enemy piece of each type, over the sampled positions
  20     log2 of the estimated number of move histories that fit, over 15 (at most 1)
  21     how likely the opponent sees each square
  22     how likely the opponent sees each of this player's pieces
  23     where the opponent's last move captured one of this player's pieces
  24     plies played, out of 200
  25     search depth (always 0: there is no search)
  26-27  own castling rights, kingside and queenside
  28-29  how likely the opponent still has each castling right
  30     the square of an en passant capture this player may make
  31     the halfmove clock over 100, averaged over the sampled positions

Each player has a belief sampler (kernel/belief_sampler.cpp). It is given that player's views and
own moves only, so nothing here comes from the hidden part of the board. The piece-count potential
(`phi`) does use the true board, but it is a training reward and the player never sees it.
"""
import random

import chess
import numpy as np

from fow_shared.values import _available_fog_moves, terminal_score

from . import belief
from .moves import N_ACTIONS, TYPE_OF

MAX_PLIES = 200
N_PLANES = belief.N_PLANES
SCALED_PLANES = tuple(range(N_PLANES))  # every plane is stored as 0..255
P_OWN, P_SEEN_ENEMY, P_SEEN, P_ANY_ENEMY, P_PROBABILITY, P_POPULATION, P_THEIR_VIEW, P_OURS_SEEN = 0, 6, 12, 13, 14, 20, 21, 22
P_LOSS, P_PLY, P_DEPTH, P_CASTLE, P_ENEMY_CASTLE, P_EN_PASSANT, P_CLOCK = 23, 24, 25, 26, 28, 30, 31
BELIEF_CAP = 1024  # the most positions a sampler keeps; the training run and the match player use the same value

_PIECE_VALUES = (1, 3, 3, 5, 9, 0)  # pawn, knight, bishop, rook, queen, king
_VICTIM_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}


def material_balance(board: chess.Board, color: chess.Color) -> int:
    """Piece values of `color` minus the opponent's (pawn 1, knight 3, bishop 3, rook 5, queen 9)."""
    own, other = board.occupied_co[color], board.occupied_co[not color]
    kinds = (board.pawns, board.knights, board.bishops, board.rooks, board.queens)
    return sum(v * ((k & own).bit_count() - (k & other).bit_count()) for v, k in zip(_PIECE_VALUES, kinds))


class Game:
    """One game: the true board, and for each player a belief sampler (indexed by colour as an int)."""

    __slots__ = ("board", "ply", "samplers")

    def __init__(self, samplers, seed: int, cap: int = BELIEF_CAP):
        board = self.board = chess.Board()
        self.ply = 0
        self.samplers = samplers
        for color in (chess.BLACK, chess.WHITE):  # both players know the start position
            belief.reset(samplers[color], board, color, seed * 2 + color, cap)

    def play(self, move: chess.Move):
        """Play `move` for the side to move. Returns None while the game goes on, with both
        players' samplers given their new views, or (reason, score for the player who would move
        next) when the move ended it."""
        board = self.board
        mover = board.turn
        captured = -1
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
            belief.step(self.samplers[chess.WHITE], self.samplers[chess.BLACK], board, move, captured, mover, self.ply)
        return ended


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

      obs      (n, 32, 64) uint8   what that player is shown
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
    `cap` is the most positions each belief sampler keeps.
    """

    def __init__(self, n: int, shaping: float = 0.0, auto_reset: bool = True, rivals=None, seed: int = 0,
                 arrays=None, opening=(0, 0), cap: int = BELIEF_CAP):
        self.n, self.shaping, self.auto_reset, self.opening, self.cap = n, shaping, auto_reset, tuple(opening), cap
        rivals = rivals or {"self": 1.0}
        if set(rivals) - set(RIVALS) or min(rivals.values()) < 0 or sum(rivals.values()) <= 0:
            raise ValueError(f"rivals must give chances for names in {RIVALS}")
        self._rival_kinds = [RIVALS.index(name) for name in rivals]
        self._rival_weights = list(rivals.values())
        self._rng = random.Random(seed)
        self._sampler_rng = random.Random(seed + 1_000_003)  # its own stream: the games stay those of the first run
        if arrays is None:
            arrays = {name: np.zeros(shape, dtype=dtype) for name, (dtype, shape) in array_fields(n).items()}
        self.obs, self.mask, self.phi = arrays["obs"], arrays["mask"], arrays["phi"]
        self.seat, self.control = arrays["seat"], arrays["control"]
        self._obs_address = self.obs.ctypes.data
        self._samplers = [(belief.create(), belief.create()) for _ in range(n)]  # (Black's, White's) of each game
        self.scripted = [0] * n
        self.games = [self._new_game(i) for i in range(n)]
        self.rival = [self._draw_rival() for _ in range(n)]
        self.tables = [None] * n
        self.alive = np.ones(n, dtype=np.bool_)
        self.results = [None] * n
        self.finished = []
        for i in range(n):
            self._prepare(i)

    def __del__(self):
        try:
            for pair in getattr(self, "_samplers", ()):
                for handle in pair:
                    belief.destroy(handle)
            self._samplers = []
        except Exception:  # the interpreter is shutting down and the library is already gone
            pass

    def _new_game(self, i: int) -> Game:
        """A new game after a random opening: a number of plies drawn evenly from `opening`, each a
        random legal move, as in the team's matches (2 to 8 plies there). Both players watch the
        opening, so their samplers follow it. An opening that would end the game is drawn again."""
        low, high = self.opening
        while True:
            game = Game(self._samplers[i], self._sampler_rng.getrandbits(48), self.cap)
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
        belief.planes_into(game.samplers[color], self._obs_address + i * belief.PLANE_BYTES)
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
                self.games[i] = self._new_game(i)
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
