"""Versioned PR #28 adjudication, independent of private draw history."""

from fow_shared.values import fog_legal_moves


RULES_ID = "paper2021_fow_no_moves_draw_v1"
LEGACY_RULES_ID = "paper2021_fow_no_moves_unresolved_v1"
NO_MOVE_RULE = "terminal_draw_v1"
TERMINAL_PRECEDENCE = ("king_capture", "fifty_move", "threefold_repetition", "no_legal_moves")


def has_fow_moves(board):
    if next(board.generate_pseudo_legal_moves(), None) is not None:
        return True
    position = board.copy(stack=False)
    position.halfmove_clock = 0
    return bool(fog_legal_moves(position))
