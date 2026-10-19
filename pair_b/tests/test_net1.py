"""Network 1 (D3): one board plus Stockfish's depth-1 value in, a corrected value out."""
import torch

from pairb.net1 import Network1


def small():
    torch.manual_seed(0)
    return Network1(blocks=1, channels=8)


def test_output_is_one_value_per_board_inside_minus_one_to_one():
    net = small().eval()
    out = net(torch.rand(5, 19, 8, 8), torch.tensor([-1.0, -0.5, 0.0, 0.3, 1.0]))
    assert out.shape == (5,)
    assert bool(((out > -1) & (out < 1)).all())


# Catches: a network that does not start from the depth-1 value (no residual form, or a last
# layer that is not zeroed), so training would begin worse than the baseline it must beat.
def test_a_fresh_network_returns_the_depth1_value_clipped_to_0999():
    net = small().eval()
    out = net(torch.rand(5, 19, 8, 8), torch.tensor([-1.0, -0.5, 0.0, 0.3, 1.0]))
    assert torch.allclose(out, torch.tensor([-0.999, -0.5, 0.0, 0.3, 0.999]), atol=1e-5)


# Catches: gradients that never reach the weights (a detached output, a frozen layer).
def test_training_steps_reduce_the_error_on_a_small_batch():
    net = small().train()
    g = torch.Generator().manual_seed(1)
    planes = (torch.rand(64, 19, 8, 8, generator=g) > 0.8).float()
    d1 = torch.rand(64, generator=g) * 1.6 - 0.8
    target = torch.tanh(torch.atanh(d1) + planes[:, 0].sum((1, 2)) / 8 - 0.5)
    opt = torch.optim.Adam(net.parameters(), lr=3e-3)
    first = None
    for _ in range(300):
        loss = torch.mean((net(planes, d1) - target) ** 2)
        first = first if first is not None else loss.item()
        opt.zero_grad()
        loss.backward()
        opt.step()
    assert loss.item() < 0.25 * first
