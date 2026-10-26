"""Numeric LP fixtures with original flow rows, independent of live game objects."""

import json
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix

from .sequence_form import SequenceForm


def save_form(form, path):
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    arrays = {}
    for name, matrix in (("A", form.A), ("B", form.B), ("C", form.C),
                         ("E", form.flows[0]), ("F", form.flows[1])):
        arrays.update({name + "_" + key: getattr(matrix, key)
                       for key in ("data", "indices", "indptr")})
        arrays[name + "_shape"] = matrix.shape
    arrays["metadata"] = json.dumps(dict(schema=1, infosets=[
        [[parent, indices] for parent, _, indices in table.values()]
        for table in form.infosets]))
    arrays["e"], arrays["f"] = form.rhs
    np.savez_compressed(path, **arrays)


def load_form(path):
    form = SequenceForm.__new__(SequenceForm)
    with np.load(path, allow_pickle=False) as arrays:
        metadata = json.loads(str(arrays["metadata"]))
        if metadata["schema"] != 1:
            raise ValueError("unknown LP fixture schema")
        matrices = {name: csr_matrix((arrays[name + "_data"], arrays[name + "_indices"],
                                     arrays[name + "_indptr"]), shape=arrays[name + "_shape"])
                    for name in ("A", "B", "C", "E", "F")}
        form.A, form.B, form.C = (matrices[name] for name in ("A", "B", "C"))
        form.flows = [matrices[name] for name in ("E", "F")]
        form.rhs = [arrays[name] for name in ("e", "f")]
        form.sequences = [list(range(size)) for size in form.C.shape]
        form.infosets = [{i: (parent, tuple(range(len(indices))), indices)
                          for i, (parent, indices) in enumerate(table)}
                         for table in metadata["infosets"]]
    return form
