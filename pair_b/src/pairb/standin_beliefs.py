"""Practice beliefs for the belief network (D6), made without Pair A's tracker.

A belief is the true board plus alternatives in which some of the opponent's unseen pieces stand
on other unseen squares. An alternative is kept only if the player could not tell it from the
truth: the same squares seen, the same pieces on them and the same legal moves (pairb.observe).
Weights are uniform. These stand in for the tracker's sampled roots until Pair A's player runs;
records are written in Teal's TrainingRecord format, so training reads real labels unchanged.
"""
import random

import chess

from fow_shared.contracts import AgentInput, Belief, Decision, Hypothesis, TrainingRecord
from fow_shared.values import standard_fen

from .observe import observe


def _looks_the_same(board: chess.Board, seen, player: str, ply: int) -> bool:
    got = observe(board, player, ply)
    return (got.visible_squares, got.visible_pieces, got.legal_moves, got.terminal) == seen


def _drop_stale_en_passant(board: chess.Board) -> None:
    """Keep an en passant square only while the pawn that just moved two squares is behind it."""
    if board.ep_square is None:
        return
    behind = board.ep_square + (-8 if board.turn == chess.WHITE else 8)
    if board.piece_at(behind) != chess.Piece(chess.PAWN, not board.turn):
        board.ep_square = None


def make_turn(board: chess.Board, rng: random.Random, n_hypotheses: int = 8, ply: int = 0,
              max_moved: int = 3, tries: int = 64) -> AgentInput:
    """A practice belief for the side to move on the true `board`, as a fow_shared AgentInput."""
    player = "white" if board.turn == chess.WHITE else "black"
    obs = observe(board, player, ply)
    seen = (obs.visible_squares, obs.visible_pieces, obs.legal_moves, obs.terminal)
    visible = set(obs.visible_squares)
    them = not board.turn
    hidden = [sq for sq in chess.SquareSet(board.occupied_co[them]) if chess.square_name(sq) not in visible]
    empty = [sq for sq in chess.SQUARES if board.piece_at(sq) is None and chess.square_name(sq) not in visible]
    fens = [standard_fen(board)]
    for _ in range(tries if hidden and empty else 0):
        if len(fens) >= n_hypotheses:
            break
        alt = board.copy(stack=False)
        free = list(empty)
        for sq in rng.sample(hidden, rng.randint(1, min(max_moved, len(hidden)))):
            piece = alt.piece_at(sq)
            spots = [s for s in free if piece.piece_type != chess.PAWN or chess.square_rank(s) not in (0, 7)]
            if not spots:
                continue
            to = rng.choice(spots)
            alt.remove_piece_at(sq)
            alt.set_piece_at(to, piece)
            free.remove(to)
            free.append(sq)
        alt.castling_rights = alt.clean_castling_rights()
        _drop_stale_en_passant(alt)
        fen = standard_fen(alt)
        if fen not in fens and _looks_the_same(alt, seen, player, ply):
            fens.append(fen)
    rng.shuffle(fens)
    belief = Belief(player, ply, tuple(Hypothesis(f, 1 / len(fens)) for f in fens), weighting="uniform")
    return AgentInput(obs, belief, time_budget_ms=1000)


def record_for(turn: AgentInput, hypothesis_values, seed: int, game_id: str, label: str,
               diagnostics=None) -> TrainingRecord:
    """A TrainingRecord for a practice belief: the labels per board and their weighted mean.

    There is no solver here, so the policy is uniform over the legal moves and the move is the
    first of them; the belief network does not learn from either. `diagnostics` may carry
    baselines, such as quick Stockfish's value of each board as "d1:<index>".
    """
    moves = turn.observation.legal_moves
    root = sum(h.weight * v for h, v in zip(turn.belief.hypotheses, hypothesis_values))
    decision = Decision(moves[0], {m: 1 / len(moves) for m in moves}, dict(diagnostics or {}))
    return TrainingRecord(turn, decision, max(-1.0, min(1.0, root)), tuple(hypothesis_values), seed,
                          agent_name=label, config_id=f"d6-{label}-v1", game_id=game_id)
