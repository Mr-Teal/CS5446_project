"""Move encoding for the belief network's policy head (growth prior).

A move is a (from, to) pair of squares in the same mirrored board frame as fow_shared.features: the mover's
home rank is always row 7, so Black's moves are flipped top to bottom like Black's planes. Index =
from_row * 512 + from_col * 64 + to_row * 8 + to_col, 4096 slots. Promotions share the pawn move's slot (the
solver's policies promote to a queen in practice; the prior is only used to order search, never to pick the
piece). The policy target of a record is decision.root_policy spread over these slots; the legal mask is
observation.legal_moves, which root_policy covers exactly (fow_shared.contracts.Decision.validate_for).
"""
from __future__ import annotations

from typing import Iterable, Mapping

import chess
import numpy as np

from fow_shared.features import _index

N_MOVES = 64 * 64


def square_index(square: str, player: str) -> int:
    """0..63 in the mirrored frame: row * 8 + col, row 7 = the mover's home rank."""
    row, col = _index(square, player)
    return row * 8 + col


def move_index(uci: str, player: str) -> int:
    """0..4095 for a UCI move, from the mover's mirrored frame; promotion suffixes are ignored."""
    move = chess.Move.from_uci(uci)
    return square_index(chess.square_name(move.from_square), player) * 64 + square_index(chess.square_name(move.to_square), player)


def legal_mask(legal_moves: Iterable[str], player: str) -> np.ndarray:
    mask = np.zeros(N_MOVES, dtype=bool)
    for uci in legal_moves:
        mask[move_index(uci, player)] = True
    return mask


def policy_vector(policy: Mapping[str, float], player: str) -> np.ndarray:
    """root_policy as a dense distribution over the 4096 slots (promotion variants of one pawn move add up)."""
    out = np.zeros(N_MOVES, dtype=np.float32)
    for uci, p in policy.items():
        out[move_index(uci, player)] += p
    return out


def decode(index: int, player: str) -> tuple[str, str]:
    """(from, to) square names of a slot, undoing the mirroring; promotion piece is not encoded."""
    from_i, to_i = divmod(index, 64)

    def name(i: int) -> str:
        row, col = divmod(i, 8)
        rank = 7 - row if player == "white" else row
        return chess.square_name(chess.square(col, rank))

    return name(from_i), name(to_i)
