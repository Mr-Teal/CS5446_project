"""Output-budget continuation, exact support, and sampling-stream parity."""

import pytest

from pair_a_prep import belief_tracker as module
from pair_a_prep.belief_tracker import BeliefBudgetError, BeliefTracker
from pair_a_prep.rules_adapter import RulesAdapter


FEN = "7k/8/8/8/8/8/P7/K7 w - - 0 1"
MOVES = ("a1b1", "h8g8", "b1a1", "g8h8", "a2a3", "h8g8", "a3a4")
RULES = RulesAdapter()


@pytest.fixture(params=("python", "native"))
def backend(request):
    if request.param == "native":
        from pair_a_prep._belief_native import library
        if library() is None:
            pytest.skip("optional native backend not built")
    return request.param


def views():
    state = RULES.initial_state(FEN)
    result = [(RULES.observe(state, "white"), None)]
    for move in MOVES:
        own = move if RULES.current_player(state) == "white" else None
        state = RULES.apply_move(state, move)
        result.append((RULES.observe(state, "white"), own))
    return result


def prepare(backend, sample_size, target=2):
    stream = views()
    actual = BeliefTracker(FEN, sample_size=sample_size, backend=backend)
    reference = BeliefTracker(FEN, sample_size=sample_size, backend="python")
    for tracker in (actual, reference):
        tracker.reset("white", 89)
        for view, own in stream[:target]:
            tracker.update(view, own)
    return actual, reference, stream


def interrupt_output(monkeypatch, call, reason, *, items=1):
    """Exercise real output checks after expansion, with a deterministic budget."""
    with monkeypatch.context() as patch:
        if reason == "time":
            clock = [0.0]
            calls = [0]
            real = module.history_id

            def history_id(*args):
                identity = real(*args)
                calls[0] += 1
                if calls[0] >= items:
                    clock[0] = 2.0
                return identity

            patch.setattr(module, "perf_counter", lambda: clock[0])
            patch.setattr(module, "history_id", history_id)
            return call(time_budget_ms=1000)

        real = BeliefTracker._make_belief

        def limited(self, nodes, ply, complete, rng, deadline, cap, accounted):
            assert self._pending.finished
            cap = accounted + items * (512 + 80 * (ply + 1))
            return real(self, nodes, ply, complete, rng, deadline, cap, accounted)

        patch.setattr(BeliefTracker, "_make_belief", limited)
        return call(memory_budget_mb=64)


@pytest.mark.parametrize("reason", ("time", "memory"))
@pytest.mark.parametrize("target,sample_size", ((2, 7), (2, 2), (4, 7), (4, None)))
def test_output_resume_matches_uninterrupted_histories_weights_and_future_rng(
        monkeypatch, backend, reason, target, sample_size):
    actual, reference, stream = prepare(backend, sample_size, target)
    expected = reference.update(*stream[target])
    partial = interrupt_output(monkeypatch,
        lambda **budget: actual.update_budgeted(*stream[target], **budget), reason)
    assert partial.status == "partial" and partial.stopped_by == reason
    assert partial.expansion_complete and partial.support_complete and actual.support_complete
    assert partial.belief.population_size == expected.population_size
    assert len(partial.belief.hypotheses) == 1
    assert partial.belief.weighting == "uniform_over_returned_histories"
    assert actual._pending is not None
    nodes = tuple(map(id, actual._nodes))

    repeated = interrupt_output(monkeypatch, actual.resume, reason)
    assert repeated.status == "partial" and repeated.belief == partial.belief
    assert repeated.attempted_transitions == partial.attempted_transitions
    assert tuple(map(id, actual._nodes)) == nodes
    resumed = actual.resume(time_budget_ms=10000, memory_budget_mb=64)
    assert resumed.status == "complete" and resumed.stopped_by is None
    assert resumed.support_complete and actual.support_complete
    assert resumed.belief == expected
    assert resumed.attempted_transitions == partial.attempted_transitions
    assert tuple(map(id, actual._nodes)) == nodes
    assert actual._rng.getstate() == reference._rng.getstate()
    with pytest.raises(ValueError, match="no pending update"):
        actual.resume()
    for view, own in stream[target + 1:]:
        assert actual.update(view, own) == reference.update(view, own)
        assert actual._rng.getstate() == reference._rng.getstate()


@pytest.mark.parametrize("reason", ("time", "memory"))
def test_advancing_after_output_stop_preserves_exact_support(monkeypatch, backend, reason):
    actual, reference, stream = prepare(backend, None)
    reference.update(*stream[2])
    partial = interrupt_output(monkeypatch,
        lambda **budget: actual.update_budgeted(*stream[2], **budget), reason)
    assert partial.support_complete and actual.support_complete
    for view, own in stream[3:]:
        result = actual.update_budgeted(view, own)
        assert result.status == "complete" and result.support_complete
        assert actual.support_complete and actual.storage_stats()["support_complete"]
        assert result.belief == reference.update(view, own)


def test_zero_output_can_resume_without_accepting_an_unreturned_view(monkeypatch, backend):
    actual, reference, stream = prepare(backend, 7)
    expected = reference.update(*stream[2])

    def update(**budget):
        actual.memory_budget_mb = budget["memory_budget_mb"]
        return actual.update(*stream[2])

    with pytest.raises(BeliefBudgetError, match="resume the pending update") as error:
        interrupt_output(monkeypatch, update, "memory", items=0)
    result = error.value.result
    assert result.belief is None and result.status == "no_candidate"
    assert result.expansion_complete and result.generated_valid_count == 3
    assert actual._previous.ply == 1 and not actual.support_complete
    with pytest.raises(ValueError, match="resume"):
        actual.update(*stream[2])
    resumed = actual.resume(memory_budget_mb=64)
    assert resumed.belief == expected and actual.support_complete
    assert actual._rng.getstate() == reference._rng.getstate()


@pytest.mark.parametrize("affordable", (0, 1))
def test_small_memory_on_output_resume_keeps_graph_and_can_retry(monkeypatch, backend, affordable):
    actual, reference, stream = prepare(backend, 2)
    expected = reference.update(*stream[2])
    partial = interrupt_output(monkeypatch,
        lambda **budget: actual.update_budgeted(*stream[2], **budget), "time")
    cap = 0 if affordable == 0 else actual.storage_stats()["owned_bytes"] + 512 + 80 * 3
    limited = actual.resume(memory_budget_mb=cap / 1024**2)
    assert limited.stopped_by == "memory"
    if affordable == 0:
        assert limited.belief is None
    else:
        assert len(limited.belief.hypotheses) == 1
        assert limited.belief.weighting == "uniform_over_returned_histories"
    assert limited.expansion_complete and limited.support_complete and actual.support_complete
    assert actual._previous.ply == 2 and actual.population_size == 3
    assert limited.attempted_transitions == partial.attempted_transitions
    with pytest.raises(ValueError):
        actual.resume(time_budget_ms=-1)
    assert actual.resume(memory_budget_mb=64).belief == expected
    assert actual._rng.getstate() == reference._rng.getstate()


@pytest.mark.parametrize("reason", ("time", "memory"))
def test_output_completion_does_not_erase_earlier_pruning(monkeypatch, backend, reason):
    actual, reference, stream = prepare(backend, 2, 4)
    for tracker in (actual, reference):
        tracker.prune(2)
    expected = reference.update(*stream[4])
    partial = interrupt_output(monkeypatch,
        lambda **budget: actual.update_budgeted(*stream[4], **budget), reason)
    assert partial.expansion_complete and not partial.support_complete
    assert not actual.support_complete
    resumed = actual.resume(time_budget_ms=10000, memory_budget_mb=64)
    assert resumed.stopped_by is None and resumed.status == "partial"
    assert not resumed.support_complete and not actual.support_complete
    assert resumed.belief == expected and resumed.belief.population_size is None
    assert actual._pending is None
    assert actual._rng.getstate() == reference._rng.getstate()


def test_reset_cancels_pending_output(monkeypatch, backend):
    actual, reference, stream = prepare(backend, 7)
    interrupt_output(monkeypatch,
        lambda **budget: actual.update_budgeted(*stream[2], **budget), "time")
    actual.reset("white", 89)
    reference.reset("white", 89)
    with pytest.raises(ValueError, match="no pending update"):
        actual.resume()
    for view, own in stream[:3]:
        assert actual.update(view, own) == reference.update(view, own)
    assert actual.support_complete
