"""Optional native PCFR+ round (pcfr_kernel.cpp): loader, flattened tree and flat solver state.

PCFRPlus keeps the Node tree, expand(), information_sets and the infoset-key <-> id mapping. NativeState compiles
the tree into arrays (nodes in DFS order) after __init__ and after every expand(), and holds the solver state in
flat float64 arrays, one block of actions per information set. The solver's Python-visible state
(minimizers[p][key].regrets / .strategy / .previous_utility / ._pending, _strategy, _sums, _previous_opponent)
becomes views of those arrays: reads see the kernel's results, in-place writes and assignments write through.
_initial_actions stays a plain dict and is handed to the kernel around each step. Chance probabilities are re-read
from the tree's dicts before every kernel call, because the blended gadget's controller rewrites its root
distribution in place between rounds.

Instrumentation that replaces PCFRPlus._utilities or a minimizer's observe/next_strategy on an instance (to count
or spy on calls) sets `instrumented`, and PCFRPlus.step then runs that solver's rounds in Python on the same views.

Build with `python -m pair_a_prep.build_pcfr_kernel`; library() returns None when the build is missing or stale.
"""

import ctypes as C
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
from itertools import chain
import json
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
                       ("pcfr_step", [solver, C.c_int64])):
        function = getattr(dll, name)
        function.argtypes, function.restype = args, C.c_int
    return dll


_ERRORS = {-1: "observe the pending strategy first", -2: "request a strategy before observing utilities"}


def _check(code):
    if code:
        raise ValueError(_ERRORS.get(code, f"native PCFR+ kernel failed with code {code}"))


def _pointer(array):
    return array.ctypes.data


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
            levels = {}
            for key in solver._order[p]:  # deepest first
                levels.setdefault(solver._depth[p][key], []).append(self.index[p][key])
            actions = int(offsets[p][-1])
            self.sides.append(dict(
                offset=offsets[p],
                depth=np.array([solver._depth[p][key] for key in sets[p]], dtype=np.int32),
                level_begin=np.cumsum([0] + [len(v) for v in levels.values()]).astype(np.int32),
                level_sets=np.array([i for v in levels.values() for i in v], dtype=np.int32),
                level_depth=np.array(list(levels), dtype=np.int32),
                regrets=np.zeros(actions), strategy=np.zeros(actions), previous_utility=np.zeros(actions),
                sums=np.zeros(actions), pending=np.zeros(len(sets[p]), dtype=np.int8),
                initial_action=np.full(len(sets[p]), -1, dtype=np.int32),
                previous_opponent=np.zeros(int(offsets[1 - p][-1]))))
        self._load(solver)
        self.struct = self._structure(solver)

    def _compile_tree(self, root, sets):
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
                return i
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
            return i

        visit(root)
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
