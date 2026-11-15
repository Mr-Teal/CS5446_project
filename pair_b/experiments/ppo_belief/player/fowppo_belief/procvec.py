"""VecFow spread over worker processes, so that game generation uses several CPU cores.

ProcVec has the same arrays and step() as VecFow. The arrays live in shared memory: each worker
owns a slice of the games and writes its slice in place, so a step sends only a wake-up message
each way. Read the arrays between steps, never during one.
"""
import multiprocessing as mp
import traceback
from multiprocessing import shared_memory

import numpy as np

from .env import VecFow, array_fields

_STEP_FIELDS = {"actions": np.int64, "term_r": np.float32, "done": np.bool_}


def _fields(n: int) -> dict:
    fields = array_fields(n)
    fields.update({name: (dtype, (n,)) for name, dtype in _STEP_FIELDS.items()})
    return fields


def _open_block(name: str) -> shared_memory.SharedMemory:
    """Attach to a block that the parent owns. A worker that exits must not remove it."""
    try:
        return shared_memory.SharedMemory(name=name, track=False)  # Python 3.13 and newer
    except TypeError:
        # Python 3.12 has no `track`. A worker started by multiprocessing shares the parent's
        # resource tracker, so the block stays until the parent removes it.
        return shared_memory.SharedMemory(name=name)


def _attach(names: dict, n: int):
    blocks = {name: _open_block(names[name]) for name in names}
    arrays = {name: np.ndarray(shape, dtype=dtype, buffer=blocks[name].buf) for name, (dtype, shape) in _fields(n).items()}
    return blocks, arrays


def _worker(conn, names: dict, n: int, low: int, high: int, kwargs: dict) -> None:
    blocks, arrays = _attach(names, n)
    mine = {name: array[low:high] for name, array in arrays.items()}
    vec = VecFow(high - low, arrays=mine, **kwargs)
    conn.send("ready")
    try:
        while conn.recv() is not None:
            try:
                term_r, done = vec.step(mine["actions"])
            except Exception:  # tell the trainer why, then stop
                conn.send(("error", traceback.format_exc()))
                break
            mine["term_r"][:], mine["done"][:] = term_r, done
            conn.send(("ok", vec.finished))
            vec.finished = []
    finally:
        del mine, arrays, vec
        for block in blocks.values():
            block.close()


class ProcVec:
    def __init__(self, n: int, workers: int, shaping: float = 0.0, rivals=None, seed: int = 0, opening=(0, 0),
                 timeout: float = 300.0):
        self.n, self.timeout = n, timeout
        self._blocks = {name: shared_memory.SharedMemory(create=True, size=max(1, int(np.prod(shape)) * np.dtype(dtype).itemsize))
                        for name, (dtype, shape) in _fields(n).items()}
        names = {name: block.name for name, block in self._blocks.items()}
        arrays = {name: np.ndarray(shape, dtype=dtype, buffer=self._blocks[name].buf)
                  for name, (dtype, shape) in _fields(n).items()}
        for array in arrays.values():
            array[...] = 0
        self.obs, self.mask, self.phi = arrays["obs"], arrays["mask"], arrays["phi"]
        self.seat, self.control = arrays["seat"], arrays["control"]
        self._actions, self._term_r, self._done = arrays["actions"], arrays["term_r"], arrays["done"]
        self.finished = []
        context = mp.get_context("spawn")
        bounds = np.linspace(0, n, workers + 1).astype(int)
        self._conns, self._procs = [], []
        for w in range(workers):
            parent, child = context.Pipe()
            kwargs = {"shaping": shaping, "rivals": rivals, "seed": seed * 1000 + w, "opening": tuple(opening)}
            proc = context.Process(target=_worker, args=(child, names, n, int(bounds[w]), int(bounds[w + 1]), kwargs),
                                   daemon=True)
            proc.start()
            child.close()
            self._conns.append(parent)
            self._procs.append(proc)
        for conn in self._conns:
            if conn.recv() != "ready":
                raise RuntimeError("a game worker did not start")

    def step(self, actions):
        self._actions[:] = actions
        for conn in self._conns:
            conn.send(1)
        for w, conn in enumerate(self._conns):
            if not conn.poll(self.timeout):
                raise RuntimeError(f"game worker {w} did not answer within {self.timeout:.0f} s")
            try:
                status, payload = conn.recv()
            except EOFError:
                raise RuntimeError(f"game worker {w} stopped") from None
            if status != "ok":
                raise RuntimeError(f"game worker {w} failed:\n{payload}")
            self.finished.extend(payload)
        return self._term_r.copy(), self._done.copy()

    def close(self) -> None:
        for conn in self._conns:
            try:
                conn.send(None)
            except (BrokenPipeError, OSError):
                pass
        for proc in self._procs:
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()
        self._conns, self._procs = [], []
        self.obs = self.mask = self.phi = self.seat = self.control = None
        self._actions = self._term_r = self._done = None
        for block in self._blocks.values():
            block.close()
            block.unlink()
        self._blocks = {}
