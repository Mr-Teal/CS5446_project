"""Network 1 (D3): one board plus Stockfish's depth-1 value in, a corrected value out.

Both values are from the side to move's view. The output is tanh(atanh(d1) + correction), and
the last layer starts at zero, so a fresh network returns the depth-1 value exactly and training
only has to learn the correction towards the depth-11 value (the proposal's "residual" Network 1).
"""
import torch
from torch import nn

D1_CLIP = 0.999  # atanh(+-1) is infinite; forced mates enter as +-0.999


class ResBlock(nn.Module):
    def __init__(self, channels: int):
        super().__init__()
        self.conv1 = nn.Conv2d(channels, channels, 3, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(channels)
        self.conv2 = nn.Conv2d(channels, channels, 3, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(channels)

    def forward(self, x):
        y = torch.relu(self.bn1(self.conv1(x)))
        return torch.relu(x + self.bn2(self.conv2(y)))


class Network1(nn.Module):
    def __init__(self, blocks: int = 6, channels: int = 64, in_planes: int = 19):
        super().__init__()
        self.config = {"blocks": blocks, "channels": channels, "in_planes": in_planes}
        self.stem = nn.Sequential(nn.Conv2d(in_planes, channels, 3, padding=1, bias=False),
                                  nn.BatchNorm2d(channels), nn.ReLU())
        self.trunk = nn.Sequential(*[ResBlock(channels) for _ in range(blocks)])
        self.head = nn.Sequential(nn.Conv2d(channels, 8, 1, bias=False), nn.BatchNorm2d(8), nn.ReLU())
        self.fc1 = nn.Linear(8 * 64 + 1, 128)
        self.fc2 = nn.Linear(128, 1)
        nn.init.zeros_(self.fc2.weight)
        nn.init.zeros_(self.fc2.bias)

    def forward(self, planes: torch.Tensor, d1: torch.Tensor) -> torch.Tensor:
        """planes: (N, 19, 8, 8); d1: (N,) depth-1 values. Returns (N,) values in (-1, 1)."""
        d1 = d1.clamp(-D1_CLIP, D1_CLIP)
        z = self.head(self.trunk(self.stem(planes))).flatten(1)
        h = torch.relu(self.fc1(torch.cat([z, d1[:, None]], dim=1)))
        return torch.tanh(torch.atanh(d1) + self.fc2(h).squeeze(1))
