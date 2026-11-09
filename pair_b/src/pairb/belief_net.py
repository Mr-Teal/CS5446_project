"""The belief network (D6): scores every board of a belief, knowing the whole belief.

One shared residual trunk reads each board (the 32 planes of fow_shared.features) into an
embedding. The belief's weighted mean embedding summarises all its boards, and each board's value
comes from its own embedding next to that summary, so the same board can be worth different
amounts under different beliefs; the value networks of DeepStack and ReBeL also condition on the
whole belief. Values are for the side to move (the deciding player), in (-1, 1).

With use_d1 the network also reads quick Stockfish's value of each board and corrects it, as
Network 1 does; without it, the leaf needs no engine call at all.
"""
import torch
from torch import nn

from .moves import N_MOVES
from .net1 import D1_CLIP, ResBlock


class BeliefNetwork(nn.Module):
    def __init__(self, blocks: int = 6, channels: int = 64, embed: int = 128, in_planes: int = 32,
                 use_d1: bool = False, use_context: bool = True, policy_head: bool = False):
        super().__init__()
        self.config = {"blocks": blocks, "channels": channels, "embed": embed, "in_planes": in_planes,
                       "use_d1": use_d1, "use_context": use_context}
        if policy_head:  # absent from older checkpoints' configs, so only written when on
            self.config["policy_head"] = True
        self.use_d1, self.use_context = use_d1, use_context
        # Policy head (growth prior): per-board logits over the 4096 from-to slots of pairb.moves, from the
        # board's own trunk features, so the search's per-board leaf path can ask for a move prior.
        self.policy = (nn.Sequential(nn.Linear(8 * 64, 128), nn.ReLU(), nn.Linear(128, N_MOVES))
                       if policy_head else None)
        self.stem = nn.Sequential(nn.Conv2d(in_planes, channels, 3, padding=1, bias=False),
                                  nn.BatchNorm2d(channels), nn.ReLU())
        self.trunk = nn.Sequential(*[ResBlock(channels) for _ in range(blocks)])
        self.head = nn.Sequential(nn.Conv2d(channels, 8, 1, bias=False), nn.BatchNorm2d(8), nn.ReLU())
        self.embed = nn.Linear(8 * 64 + int(use_d1), embed)
        self.value = nn.Sequential(nn.Linear(embed * (2 if use_context else 1), 128), nn.ReLU(), nn.Linear(128, 1))
        nn.init.zeros_(self.value[-1].weight)  # a fresh network returns 0, or exactly d1 with use_d1
        nn.init.zeros_(self.value[-1].bias)

    def forward(self, planes: torch.Tensor, weights: torch.Tensor, belief: torch.Tensor, n_beliefs: int,
                d1: torch.Tensor | None = None, return_policy: bool = False):
        """planes (H, 32, 8, 8) for H boards; weights (H,) summing to 1 within each belief; belief (H,)
        the belief index 0..n_beliefs-1 of each board; d1 (H,) only with use_d1. Returns (H,) values, or
        with return_policy the pair (values, policy logits (H, 4096)); the latter needs policy_head."""
        z = self.head(self.trunk(self.stem(planes))).flatten(1)
        logits = self.policy(z) if (return_policy and self.policy is not None) else None
        if self.use_d1:
            d1 = d1.clamp(-D1_CLIP, D1_CLIP)
            z = torch.cat([z, d1[:, None]], dim=1)
        e = torch.relu(self.embed(z))
        if self.use_context:
            summary = e.new_zeros(n_beliefs, e.shape[1]).index_add(0, belief, e * weights[:, None])
            e = torch.cat([e, summary[belief]], dim=1)
        out = self.value(e).squeeze(1)
        values = torch.tanh(torch.atanh(d1) + out) if self.use_d1 else torch.tanh(out)
        if return_policy:
            if logits is None:
                raise ValueError("return_policy needs a network built with policy_head=True")
            return values, logits
        return values
