"""The trained network as a fow_shared Agent, so it can play in the team's match loop.

The agent uses only what the match loop hands it: the player's own observations after every ply and
its own moves (AgentInput.history and .observation). ObservedBelief feeds that stream to a belief
sampler of its own, the same C++ sampler with the same cap as in training, and reads the 32 planes
from it; tests/training/test_agent.py checks that these planes equal the training environment's.
The belief in AgentInput (the match loop's tracker) is not read.
"""
import chess
import numpy as np
import torch

from fow_shared.contracts import AgentInput, Belief, Decision, Hypothesis, Observation

from . import belief
from .env import BELIEF_CAP
from .model import PolicyValueNet
from .moves import N_ACTIONS, action_of


class ObservedBelief:
    """One player's belief sampler, fed with that player's observations in ply order."""

    def __init__(self, color: chess.Color, seed: int, cap: int = BELIEF_CAP):
        self.color = color
        self.handle = belief.create()
        belief.reset(self.handle, chess.Board(), color, seed, cap)  # both players know the start position
        self.own_all = chess.Board().occupied_co[color]
        self.statuses = []

    def __del__(self):
        if getattr(self, "handle", None):
            belief.destroy(self.handle)
            self.handle = None

    def see(self, observation: Observation, own_move=None) -> None:
        """Take in this player's next observation (one arrives after every ply). `own_move` is this
        player's move that led to it, as UCI, or None after the opponent's move. The first
        observation, at ply 0, shows the start position and changes nothing."""
        white = self.color == chess.WHITE
        own_all = 0
        for name, symbol in observation.visible_pieces.items():
            if symbol is not None and symbol.isupper() == white:
                own_all |= chess.BB_SQUARES[chess.parse_square(name)]
        if observation.ply > 0:
            # A piece of ours that vanished while the opponent moved was captured on that square.
            lost = self.own_all & ~own_all if own_move is None else 0
            captured = lost.bit_length() - 1 if lost else -1
            move = None if own_move is None else chess.Move.from_uci(own_move)
            self.statuses.append(belief.update(self.handle, belief.view_of(observation, captured), move, observation.ply))
        self.own_all = own_all

    def planes(self) -> np.ndarray:
        return belief.planes(self.handle)


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

    def __init__(self, model: PolicyValueNet, sample: bool = True, name: str = "ppo-belief", cap: int = BELIEF_CAP):
        self.model, self.sample, self.name, self.cap = model.eval(), sample, name, cap
        self._generator = torch.Generator()
        self._seed = 0
        self._belief = None
        self._fed = 0

    @classmethod
    def from_checkpoint(cls, path, sample: bool = True, name: str = "ppo-belief") -> "PpoAgent":
        saved = torch.load(path, map_location="cpu")
        model = PolicyValueNet(saved["config"]["blocks"], saved["config"]["channels"])
        model.load_state_dict(saved["model"])
        return cls(model, sample, name)

    def reset(self, player: str, seed: int) -> None:
        self._generator.manual_seed(seed)
        self._seed = seed
        self._belief = None
        self._fed = 0

    def _follow(self, turn: AgentInput) -> ObservedBelief:
        """Bring the sampler up to this turn. Observations already taken in are not fed again."""
        observations = [event.observation for event in turn.history] + [turn.observation]
        led = [None] + [event.own_move for event in turn.history]  # the own move that led to each observation
        if self._belief is None or self._fed > len(observations) - 1:
            color = chess.WHITE if turn.observation.player == "white" else chess.BLACK
            self._belief, self._fed = ObservedBelief(color, self._seed, self.cap), 0
        for observation, own_move in zip(observations[self._fed:], led[self._fed:]):
            self._belief.see(observation, own_move)
        self._fed = len(observations)
        return self._belief

    @torch.no_grad()
    def act(self, turn: AgentInput) -> Decision:
        observation = turn.observation
        planes = self._follow(turn).planes()
        table = action_table(observation)
        if not table:
            raise ValueError("the observation has no legal move to choose from")
        mask = np.zeros(N_ACTIONS, dtype=np.bool_)
        mask[list(table)] = True
        logits, value = self.model(torch.from_numpy(planes)[None], torch.from_numpy(mask)[None])
        chances = torch.softmax(logits[0].double(), dim=0)
        if self.sample:
            action = int(torch.multinomial(chances, 1, generator=self._generator))
        else:
            action = int(chances.argmax())
        policy = dict.fromkeys(observation.legal_moves, 0.0)
        total = float(sum(chances[a] for a in table))
        for a, uci in table.items():
            policy[uci] = float(chances[a]) / total
        state = belief.counters(self._belief.handle)
        return Decision(table[action], policy, {"value": float(value[0]), "belief_boards": float(belief.count(self._belief.handle)),
                                                "belief_repairs": float(state["repairs"]), "belief_blank": float(state["blank"])})


class NoBelief:
    """A BeliefTracker placeholder for the match loop, which needs a tracker for each colour. The PPO
    player never reads it: it keeps its own sampler (ObservedBelief)."""

    def reset(self, player: str, seed: int) -> None:
        self._player = player

    def update(self, observation: Observation, own_move=None) -> Belief:
        return Belief(self._player, observation.ply, (Hypothesis(chess.STARTING_FEN, 1.0),), weighting="placeholder")
