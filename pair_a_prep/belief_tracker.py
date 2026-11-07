"""History-preserving inference, with lossless compression and resumable budgets."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from math import isfinite
from random import Random
from time import perf_counter
import sys

from fow_shared.contracts import Belief, Hypothesis, Observation
from ._belief_graph import (encode_state, ObservationFilter, PathNode, StateNode, history_id,
                            position_key, position_bit, repetition_paths, successors)
from .rules_adapter import RulesAdapter
from ._belief_memory import budget_inventory, edge_bytes, path_bytes, state_bytes


class BeliefCapacityError(RuntimeError):
    """The legacy exact history-count limit was exceeded; nothing was committed."""


class BeliefBudgetError(RuntimeError):
    """No current-ply hypothesis is available yet; inspect result or resume()."""

    def __init__(self, result):
        self.result = result
        remedy = ("no descendants of retained support; rebuild from the private stream"
                  if result.expansion_complete and result.generated_valid_count == 0
                  else "resume the pending update")
        super().__init__(f"{result.status}: stopped by {result.stopped_by}; {remedy}")


@dataclass(frozen=True)
class TrackerUpdate:
    belief: Belief | None
    status: str
    stopped_by: str | None
    support_complete: bool
    expansion_complete: bool
    generated_valid_count: int
    retained_count: int
    state_count: int
    attempted_transitions: int
    elapsed_ms: float
    accounted_bytes: int
    memory_inventory_count: int = 0
    memory_inventory_ms: float = 0.0
    temporary_peak_bytes: int = 0


@dataclass
class _Pending:
    observation: Observation
    own_move: str | None
    parents: tuple[StateNode, ...]
    previous_complete: bool
    rng_state: object
    stream: object
    nodes: dict
    previous: Observation | None = None
    finished: bool = False
    waiting: object = None
    count: int = 0
    attempts: int = 0
    # Conservative logical allocation accounting; not process RSS.
    accounted: int = 0
    inventory_ready: bool = False
    inventory_count: int = 0
    inventory_ms: float = 0.0
    output_bytes: int = 0
    temporary_peak: int = 0
    state_charge: int = 0


def _positive(name, value, *, integer=False, zero=False):
    if value is not None and (isinstance(value, bool) or
            (integer and type(value) is not int) or not isinstance(value, (int, float)) or
            not isfinite(value) or value < 0 or (not zero and value == 0)):
        raise ValueError(f"{name} must be {'a positive integer' if integer else 'nonnegative and finite'} or None")


class BeliefTracker:
    """Keep every feasible history by default, sharing computation and path prefixes.

    ``sample_size`` limits output only. ``max_candidates`` retains its legacy
    atomic-error behavior. Optional time/memory budgets return a partial Belief
    through update(), or richer metadata through update_budgeted(). resume()
    continues the same observation. Advancing to a NEW observation discards any
    unfinished branches and permanently marks support incomplete, until reset.
    No time, memory, state-count or particle cap is enabled by default.
    """

    def __init__(self, initial_fen=None, *, sample_size=None, max_candidates=None,
                 time_budget_ms=None, memory_budget_mb=None, backend="auto"):
        _positive("sample_size", sample_size, integer=True)
        _positive("max_candidates", max_candidates, integer=True)
        _positive("time_budget_ms", time_budget_ms, zero=True)
        _positive("memory_budget_mb", memory_budget_mb, zero=True)
        if backend not in ("auto", "python", "native"):
            raise ValueError("backend must be auto, python, or native")
        from ._belief_native import library
        self.backend = "native" if backend != "python" and library() is not None else "python"
        if backend == "native" and self.backend != "native":
            raise ValueError("native backend unavailable; run python -m pair_a_prep.build_belief_kernel")
        self._rules = RulesAdapter()
        self._initial_fen = initial_fen
        self._sample_size = sample_size
        self._max_candidates = max_candidates
        self.time_budget_ms = time_budget_ms
        self.memory_budget_mb = memory_budget_mb
        self._player = None
        self._previous = None
        self._nodes = ()
        self._rng = Random()
        self._pending = None
        self._complete = True
        self._root_id = ""
        self.last_update = None

    @property
    def population_size(self):
        """Represented histories, an exact total only when support_complete is true."""
        return sum(n.paths.count for n in self._nodes)

    @property
    def state_count(self):
        """Distinct board/counter states; all draw histories remain in the DAG."""
        return len(self._nodes)

    @property
    def support_complete(self):
        pending = self._pending
        return self._complete and (pending is None or (
            pending.finished and self._previous is pending.observation))

    def reset(self, player, seed, initial_fen=None):
        if player not in ("white", "black"):
            raise ValueError("player must be white or black")
        if type(seed) is not int:
            raise ValueError("seed must be an integer")
        state = self._rules.initial_state(self._initial_fen if initial_fen is None else initial_fen)
        board = state.board_copy()
        self._game_fen = state.fen
        key = position_key(board)
        self._nodes = (StateNode(encode_state(board), PathNode([], 1, key, position_bit(key))),)
        self._root_id = sha256(state.fen.encode("ascii")).hexdigest()
        self._player, self._previous = player, None
        self._rng = Random(seed)
        self._pending = None
        self._complete = True
        self.last_update = None

    def _validate(self, observation, own_move):
        if self._player is None:
            raise ValueError("reset must be called before update")
        if not isinstance(observation, Observation):
            raise ValueError("observation must be a shared Observation")
        observation = replace(observation, visible_pieces=dict(observation.visible_pieces))
        if observation.player != self._player:
            raise ValueError("observation belongs to another player")
        expected_ply = 0 if self._previous is None else self._previous.ply + 1
        if type(observation.ply) is not int or observation.ply != expected_ply:
            raise ValueError(f"expected ply {expected_ply}, got {observation.ply}")
        if self._previous is None:
            if own_move is not None:
                raise ValueError("initial observation cannot have an own_move")
        else:
            if self._previous.terminal:
                raise ValueError("cannot advance a terminal belief; reset for a new game")
            if observation.side_to_move == self._previous.side_to_move:
                raise ValueError("side_to_move must alternate after each ply")
            if self._previous.side_to_move == self._player:
                if own_move is None or own_move not in self._previous.legal_moves:
                    raise ValueError("own_move must name an available action from the previous view")
            elif own_move is not None:
                raise ValueError("opponent moves must remain unknown; own_move must be None")
        return observation

    def update(self, observation, own_move=None):
        result = self.update_budgeted(observation, own_move)
        if result.belief is None:
            raise BeliefBudgetError(result)
        return result.belief

    def update_budgeted(self, observation, own_move=None, *, time_budget_ms=None,
                        memory_budget_mb=None):
        """Consume the next view. A zero budget is valid and returns no_candidate.

        Per-call None uses the constructor default. A pending empty update must
        be resumed or reset, never skipped. Nonempty partial support can advance;
        its unexpanded alternatives are then lost and the loss is reported.
        """
        began = perf_counter()
        _positive("time_budget_ms", time_budget_ms, zero=True)
        _positive("memory_budget_mb", memory_budget_mb, zero=True)
        observation = self._validate(observation, own_move)
        if self._pending is not None and self._previous is not self._pending.observation:
            raise ValueError("pending update has no accepted current belief; call resume()")
        if self._pending is not None:
            # Discarding unfinished output loses no branches of a finished graph.
            self._complete = self.support_complete
            self._pending = None
        expected = ObservationFilter(observation)
        initial = self._previous is None
        parents = self._nodes

        def transitions():
            for parent in parents:
                if initial:
                    parent_board = parent.board
                    if expected.cheap(parent_board, None) and expected.full(parent_board, 1):
                        yield parent, None
                else:
                    children = None
                    if self.backend == "native":
                        from ._belief_native import transitions
                        children = transitions(parent, own_move, expected)
                    for child in (successors(parent, own_move, expected) if children is None else children):
                        yield parent, child

        self._pending = _Pending(observation, own_move, parents, self._complete,
                                 self._rng.getstate(), transitions(), {}, self._previous)
        return self._run_pending(began, time_budget_ms, memory_budget_mb, initial=initial)

    def resume(self, *, time_budget_ms=None, memory_budget_mb=None):
        """Continue expansion, then re-materialize output using the saved RNG.

        Finished graphs are reused. Output is regenerated from its start, so
        enough output budget is required to return the entire requested sample.
        """
        if self._pending is None:
            raise ValueError("no pending update")
        return self._run_pending(perf_counter(), time_budget_ms, memory_budget_mb,
                                 initial=self._pending.observation.ply == 0)

    def _run_pending(self, began, time_ms, memory_mb, *, initial):
        time_ms = self.time_budget_ms if time_ms is None else time_ms
        memory_mb = self.memory_budget_mb if memory_mb is None else memory_mb
        _positive("time_budget_ms", time_ms, zero=True)
        _positive("memory_budget_mb", memory_mb, zero=True)
        deadline = None if time_ms is None else began + time_ms / 1000
        cap = None if memory_mb is None else int(memory_mb * 1024 * 1024)
        pending = self._pending
        # Inventory once per observation, including when a finite memory limit
        # is first enabled on resume. Retain the ledger across time slices.
        if cap is not None and not pending.inventory_ready:
            inventory_started = perf_counter()
            pending.accounted = budget_inventory(self)
            pending.inventory_ready = True
            pending.inventory_count += 1
            pending.inventory_ms += (perf_counter() - inventory_started) * 1000
            pending.output_bytes = 0  # Any prior output is in this inventory.
        measure_memory = pending.inventory_ready
        stopped = None
        finished = pending.finished
        try:
            while not finished:
                if deadline is not None and perf_counter() >= deadline:
                    stopped = "time"
                    break
                output_count = min(pending.count + 1, self._sample_size or pending.count + 1)
                reserve = (65536 + pending.output_bytes
                           + output_count * (512 + 80 * (pending.observation.ply + 1)))
                if cap is not None and pending.accounted + reserve > cap:
                    stopped = "memory"
                    break
                if pending.waiting is None:
                    try:
                        pending.waiting = next(pending.stream)
                    except StopIteration:
                        finished = True
                        pending.finished = True
                        break
                    pending.attempts += 1
                parent, child = pending.waiting
                if initial:
                    pending.nodes[parent.key()] = parent
                    pending.count = parent.paths.count
                    pending.waiting = None
                    continue
                if child is None:
                    pending.waiting = None
                    continue
                board, move, needs_repetition = child
                paths = parent.paths
                filtered_bytes = 0
                if needs_repetition is True and board.halfmove_clock < 4:
                    pending.waiting = None
                    continue
                if needs_repetition is not None and board.halfmove_clock >= 4:
                    # Small draw tests are normally rejected by the Bloom
                    # prefilter; collisions only trigger exact graph traversal.
                    temporary_bytes = 0

                    def check():
                        nonlocal temporary_bytes
                        if deadline is not None and perf_counter() >= deadline:
                            raise _BudgetStop("time")
                        # Scratch/memo entries live within this one filter call.
                        # Repeated work does not retain all previous temporaries.
                        if measure_memory:
                            temporary_bytes += 1024
                            pending.temporary_peak = max(pending.temporary_peak, temporary_bytes)
                        if cap is not None:
                            if pending.accounted + reserve + temporary_bytes + filtered_bytes > cap:
                                raise _BudgetStop("memory")

                    def created(node):
                        nonlocal filtered_bytes
                        if measure_memory:
                            filtered_bytes += path_bytes(node)
                        if cap is not None and pending.accounted + reserve + temporary_bytes + filtered_bytes > cap:
                            raise _BudgetStop("memory")

                    try:
                        paths = repetition_paths(paths, position_key(board),
                                                  board.halfmove_clock, needs_repetition, check, created)
                    except _BudgetStop as exc:
                        stopped = str(exc)
                        break
                    if paths is None:
                        pending.waiting = None
                        continue
                count = pending.count + paths.count
                if self._max_candidates is not None and count > self._max_candidates:
                    raise BeliefCapacityError(
                        f"ply {pending.observation.ply}: more than {self._max_candidates} "
                        "consistent histories; exact update was not committed")
                key = encode_state(board)
                node = pending.nodes.get(key)
                old_count = 0 if node is None else node.paths.count
                old_recent = 0 if node is None else node.paths.recent
                new_count = old_count + paths.count
                new_recent = old_recent | paths.recent if board.halfmove_clock else old_recent
                new_node = node is None
                if new_node:
                    effective = position_key(board)
                    node = StateNode(key,
                                     PathNode([], 0, effective, position_bit(effective)))
                allocation = 0
                if measure_memory:
                    allocation = filtered_bytes + edge_bytes(move, old_count, new_count, old_recent, new_recent)
                    if new_node:
                        if not pending.state_charge:
                            pending.state_charge = state_bytes(node)
                        allocation += pending.state_charge
                if cap is not None and pending.accounted + reserve + allocation > cap:
                    stopped = "memory"
                    break
                if new_node:
                    pending.nodes[key] = node
                pending.accounted += allocation
                node.paths.incoming.append((paths, move))
                node.paths.count = new_count
                if board.halfmove_clock:
                    node.paths.recent |= paths.recent
                pending.count = count
                pending.waiting = None
        except BaseException:
            self._nodes = pending.parents
            self._previous = pending.previous
            self._complete = pending.previous_complete
            self._rng.setstate(pending.rng_state)
            self._pending = None
            raise
        complete = finished and pending.previous_complete
        if finished and not pending.nodes:
            self._pending = None
            if pending.previous_complete:
                raise ValueError(f"ply {pending.observation.ply}: no candidate history matches the observation")
            return self._result(pending, None, "no_candidate", None, False, True, began)
        nodes = tuple(pending.nodes.values())
        # Re-sampling after resume must not consume extra RNG compared with one
        # uninterrupted update. Sampling depends only on the final graph/order.
        rng = Random()
        rng.setstate(pending.rng_state)
        belief, output_stopped = self._make_belief(nodes, pending.observation.ply,
                                                  complete, rng, deadline, cap,
                                                  pending.accounted + pending.output_bytes)
        stopped = stopped or output_stopped
        if nodes and belief is not None:
            self._nodes = nodes
            self._previous = pending.observation
            self._rng.setstate(rng.getstate())
            self._complete = complete
        if finished and belief is not None and output_stopped is None:
            self._pending = None
        status = "complete" if complete and stopped is None else "partial" if belief else "no_candidate"
        return self._result(pending, belief, status, stopped, complete, finished, began)

    def _result(self, pending, belief, status, stopped, complete, finished, began):
        pending.output_bytes = (0 if belief is None else
            len(belief.hypotheses) * (512 + 80 * (pending.observation.ply + 1)))
        result = TrackerUpdate(belief, status, stopped, complete, finished,
                               pending.count, pending.count, len(pending.nodes),
                               pending.attempts, (perf_counter() - began) * 1000,
                               pending.accounted + pending.output_bytes,
                               pending.inventory_count, pending.inventory_ms, pending.temporary_peak)
        self.last_update = result
        return result

    def prune(self, max_histories):
        """Opt-in uniform history pruning; preserve complete paths of survivors.

        Sampling is uniform over the currently represented histories, not an
        unknown full support after an interrupted update. It does not change
        the default exact mode. Repetition graphs are rebuilt from selected
        hypothetical paths, never from a referee FEN or an opponent move log.
        """
        import chess
        _positive("max_histories", max_histories, integer=True)
        if self._previous is None:
            raise ValueError("prune requires a current observation")
        if max_histories is None:
            raise ValueError("max_histories must be a positive integer")
        count = self.population_size
        if count <= max_histories:
            return
        ranks = set()
        while len(ranks) < max_histories:
            ranks.add(self._rng.randrange(count))
        selected = []
        offset = index = 0
        for rank in sorted(ranks):
            while rank >= offset + self._nodes[index].paths.count:
                offset += self._nodes[index].paths.count
                index += 1
            selected.append(self._nodes[index].paths.path_at(rank - offset))
        board = self._rules.initial_state(self._game_fen).board_copy()
        root_key = position_key(board)
        root = PathNode([], 1, root_key, position_bit(root_key))
        prefixes = {}
        nodes = {}
        for moves in selected:
            board = self._rules.initial_state(self._game_fen).board_copy()
            path = root
            for move in moves:
                board.push(chess.Move.from_uci(move))
                prefix = (path, move)
                child = prefixes.get(prefix)
                if child is None:
                    key = position_key(board)
                    recent = position_bit(key) | (path.recent if board.halfmove_clock else 0)
                    child = PathNode([(path, move)], 1, key, recent)
                    prefixes[prefix] = child
                path = child
            node = StateNode(encode_state(board), path)
            key = node.key()
            existing = nodes.get(key)
            if existing is None:
                # Separate the final accumulator from immutable prefix nodes.
                node.paths = PathNode(list(path.incoming), 1, path.position, path.recent)
                nodes[key] = node
            else:
                existing.paths.incoming.extend(path.incoming)
                existing.paths.count += 1
                existing.paths.recent |= path.recent
        self._nodes = tuple(nodes.values())
        self._pending = None
        self._complete = False
        self.last_update = None

    def _make_belief(self, nodes, ply, complete, rng, deadline, cap, accounted):
        count = sum(n.paths.count for n in nodes)
        if not count:
            return None, None
        size = min(count, self._sample_size or count)
        stopped = None
        if cap is not None:
            affordable = max(0, (cap - accounted) // (512 + 80 * (ply + 1)))
            if size > affordable:
                size = affordable
                stopped = "memory"
        if not size:
            return None, stopped
        if size == count:
            indices = range(count)
        elif count <= sys.maxsize:
            indices = sorted(rng.sample(range(count), size))
        else:
            # random.sample(range(...)) overflows Py_ssize_t for huge DAG counts.
            selected = set()
            while len(selected) < size:
                selected.add(rng.randrange(count))
            indices = sorted(selected)
        items = []
        node_index, offset = 0, 0
        for rank in indices:
            # Always allow one valid output. This and one transition are the
            # documented cooperative deadline granularity, not a hard timeout.
            if items and deadline is not None and perf_counter() >= deadline:
                stopped = "time"
                break
            if cap is not None and accounted + (len(items) + 1) * (512 + 80 * (ply + 1)) > cap:
                stopped = "memory"
                break
            while rank >= offset + nodes[node_index].paths.count:
                offset += nodes[node_index].paths.count
                node_index += 1
            node = nodes[node_index]
            moves = node.paths.path_at(rank - offset)
            items.append((node.board.fen(en_passant="fen"), history_id(self._root_id, moves), moves))
        if not items:
            return None, stopped
        # An interrupted output prefix is not a uniform sample of full support.
        weighting = "uniform" if complete and stopped is None else "uniform_over_returned_histories"
        return Belief(self._player, ply, tuple(Hypothesis(fen, 1 / len(items), hid, moves)
                      for fen, hid, moves in items), count if complete else None, weighting), stopped

    def storage_stats(self):
        """Inspect owned Python allocations (outside update timing in benchmarks).

        Counts each reachable object once. Includes pending state and last
        returned Belief, excludes interpreter/global shared code and caller logs.
        Allocator fragmentation and process RSS are separate measurements.
        """
        seen = set()
        total = 0
        stack = [self.__dict__]
        path_nodes = edges = 0
        while stack:
            obj = stack.pop()
            if id(obj) in seen:
                continue
            seen.add(id(obj))
            total += sys.getsizeof(obj)
            if isinstance(obj, PathNode):
                path_nodes += 1
                edges += len(obj.incoming)
                stack.extend((obj.incoming, obj.count, obj.position, obj.recent))
            elif isinstance(obj, (list, tuple, set, frozenset)):
                stack.extend(obj)
            elif isinstance(obj, dict):
                stack.extend(obj.keys())
                stack.extend(obj.values())
            elif isinstance(obj, StateNode):
                stack.extend((obj.packed, obj.paths))
            elif hasattr(obj, "__dict__") and not isinstance(obj, (type,)):
                stack.append(obj.__dict__)
        return {"owned_bytes": total, "path_nodes": path_nodes, "path_edges": edges,
                "state_count": self.state_count, "history_count": self.population_size,
                "support_complete": self.support_complete}


class _BudgetStop(Exception):
    pass
