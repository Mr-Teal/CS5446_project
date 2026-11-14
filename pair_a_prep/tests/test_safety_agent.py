"""Tests of pair_a_prep.safety_agent (15 Nov 2026). The fixture is the qa4 note's position: after 1.Nh3 d5 2.c4 Qd6
3.Qa4+, Black's exact tracker holds 10 boards (one per White third move), each weight 0.1; on the Qa4+ board
3...dxc4 lets White take the king, 3...Bd7 does not."""
import chess
import pytest
import torch

from fow_shared.contracts import AgentInput, Decision, HistoryEvent
from pair_a_prep import safety_agent
from pair_a_prep.evaluation_factories import HistoryTrackerFactory
from pair_a_prep.safety_agent import LastMovePrior, SafeSearchAgent, SafeSearchFactory, loses_king
from pairb.belief_data import ENCODING
from pairb.policy_net import PolicyNetwork
from pairb.rules import pick_rules

MOVES = ["g1h3", "d7d5", "c2c4", "d8d6", "d1a4"]


def qa4_turn():
    rules = pick_rules("teal")
    tracker = HistoryTrackerFactory({"sample_size": "16", "max_candidates": "none", "tracker_policy": "exact",
                                     "tracker_backend": "auto"}).create_tracker(rules, initial_fen=None)
    tracker.reset("black", 1)
    state, history = rules.initial_state(None), []
    belief = tracker.update(rules.observe(state, "black"))
    for ply, move in enumerate(MOVES):
        history.append(HistoryEvent(rules.observe(state, "black"), move if ply % 2 == 1 else None))
        state = rules.apply_move(state, move)
        belief = tracker.update(rules.observe(state, "black"), own_move=move if ply % 2 == 1 else None)
    return AgentInput(rules.observe(state, "black"), belief, 5000, tuple(history))


def check_board_fen(turn):
    return next(h.fen for h in turn.belief.hypotheses if h.candidate_moves[-1] == "d1a4")


class FakeEvaluator:
    def __init__(self, values):
        self.values = values

    def evaluate_children(self, fen):
        return {m.uci(): self.values.get(m.uci(), 0.0) for m in chess.Board(fen).pseudo_legal_moves} | {
            m: self.values.get(m, 0.0) for m in self.values}


class FakeInner:
    """Stands in for the search agent: plays a fixed move and has no solve to read (so the leaf average is used)."""
    name = "fake"
    last_projection = last_solver = last_bridge = None

    def __init__(self, move, values):
        self.move, self.evaluator, self.seen = move, FakeEvaluator(values), None

    def reset(self, player, seed):
        pass

    def act(self, turn):
        self.seen = turn
        return Decision(self.move, {m: float(m == self.move) for m in turn.observation.legal_moves}, {"x": 1.0})


# Catches: a king-capture check that misses the unseen queen, or flags a blocking move.
def test_loses_king_on_the_check_board_only_for_moves_that_ignore_the_check():
    turn = qa4_turn()
    assert len(turn.belief.hypotheses) == 10
    fen = check_board_fen(turn)
    assert loses_king(fen, "d5c4") and loses_king(fen, "d5d4")
    assert not loses_king(fen, "c8d7") and not loses_king(fen, "c7c6")
    quiet = next(h.fen for h in turn.belief.hypotheses if h.candidate_moves[-1] == "e2e3")
    assert not loses_king(quiet, "d5c4")


# Catches: an unsafe move kept although a safe one exists, or a safe move chosen other than the best by value.
def test_an_unsafe_choice_is_replaced_by_the_best_safe_move():
    turn = qa4_turn()
    inner = FakeInner("d5c4", {"d5c4": 0.9, "c8d7": 0.2, "c8e6": 0.1})
    d = SafeSearchAgent(inner, True, None, 150).act(turn)
    assert d.move == "c8d7" and d.diagnostics["safety_override"] == 1.0
    assert d.diagnostics["safety_value_from_solver"] == 0.0 and d.diagnostics["safety_unsafe_moves"] > 0
    assert d.root_policy["c8d7"] == 1.0 and sum(d.root_policy.values()) == 1.0 and d.diagnostics["x"] == 1.0
    assert inner.seen.time_budget_ms < turn.time_budget_ms  # the wrapper's time comes out of the search's budget


# Catches: a safe choice overridden, the rule active when switched off, or a move forced when every move is unsafe.
def test_safe_choices_pass_and_the_rule_yields_when_nothing_is_safe(monkeypatch):
    turn = qa4_turn()
    assert SafeSearchAgent(FakeInner("c8d7", {}), True, None, 150).act(turn).diagnostics["safety_override"] == 0.0
    assert SafeSearchAgent(FakeInner("d5c4", {}), False, None, 150).act(turn).move == "d5c4"
    monkeypatch.setattr(safety_agent, "loses_king", lambda fen, move: True)
    d = SafeSearchAgent(FakeInner("d5c4", {}), True, None, 150).act(turn)
    assert d.move == "d5c4" and d.diagnostics["safety_override"] == 0.0


# Catches: prior weights that do not follow the policy network's probability of each board's last opponent move,
# or that the search does not receive.
def test_the_prior_weights_boards_by_the_opponents_last_move(tmp_path):
    torch.manual_seed(0)
    net = PolicyNetwork("pooled-conv", blocks=1, channels=8, embed=16, hidden=32)
    torch.save({"state_dict": net.state_dict(), "config": net.config, "encoding": ENCODING}, tmp_path / "best.pt")
    prior = LastMovePrior(str(tmp_path / "best.pt"), "cpu")
    turn = qa4_turn()
    weights = prior.weights(turn)
    start = _replay(prior, MOVES[:4])  # every board's last White move is played from this one position
    p = [prior.probability(start, h.candidate_moves[-1]) for h in turn.belief.hypotheses]
    assert sum(weights) == pytest.approx(1.0)
    assert weights == pytest.approx([x / sum(p) for x in p])
    inner = FakeInner("c8d7", {})
    SafeSearchAgent(inner, True, prior, 150).act(turn)
    assert [h.weight for h in inner.seen.belief.hypotheses] == pytest.approx(weights)
    assert inner.seen.belief.weighting == "policy-last-move"


def _replay(prior, moves):
    state = prior.rules.initial_state(None)
    for m in moves:
        state = prior.rules.apply_move(state, m)
    return state


# Catches: the factory not building a working search agent around the wrapper (material leaf, a short search).
def test_the_factory_wraps_a_real_search_agent():
    agent = SafeSearchFactory({"search_mode": "subgame", "leaf_evaluator": "material", "leaf_depth": "0",
                               "solver_rounds": "64", "max_nodes": "4096", "max_evaluator_calls": "512",
                               "stop_on_time": "true", "safety_rule": "true"}).load_model()
    agent.reset("black", 3)
    turn = qa4_turn()
    d = agent.act(turn)
    assert d.move in turn.observation.legal_moves and "safety_override" in d.diagnostics
    assert not any(loses_king(h.fen, d.move) for h in turn.belief.hypotheses)  # a safe move exists here
