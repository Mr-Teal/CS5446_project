"""The policy network (stage 1): a move distribution for our turn, read from the whole belief.

We cannot tell the boards of a belief apart, so our move must be the same on all of them: a policy is a
function of the belief, not of one board. The network has the belief network's board reader (as in
pairb.belief_net: stem, residual blocks, 1x1 conv to 8 channels, a linear embedding with ReLU) with its own
weights, then an MLP (embed -> hidden -> the 4096 from-to slots of pairb.moves) whose illegal slots are masked.
Two designs:

  pooled     one distribution per belief, read from the weighted mean of its boards' embeddings;
  per-board  one distribution per board, read from that board's embedding alone (the first attempt's design);
             the belief's distribution is the weight-averaged softmax of its boards.

Two more designs (stage 4) replace the MLP with a convolutional output, as AlphaZero's policy: from the residual
blocks' feature map, a 3x3 conv (channels -> 64) with ReLU and a 1x1 conv to 64 move-type planes (MOVE_TYPES:
8 directions x distance 1-7, then the 8 knight jumps), one logit per (from square, move type), so the same weights
serve every square. A fixed table (conv_slots) places each on-board (from, type) logit in its from-to slot.

  pooled-conv     one distribution per belief, from the weighted mean of its boards' feature maps;
  per-board-conv  the same output on each board's own feature map; the belief's distribution is the
                  weight-averaged softmax of its boards.

The conv designs ignore embed and hidden. Weights are normalised within each belief.
"""
import numpy as np
import torch
from torch import nn

from .belief_data import belief_batches, rows_of
from .moves import N_MOVES
from .net1 import ResBlock

DESIGNS = ("pooled", "per-board", "pooled-conv", "per-board-conv")
MASKED = -1e9  # the logit of an illegal slot: its probability underflows to exactly 0
CE_FLOOR = 1e-9  # probabilities are clamped here inside a cross-entropy, as pairb.policy_eval does
DIRECTIONS = ((-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1))  # (row, col) steps
KNIGHT = ((-2, -1), (-2, 1), (-1, 2), (1, 2), (2, 1), (2, -1), (1, -2), (-1, -2))
MOVE_TYPES = tuple((dr * d, dc * d) for dr, dc in DIRECTIONS for d in range(1, 8)) + KNIGHT  # 64 (row, col) offsets


def conv_slots() -> tuple[np.ndarray, np.ndarray]:
    """For every move type t and from square s (row * 8 + col, pairb.moves' mirrored frame) whose target is on the
    board: the index t * 64 + s in the flattened move-type planes, and the from-to slot s * 64 + target."""
    src, dst = [], []
    for t, (dr, dc) in enumerate(MOVE_TYPES):
        for r in range(8):
            for c in range(8):
                if 0 <= r + dr < 8 and 0 <= c + dc < 8:
                    src.append(t * 64 + r * 8 + c)
                    dst.append((r * 8 + c) * 64 + (r + dr) * 8 + (c + dc))
    return np.array(src), np.array(dst)


def pooled_design(design: str) -> bool:
    """One distribution per belief (pooled, pooled-conv) rather than per board."""
    return design.startswith("pooled")


def normalised(weights: torch.Tensor, belief: torch.Tensor, n_beliefs: int) -> torch.Tensor:
    total = weights.new_zeros(n_beliefs).index_add(0, belief, weights)
    return weights / total[belief]


class PolicyNetwork(nn.Module):
    def __init__(self, design: str = "pooled", blocks: int = 6, channels: int = 64, embed: int = 128,
                 hidden: int = 256, in_planes: int = 32):
        super().__init__()
        if design not in DESIGNS:
            raise ValueError(f"design must be one of {DESIGNS}")
        self.design = design
        self.pooled, self.conv = pooled_design(design), design.endswith("-conv")
        self.config = {"design": design, "blocks": blocks, "channels": channels, "embed": embed,
                       "hidden": hidden, "in_planes": in_planes}
        self.stem = nn.Sequential(nn.Conv2d(in_planes, channels, 3, padding=1, bias=False),
                                  nn.BatchNorm2d(channels), nn.ReLU())
        self.trunk = nn.Sequential(*[ResBlock(channels) for _ in range(blocks)])
        if self.conv:
            self.move_types = nn.Sequential(nn.Conv2d(channels, 64, 3, padding=1), nn.ReLU(),
                                            nn.Conv2d(64, len(MOVE_TYPES), 1))
            src, dst = conv_slots()
            self.register_buffer("slot_src", torch.from_numpy(src), persistent=False)
            self.register_buffer("slot_dst", torch.from_numpy(dst), persistent=False)
        else:
            self.head = nn.Sequential(nn.Conv2d(channels, 8, 1, bias=False), nn.BatchNorm2d(8), nn.ReLU())
            self.embed = nn.Linear(8 * 64, embed)
            self.policy = nn.Sequential(nn.Linear(embed, hidden), nn.ReLU(), nn.Linear(hidden, N_MOVES))

    def forward(self, planes, weights, belief, n_beliefs: int, legal):
        """Masked log-probabilities over the 4096 slots. planes (H, 32, 8, 8) for H boards; weights (H,);
        belief (H,) the belief index 0..n_beliefs-1 of each board; legal (n_beliefs, 4096) bool.
        pooled designs: (n_beliefs, 4096), one row per belief; per-board designs: (H, 4096), one row per board."""
        x = self.trunk(self.stem(planes))
        if self.conv:
            if self.pooled:
                w = normalised(weights, belief, n_beliefs)
                x = x.new_zeros(n_beliefs, *x.shape[1:]).index_add(0, belief, x * w[:, None, None, None])
            types = self.move_types(x).flatten(1)  # (rows, 64 * 64): type t from square s at t * 64 + s
            logits = types.new_full((types.shape[0], N_MOVES), MASKED)
            logits[:, self.slot_dst] = types[:, self.slot_src]
        else:
            e = torch.relu(self.embed(self.head(x).flatten(1)))
            if self.pooled:
                w = normalised(weights, belief, n_beliefs)
                e = e.new_zeros(n_beliefs, e.shape[1]).index_add(0, belief, e * w[:, None])
            logits = self.policy(e)
        mask = legal if self.pooled else legal[belief]
        return torch.log_softmax(logits.masked_fill(~mask, MASKED), dim=1)

    def belief_probs(self, planes, weights, belief, n_beliefs: int, legal) -> torch.Tensor:
        """(n_beliefs, 4096): each belief's move distribution."""
        p = self(planes, weights, belief, n_beliefs, legal).exp()
        if self.pooled:
            return p
        w = normalised(weights, belief, n_beliefs)
        return p.new_zeros(n_beliefs, N_MOVES).index_add(0, belief, p * w[:, None])


def policy_loss(design: str, logp, target, weights, belief, n_beliefs: int) -> torch.Tensor:
    """Cross-entropy with the soft targets (n_beliefs, 4096), averaged over beliefs. The per-board designs train
    every board toward its belief's target, each board's term weighted by its normalised weight."""
    if pooled_design(design):
        return -(target * logp).sum(1).mean()
    w = normalised(weights, belief, n_beliefs)
    return (w * -(target[belief] * logp).sum(1)).sum() / n_beliefs


def cross_entropy(probs: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """Per-belief cross-entropy of predicted distributions against target distributions."""
    return -(target * torch.log(probs.clamp_min(CE_FLOOR))).sum(1)


@torch.no_grad()
def predict(net: PolicyNetwork, arrays: dict, beliefs: np.ndarray, device, planes=None, legal=None,
            max_beliefs: int = 256) -> torch.Tensor:
    """(len(beliefs), 4096) belief distributions on `device`. planes / legal: the arrays already on the
    device (all positions), or None to copy each chunk from `arrays`."""
    net.eval()
    sizes = np.bincount(arrays["belief"], minlength=len(arrays["move_start"]) - 1)
    out = []
    for chunk in belief_batches(sizes, np.asarray(beliefs), max_boards=1 << 30, max_beliefs=max_beliefs):
        rows, local = rows_of(arrays, chunk)
        r = torch.from_numpy(rows).to(device)
        c = torch.from_numpy(chunk).to(device)
        x = planes[r] if planes is not None else torch.from_numpy(arrays["planes"][rows]).to(device)
        lg = legal[c] if legal is not None else torch.from_numpy(arrays["legal"][chunk]).to(device)
        w = torch.from_numpy(arrays["weight"][rows]).to(device)
        out.append(net.belief_probs(x.float(), w, torch.from_numpy(local).to(device), len(chunk), lg))
    return torch.cat(out)
