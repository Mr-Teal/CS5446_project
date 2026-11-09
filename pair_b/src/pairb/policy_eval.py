"""Policy-head metrics on dataset arrays: how well the network's move prior matches the solver's root policy.

Position level: each board's masked softmax is averaged over the belief's boards by hypothesis weight, then
compared with the record's root_policy. Reported: mean cross-entropy, top-1 agreement, and the cross-entropy of
a uniform prior over the legal moves as the reference a useless head would score.
"""
import numpy as np
import torch

from .belief_data import belief_batches, rows_of


@torch.no_grad()
def policy_metrics(net, arrays: dict, beliefs: np.ndarray, device, max_boards: int = 4096, planes=None) -> dict:
    if net.policy is None or "policy" not in arrays:
        return {}
    net.eval()
    ce_sum = uni_sum = 0.0
    top1 = n = 0
    for chunk in belief_batches(np.bincount(arrays["belief"]), beliefs, max_boards):
        rows, local = rows_of(arrays, chunk)
        x = planes[torch.from_numpy(rows).to(device)] if planes is not None else torch.from_numpy(arrays["planes"][rows]).to(device)
        w = torch.from_numpy(arrays["weight"][rows]).to(device)
        local_t = torch.from_numpy(local).to(device)
        d1 = torch.from_numpy(np.nan_to_num(arrays["d1"][rows])).to(device) if net.use_d1 else None
        _, logits = net(x.float(), w, local_t, len(chunk), d1, return_policy=True)
        legal = torch.from_numpy(arrays["legal"][chunk]).to(device)                      # (B, 4096)
        probs = torch.softmax(logits.masked_fill(~legal[local_t], -1e9), dim=1)          # per board
        pos = probs.new_zeros(len(chunk), probs.shape[1]).index_add(0, local_t, probs * w[:, None])
        target = torch.from_numpy(arrays["policy"][chunk].astype(np.float32)).to(device)
        ce_sum += float((-(target * torch.log(pos.clamp_min(1e-9))).sum(1)).sum())
        uni_sum += float(torch.log(legal.sum(1).float()).sum())
        top1 += int((pos.argmax(1) == target.argmax(1)).sum())
        n += len(chunk)
    return {"policy_ce": round(ce_sum / max(n, 1), 6), "uniform_ce": round(uni_sum / max(n, 1), 6),
            "policy_top1": round(top1 / max(n, 1), 6), "positions": n}
