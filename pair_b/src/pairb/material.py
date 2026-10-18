"""The piece-value evaluator: the crudest leaf, counting pieces (pawn 1, knight 3, bishop 3,
rook 5, queen 9), the hand-made "utility of a state" from the lectures.

It answers fow_shared's three LeafEvaluator calls, like StockfishEvaluator, so a match can use it
as the simple-evaluation comparison ([1] also tests Obscuro against a simple evaluator). The
balance goes through fow_shared's tanh(cp / 600), so a pawn counts like Stockfish's +100.
Boards decided by a fog-of-war rule keep the rule's exact value.
"""
import chess

from fow_shared.contracts import LeafValues
from fow_shared.values import cp_to_score, fog_legal_moves, rule_score, terminal_score

PIECE_CP = {chess.PAWN: 100, chess.KNIGHT: 300, chess.BISHOP: 300, chess.ROOK: 500, chess.QUEEN: 900,
            chess.KING: 0}
_SIGN = {"white": 1.0, "black": -1.0}


def _side_to_move_value(board: chess.Board) -> float:
    """The board's value for its side to move: by rule, else by counting material."""
    rule = rule_score(board)
    if rule is not None:
        return rule[1]
    balance = sum(PIECE_CP[p.piece_type] * (1 if p.color == board.turn else -1)
                  for p in board.piece_map().values())
    return cp_to_score(balance)


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
        values = {}
        for move in fog_legal_moves(board):
            child = board.copy(stack=False)
            child.push(move)
            values[move.uci()] = -_side_to_move_value(child) + 0.0  # + 0.0 turns -0.0 into 0.0
        return values

    def evaluate_boards(self, fens: list[str], player: str) -> list[float]:
        """One value per board, same order, from `player`'s view ("white" or "black")."""
        if player not in _SIGN:
            raise ValueError(f"player must be 'white' or 'black', got {player!r}")
        values = []
        for fen in fens:
            board = chess.Board(fen)
            v = _side_to_move_value(board)
            values.append(v if (board.turn == chess.WHITE) == (player == "white") else -v + 0.0)
        return values

    def evaluate_beliefs(self, turns) -> list[LeafValues]:
        """One LeafValues per belief (fow_shared AgentInput), each board scored on its own."""
        answers = []
        for turn in turns:
            fens = [h.fen for h in turn.belief.hypotheses]
            answer = LeafValues(tuple(self.evaluate_boards(fens, turn.observation.player)))
            answer.validate_for(turn)
            answers.append(answer)
        return answers
