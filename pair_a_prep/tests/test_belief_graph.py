"""Lossless compression, resumable budgets, and independent reference parity."""

from dataclasses import replace
from random import Random

import pytest

from pair_a_prep.belief_tracker import BeliefTracker, BeliefBudgetError
from pair_a_prep._belief_graph import PathNode
from pair_a_prep.rules_adapter import RulesAdapter
from pair_a_prep.tests.reference_belief_tracker import BeliefTracker as Reference


RULES = RulesAdapter()
KINGS = "7k/8/8/8/8/8/8/K7 w - - 0 1"


def stream(fen, moves, player):
    state = RULES.initial_state(fen)
    yield RULES.observe(state, player), None
    for move in moves:
        mover = RULES.current_player(state)
        state = RULES.apply_move(state, move)
        yield RULES.observe(state, player), move if mover == player else None


def support(belief):
    return {(h.fen, h.history_id, h.candidate_moves, h.weight) for h in belief.hypotheses}


@pytest.mark.parametrize("player", ["white", "black"])
@pytest.mark.parametrize("backend", ["python", "auto"])
@pytest.mark.parametrize("fen,moves", [
    (KINGS, ["a1b1", "h8g8", "b1a1", "g8h8"] * 2),
    (None, ["e2e4", "f7f6", "d1h5", "g7g5", "h5e8"]),
    ("4k3/8/8/4KPpr/8/8/8/8 w - g6 0 1", ["f5g6"]),
    ("7k/8/8/8/8/8/p7/7K b - - 0 1", ["a2a1q", "h1g1"]),
    ("4k2r/8/8/8/8/8/8/R3K2R w KQk - 0 1", ["e1c1", "e8g8"]),
])
def test_every_history_identity_fen_weight_matches_frozen_reference(player, backend, fen, moves):
    old, new = Reference(fen), BeliefTracker(fen, backend=backend)
    for t in (old, new):
        t.reset(player, 22)
    for view, own in stream(fen, moves, player):
        a, b = old.update(view, own), new.update(view, own)
        assert support(a) == support(b)
        assert a.population_size == b.population_size == new.population_size
        assert new.support_complete


@pytest.mark.parametrize("seed", range(10))
def test_random_small_games_reference_equivalence(seed):
    rng = Random(seed)
    fen = "7k/8/8/8/8/8/P7/K7 w - - 0 1"
    old, new = Reference(fen), BeliefTracker(fen)
    for t in (old, new):
        t.reset("white", seed)
    state = RULES.initial_state(fen)
    move = None
    for ply in range(8):
        view = RULES.observe(state, "white")
        assert support(old.update(view, move)) == support(new.update(view, move))
        if view.terminal:
            break
        mover = RULES.current_player(state)
        selected = rng.choice(RULES.legal_moves(state))
        state = RULES.apply_move(state, selected)
        move = selected if mover == "white" else None


def test_pawn_move_merges_draw_context_but_keeps_every_hidden_history():
    fen = "7k/8/8/8/8/8/P7/K7 w - - 0 1"
    tracker = BeliefTracker(fen)
    tracker.reset("white", 1)
    for view, move in stream(fen, ["a1b1", "h8g8", "b1a1", "g8h8", "a2a3"], "white"):
        belief = tracker.update(view, move)
    assert tracker.population_size == 18
    assert tracker.state_count == 9
    assert len({h.history_id for h in belief.hypotheses}) == 18
    assert tracker.storage_stats()["path_edges"] >= 18


def test_nonzero_draw_contexts_share_boards_but_preserve_every_path():
    tracker = BeliefTracker(KINGS)
    tracker.reset("white", 1)
    for view, move in stream(KINGS, ["a1b1", "h8g8", "b1a1", "g8h8"], "white"):
        belief = tracker.update(view, move)
    assert tracker.state_count == len({h.fen for h in belief.hypotheses}) == 9
    assert len(belief.hypotheses) == 18


def test_zero_time_then_resume_is_exact_and_does_not_advance():
    tracker = BeliefTracker(KINGS)
    tracker.reset("white", 1)
    obs = RULES.observe(RULES.initial_state(KINGS), "white")
    result = tracker.update_budgeted(obs, time_budget_ms=0)
    assert result.belief is None and result.stopped_by == "time"
    assert result.status == "no_candidate"
    assert tracker._previous is None
    result = tracker.resume()
    assert result.support_complete and result.belief.ply == 0


def test_too_small_memory_then_larger_budget_resumes_exactly():
    tracker = BeliefTracker(KINGS)
    tracker.reset("white", 1)
    obs = RULES.observe(RULES.initial_state(KINGS), "white")
    result = tracker.update_budgeted(obs, memory_budget_mb=0)
    assert result.belief is None and result.stopped_by == "memory"
    assert tracker.resume(memory_budget_mb=1).support_complete


def interrupted_tracker(monkeypatch):
    import pair_a_prep.belief_tracker as module
    tracker = BeliefTracker(KINGS, backend="python")
    tracker.reset("white", 1)
    views = list(stream(KINGS, ["a1b1", "h8g8"], "white"))
    for view, move in views[:2]:
        tracker.update(view, move)
    real = module.successors

    def controlled(*args):
        for i, result in enumerate(real(*args)):
            if i == 1:
                # Deterministic interruption after one generated valid child.
                monkeypatch.setattr(module, "perf_counter", lambda: 10000000000.0)
            yield result
    monkeypatch.setattr(module, "successors", controlled)
    result = tracker.update_budgeted(*views[2], time_budget_ms=10000)
    return tracker, result, views


def test_partial_resume_recovers_full_support(monkeypatch):
    tracker, partial, views = interrupted_tracker(monkeypatch)
    assert partial.status == "partial" and not partial.support_complete
    assert partial.belief.population_size is None
    assert all(len(h.candidate_moves) == 2 for h in partial.belief.hypotheses)
    monkeypatch.undo()
    resumed = tracker.resume()
    ref = Reference(KINGS)
    ref.reset("white", 1)
    for view, move in views:
        expected = ref.update(view, move)
    assert resumed.support_complete
    assert support(resumed.belief) == support(expected)


def test_advancing_partial_retains_only_valid_paths_and_never_claims_exactness(monkeypatch):
    tracker, partial, views = interrupted_tracker(monkeypatch)
    monkeypatch.undo()
    state = RULES.initial_state(KINGS)
    for action in partial.belief.hypotheses[0].candidate_moves:
        state = RULES.apply_move(state, action)
    state = RULES.apply_move(state, "b1a1")
    result = tracker.update_budgeted(RULES.observe(state, "white"), "b1a1")
    assert result.expansion_complete and not result.support_complete
    assert result.belief.population_size is None
    assert all(len(h.candidate_moves) == 3 for h in result.belief.hypotheses)


def test_constructor_budget_returns_explicit_exception_if_no_output():
    tracker = BeliefTracker(KINGS, time_budget_ms=0)
    tracker.reset("white", 1)
    with pytest.raises(BeliefBudgetError) as error:
        tracker.update(RULES.observe(RULES.initial_state(KINGS), "white"))
    assert error.value.result.status == "no_candidate"
    assert tracker.resume(time_budget_ms=1000).support_complete


def test_invalid_budget_does_not_leave_pending_state():
    tracker = BeliefTracker(KINGS)
    tracker.reset("white", 1)
    view = RULES.observe(RULES.initial_state(KINGS), "white")
    with pytest.raises(ValueError):
        tracker.update_budgeted(view, time_budget_ms=-1)
    assert tracker.update(view).population_size == 1


def test_path_rank_preserves_multiplicity_without_expansion():
    root = PathNode()
    node = root
    for _ in range(70):
        node = PathNode([(node, "a1b1"), (node, "a1a2")], node.count * 2)
    assert node.count == 2 ** 70
    assert node.path_at(0) == ("a1b1",) * 70
    assert node.path_at(node.count - 1) == ("a1a2",) * 70


def test_explicit_pruning_keeps_valid_full_paths_and_remembers_loss():
    tracker = BeliefTracker(KINGS)
    tracker.reset("white", 8)
    observations = list(stream(KINGS, ["a1b1", "h8g8", "b1a1", "g8h8"], "white"))
    for view, move in observations:
        full = tracker.update(view, move)
    tracker.prune(5)
    assert tracker.population_size == 5
    assert not tracker.support_complete
    selected = {n.paths.path_at(i) for n in tracker._nodes for i in range(n.paths.count)}
    assert selected <= {h.candidate_moves for h in full.hypotheses}
    state = RULES.initial_state(KINGS)
    for move in next(iter(selected)):
        state = RULES.apply_move(state, move)
    state = RULES.apply_move(state, "a1b1")
    belief = tracker.update(RULES.observe(state, "white"), "a1b1")
    assert belief.population_size is None and not tracker.support_complete
    assert all(h.candidate_moves[:-1] in selected for h in belief.hypotheses)


@pytest.mark.parametrize("seed", range(12))
def test_native_transition_filter_matches_python_on_random_play(seed):
    from pair_a_prep._belief_native import library, transitions
    from pair_a_prep._belief_graph import (ObservationFilter, StateNode, PathNode,
                                           position_key, position_bit, successors)
    if library() is None:
        pytest.skip("optional native backend not built")
    rng = Random(seed + 9321)
    state = RULES.initial_state()
    for _ in range(20):
        if RULES.terminal(state):
            break
        mover = RULES.current_player(state)
        move = rng.choice(RULES.legal_moves(state))
        child = RULES.apply_move(state, move)
        key = position_key(state._board)
        parent = StateNode(state.board_copy(), PathNode([], 1, key, position_bit(key)))
        for viewer in ("white", "black"):
            expected = ObservationFilter(RULES.observe(child, viewer))
            own = move if mover == viewer else None
            native = transitions(parent, own, expected)
            if native is None:
                continue
            def signature(results):
                return [(b.fen(en_passant="fen"), b.promoted, m, rep)
                        for result in results if result is not None for b, m, rep in [result]]
            assert signature(native) == signature(successors(parent, own, expected))
        state = child


@pytest.mark.parametrize("reason", ["time", "memory"])
def test_interrupted_repetition_filter_retries_the_same_transition(monkeypatch, reason):
    import pair_a_prep.belief_tracker as module
    tracker = BeliefTracker(KINGS, backend="python")
    tracker.reset("white", 4)
    views = list(stream(KINGS, ["a1b1", "h8g8", "b1a1", "g8h8"], "white"))
    for view, move in views[:-1]:
        tracker.update(view, move)
    def interrupted(*args):
        raise module._BudgetStop(reason)
    monkeypatch.setattr(module, "repetition_paths", interrupted)
    result = tracker.update_budgeted(*views[-1])
    assert result.belief is None and result.stopped_by == reason
    assert tracker._previous.ply == 3
    monkeypatch.undo()
    result = tracker.resume()
    ref = Reference(KINGS)
    ref.reset("white", 4)
    for view, move in views:
        expected = ref.update(view, move)
    assert result.support_complete
    assert support(result.belief) == support(expected)


def test_pruning_can_replay_a_fog_legal_move_that_exposes_the_king():
    fen = "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1"
    tracker = BeliefTracker(fen)
    tracker.reset("white", 19)
    for view, move in stream(fen, ["e2f2", "a8b8"], "white"):
        tracker.update(view, move)
    assert tracker.population_size > 1
    tracker.prune(1)
    node = tracker._nodes[0]
    assert node.paths.path_at(0)[0] == "e2f2"
    assert tracker.population_size == 1 and not tracker.support_complete
