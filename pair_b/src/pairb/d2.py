"""D2 stand-in dataset: positions from seeded games, labelled with Stockfish (D1 spec §6).

Games use ordinary chess moves, mixing Stockfish depth-1 moves with random ones; results are
scored with fog-of-war rules where they differ (stalemate is a win). Labels follow the paper's
leaf ([1] App. C.5): Stockfish in MultiPV mode at the parent, one score per child, at depth 1
("d1") and at the deeper label depth ("d11").
"""
import random

import chess
import chess.engine

from .values import rule_value, score_to_value


def game_end(board: chess.Board) -> tuple[str, int] | None:
    """How a D2 game ends here, as (termination, result from White's view), or None if it goes on.

    D2 games are ordinary chess, a stand-in until Pair A's agent can play fog-of-war games, so
    they stop when chess has no legal move. Results are scored with fog-of-war rules where they
    differ: a stalemate is a win for the side that delivered it.
    """
    if board.is_checkmate() or board.is_stalemate():
        return ("checkmate" if board.is_checkmate() else "stalemate"), (-1 if board.turn == chess.WHITE else 1)
    if board.halfmove_clock >= 100:
        return "fifty-move", 0
    if board.is_repetition(3):
        return "repetition", 0
    return None


def play_game(seed: int, engine: chess.engine.SimpleEngine, max_plies: int = 300,
              eps_range: tuple[float, float] = (0.02, 0.15)) -> tuple[list[str], dict]:
    """One seeded game: 2-8 random opening moves, then Stockfish depth-1 moves with a random
    move mixed in at rate eps, drawn per game from eps_range. The same seed gives the same game
    on any machine."""
    rng = random.Random(seed)
    eps = round(rng.uniform(*eps_range), 3)
    opening_plies = rng.randint(2, 8)
    board = chess.Board()
    game = object()  # one ucinewgame per game, so earlier games cannot change this one
    moves = []
    while (end := game_end(board)) is None and len(moves) < max_plies:
        legal = sorted(board.legal_moves, key=chess.Move.uci)
        if len(moves) < opening_plies or rng.random() < eps:
            move = rng.choice(legal)
        else:
            move = engine.play(board, chess.engine.Limit(depth=1), game=game).move
        board.push(move)
        moves.append(move.uci())
    termination, result = end if end is not None else ("max-plies", None)
    return moves, {"termination": termination, "result": result, "eps": eps, "opening_plies": opening_plies}


def pick_parents(n_moves: int, k: int, seed: int, min_ply: int = 8) -> list[int]:
    """Up to k plies whose position (after that many moves) becomes a parent: after the opening,
    and never the final position, which may be finished."""
    candidates = list(range(min_ply, n_moves))
    rng = random.Random(f"parents-{seed}")
    return sorted(rng.sample(candidates, min(k, len(candidates))))


def label_parent(parent: chess.Board, game_id: str, ply: int, ev1, ev_deep) -> list[dict]:
    """One record per chess-legal child of `parent`, the position after `ply` moves."""
    shallow = ev1.children_scores(parent)
    deep = ev_deep.children_scores(parent)
    moves = sorted(m.uci() for m in parent.legal_moves)
    if sorted(shallow) != moves or sorted(deep) != moves:
        raise RuntimeError(f"Stockfish did not score every move of {parent.fen()}")
    parent_fen = parent.fen()
    records = []
    for uci in moves:
        child = parent.copy()  # keeps the game's history, so a repetition draw is seen
        child.push_uci(uci)
        rule = rule_value(child)
        records.append({
            "id": f"d2-{game_id}-{ply:03d}-{uci}", "game_id": game_id, "ply": ply + 1,
            "parent_fen": parent_fen, "move": uci, "fen": child.fen(),
            "rule": {"name": rule[0], "v": rule[1]} if rule else None,
            "d1": None if rule else _score_record(shallow[uci]),
            "d11": None if rule else _score_record(deep[uci]),
        })
    return records


def _score_record(score: chess.engine.Score) -> dict:
    return {"cp": score.score(), "mate": score.mate(), "v": round(score_to_value(score), 6)}
