"""The belief network as a leaf evaluator (D6): fow_shared's three LeafEvaluator calls.

evaluate_beliefs is its real use: every board of a belief is scored knowing the whole belief, and
all the beliefs of one call go through one network pass without mixing. evaluate_boards and
evaluate_children have no belief to give, so each board becomes a belief of its own, built from
what its side to move would see if that board were true (pairb.observe). Boards the fog-of-war
rules decide keep the rule's exact value. A use_d1 network also reads quick Stockfish's value of
each board: one depth-1 call per board, children included, because that is the value it trained
on (a parent's MultiPV score of a child differs from the child's own by 0.07 on average).
"""
from pathlib import Path

import chess
import numpy as np
import torch

from fow_shared.contracts import AgentInput, Belief, Hypothesis, LeafValues
from fow_shared.features import encode_belief
from fow_shared.values import fog_legal_moves, standard_fen, terminal_score

from .belief_data import ENCODING, opponent_visible
from .belief_net import BeliefNetwork
from .network_evaluator import pick_device
from .observe import observe
from .stockfish import StockfishEvaluator, _sign
from .values import rule_value


def _player(board: chess.Board) -> str:
    return "white" if board.turn == chess.WHITE else "black"


def _to_white(board: chess.Board) -> float:
    return 1.0 if board.turn == chess.WHITE else -1.0


def _alone(board: chess.Board) -> AgentInput:
    """A belief holding just this board, as its side to move would see it."""
    player = _player(board)
    return AgentInput(observe(board, player), Belief(player, 0, (Hypothesis(standard_fen(board), 1.0),)), 1000)


class BeliefNetworkEvaluator:
    def __init__(self, net: BeliefNetwork, label: str = "belief", *, name: str | None = None,
                 stockfish_path: str = "stockfish", device: str | None = None, new_game_each_call: bool = True):
        self.device = pick_device(device)
        self.net = net.to(self.device).eval()
        self.stockfish = (StockfishEvaluator(depth=1, path=stockfish_path, new_game_each_call=new_game_each_call)
                          if net.use_d1 else None)
        self.name = name if name is not None else (f"{label}+{self.stockfish.name}" if self.stockfish else label)

    @classmethod
    def from_checkpoint(cls, path, **kwargs) -> "BeliefNetworkEvaluator":
        """A best.pt written by scripts/train_belief_net.py, labelled with its run folder's name."""
        ckpt = torch.load(path, map_location="cpu")
        if ckpt.get("encoding") != ENCODING:
            raise ValueError(f"checkpoint was trained on {ckpt.get('encoding')!r}, not {ENCODING!r}")
        net = BeliefNetwork(**ckpt["config"])
        net.load_state_dict(ckpt["state_dict"])
        return cls(net, Path(path).parent.name, **kwargs)

    def close(self):
        if self.stockfish is not None:
            self.stockfish.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def evaluate_beliefs(self, turns) -> list[LeafValues]:
        """One LeafValues per belief (fow_shared AgentInput), from its acting player's view."""
        turns = list(turns)
        known = [[self._known(chess.Board(h.fen)) for h in t.belief.hypotheses] for t in turns]
        values = iter(self._score(turns, known))
        answers = []
        for turn, boards in zip(turns, known):
            sign = _sign(turn.observation.player)
            answer = LeafValues(tuple(sign * v + 0.0 if by_rule else next(values) for v, by_rule in boards))
            answer.validate_for(turn)
            answers.append(answer)
        return answers

    def evaluate_boards(self, fens: list[str], player: str) -> list[float]:
        """One value per board, same order, from `player`'s view ("white" or "black")."""
        sign = _sign(player)
        boards = [chess.Board(fen) for fen in fens]
        white = self._white_values(boards, [self._known(b) for b in boards])
        return [sign * v + 0.0 for v in white]

    def evaluate_children(self, fen: str) -> dict[str, float]:
        """{move: value} for every fog-of-war legal move, from the moving player's view."""
        board = chess.Board(fen)
        if terminal_score(board) is not None:
            return {}
        known = {}
        for move in fog_legal_moves(board):
            child = board.copy()  # keeps the history for the rule checks
            child.push(move)
            known[move.uci()] = self._known(child)
        children = []
        for uci in known:
            child = board.copy(stack=False)
            child.push(chess.Move.from_uci(uci))  # push_uci would refuse fog-only moves
            children.append(child)
        white = self._white_values(children, list(known.values()))
        sign = _to_white(board)
        return {uci: sign * v + 0.0 for uci, v in zip(known, white)}

    def _known(self, board: chess.Board) -> tuple[float, bool]:
        """White-view value of a board the rules decide, flagged True; otherwise quick Stockfish's
        value with use_d1, or NaN, flagged False."""
        if self.stockfish is not None:
            return self.stockfish.board_value(board)
        rule = rule_value(board)
        return (rule[1], True) if rule is not None else (float("nan"), False)

    def _white_values(self, boards: list[chess.Board], known: list[tuple[float, bool]]) -> list[float]:
        """White-view values of boards scored one by one (each a belief of its own)."""
        engine = [i for i, (_, by_rule) in enumerate(known) if not by_rule]
        scored = self._score([_alone(boards[i]) for i in engine], [[known[i]] for i in engine])
        white = [v for v, _ in known]
        for i, v in zip(engine, scored):
            white[i] = _to_white(boards[i]) * v
        return white

    @torch.no_grad()
    def _score(self, turns: list[AgentInput], known: list[list[tuple[float, bool]]]) -> list[float]:
        """Network values, each for its belief's acting player, of the boards no rule decides, in
        order. All the boards of all the beliefs go through one pass."""
        if not turns:
            return []
        planes, weights, belief, d1, engine = [], [], [], [], []
        for b, (turn, boards) in enumerate(zip(turns, known)):
            p, w = encode_belief(turn, opponent_visible)
            sign = _sign(turn.observation.player)
            planes.append(p)
            weights.append(w)
            belief.append(np.full(len(w), b))
            d1.extend(sign * v for v, _ in boards)
            engine.extend(not by_rule for _, by_rule in boards)
        to = lambda a, dtype: torch.from_numpy(np.asarray(a, dtype=dtype)).to(self.device)
        d = to(np.nan_to_num(np.array(d1, dtype=np.float32)), np.float32) if self.net.use_d1 else None
        out = self.net(to(np.concatenate(planes), np.float32), to(np.concatenate(weights), np.float32),
                       to(np.concatenate(belief), np.int64), len(turns), d).cpu().numpy()
        return [float(v) for v, keep in zip(out, engine) if keep]
