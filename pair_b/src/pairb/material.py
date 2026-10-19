"""The piece-value evaluator: the crudest leaf, counting pieces (pawn 1, knight 3, bishop 3,
rook 5, queen 9), the hand-made "utility of a state" from the lectures.

It answers fow_shared's three LeafEvaluator calls, like StockfishEvaluator, so a match can use it
as the simple-evaluation comparison ([1] also tests Obscuro against a simple evaluator). The
balance goes through fow_shared's tanh(cp / 600), so a pawn counts like Stockfish's +100.
Boards decided by a fog-of-war rule keep the rule's exact value.
"""
import chess

from fow_shared.contracts import LeafValues
from fow_shared.values import cp_to_score, fog_legal_moves, terminal_score

from .values import rule_value

PIECE_CP = {chess.PAWN: 100, chess.KNIGHT: 300, chess.BISHOP: 300, chess.ROOK: 500, chess.QUEEN: 900,
            chess.KING: 0}
_SIGN = {"white": 1.0, "black": -1.0}


def _sign(player: str) -> float:
    if player not in _SIGN:
        raise ValueError(f"player must be 'white' or 'black', got {player!r}")
    return _SIGN[player]


class MaterialEvaluator:
    name = "material-1-3-3-5-9"

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def evaluate_children(self, fen: str) -> dict[str, float]:
        """{move: value} for every fog-of-war legal move, from the moving player's view."""
        board = chess.Board(fen)
        if terminal_score(board) is not None:
            return {}
        sign = 1.0 if board.turn == chess.WHITE else -1.0
        return {uci: sign * v + 0.0 for uci, (v, _) in self.children_values(board).items()}  # + 0.0: no -0.0

    def evaluate_boards(self, fens: list[str], player: str) -> list[float]:
        """One value per board, same order, from `player`'s view ("white" or "black")."""
        sign = _sign(player)
        return [sign * self.board_value(chess.Board(fen))[0] + 0.0 for fen in fens]

    def evaluate_beliefs(self, turns) -> list[LeafValues]:
        """One LeafValues per belief (fow_shared AgentInput), each board scored on its own."""
        answers = []
        for turn in turns:
            fens = [h.fen for h in turn.belief.hypotheses]
            answer = LeafValues(tuple(self.evaluate_boards(fens, turn.observation.player)))
            answer.validate_for(turn)
            answers.append(answer)
        return answers

    def board_value(self, board: chess.Board) -> tuple[float, bool]:
        """One board's value from White's view, and whether a rule decided it (else counted)."""
        rule = rule_value(board)
        if rule is not None:
            return rule[1], True
        balance = sum(PIECE_CP[p.piece_type] * (1 if p.color == chess.WHITE else -1)
                      for p in board.piece_map().values())
        return cp_to_score(balance), False

    def children_values(self, board: chess.Board) -> dict[str, tuple[float, bool]]:
        """White-view value of every fog-legal child, and whether a rule decided it. Each child
        keeps the board's history, so a repetition draw is seen when the board carries it."""
        values = {}
        for move in fog_legal_moves(board):
            child = board.copy()
            child.push(move)
            values[move.uci()] = self.board_value(child)
        return values
