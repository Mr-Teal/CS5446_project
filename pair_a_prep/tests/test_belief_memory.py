"""Inventory reuse, temporary lifetime and independent retained-size checks."""

import pytest

from pair_a_prep import belief_tracker as module
from pair_a_prep.belief_tracker import BeliefTracker
from pair_a_prep._belief_graph import PathNode, repetition_paths
from pair_a_prep.tests.test_belief_output_resume import backend, prepare, interrupt_output
from pair_a_prep.tests.test_belief_graph import KINGS, stream
from pair_a_prep.tests.reference_belief_tracker import BeliefTracker as Reference


def test_repeated_time_slices_inventory_only_once(monkeypatch, backend):
    actual, reference, observations = prepare(backend, 7)
    expected = reference.update(*observations[2])
    calls = []
    real = module.budget_inventory

    def inventory(tracker):
        calls.append(1)
        return real(tracker)

    monkeypatch.setattr(module, "budget_inventory", inventory)
    stopped = actual.update_budgeted(*observations[2], time_budget_ms=0, memory_budget_mb=64)
    for _ in range(5):
        stopped = actual.resume(time_budget_ms=0, memory_budget_mb=64)
    assert len(calls) == stopped.memory_inventory_count == 1
    assert stopped.attempted_transitions == 0
    completed = actual.resume(time_budget_ms=10000, memory_budget_mb=64)
    assert completed.belief == expected
    assert len(calls) == 1
    actual.update_budgeted(*observations[3], memory_budget_mb=64)
    assert len(calls) == 2


def test_enable_memory_limit_after_time_only_output_stop(monkeypatch, backend):
    actual, reference, observations = prepare(backend, 7)
    expected = reference.update(*observations[2])
    initial = interrupt_output(monkeypatch,
        lambda **kwargs: actual.update_budgeted(*observations[2], **kwargs), "time")
    assert initial.memory_inventory_count == 0
    failed = actual.resume(memory_budget_mb=0)
    assert failed.stopped_by == "memory" and failed.memory_inventory_count == 1
    recovered = actual.resume(memory_budget_mb=64)
    assert recovered.memory_inventory_count == 1
    assert recovered.belief == expected


def test_repeated_output_retries_do_not_accumulate_allocations(monkeypatch, backend):
    actual, reference, observations = prepare(backend, 7)
    expected = reference.update(*observations[2])
    first = interrupt_output(monkeypatch,
        lambda **kwargs: actual.update_budgeted(*observations[2], memory_budget_mb=64, **kwargs), "time")
    for _ in range(10):
        repeated = interrupt_output(monkeypatch, actual.resume, "time")
        assert repeated.accounted_bytes == first.accounted_bytes
        assert repeated.belief == first.belief
        assert repeated.memory_inventory_count == 1
    assert actual.resume(memory_budget_mb=64).belief == expected


@pytest.mark.parametrize("player", ("white", "black"))
def test_structural_charge_covers_retained_objects_and_preserves_histories(backend, player):
    tracker = BeliefTracker(KINGS, sample_size=7, backend=backend)
    reference = Reference(KINGS, sample_size=7)
    for item in (tracker, reference):
        item.reset(player, 7)
    moves = ["a1b1", "h8g8", "b1a1", "g8h8"] * 2
    for view, own in stream(KINGS, moves, player):
        result = tracker.update_budgeted(view, own, memory_budget_mb=64)
        expected = reference.update(view, own)
        # Sampling algorithms differ; compare full cardinality and validate each
        # returned history independently using the unsampled reference below.
        assert result.support_complete and result.belief.population_size == expected.population_size
        assert result.accounted_bytes >= tracker.storage_stats()["owned_bytes"]
    full = Reference(KINGS)
    full.reset(player, 7)
    for view, own in stream(KINGS, moves, player):
        expected = full.update(view, own)
    assert {h.history_id for h in result.belief.hypotheses} <= {h.history_id for h in expected.hypotheses}


def test_filter_scratch_is_released_between_transitions(monkeypatch, backend):
    tracker = BeliefTracker(KINGS, sample_size=3, backend=backend)
    reference = BeliefTracker(KINGS, sample_size=3, backend="python")
    observations = list(stream(KINGS, ["a1b1", "h8g8", "b1a1", "g8h8"], "white"))
    for item in (tracker, reference):
        item.reset("white", 11)
        for view, own in observations[:-1]:
            item.update(view, own)
    expected = reference.update(*observations[-1])
    real = module.repetition_paths

    def expensive(node, key, horizon, draw, check, created):
        # Repeated temporary visits simulate a large filter that retains only
        # the actual exact result. The scratch must not become graph storage.
        for _ in range(10000):
            check()
        return real(node, key, horizon, draw, check, created)

    monkeypatch.setattr(module, "repetition_paths", expensive)
    result = tracker.update_budgeted(*observations[-1], memory_budget_mb=16)
    assert result.status == "complete" and result.belief == expected
    assert result.temporary_peak_bytes >= 10_000_000
    assert result.accounted_bytes < 1_000_000


def test_interrupted_filter_does_not_charge_discarded_temporary_work(monkeypatch, backend):
    actual, reference, observations = prepare(backend, 7, 4)
    expected = reference.update(*observations[4])
    def interrupted(node, key, horizon, draw, check, created):
        for _ in range(1000):
            check()
        raise module._BudgetStop("time")

    with monkeypatch.context() as patch:
        patch.setattr(module, "repetition_paths", interrupted)
        first = actual.update_budgeted(*observations[4], memory_budget_mb=64)
        for _ in range(4):
            repeated = actual.resume(memory_budget_mb=64)
            assert repeated.accounted_bytes == first.accounted_bytes
    assert actual.resume(memory_budget_mb=64).belief == expected


def test_filtered_path_allocation_callback_only_reports_new_nodes():
    key, other = b"key", b"other"
    from pair_a_prep._belief_graph import position_bit
    bit = position_bit(key)
    repeated = PathNode([], 1, key, bit)
    different = PathNode([], 1, other, position_bit(other))
    middle = PathNode([(repeated, "a1b1"), (different, "a1a2")], 2, key, bit)
    root = PathNode([(middle, "h8g8")], 2, other, bit)
    allocated = []
    filtered = repetition_paths(root, key, 3, False, created=allocated.append)
    assert filtered.count == 1 and filtered.path_at(0) == ("a1a2", "h8g8")
    assert len(allocated) == 2
    assert all(node not in (root, middle, repeated, different) for node in allocated)


def test_large_shared_graph_inventory_visits_nodes_once_not_full_paths(monkeypatch):
    from pair_a_prep import _belief_memory as memory
    from pair_a_prep._belief_graph import StateNode, encode_state
    tracker = BeliefTracker(KINGS, sample_size=3, backend="python")
    tracker.reset("white", 17)
    board = tracker._nodes[0].board
    path = tracker._nodes[0].paths
    for _ in range(2000):
        path = PathNode([(path,"a1b1"),(path,"a1a2")],path.count*2,path.position,path.recent)
    tracker._nodes = tuple(StateNode(encode_state(board),path) for _ in range(100))
    calls=[]
    real=memory.path_bytes

    def charge(node):
        calls.append(node)
        return real(node)

    monkeypatch.setattr(memory,"path_bytes",charge)
    estimated=memory.budget_inventory(tracker)
    assert len(calls)==len(set(calls))==2001
    assert estimated>=tracker.storage_stats()['owned_bytes']


def test_packed_inventory_never_decodes_boards(monkeypatch):
    from pair_a_prep import _belief_graph as graph, _belief_memory as memory
    tracker = BeliefTracker(KINGS, sample_size=3, backend="python")
    tracker.reset("white", 17)

    def forbidden(_):
        raise AssertionError("inventory must inspect retained bytes, not allocate a Board")

    monkeypatch.setattr(graph, "decode_state", forbidden)
    assert memory.budget_inventory(tracker) >= tracker.storage_stats()["owned_bytes"]


def test_packed_allocation_never_decodes_boards(monkeypatch):
    from pair_a_prep import _belief_graph as graph, _belief_memory as memory
    tracker = BeliefTracker(KINGS, sample_size=3, backend="python")
    tracker.reset("white", 17)

    def forbidden(_):
        raise AssertionError("allocation charges must not decode retained packed data")

    monkeypatch.setattr(graph, "decode_state", forbidden)
    charge = memory.state_bytes(tracker._nodes[0])
    assert 0 < charge < 1024  # Includes object/DAG/container costs, not just 78 bytes.


def test_inventory_counts_shared_packed_payload_once(monkeypatch):
    from pair_a_prep import _belief_memory as memory
    from pair_a_prep._belief_graph import StateNode
    tracker = BeliefTracker(KINGS, sample_size=3, backend="python")
    tracker.reset("white", 17)
    original = tracker._nodes[0]
    tracker._nodes = (original, StateNode(original.packed, original.paths))
    calls = []
    real = memory.getsizeof

    def size(value):
        if value is original.packed:
            calls.append(value)
        return real(value)

    monkeypatch.setattr(memory, "getsizeof", size)
    assert memory.budget_inventory(tracker) >= tracker.storage_stats()["owned_bytes"]
    assert len(calls) == 1


@pytest.mark.parametrize("interrupt", (False, True))
def test_filter_releases_temporary_closure_without_cyclic_gc(interrupt):
    import gc
    import weakref
    from pair_a_prep._belief_graph import position_bit

    class Callback:
        def __call__(self, *args):
            if interrupt and not args:
                raise RuntimeError("stop")

    callback = Callback()
    reference = weakref.ref(callback)
    node = PathNode([], 1, b"key", position_bit(b"key"))
    enabled = gc.isenabled()
    gc.disable()
    try:
        try:
            repetition_paths(node, b"key", 3, False, callback, callback)
        except RuntimeError:
            assert interrupt
        del callback
        assert reference() is None, "recursive closure retains filter temporaries until cyclic GC"
    finally:
        if enabled:
            gc.enable()
        gc.collect()
