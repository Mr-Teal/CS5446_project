"""A training step with invalid numbers must be dropped, not allowed to break the network."""
import copy

import numpy as np
import torch

from fowppo import ppo
from fowppo.env import VecFow
from fowppo.model import PolicyValueNet

SETTINGS = dict(epochs=1, minibatch=16, clip=0.2, value_coef=0.5, entropy_coef=0.01, max_grad_norm=0.5)


def make_batch(rows=64, seed=0):
    """A real batch: positions from random play, the actions and log-chances of a fresh network."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    vec = VecFow(rows, opening=(0, 8), seed=seed)
    model = PolicyValueNet(blocks=1, channels=8)
    obs, mask = torch.from_numpy(vec.obs.copy()), torch.from_numpy(vec.mask.copy())
    with torch.no_grad():
        logits, value = model(obs, mask)
        dist = torch.distributions.Categorical(logits=logits)
        action = dist.sample()
        logp = dist.log_prob(action)
    batch = {"obs": obs, "mask": mask, "action": action, "logp": logp,
             "adv": torch.from_numpy(rng.normal(size=rows).astype(np.float32)),
             "ret": value + torch.from_numpy(rng.normal(size=rows).astype(np.float32))}
    return model, torch.optim.Adam(model.parameters(), lr=3e-4, eps=1e-5), batch


def flat(model):
    return torch.cat([p.detach().flatten() for p in model.parameters()])


def test_a_healthy_update_trains_and_skips_nothing():
    model, optimizer, batch = make_batch()
    before = flat(model).clone()
    stats = ppo.guarded_update(model, optimizer, batch, **SETTINGS)
    assert stats["skipped_steps"] == 0 and stats["restored"] is False
    assert all(np.isfinite(stats[k]) for k in ("policy_loss", "value_loss", "entropy", "approx_kl"))
    assert not torch.equal(before, flat(model))  # it learned


def test_one_invalid_advantage_skips_one_step_and_keeps_the_weights_valid():
    model, optimizer, batch = make_batch()
    before = flat(model).clone()
    batch["adv"][5] = float("nan")  # one bad row: exactly one of the four minibatches holds it
    stats = ppo.guarded_update(model, optimizer, batch, **SETTINGS)
    assert stats["skipped_steps"] == 1 and stats["restored"] is False
    assert ppo.weights_are_finite(model)
    assert not torch.equal(before, flat(model))  # the three good minibatches still trained


def test_an_overflowing_chance_ratio_is_skipped():
    model, optimizer, batch = make_batch()
    batch["logp"][3] = -1e9  # the new chance divided by this old chance overflows to infinity
    batch["adv"][3] = -5.0  # and the move looked bad, so the loss itself becomes infinite
    stats = ppo.guarded_update(model, optimizer, batch, **SETTINGS)
    assert stats["skipped_steps"] == 1 and ppo.weights_are_finite(model)


def test_without_the_guard_the_same_fault_breaks_the_network(monkeypatch):
    # The fault of 15 November, reproduced: this is what the guard prevents.
    model, optimizer, batch = make_batch()
    batch["adv"][5] = float("nan")
    monkeypatch.setattr(torch, "isfinite", lambda tensor: torch.ones_like(tensor, dtype=torch.bool))
    ppo.ppo_update(model, optimizer, batch, **SETTINGS)
    monkeypatch.undo()
    assert not ppo.weights_are_finite(model)


def test_weights_that_turn_invalid_anyway_are_put_back(monkeypatch):
    model, optimizer, batch = make_batch()
    before = flat(model).clone()
    optimizer_before = copy.deepcopy(optimizer.state_dict())

    def poisoned_update(model, optimizer, batch, **settings):
        with torch.no_grad():
            next(model.parameters()).fill_(float("nan"))
        return {"skipped_steps": 0}

    monkeypatch.setattr(ppo, "ppo_update", poisoned_update)
    stats = ppo.guarded_update(model, optimizer, batch, **SETTINGS)
    assert stats["restored"] is True
    assert torch.equal(before, flat(model))
    assert optimizer.state_dict()["param_groups"] == optimizer_before["param_groups"]
    monkeypatch.undo()
    assert ppo.guarded_update(model, optimizer, batch, **SETTINGS)["restored"] is False  # and training goes on
