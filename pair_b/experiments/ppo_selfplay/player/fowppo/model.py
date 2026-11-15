"""The policy-and-value network: a small residual tower, one move head and one value head.

There is no batch normalisation: PPO compares the policy that collected the data with the policy
being trained, and batch statistics would make the two differ on the same weights. Each residual
block starts as the identity (its second convolution starts at zero), which keeps a tower without
normalisation stable.
"""
import math

import torch
from torch import nn

from .env import N_PLANES, SCALED_PLANES


class Block(nn.Module):
    def __init__(self, channels: int):
        super().__init__()
        self.conv1 = nn.Conv2d(channels, channels, 3, padding=1)
        self.conv2 = nn.Conv2d(channels, channels, 3, padding=1)
        nn.init.orthogonal_(self.conv1.weight, math.sqrt(2))
        nn.init.zeros_(self.conv1.bias)
        nn.init.zeros_(self.conv2.weight)
        nn.init.zeros_(self.conv2.bias)

    def forward(self, x):
        y = self.conv1(torch.relu(x))
        return x + self.conv2(torch.relu(y))


class PolicyValueNet(nn.Module):
    def __init__(self, blocks: int = 4, channels: int = 64):
        super().__init__()
        self.config = {"blocks": blocks, "channels": channels}
        scale = torch.ones(1, N_PLANES, 1, 1)
        scale[0, list(SCALED_PLANES)] = 1 / 255
        self.register_buffer("scale", scale)
        self.stem = nn.Conv2d(N_PLANES, channels, 3, padding=1)
        self.tower = nn.Sequential(*[Block(channels) for _ in range(blocks)])
        self.policy = nn.Conv2d(channels, 64, 1)  # 64 move types for each from-square
        self.value_conv = nn.Conv2d(channels, 8, 1)
        self.value_hidden = nn.Linear(8 * 64, 128)
        self.value_out = nn.Linear(128, 1)
        for layer, gain in ((self.stem, math.sqrt(2)), (self.policy, 0.01), (self.value_conv, math.sqrt(2)),
                            (self.value_hidden, math.sqrt(2)), (self.value_out, 1.0)):
            nn.init.orthogonal_(layer.weight, gain)
            nn.init.zeros_(layer.bias)

    def forward(self, obs: torch.Tensor, mask: torch.Tensor):
        """obs: (N, 25, 64) uint8 as the environment writes it; mask: (N, 4096) bool legal actions.
        Returns move logits (N, 4096), illegal moves at -1e9, and values (N,) for the player to move."""
        x = obs.view(-1, N_PLANES, 8, 8).float() * self.scale
        z = torch.relu(self.tower(self.stem(x)))
        logits = self.policy(z).flatten(1).masked_fill(~mask, -1e9)
        hidden = torch.relu(self.value_hidden(torch.relu(self.value_conv(z)).flatten(1)))
        return logits, self.value_out(hidden).squeeze(1)
