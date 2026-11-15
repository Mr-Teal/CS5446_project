"""Advantages and returns: each player learns from its own chain of decisions, two plies apart."""
import numpy as np

from fowppo.ppo import compute_targets


def slow_targets(values, phi, term_r, done, gamma, lam, T):
    """The same quantity, one environment and one decision chain at a time."""
    rows, n = values.shape
    adv = np.zeros((T, n))
    for e in range(n):
        for start in (T - 1, T - 2):  # the two interleaved chains
            carry = 0.0
            for t in range(start, -1, -2):
                if done[t, e]:  # the mover's own move ended the game
                    reward, nxt, alive = term_r[t, e] - phi[t, e], 0.0, 0.0
                elif done[t + 1, e]:  # the opponent's reply ended it
                    reward, nxt, alive = -term_r[t + 1, e] - phi[t, e], 0.0, 0.0
                else:
                    reward, nxt, alive = gamma * phi[t + 2, e] - phi[t, e], values[t + 2, e], 1.0
                delta = reward + gamma * nxt - values[t, e]
                carry = delta + gamma * lam * alive * carry
                adv[t, e] = carry
    return adv, adv + values[:T]


def test_matches_the_slow_reference_on_random_games():
    rng = np.random.default_rng(0)
    T, n = 40, 16
    values = rng.normal(size=(T + 2, n))
    phi = rng.normal(scale=0.1, size=(T + 2, n))
    done = rng.random((T + 2, n)) < 0.1
    term_r = np.where(done, rng.choice([0.0, 1.0], size=(T + 2, n)), 0.0)
    fast = compute_targets(values, phi, term_r, done, gamma=0.99, lam=0.9, T=T)
    slow = slow_targets(values, phi, term_r, done, gamma=0.99, lam=0.9, T=T)
    np.testing.assert_allclose(fast[0], slow[0], atol=1e-9)
    np.testing.assert_allclose(fast[1], slow[1], atol=1e-9)


def test_king_capture_pays_the_winner_and_charges_the_loser():
    # Plies 0..4 of one game: White, Black, White, Black, then White takes the king at ply 4.
    T = 5
    values = np.zeros((T + 2, 1))
    phi = np.zeros((T + 2, 1))
    done = np.zeros((T + 2, 1), dtype=bool)
    term_r = np.zeros((T + 2, 1))
    done[4, 0], term_r[4, 0] = True, 1.0
    adv, ret = compute_targets(values, phi, term_r, done, gamma=1.0, lam=1.0, T=T)
    assert ret[:, 0].tolist() == [1.0, -1.0, 1.0, -1.0, 1.0]  # White's plies +1, Black's plies -1


def test_shaping_cancels_over_a_whole_game():
    # With gamma = 1 the piece-count hints add up to minus the starting potential, here zero,
    # so a drawn game returns 0 from its first move whatever happened to the pieces.
    T = 6
    values = np.zeros((T + 2, 1))
    phi = np.array([[0.0], [0.0], [0.2], [-0.2], [0.1], [-0.1], [0.0], [0.0]])
    done = np.zeros((T + 2, 1), dtype=bool)
    term_r = np.zeros((T + 2, 1))
    done[5, 0] = True  # the game ends in a draw at ply 5
    _, ret = compute_targets(values, phi, term_r, done, gamma=1.0, lam=1.0, T=T)
    assert abs(ret[0, 0]) < 1e-12 and abs(ret[1, 0]) < 1e-12
