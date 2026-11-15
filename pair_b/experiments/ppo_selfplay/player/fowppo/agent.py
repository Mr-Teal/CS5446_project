"""The trained network as a fow_shared Agent, so it can play in the team's match loop.

The agent uses only what the match loop hands it: the player's own observations after every ply
(AgentInput.history and .observation). ObservationMemory turns that stream into the 25 planes the
network was trained on, with the same memory rule and plane writer as the training environment
(env.remember and env.write_planes); tests/test_agent.py checks the two give identical planes.
The belief in AgentInput is not read: this player keeps its own simple memory.
"""
import chess
import numpy as np
import torch

from fow_shared.contracts import AgentInput, Belief, Decision, Hypothesis, Observation

from .env import N_PLANES, remember, write_planes
from .model import PolicyValueNet
from .moves import N_ACTIONS, action_of

_KIND = {"p": 0, "n": 1, "b": 2, "r": 3, "q": 4, "k": 5}


class ObservationMemory:
    """One player's view and memory, built from that player's observations in ply order."""

    def __init__(self, color: chess.Color):
        start = chess.Board()  # both players know the start position
        self.color = color
        self.memory = [start.pieces_mask(kind, not color) for kind in chess.PIECE_TYPES]
        self.age = np.zeros(64, dtype=np.uint8)
        self.own, self.enemy_seen = [0] * 6, [0] * 6
        self.own_all = start.occupied_co[color]
        self.seen = self.loss = self.ply = 0
        self.kingside = self.queenside = True

    def see(self, observation: Observation) -> None:
        """Take in this player's next observation (one arrives after every ply, the start included)."""
        white = self.color == chess.WHITE
        own, enemy, seen = [0] * 6, [0] * 6, 0
        for name, symbol in observation.visible_pieces.items():
            bit = chess.BB_SQUARES[chess.parse_square(name)]
            seen |= bit
            if symbol is not None:
                (own if symbol.isupper() == white else enemy)[_KIND[symbol.lower()]] |= bit
        own_all = 0
        for bitboard in own:
            own_all |= bitboard
        if observation.ply > 0:  # the start position is known, not seen after a move
            remember(self.memory, self.age, seen, enemy)
        # A piece of ours that vanished while the opponent moved was captured on that square.
        opponent_just_moved = observation.ply > 0 and observation.side_to_move == observation.player
        self.loss = self.own_all & ~own_all if opponent_just_moved else 0
        rank = chess.BB_RANK_1 if white else chess.BB_RANK_8
        king_home = bool(own[5] & chess.BB_FILE_E & rank)
        self.kingside = self.kingside and king_home and bool(own[3] & chess.BB_FILE_H & rank)
        self.queenside = self.queenside and king_home and bool(own[3] & chess.BB_FILE_A & rank)
        self.own, self.enemy_seen, self.own_all, self.seen, self.ply = own, enemy, own_all, seen, observation.ply

    def planes(self) -> np.ndarray:
        out = np.zeros((N_PLANES, 64), dtype=np.uint8)
        write_planes(out, self.color, self.own, self.enemy_seen, self.seen, self.memory, self.age, self.loss,
                     self.kingside, self.queenside, self.ply)
        return out


def action_table(observation: Observation) -> dict:
    """{action: UCI move} for the observation's legal moves. Under-promotions have no action."""
    black = observation.player == "black"
    table = {}
    for uci in observation.legal_moves:
        move = chess.Move.from_uci(uci)
        if move.promotion in (None, chess.QUEEN):
            table[action_of(move, black)] = uci
    return table


class PpoAgent:
    """fow_shared's Agent. `sample` plays a move drawn from the policy, as in training; otherwise the
    most likely move."""

    def __init__(self, model: PolicyValueNet, sample: bool = True, name: str = "ppo"):
        self.model, self.sample, self.name = model.eval(), sample, name
        self._generator = torch.Generator()

    @classmethod
    def from_checkpoint(cls, path, sample: bool = True, name: str = "ppo") -> "PpoAgent":
        saved = torch.load(path, map_location="cpu")
        model = PolicyValueNet(saved["config"]["blocks"], saved["config"]["channels"])
        model.load_state_dict(saved["model"])
        return cls(model, sample, name)

    def reset(self, player: str, seed: int) -> None:
        self._generator.manual_seed(seed)

    @torch.no_grad()
    def act(self, turn: AgentInput) -> Decision:
        observation = turn.observation
        memory = ObservationMemory(chess.WHITE if observation.player == "white" else chess.BLACK)
        for event in turn.history:
            memory.see(event.observation)
        memory.see(observation)
        table = action_table(observation)
        if not table:
            raise ValueError("the observation has no legal move to choose from")
        mask = np.zeros(N_ACTIONS, dtype=np.bool_)
        mask[list(table)] = True
        logits, value = self.model(torch.from_numpy(memory.planes())[None], torch.from_numpy(mask)[None])
        chances = torch.softmax(logits[0].double(), dim=0)
        if self.sample:
            action = int(torch.multinomial(chances, 1, generator=self._generator))
        else:
            action = int(chances.argmax())
        policy = dict.fromkeys(observation.legal_moves, 0.0)
        total = float(sum(chances[a] for a in table))
        for a, uci in table.items():
            policy[uci] = float(chances[a]) / total
        return Decision(table[action], policy, {"value": float(value[0])})


class NoBelief:
    """A BeliefTracker for a player that does not use beliefs: it returns a one-board placeholder.
    The match loop needs a tracker for each colour; the PPO player never reads this one."""

    def reset(self, player: str, seed: int) -> None:
        self._player = player

    def update(self, observation: Observation, own_move=None) -> Belief:
        return Belief(self._player, observation.ply, (Hypothesis(chess.STARTING_FEN, 1.0),), weighting="placeholder")
