"""The belief network (D6): one shared board reader, a weighted summary of the whole belief, and a
value per board that can depend on that summary. Small networks on the CPU, so this runs fast."""
import pytest

torch = pytest.importorskip("torch")  # Intel Macs have no torch build: skip this file there

from pairb.belief_net import BeliefNetwork
from pairb.net1 import D1_CLIP


def net(**kw):
    torch.manual_seed(0)
    return BeliefNetwork(blocks=1, channels=8, embed=16, **kw).eval()


def two_beliefs():
    torch.manual_seed(1)
    planes = torch.rand(5, 32, 8, 8)
    weights = torch.tensor([0.5, 0.25, 0.25, 0.6, 0.4])
    belief = torch.tensor([0, 0, 0, 1, 1])
    d1 = torch.tensor([0.3, -0.2, 1.0, 0.0, -1.0])
    return planes, weights, belief, d1


# Catches: a fresh network that does not start where it should (0, or exactly depth 1 if fed it).
def test_a_fresh_network_starts_at_zero_or_at_its_depth_1_input():
    planes, weights, belief, d1 = two_beliefs()
    assert torch.equal(net()(planes, weights, belief, 2), torch.zeros(5))
    got = net(use_d1=True)(planes, weights, belief, 2, d1)
    assert torch.allclose(got, d1.clamp(-D1_CLIP, D1_CLIP), atol=1e-6)


def trained(**kw):
    """A network nudged away from its start, so its outputs depend on its inputs."""
    m = net(**kw)
    with torch.no_grad():
        for p in m.parameters():
            p.add_(0.1 * torch.randn_like(p))
    return m.eval()


# Catches: the order of a belief's boards changing their values (the summary must not care).
def test_reordering_a_beliefs_boards_reorders_their_values():
    planes, weights, belief, _ = two_beliefs()
    m = trained()
    order = torch.tensor([2, 0, 1, 4, 3])
    assert torch.allclose(m(planes[order], weights[order], belief[order], 2), m(planes, weights, belief, 2)[order], atol=1e-6)


# Catches: one belief's boards leaking into another's values when several are scored together.
def test_beliefs_scored_together_do_not_mix():
    planes, weights, belief, _ = two_beliefs()
    m = trained()
    together = m(planes, weights, belief, 2)
    first = m(planes[:3], weights[:3], belief[:3], 1)
    second = m(planes[3:], weights[3:], belief[3:] - 1, 1)
    assert torch.allclose(together, torch.cat([first, second]), atol=1e-6)


def fit(m, steps=400):
    """The same board X sits in two beliefs with different company, and should be worth +0.8 in
    one and -0.8 in the other. Only a network that reads the rest of the belief can manage both."""
    torch.manual_seed(2)
    x, y1, y2 = torch.rand(3, 32, 8, 8)
    planes = torch.stack([x, y1, x, y2])
    weights = torch.full((4,), 0.5)
    belief = torch.tensor([0, 0, 1, 1])
    target = torch.tensor([0.8, 0.0, -0.8, 0.0])
    opt = torch.optim.Adam(m.parameters(), lr=3e-3)
    m.train()
    for _ in range(steps):
        loss = ((m(planes, weights, belief, 2) - target) ** 2).mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
    m.eval()
    with torch.no_grad():
        return ((m(planes, weights, belief, 2) - target) ** 2).mean().item()


# Catches: a summary that never reaches the per-board values, which would make the network blind
# to the fog: it could not give one board different values under different beliefs.
def test_only_reading_the_whole_belief_lets_one_board_take_two_values():
    assert fit(net()) < 0.02
    assert fit(net(use_context=False)) > 0.25
