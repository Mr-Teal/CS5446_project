"""PPO for two players who take turns: targets for each player's own decisions, and the update."""
import copy

import numpy as np
import torch
from torch import nn
from torch.distributions import Categorical


def compute_targets(values, phi, term_r, done, gamma: float, lam: float, T: int):
    """Advantages and returns for rows 0..T-1 of a (T + 2, n) record of plies.

    Row t is one ply of each game. `values` and `phi` belong to the player who moves at that ply,
    before the move; `term_r` is that player's reward from its own move (+1 for taking the king);
    `done` says the game ended at that ply (the next row starts a new game).

    A player's next decision is two plies later, so its value is bootstrapped from row t + 2, never
    from the opponent's row: the opponent sees different things, and its value is not this
    player's value. Between two decisions the player collects:

      its own move ended the game      term_r[t]       - phi[t]
      the opponent's reply ended it    -term_r[t + 1]  - phi[t]
      the game goes on                 gamma * phi[t + 2] - phi[t]

    The phi terms are potential-based reward shaping (a finished game has potential 0), so they
    change how fast the player learns and not which policy is best. Rows T and T + 1 are read only
    as "what came next"; advantages are cut off there and the value estimate stands in.
    """
    own_end = done[:T]
    reply_end = done[1:T + 1] & ~own_end
    ended = own_end | reply_end
    reward = (np.where(own_end, term_r[:T], 0.0) - np.where(reply_end, term_r[1:T + 1], 0.0)
              - phi[:T] + np.where(ended, 0.0, gamma * phi[2:T + 2]))
    delta = reward + gamma * np.where(ended, 0.0, values[2:T + 2]) - values[:T]
    adv = np.zeros((T + 2,) + values.shape[1:], dtype=np.float64)
    decay = gamma * lam * ~ended
    for t in range(T - 1, -1, -1):
        adv[t] = delta[t] + decay[t] * adv[t + 2]
    return adv[:T], adv[:T] + values[:T]


def ppo_update(model, optimizer, batch, *, epochs: int, minibatch: int, clip: float, value_coef: float,
               entropy_coef: float, max_grad_norm: float):
    """PPO's clipped update over `batch`: tensors obs, mask, action, logp, adv, ret on the model's device.

    A minibatch whose loss or gradient is not a finite number is skipped: it changes no weight.
    `skipped_steps` in the result counts them; the other statistics average the steps that were taken.
    """
    size = batch["action"].shape[0]
    totals = {"policy_loss": 0.0, "value_loss": 0.0, "entropy": 0.0, "approx_kl": 0.0, "clip_fraction": 0.0}
    count = skipped = 0
    for _ in range(epochs):
        order = torch.randperm(size).to(batch["action"].device)
        for start in range(0, size, minibatch):
            rows = order[start:start + minibatch]
            logits, value = model(batch["obs"][rows], batch["mask"][rows])
            dist = Categorical(logits=logits, validate_args=False)
            log_ratio = dist.log_prob(batch["action"][rows]) - batch["logp"][rows]
            ratio = log_ratio.exp()
            adv = batch["adv"][rows]
            adv = (adv - adv.mean()) / (adv.std() + 1e-8)
            policy_loss = -torch.min(ratio * adv, ratio.clamp(1 - clip, 1 + clip) * adv).mean()
            value_loss = 0.5 * (value - batch["ret"][rows]).pow(2).mean()
            entropy = dist.entropy().mean()
            loss = policy_loss + value_coef * value_loss - entropy_coef * entropy
            optimizer.zero_grad(set_to_none=True)
            if not bool(torch.isfinite(loss)):
                skipped += 1
                continue
            loss.backward()
            norm = nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm)
            if not bool(torch.isfinite(norm)):
                optimizer.zero_grad(set_to_none=True)
                skipped += 1
                continue
            optimizer.step()
            with torch.no_grad():
                totals["policy_loss"] += policy_loss.item()
                totals["value_loss"] += value_loss.item()
                totals["entropy"] += entropy.item()
                totals["approx_kl"] += ((ratio - 1) - log_ratio).mean().item()
                totals["clip_fraction"] += ((ratio - 1).abs() > clip).float().mean().item()
            count += 1
    stats = {name: total / max(count, 1) for name, total in totals.items()}
    stats["skipped_steps"] = skipped
    return stats


def weights_are_finite(model) -> bool:
    return bool(torch.stack([torch.isfinite(p).all() for p in model.parameters()]).all())


def guarded_update(model, optimizer, batch, **settings):
    """ppo_update that can never leave the network with invalid weights.

    The weights and the optimizer's state are copied first. If any weight is not a finite number
    after the update (the per-step check in ppo_update should already prevent it), the copies are
    put back, so the whole update is dropped and training goes on. `restored` in the result says
    whether that happened.
    """
    weights = {name: tensor.detach().clone() for name, tensor in model.state_dict().items()}
    optimizer_state = copy.deepcopy(optimizer.state_dict())
    stats = ppo_update(model, optimizer, batch, **settings)
    stats["restored"] = not weights_are_finite(model)
    if stats["restored"]:
        model.load_state_dict(weights)
        optimizer.load_state_dict(optimizer_state)
    return stats
