"""Scoring a trained Network 1 on dataset arrays (D3). Shared by the training and evaluation scripts."""
import torch

from .data import HALFMOVE_PLANE
from .metrics import choice_metrics


def as_float(planes_u8: torch.Tensor) -> torch.Tensor:
    """Packed uint8 planes (pairb.data.pack) back to the network's float input."""
    x = planes_u8.float()
    x[:, HALFMOVE_PLANE] /= 100
    return x


PIECE_CP = torch.tensor([100.0, 300.0, 300.0, 500.0, 900.0, 0.0])  # pawn, knight, bishop, rook, queen, king


def material_pred(planes_u8: torch.Tensor) -> torch.Tensor:
    """The piece-value baseline (pairb.material) read from packed planes: tanh(balance / 600) for
    the side to move, whose pieces are planes 0-5 and the opponent's 6-11."""
    counts = planes_u8[:, :12].float().sum(dim=(2, 3))
    balance = (counts[:, :6] - counts[:, 6:]) @ PIECE_CP.to(counts.device)
    return torch.tanh(balance / 600)


@torch.no_grad()
def predict(net, planes: torch.Tensor, d1: torch.Tensor, batch: int = 4096) -> torch.Tensor:
    net.eval()
    return torch.cat([net(as_float(planes[i:i + batch]), d1[i:i + batch]) for i in range(0, len(d1), batch)])


def _mean(x: torch.Tensor):
    return round(float(x.mean()), 6) if len(x) else None


def errors(pred: torch.Tensor, y: torch.Tensor, parents, d1: torch.Tensor | None = None) -> dict:
    """Value errors overall and on close (|y| < 0.3) and decided (|y| > 0.9) positions, plus
    move choice among siblings. With d1 given, also the error on positions the depth-1 score
    calls close, which is how the network meets them in play."""
    err = (pred - y).abs()
    out = {"mse": _mean(err ** 2), "mae": _mean(err),
           "mae_close": _mean(err[y.abs() < 0.3]), "mae_decided": _mean(err[y.abs() > 0.9])}
    if d1 is not None:
        out["mae_close_by_d1"] = _mean(err[d1.abs() < 0.3])
    choice = choice_metrics(parents, pred.cpu().numpy(), y.cpu().numpy())
    out["choice"] = {k: round(v, 6) if isinstance(v, float) else v for k, v in choice.items()}
    return out
