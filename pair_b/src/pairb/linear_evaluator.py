"""NumPy linear correction behind the shared LeafEvaluator interface."""
from pathlib import Path

import chess
import numpy as np

from fow_shared.contracts import LeafValues
from fow_shared.values import terminal_score

from .encode import encode_board, stm_sign
from .linear import LinearCorrection
from .stockfish import StockfishEvaluator, _sign


class LinearEvaluator:
    def __init__(self, model, *, stockfish_path="stockfish", new_game_each_call=True,
                 name=None):
        self.model = model
        self.stockfish = StockfishEvaluator(depth=1, path=stockfish_path,
                                            new_game_each_call=new_game_each_call)
        self.name = name or f"linear+{self.stockfish.name}"

    @classmethod
    def from_checkpoint(cls, path, **kwargs):
        model = LinearCorrection.load(path)  # validate before starting an engine
        kwargs.setdefault("name", f"{Path(path).parent.name}+stockfish-d1-linear")
        return cls(model, **kwargs)

    def close(self):
        self.stockfish.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _correct(self, boards, white_values):
        if not boards:
            return []
        signs = np.array([stm_sign(b) for b in boards])
        planes = np.stack([encode_board(b) for b in boards])
        return (signs * self.model.predict(planes, signs * white_values)).tolist()

    def _white_values(self, boards):
        scored = [self.stockfish.board_value(b) for b in boards]
        values = [v for v, _ in scored]
        indices = [i for i, (_, rule) in enumerate(scored) if not rule]
        for i, v in zip(indices, self._correct([boards[i] for i in indices],
                                               [values[i] for i in indices])):
            values[i] = v
        return values

    def evaluate_children(self, fen):
        board = chess.Board(fen)
        if terminal_score(board) is not None:
            return {}
        children = self.stockfish.children_values(board)
        moves = [uci for uci, (_, rule) in children.items() if not rule]
        boards = []
        for uci in moves:
            child = board.copy(stack=False)
            child.push(chess.Move.from_uci(uci))
            boards.append(child)
        corrected = dict(zip(moves, self._correct(boards, [children[m][0] for m in moves])))
        return {uci: stm_sign(board) * corrected.get(uci, v) for uci, (v, _) in children.items()}

    def evaluate_boards(self, fens, player):
        sign = _sign(player)
        return [sign * v for v in self._white_values([chess.Board(f) for f in fens])]

    def evaluate_beliefs(self, turns):
        turns = list(turns)
        white = self._white_values([chess.Board(h.fen) for t in turns for h in t.belief.hypotheses])
        answers, start = [], 0
        for turn in turns:
            end = start + len(turn.belief.hypotheses)
            answer = LeafValues(tuple(_sign(turn.observation.player) * v for v in white[start:end]))
            answer.validate_for(turn)
            answers.append(answer)
            start = end
        return answers
