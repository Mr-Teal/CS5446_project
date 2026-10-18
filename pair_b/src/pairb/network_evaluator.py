"""Network 1 as a leaf evaluator (D4): Stockfish's depth-1 value, corrected by the network.

It answers the three LeafEvaluator calls of fow_shared, like StockfishEvaluator, so a search or
a match swaps one for the other. Each call costs what Obscuro's leaf costs ([1] App. C.5: one
depth-1 Stockfish call, MultiPV over a node's children) plus one network pass over every board
it scores. Boards decided by a fog-of-war rule keep the rule's exact value and never reach the
network. Values follow fow_shared's rule: from the acting player's point of view.
"""
from pathlib import Path

import chess
import numpy as np
import torch

from fow_shared.contracts import LeafValues
from fow_shared.values import terminal_score

from .data import ENCODING
from .encode import encode_board, stm_sign
from .net1 import Network1
from .stockfish import StockfishEvaluator, _sign


def pick_device(device: str | None = None) -> str:
    if device:
        return device
    if torch.cuda.is_available():
        return "cuda"
    return "mps" if torch.backends.mps.is_available() else "cpu"


class NetworkEvaluator:
    def __init__(self, net: Network1, label: str = "network", *, name: str | None = None,
                 stockfish_path: str = "stockfish", device: str | None = None, new_game_each_call: bool = True):
        """new_game_each_call: as for StockfishEvaluator; inside a search, False is about 6x faster."""
        self.device = pick_device(device)
        self.net = net.to(self.device).eval()
        self.stockfish = StockfishEvaluator(depth=1, path=stockfish_path, new_game_each_call=new_game_each_call)
        self.name = name if name is not None else f"{label}+{self.stockfish.name}"  # e.g. net1-v2+stockfish-19-d1

    @classmethod
    def from_checkpoint(cls, path, **kwargs) -> "NetworkEvaluator":
        """A best.pt written by scripts/train_net1.py, labelled with its run folder's name."""
        ckpt = torch.load(path, map_location="cpu")
        if ckpt.get("encoding") != ENCODING:
            raise ValueError(f"checkpoint was trained on input planes {ckpt.get('encoding')!r}, not {ENCODING!r}")
        net = Network1(**ckpt["config"])
        net.load_state_dict(ckpt["state_dict"])
        return cls(net, Path(path).parent.name, **kwargs)

    def close(self):
        self.stockfish.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def evaluate_children(self, fen: str) -> dict[str, float]:
        """{move: value} for every fog-of-war legal move, from the moving player's view."""
        board = chess.Board(fen)
        if terminal_score(board) is not None:
            return {}
        children = self.stockfish.children_values(board)
        engine = [uci for uci, (_, by_rule) in children.items() if not by_rule]
        boards = []
        for uci in engine:
            child = board.copy(stack=False)
            child.push(chess.Move.from_uci(uci))  # push_uci would refuse fog-only moves
            boards.append(child)
        corrected = dict(zip(engine, self._correct(boards, [children[uci][0] for uci in engine])))
        sign = 1.0 if board.turn == chess.WHITE else -1.0
        return {uci: sign * corrected.get(uci, v) for uci, (v, _) in children.items()}

    def evaluate_boards(self, fens: list[str], player: str) -> list[float]:
        """One value per board, same order, from `player`'s view ("white" or "black")."""
        sign = _sign(player)
        return [sign * v for v in self._white_values([chess.Board(fen) for fen in fens])]

    def evaluate_beliefs(self, turns) -> list[LeafValues]:
        """One LeafValues per belief (fow_shared AgentInput). Every board of every belief goes
        through one network pass; each answer keeps its own boards, in order."""
        white = self._white_values([chess.Board(h.fen) for t in turns for h in t.belief.hypotheses])
        answers, start = [], 0
        for t in turns:
            end = start + len(t.belief.hypotheses)
            sign = _sign(t.observation.player)
            answer = LeafValues(tuple(sign * v for v in white[start:end]))
            answer.validate_for(t)
            answers.append(answer)
            start = end
        return answers

    def _white_values(self, boards: list[chess.Board]) -> list[float]:
        scored = [self.stockfish.board_value(b) for b in boards]
        engine = [i for i, (_, by_rule) in enumerate(scored) if not by_rule]
        values = [v for v, _ in scored]
        for i, v in zip(engine, self._correct([boards[i] for i in engine], [values[i] for i in engine])):
            values[i] = v
        return values

    @torch.no_grad()
    def _correct(self, boards: list[chess.Board], d1_white: list[float]) -> list[float]:
        """White-view values from Network 1. It works in each board's side-to-move view, as trained."""
        if not boards:
            return []
        signs = np.array([stm_sign(b) for b in boards], dtype=np.float32)
        planes = torch.from_numpy(np.stack([encode_board(b) for b in boards])).to(self.device)
        d1 = torch.from_numpy(signs * np.asarray(d1_white, dtype=np.float32)).to(self.device)
        return (signs * self.net(planes, d1).cpu().numpy()).tolist()
