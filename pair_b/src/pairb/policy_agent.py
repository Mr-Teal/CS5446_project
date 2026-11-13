"""The policy network as a searchless player (13 Nov 2026), for strength games against OnePlyBot.

PolicyAgent plays the legal move with the highest probability under a trained policy network (pairb.policy_net) on
the belief its tracker gives: the belief is encoded exactly as for training (fow_shared.features.encode_belief with
pairb.belief_data.opponent_visible), the network gives one distribution over the 4,096 from-to slots of the mirrored
frame (pairb.moves), restricted to the legal moves. Promotion variants of one pawn move share a slot; the slot's
probability goes to the queen promotion, as the offline evaluation plays it, and the under-promotions get 0. Exact
ties are broken by a random.Random seeded at reset, drawn on every turn. No search; time_budget_ms is not used.

PolicyFactory is the pair_c factory (``factory = pairb.policy_agent:PolicyFactory``): settings ``checkpoint_path``
(a best.pt of train_policy_net.py) and ``device``. The tracker is built by the runner from the same section.
"""
from __future__ import annotations

import random
from time import perf_counter
from typing import Mapping

import numpy as np
import torch

from fow_shared.contracts import AgentInput, Decision
from fow_shared.features import encode_belief

from .belief_data import ENCODING, opponent_visible
from .moves import legal_mask, move_index
from .policy_net import PolicyNetwork

TIE_TOLERANCE = 1e-12


class PolicyAgent:
    name = "pairb-policy-net"

    def __init__(self, net: PolicyNetwork, device: torch.device):
        self.net = net.eval()
        self.device = device
        self._rng: random.Random | None = None

    def reset(self, player: str, seed: int) -> None:
        self._rng = random.Random(seed)

    def move_probabilities(self, turn: AgentInput) -> dict[str, float]:
        """Every legal move's probability under the network (under-promotions 0; sums to 1)."""
        moves, player = turn.observation.legal_moves, turn.observation.player
        planes, weights = encode_belief(turn, opponent_visible)
        d = self.device
        legal = torch.from_numpy(legal_mask(moves, player)[None]).to(d)
        with torch.no_grad():
            probs = self.net.belief_probs(torch.from_numpy(np.asarray(planes, dtype=np.float32)).to(d),
                                          torch.from_numpy(np.asarray(weights, dtype=np.float32)).to(d),
                                          torch.zeros(len(weights), dtype=torch.long, device=d), 1, legal)[0]
        probs = probs.double().cpu().numpy()
        by_slot: dict[int, list[str]] = {}
        for m in moves:
            by_slot.setdefault(move_index(m, player), []).append(m)
        out = {m: 0.0 for m in moves}
        for slot, group in by_slot.items():
            queens = [m for m in group if m.endswith("q")]
            out[queens[0] if len(group) > 1 and queens else group[0]] = float(probs[slot])
        total = sum(out.values())
        return {m: p / total for m, p in out.items()}

    def act(self, turn: AgentInput) -> Decision:
        if self._rng is None:
            raise RuntimeError("call reset(player, seed) before act")
        started = perf_counter()
        if not turn.observation.legal_moves:
            raise ValueError("the observation has no legal move to choose from")
        policy = self.move_probabilities(turn)
        best = max(policy.values())
        chosen = self._rng.choice(sorted(m for m, p in policy.items() if best - p <= TIE_TOLERANCE))
        elapsed_ms = (perf_counter() - started) * 1000
        diagnostics = {"guesses": float(len(turn.belief.hypotheses)), "top_probability": best,
                       "elapsed_ms": elapsed_ms, "search_nodes": 0.0}
        return Decision(chosen, policy, diagnostics)


class PolicyFactory:
    """pair_c factory: one PolicyAgent per player section."""

    def __init__(self, settings: Mapping[str, str]):
        self.settings = settings

    def load_model(self) -> PolicyAgent:
        path = self.settings["checkpoint_path"].strip()
        device = torch.device(self.settings.get("device", "cpu").strip() or "cpu")
        ckpt = torch.load(path, map_location="cpu", weights_only=True)
        if ckpt.get("encoding") != ENCODING:
            raise ValueError(f"{path}: encoding {ckpt.get('encoding')!r}, this code encodes {ENCODING!r}")
        net = PolicyNetwork(**ckpt["config"])
        net.load_state_dict(ckpt["state_dict"])
        return PolicyAgent(net.to(device), device)

    def reset_game(self) -> None:
        """Nothing carries over between games: the agent keeps no cache, and reset reseeds the tie-break."""
