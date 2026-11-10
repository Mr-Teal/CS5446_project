"""Optional native PCFR+ round (pcfr_kernel.cpp): loader, flattened tree and flat solver state.

PCFRPlus keeps the Node tree, expand(), information_sets and the infoset-key <-> id mapping. NativeState compiles
the tree into arrays (nodes in DFS order) after __init__, and holds the solver state in flat float64 arrays, one
block of actions per information set. The solver's Python-visible state
(minimizers[p][key].regrets / .strategy / .previous_utility / ._pending, _strategy, _sums, _previous_opponent)
becomes views of those arrays: reads see the kernel's results, in-place writes and assignments write through.
_initial_actions stays a plain dict and is handed to the kernel around each step.

expand() does not recompile: GraftIndex indexes only the grafted subtrees, and NativeState.extend appends their
nodes (the replaced leaf's slot in its parent points at the new subtree; the leaf stays as an unreachable node) and
their new information sets (ids after the existing ones; the state arrays have spare room, so the existing views
stay valid). Chance probabilities are re-read from the tree's dicts before every kernel call, because the blended
gadget's controller rewrites its root distribution in place between rounds.

Instrumentation that replaces PCFRPlus._utilities or a minimizer's observe/next_strategy on an instance (to count
or spy on calls) sets `instrumented`, and PCFRPlus.step then runs that solver's rounds in Python on the same views.

Threads: FOW_PCFR_THREADS (default 1) sets the number of threads of the kernel's root-parallel walks when the
library is loaded, FOW_PCFR_PARALLEL_NODES the smallest tree they run on (default 1024 nodes); set_threads()
changes both. The results do not depend on them (see pcfr_kernel.cpp).

Build with `python -m pair_a_prep.build_pcfr_kernel`; library() returns None when the build is missing or stale.
"""

from bisect import bisect_left, insort
import ctypes as C
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
from itertools import chain
import json
import os
from pathlib import Path

import numpy as np

from .pcfr import PredictiveRMPlus

_P = C.c_void_p


class Side(C.Structure):
    _fields_ = [("n_sets", C.c_int32), ("n_levels", C.c_int32), ("offset", _P), ("depth", _P),
                ("level_begin", _P), ("level_sets", _P), ("level_depth", _P), ("regrets", _P),
                ("strategy", _P), ("previous_utility", _P), ("sums", _P), ("pending", _P),
                ("initial_action", _P), ("previous_opponent", _P), ("has_previous", _P)]


class Solver(C.Structure):
    _fields_ = [("n_nodes", C.c_int32), ("predictive", C.c_int32), ("alternating", C.c_int32),
                ("averaging_power", C.c_int32), ("kind", _P), ("player", _P), ("infoset", _P), ("payoff", _P),
                ("child_begin", _P), ("child", _P), ("chance_begin", _P), ("chance_child", _P),
                ("chance_prob", _P), ("side", Side * 2)]


class Control(C.Structure):
    """GadgetControl in pcfr_kernel.cpp: a BlendedGadgetControl's numbers and state as arrays (see run_gadget)."""
    _fields_ = [("n_groups", C.c_int32), ("n_roots", C.c_int32), ("predictive", C.c_int32),
                ("history_width", C.c_int32), ("tolerance", C.c_double),
                ("root_node", _P), ("reach_mass", _P), ("group_begin", _P), ("group_roots", _P), ("alternate", _P),
                ("alpha", _P), ("group_mass", _P), ("root_slot", _P), ("exit_slot", _P),
                ("entry_regrets", _P), ("entry_strategy", _P), ("entry_previous", _P), ("entry_pending", _P),
                ("selector_regrets", _P), ("selector_strategy", _P), ("selector_previous", _P),
                ("selector_pending", _P), ("pi_resolve", _P), ("pi_maxmargin", _P), ("p_max", _P), ("margins", _P),
                ("values", _P), ("entering", _P)]


@lru_cache(maxsize=1)
def library():
    directory = Path(__file__).parent / "_pcfr_build"
    if not (directory / "manifest.json").exists():
        return None
    from .build_pcfr_kernel import source_hashes
    record = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if record["source_sha256"] != source_hashes():
        return None
    path = directory / record["library"]
    if not path.exists() or sha256(path.read_bytes()).hexdigest() != record["dll_sha256"]:
        return None
    dll = C.CDLL(str(path))
    solver = C.POINTER(Solver)
    for name, args in (("pcfr_utilities", [solver, C.c_int, _P, _P]), ("pcfr_prepare", [solver, C.c_int]),
                       ("pcfr_observe", [solver, C.c_int]),
                       ("pcfr_accumulate_average", [solver, C.c_int, C.c_double]),
                       ("pcfr_step", [solver, C.c_int64]),
                       ("pcfr_run", [solver, C.c_int64, C.c_int64, C.POINTER(C.c_int64), C.c_int, C.c_int, _P]),
                       ("pcfr_growth_utilities", [solver, _P, _P]),
                       ("pcfr_behavioral_values", [solver, C.c_int32, _P, _P]),
                       ("pcfr_run_gadget", [solver, C.POINTER(Control), C.c_int64, C.c_int64, C.POINTER(C.c_int64),
                                            C.c_int, C.c_int, _P, _P, _P]),
                       ("pcfr_set_threads", [C.c_int, C.c_int])):
        function = getattr(dll, name)
        function.argtypes, function.restype = args, C.c_int
    dll.pcfr_parallel_walks.argtypes, dll.pcfr_parallel_walks.restype = [], C.c_int64
    dll.pcfr_set_threads(int(os.environ.get("FOW_PCFR_THREADS", "1") or 1),
                         int(os.environ.get("FOW_PCFR_PARALLEL_NODES", "-1") or -1))
    return dll


def set_threads(threads, min_nodes=-1):
    """The number of threads of the kernel's root-parallel walks (at least 1) and, if not negative, the smallest
    tree in nodes they run on (default 1024); returns the previous number of threads."""
    return library().pcfr_set_threads(int(threads), int(min_nodes))


_ERRORS = {-1: "observe the pending strategy first", -2: "request a strategy before observing utilities",
           -3: "need one finite utility per action", -4: "need one finite prediction per action"}


def _check(code):
    if code:
        raise ValueError(_ERRORS.get(code, f"native PCFR+ kernel failed with code {code}"))


def _pointer(array):
    return array.ctypes.data


def _room(needed):
    """Capacity of a state array that has to hold `needed` entries: spare room for later expansions."""
    return 2 * needed + 64


def _ranges(base, lengths):
    """child_begin / chance_begin entries after `base` for nodes with these numbers of entries."""
    return (base + np.cumsum(np.asarray(lengths, dtype=np.int64))).astype(np.int32)


def _extend_history(node, action, histories):
    """The players' own histories below `action` at `node` (as PCFRPlus._check_recall extends them)."""
    if node.player is None:
        return histories
    extended = list(histories)
    extended[node.player] += ((node.infoset, action),)
    return tuple(extended)


class GraftIndex:
    """The incremental twin of PCFRPlus._index_tree, used by expand() on the native backend.

    information_sets lists a player's sets in the DFS order of each set's first node, which is the lexicographic
    order of that node's path of child indices; _check_recall needs every set's own history. Both are kept here, so
    a graft is indexed by walking only the grafted subtrees, and sets, _order and _depth come out as _index_tree
    computes them on the whole tree (test_pcfr_native.py compares them after every expansion).
    """

    def __init__(self, root):
        self.first, self.history = ({}, {}), {}

        def visit(node, position, histories):
            if node.payoff is not None:
                return
            if node.player is not None:
                self.first[node.player].setdefault(node.infoset, position)
                self.history.setdefault((node.player, node.infoset), histories[node.player])
            for i, (action, child) in enumerate(node.children.items()):
                visit(child, position + (i,), _extend_history(node, action, histories))

        visit(root, (), ((), ()))
        self.ordered = tuple(sorted((position, key) for key, position in first.items()) for first in self.first)

    def graft(self, solver, root, paths):
        """Index `root`, the solver's tree with subtrees grafted at `paths`.

        Returns ((sets, order, depth) as _index_tree(root) gives them, staged index for commit()). Raises the errors
        the whole-tree walks raise for the grafted subtrees: an action order that differs from another node of the
        set (information_sets), then an inconsistent own history (_check_recall). Changes nothing.
        """
        sets = solver.sets
        first = (dict(self.first[0]), dict(self.first[1]))
        new, moved = ({}, {}), ({}, {})
        sites = []
        for path in paths:
            node, position, histories = root, (), ((), ())
            for action in path:
                position += (list(node.children).index(action),)
                histories = _extend_history(node, action, histories)
                node = node.children[action]
            sites.append((node, position, histories))

        def scan(node, position):
            if node.payoff is not None:
                return
            if node.player is not None:
                p, key, actions = node.player, node.infoset, tuple(node.children)
                known = sets[p].get(key) or new[p].get(key)
                if known is None:
                    new[p][key] = actions
                elif known != actions:
                    raise ValueError("nodes in one infoset need the same action order")
                old = first[p].get(key)
                if old is None or position < old:
                    first[p][key] = position
                    moved[p].setdefault(key, old)  # the position before this expansion (None: a new set)
            for i, child in enumerate(node.children.values()):
                scan(child, position + (i,))

        for node, position, _ in sites:
            scan(node, position)
        history = dict(self.history)
        for node, _, histories in sites:
            solver._check_recall(node, histories, history)
        ordered = [list(self.ordered[0]), list(self.ordered[1])]
        for p in (0, 1):
            for key, old in moved[p].items():
                if old is not None:
                    del ordered[p][bisect_left(ordered[p], (old, key))]
                insort(ordered[p], (first[p][key], key))
        new_sets = tuple({key: sets[p].get(key) or new[p][key] for _, key in ordered[p]} for p in (0, 1))
        depth = tuple({**solver._depth[p], **{key: len(history[(p, key)]) for key in new[p]}} for p in (0, 1))
        order = []
        for p in (0, 1):
            levels = {}
            for key in new_sets[p]:
                levels.setdefault(depth[p][key], []).append(key)
            # = sorted(new_sets[p], key=depth, reverse=True): stable, deepest first
            order.append([key for level in sorted(levels, reverse=True) for key in levels[level]])
        return (new_sets, tuple(order), depth), (first, tuple(ordered), history)

    def commit(self, staged):
        self.first, self.ordered, self.history = staged


class FlatMinimizer(PredictiveRMPlus):
    """A PredictiveRMPlus whose arrays are one information set's slices of NativeState."""

    def __init__(self, state, player, index, predictive):
        self.predictive = predictive
        self._bind(state, player, index)

    def __setattr__(self, name, value):
        if name in ("observe", "next_strategy"):
            self._owner.instrumented = True  # a replaced method must see its calls: the Python round takes over
        super().__setattr__(name, value)

    def _bind(self, state, player, index):
        self._owner = state
        side = state.sides[player]
        start, stop = side["offset"][index], side["offset"][index + 1]
        self._regrets = side["regrets"][start:stop]
        self._strategy = side["strategy"][start:stop]
        self._utility = side["previous_utility"][start:stop]
        self._flags, self._index = side["pending"], index

    def _set_regrets(self, value):
        self._regrets[...] = value

    def _set_strategy(self, value):
        self._strategy[...] = value

    def _set_utility(self, value):
        self._utility[...] = value

    def _set_pending(self, value):
        self._flags[self._index] = bool(value)

    regrets = property(lambda self: self._regrets, _set_regrets)
    strategy = property(lambda self: self._strategy, _set_strategy)
    previous_utility = property(lambda self: self._utility, _set_utility)
    _pending = property(lambda self: bool(self._flags[self._index]), _set_pending)

    def __deepcopy__(self, memo):
        plain = PredictiveRMPlus.__new__(PredictiveRMPlus)
        plain.predictive, plain._pending = self.predictive, self._pending
        plain.regrets, plain.previous_utility = self.regrets.copy(), self.previous_utility.copy()
        plain.strategy = self.strategy.copy()
        return plain


class FlatDict(dict):
    """key -> view of a flat array; item assignment copies into the array."""

    def __init__(self, array, slots, keys):
        super().__init__((key, array[slots[key][0]:slots[key][1]]) for key in keys)
        self._array, self._slots = array, slots

    def __setitem__(self, key, value):
        if key not in self._slots:
            raise KeyError(f"{key!r} is not an information set of this solver")
        start, stop = self._slots[key]
        self._array[start:stop] = value
        super().__setitem__(key, self._array[start:stop])

    def __deepcopy__(self, memo):
        return {key: value.copy() for key, value in self.items()}


class MinimizerDict(dict):
    """key -> FlatMinimizer; assigning another minimizer copies its state into the flat arrays."""

    def __init__(self, state, player, items):
        super().__init__(items)
        self._state, self._player = state, player

    def __setitem__(self, key, minimizer):
        index = self._state.index[self._player].get(key)
        if index is None:
            raise KeyError(f"{key!r} is not an information set of this solver")
        if not (isinstance(minimizer, FlatMinimizer) and minimizer._flags is self._state.sides[self._player]["pending"]
                and minimizer._index == index):
            flat = FlatMinimizer(self._state, self._player, index, minimizer.predictive)
            flat.regrets, flat.previous_utility = minimizer.regrets, minimizer.previous_utility
            flat.strategy, flat._pending = minimizer.strategy, minimizer._pending
            minimizer = flat
        super().__setitem__(key, minimizer)

    def __deepcopy__(self, memo):
        return {key: deepcopy(value, memo) for key, value in self.items()}


class PreviousList(list):
    """[snapshot for player 0, snapshot for player 1], each None or a FlatDict of the opponent's strategy."""

    def __init__(self, state):
        super().__init__(None for _ in (0, 1))
        self._state = state

    def __setitem__(self, player, value):
        state = self._state
        if value is None:
            state.has_previous[player] = 0
            super().__setitem__(player, None)
            return
        slots = state.slots[1 - player]
        if set(value) != set(slots):
            raise ValueError("a previous opponent strategy needs every opponent information set")
        snapshot = FlatDict(state.sides[player]["previous_opponent"], slots, ())
        for key, strategy in value.items():
            snapshot[key] = strategy
        state.has_previous[player] = 1
        super().__setitem__(player, snapshot)

    def __deepcopy__(self, memo):
        return [None if value is None else deepcopy(value, memo) for value in self]


class NativeState:
    """The compiled tree, the flat state of one PCFRPlus and the ctypes structure that points at both."""

    def __init__(self, solver, dll):
        self.dll = dll
        self.instrumented = False
        sets = solver.sets
        self.index = tuple({key: i for i, key in enumerate(player_sets)} for player_sets in sets)
        offsets = [np.zeros(len(player_sets) + 1, dtype=np.int32) for player_sets in sets]
        for p in (0, 1):
            np.cumsum([len(actions) for actions in sets[p].values()], out=offsets[p][1:])
        self.slots = tuple({key: (int(offsets[p][i]), int(offsets[p][i + 1])) for key, i in self.index[p].items()}
                           for p in (0, 1))
        self._compile_tree(solver.root, sets)
        self.has_previous = np.zeros(2, dtype=np.int8)
        self.sides = []
        for p in (0, 1):
            actions, opponent, count = int(offsets[p][-1]), int(offsets[1 - p][-1]), len(sets[p])
            self.sides.append(dict(
                offset=offsets[p],
                depth=np.array([solver._depth[p][key] for key in sets[p]], dtype=np.int32),
                **self._levels(solver, p),
                # State arrays have spare room (_room) so that expand() can append sets without moving them.
                regrets=np.zeros(_room(actions)), strategy=np.zeros(_room(actions)),
                previous_utility=np.zeros(_room(actions)), sums=np.zeros(_room(actions)),
                pending=np.zeros(_room(count), dtype=np.int8),
                initial_action=np.full(_room(count), -1, dtype=np.int32),
                previous_opponent=np.zeros(_room(opponent))))
        self._load(solver)
        self.struct = self._structure(solver)

    def _levels(self, solver, p):
        """The level-wise prepare's order: solver._order (deepest first) as set ids, grouped by depth."""
        levels = {}
        for key in solver._order[p]:  # deepest first
            levels.setdefault(solver._depth[p][key], []).append(self.index[p][key])
        return dict(level_begin=np.cumsum([0] + [len(v) for v in levels.values()]).astype(np.int32),
                    level_sets=np.array([i for v in levels.values() for i in v], dtype=np.int32),
                    level_depth=np.array(list(levels), dtype=np.int32))

    def _flatten(self, root, sets, first_id):
        """The nodes of the subtree at `root` in DFS order, numbered from first_id, as per-node lists."""
        kind, player, infoset, payoff, children, chance, dicts = [], [], [], [], [], [], []

        def visit(node):
            i = len(kind)
            kind.append(0)
            player.append(-1)
            infoset.append(-1)
            payoff.append(0.0)
            children.append(())
            chance.append(())
            if node.payoff is not None:
                payoff[i] = float(node.payoff)
                return first_id + i
            if node.player is None:
                dicts.append(node.probabilities)  # in node-id order, like the chance_prob ranges
            ids = {action: visit(child) for action, child in node.children.items()}
            children[i] = tuple(ids.values())
            if node.player is None:
                kind[i] = 1
                chance[i] = tuple((ids[action], float(prob)) for action, prob in node.probabilities.items())
            else:
                if tuple(node.children) != sets[node.player][node.infoset]:
                    raise ValueError("children must follow the information set's action order: " + node.infoset)
                kind[i], player[i], infoset[i] = 2, node.player, self.index[node.player][node.infoset]
            return first_id + i

        visit(root)
        return kind, player, infoset, payoff, children, chance, dicts

    def _compile_tree(self, root, sets):
        kind, player, infoset, payoff, children, chance, dicts = self._flatten(root, sets, 0)
        self.kind = np.array(kind, dtype=np.int8)
        self.player = np.array(player, dtype=np.int8)
        self.infoset = np.array(infoset, dtype=np.int32)
        self.payoff = np.array(payoff, dtype=np.float64)
        self.child_begin = np.cumsum([0] + [len(c) for c in children]).astype(np.int32)
        self.child = np.array([j for c in children for j in c], dtype=np.int32)
        self.chance_begin = np.cumsum([0] + [len(c) for c in chance]).astype(np.int32)
        self.chance_child = np.array([j for c in chance for j, _ in c], dtype=np.int32)
        self.chance_prob = np.array([q for c in chance for _, q in c], dtype=np.float64)
        self.chance_dicts = dicts

    def _sync_chance(self):
        """Re-read the chance probabilities from the tree (a blended gadget's controller rewrites its root's)."""
        if self.chance_dicts:
            self.chance_prob[:] = np.fromiter(chain.from_iterable(d.values() for d in self.chance_dicts),
                                              np.float64, len(self.chance_prob))

    def extend(self, solver, paths, added, strategies):
        """Append the subtrees that PCFRPlus.expand grafted at `paths` (no path is the root).

        solver.root, sets, _order and _depth are already the grafted ones; added[p] holds the new sets' minimizers
        in solver.sets order and strategies[p] their published strategies. New sets get the next ids and their
        state goes into the spare room of the state arrays (which move, with every view rebound, only when the room
        runs out); the containers gain views for them, in the order PCFRPlus.expand's Python path adds them.
        """
        sets = solver.sets
        for p in (0, 1):
            index, slots, side = self.index[p], self.slots[p], self.sides[p]
            total, ends = int(side["offset"][-1]), []
            for key in added[p]:
                index[key] = len(index)
                slots[key] = (total, total + len(sets[p][key]))
                total += len(sets[p][key])
                ends.append(total)
            side["offset"] = np.concatenate([side["offset"], np.array(ends, dtype=np.int32)])
            side["depth"] = np.concatenate([side["depth"], np.array([solver._depth[p][key] for key in added[p]],
                                                                    dtype=np.int32)])
        moved = False
        for p in (0, 1):
            side = self.sides[p]
            actions, opponent = int(side["offset"][-1]), int(self.sides[1 - p]["offset"][-1])
            for name, needed in (("regrets", actions), ("strategy", actions), ("previous_utility", actions),
                                 ("sums", actions), ("pending", len(side["depth"])),
                                 ("initial_action", len(side["depth"])), ("previous_opponent", opponent)):
                if len(side[name]) < needed:
                    array = np.full(_room(needed), -1 if name == "initial_action" else 0, dtype=side[name].dtype)
                    array[:len(side[name])] = side[name]
                    side[name], moved = array, True
        for p in (0, 1):
            side = self.sides[p]
            for key, minimizer in added[p].items():
                start, stop = self.slots[p][key]
                side["regrets"][start:stop] = minimizer.regrets
                side["previous_utility"][start:stop] = minimizer.previous_utility
                side["strategy"][start:stop] = strategies[p][key]
                side["sums"][start:stop] = 0.0
                side["pending"][self.index[p][key]] = bool(minimizer._pending)
                side["initial_action"][self.index[p][key]] = -1
            if self.has_previous[p]:
                for key in added[1 - p]:
                    start, stop = self.slots[1 - p][key]
                    side["previous_opponent"][start:stop] = strategies[1 - p][key]
        for p in (0, 1):
            side, previous = self.sides[p], list.__getitem__(solver._previous_opponent, p)
            for key, minimizer in added[p].items():
                start, stop = self.slots[p][key]
                if not moved:
                    minimizer = FlatMinimizer(self, p, self.index[p][key], minimizer.predictive)
                dict.__setitem__(solver.minimizers[p], key, minimizer)
                dict.__setitem__(solver._strategy[p], key, side["strategy"][start:stop])
                dict.__setitem__(solver._sums[p], key, side["sums"][start:stop])
            if previous is not None:
                for key in added[1 - p]:
                    start, stop = self.slots[1 - p][key]
                    dict.__setitem__(previous, key, side["previous_opponent"][start:stop])
        if moved:
            self.bind(solver)  # every view onto the moved arrays; the new minimizers become FlatMinimizers here

        n = len(self.kind)
        child, chance_child = self.child.copy(), self.chance_child.copy()
        lists = [[] for _ in range(7)]
        for path in paths:
            node_id, node = 0, solver.root
            for action in path[:-1]:
                node_id = int(child[self.child_begin[node_id] + list(node.children).index(action)])
                node = node.children[action]
            subtree = node.children[path[-1]]
            flat = self._flatten(subtree, sets, n)
            # The replaced leaf keeps its id but is no longer reachable; its parent's slot points at the subtree.
            child[self.child_begin[node_id] + list(node.children).index(path[-1])] = n
            if node.player is None:
                chance_child[self.chance_begin[node_id] + list(node.probabilities).index(path[-1])] = n
            n += len(flat[0])
            for target, items in zip(lists, flat):
                target.extend(items)
        kind, player, infoset, payoff, children, chance, dicts = lists
        self.kind = np.concatenate([self.kind, np.array(kind, dtype=np.int8)])
        self.player = np.concatenate([self.player, np.array(player, dtype=np.int8)])
        self.infoset = np.concatenate([self.infoset, np.array(infoset, dtype=np.int32)])
        self.payoff = np.concatenate([self.payoff, np.array(payoff, dtype=np.float64)])
        self.child_begin = np.concatenate([self.child_begin, _ranges(self.child_begin[-1], [len(c) for c in children])])
        self.child = np.concatenate([child, np.array([j for c in children for j in c], dtype=np.int32)])
        self.chance_begin = np.concatenate([self.chance_begin, _ranges(self.chance_begin[-1], [len(c) for c in chance])])
        self.chance_child = np.concatenate([chance_child, np.array([j for c in chance for j, _ in c], dtype=np.int32)])
        self.chance_prob = np.concatenate([self.chance_prob, np.array([q for c in chance for _, q in c],
                                                                      dtype=np.float64)])
        self.chance_dicts = self.chance_dicts + dicts
        for p in (0, 1):
            self.sides[p].update(self._levels(solver, p))
        self.struct = self._structure(solver)

    def _load(self, solver):
        """Copy the solver's current Python-visible state (views of an older state or plain objects) in."""
        for p in (0, 1):
            side, slots = self.sides[p], self.slots[p]
            for key, (start, stop) in slots.items():
                minimizer = solver.minimizers[p][key]
                strategy = solver._strategy[p][key]
                if not np.array_equal(minimizer.strategy, strategy):
                    raise ValueError("the native backend needs minimizer.strategy == the published strategy: " + key)
                side["regrets"][start:stop] = minimizer.regrets
                side["previous_utility"][start:stop] = minimizer.previous_utility
                side["strategy"][start:stop] = strategy
                side["sums"][start:stop] = solver._sums[p][key]
                side["pending"][self.index[p][key]] = bool(minimizer._pending)
            previous = solver._previous_opponent[p]
            if previous is not None:
                for key, (start, stop) in self.slots[1 - p].items():
                    side["previous_opponent"][start:stop] = previous[key]
                self.has_previous[p] = 1

    def bind(self, solver):
        """Make the solver's state containers views of this state, keeping existing minimizer objects."""
        minimizers = []
        for p in (0, 1):
            items = {}
            for key, minimizer in solver.minimizers[p].items():
                if "observe" in vars(minimizer) or "next_strategy" in vars(minimizer):
                    self.instrumented = True
                if isinstance(minimizer, FlatMinimizer):
                    minimizer._bind(self, p, self.index[p][key])
                else:
                    minimizer = FlatMinimizer(self, p, self.index[p][key], minimizer.predictive)
                items[key] = minimizer
            minimizers.append(MinimizerDict(self, p, items))
        solver.minimizers = tuple(minimizers)
        solver._strategy = tuple(FlatDict(self.sides[p]["strategy"], self.slots[p], solver._strategy[p])
                                 for p in (0, 1))
        solver._sums = tuple(FlatDict(self.sides[p]["sums"], self.slots[p], solver._sums[p]) for p in (0, 1))
        previous = PreviousList(self)
        for p in (0, 1):
            if self.has_previous[p]:
                keys = solver._previous_opponent[p]
                list.__setitem__(previous, p, FlatDict(self.sides[p]["previous_opponent"], self.slots[1 - p], keys))
        solver._previous_opponent = previous

    def _structure(self, solver):
        s = Solver(n_nodes=len(self.kind), predictive=int(bool(solver.predictive)),
                   alternating=int(solver.schedule == "alternating"), averaging_power=solver.averaging_power)
        for name in ("kind", "player", "infoset", "payoff", "child_begin", "child", "chance_begin",
                     "chance_child", "chance_prob"):
            setattr(s, name, _pointer(getattr(self, name)))
        for p in (0, 1):
            side, target = self.sides[p], s.side[p]
            target.n_sets, target.n_levels = len(side["depth"]), len(side["level_depth"])
            for name, array in side.items():
                setattr(target, name, _pointer(array))
            target.has_previous = _pointer(self.has_previous) + p
        return s

    # The kernel entry points; step() is the one PCFRPlus uses, the others serve the equivalence tests.
    def _run(self, solver, function, *args):
        """Hand solver._initial_actions to the kernel for one call; drop the ones a publish consumed."""
        self._sync_chance()
        pending = solver._initial_actions
        loaded = []
        for (p, key), action in pending.items():
            index = self.index[p].get(key) if p in (0, 1) else None
            if index is not None:
                self.sides[p]["initial_action"][index] = solver.sets[p][key].index(action)
                loaded.append((p, key, index))
        code = function(C.byref(self.struct), *args)
        for p, key, index in loaded:
            if self.sides[p]["initial_action"][index] < 0:
                del pending[p, key]  # consumed by its first publish, as PCFRPlus._publish pops it
            else:
                self.sides[p]["initial_action"][index] = -1
        previous = solver._previous_opponent
        for p in (0, 1):  # an observe took the first snapshot: expose it
            if self.has_previous[p] and list.__getitem__(previous, p) is None:
                list.__setitem__(previous, p, FlatDict(self.sides[p]["previous_opponent"], self.slots[1 - p],
                                                       solver._strategy[1 - p]))
        _check(code)

    def step(self, solver):
        self._run(solver, self.dll.pcfr_step, solver.rounds)
        solver.rounds += 1

    def run(self, solver, rounds, record=None):
        """PCFRPlus.run: `rounds` steps in one kernel call; with record=(player, key), that set's published
        strategy after each round, one row per round."""
        done, trace, player, index = C.c_int64(0), None, 0, -1
        if record is not None:
            player, key = record
            start, stop = self.slots[player][key]
            index, trace = self.index[player][key], np.empty((rounds, stop - start))
        try:
            self._run(solver, self.dll.pcfr_run, solver.rounds, rounds, C.byref(done), player, index,
                      None if trace is None else _pointer(trace))
        finally:
            solver.rounds += done.value
        return trace

    def growth_utilities(self):
        """OneSidedExpansion.utilities under the published profile: per player, the conditional utilities of every
        set in that player's flat action layout (slots)."""
        self._sync_chance()
        values = tuple(np.zeros(int(self.sides[p]["offset"][-1])) for p in (0, 1))
        _check(self.dll.pcfr_growth_utilities(C.byref(self.struct), _pointer(values[0]), _pointer(values[1])))
        return values

    def run_gadget(self, solver, control, arrays, rounds, record=None, history=None):
        """`rounds` x (PCFRPlus.run(1, record) + the control's update_from_solver) in one kernel call: returns the
        recorded rows (as run()) and p_max after each round. `control` is a Control over `arrays` (kept alive by
        the caller); history, if given, is a (rounds, control.history_width) array the kernel fills."""
        done, trace, player, index = C.c_int64(0), None, 0, -1
        if record is not None:
            player, key = record
            start, stop = self.slots[player][key]
            index, trace = self.index[player][key], np.empty((rounds, stop - start))
        p_max = np.empty(rounds)
        try:
            self._run(solver, self.dll.pcfr_run_gadget, C.byref(control), solver.rounds, rounds, C.byref(done),
                      player, index, None if trace is None else _pointer(trace), _pointer(p_max),
                      None if history is None else _pointer(history))
        finally:
            solver.rounds += done.value
        return trace, p_max

    def behavioral_values(self, nodes):
        """toy_games.value_walk of the subtrees at these flat node ids under the published strategies
        (behavioral_value with policy()), in its floating-point order."""
        self._sync_chance()
        nodes = np.ascontiguousarray(nodes, dtype=np.int32)
        values = np.zeros(len(nodes))
        _check(self.dll.pcfr_behavioral_values(C.byref(self.struct), len(nodes), _pointer(nodes), _pointer(values)))
        return values

    def prepare(self, solver, player):
        self._run(solver, self.dll.pcfr_prepare, player)

    def observe(self, solver, player):
        self._run(solver, self.dll.pcfr_observe, player)

    def accumulate_average(self, player, weight):
        _check(self.dll.pcfr_accumulate_average(C.byref(self.struct), player, float(weight)))

    def utilities(self, player, opponent=None):
        self._sync_chance()
        values = np.zeros(int(self.sides[player]["offset"][-1]))
        if opponent is not None:
            flat = np.zeros(int(self.sides[1 - player]["offset"][-1]))
            for key, (start, stop) in self.slots[1 - player].items():
                flat[start:stop] = opponent[key]
            opponent = flat
        _check(self.dll.pcfr_utilities(C.byref(self.struct), player,
                                       None if opponent is None else _pointer(opponent), _pointer(values)))
        return {key: values[start:stop] for key, (start, stop) in self.slots[player].items()}
