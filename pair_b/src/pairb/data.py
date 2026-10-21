"""D2 records to training arrays (D3)."""
import gzip
import hashlib
import json
from pathlib import Path

import chess
import numpy as np

from .encode import N_PLANES, encode_board, stm_sign

ENCODING = "net1-planes-0-18-v1"
CACHE_VERSION = 2  # bump whenever build_arrays changes what it returns
HALFMOVE_PLANE = 18
PARTS = ("part-*.jsonl", "part-*.jsonl.gz")  # a dataset's record files; a part may be gzipped


def split_of(game_id: str) -> str:
    """Spec §6: the sha1 bucket of the game ID; 0-7 train, 8 validation, 9 test."""
    bucket = int(hashlib.sha1(game_id.encode()).hexdigest(), 16) % 10
    return "train" if bucket < 8 else ("val" if bucket == 8 else "test")


def part_files(folder) -> list[Path]:
    """A dataset folder's record files, plain or gzipped, in name order. A part kept both ways
    (gzipped in place with the original left) would be read twice, so it is refused."""
    parts = sorted(p for pattern in PARTS for p in Path(folder).glob(pattern))
    names = [p.name.removesuffix(".gz") for p in parts]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise ValueError(f"{folder} has {', '.join(twice)} both plain and gzipped; keep one")
    return parts


def record_lines(folder):
    """Each record's JSON line, as written, part by part."""
    for path in part_files(folder):
        data = path.read_bytes()
        yield from (gzip.decompress(data) if path.suffix == ".gz" else data).decode().splitlines()


def read_records(folder) -> list[dict]:
    return [json.loads(line) for line in record_lines(folder)]


def pack(planes: np.ndarray) -> np.ndarray:
    """(N, 19, 8, 8) planes as uint8, 4x smaller: the 0/1 planes as they are, and the
    halfmove plane as the clock itself (it never exceeds 100 in a game that goes on)."""
    p = planes.copy()
    p[:, HALFMOVE_PLANE] *= 100
    return np.rint(p).astype(np.uint8)


def unpack(packed: np.ndarray) -> np.ndarray:
    x = packed.astype(np.float32)
    x[:, HALFMOVE_PLANE] /= 100
    return x


def build_arrays(records) -> dict[str, np.ndarray]:
    """Arrays for training, values in the side to move's view. Boards decided by a rule are
    skipped: the rules score those, not the network."""
    rows = [r for r in records if r["rule"] is None]
    planes = np.zeros((len(rows), N_PLANES, 8, 8), dtype=np.uint8)
    d1, y, sign = (np.zeros(len(rows), dtype=np.float32) for _ in range(3))
    for i, r in enumerate(rows):
        board = chess.Board(r["fen"])
        s = stm_sign(board)
        planes[i] = pack(encode_board(board)[None])[0]
        d1[i], y[i], sign[i] = s * r["d1"]["v"], s * r["d11"]["v"], s
    return {"planes": planes, "d1": d1, "y": y, "sign": sign,
            "game_id": np.array([r["game_id"] for r in rows]),
            "parent": np.array([f"{r['game_id']}|{r['parent_fen']}" for r in rows])}


def load_arrays(folder, cache_dir) -> dict[str, np.ndarray]:
    """build_arrays for a dataset folder, cached outside it. The cache key covers the manifest and each
    part file's name, size and modification time, so part files rewritten under an unchanged manifest
    are read again."""
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    parts = part_files(folder)
    files = "|".join(f"{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}" for p in parts)
    stamp = f"{manifest['created']}|{manifest['records']}|{files}"
    key = hashlib.sha1(f"{folder.resolve()}|{stamp}|{ENCODING}|{CACHE_VERSION}".encode()).hexdigest()[:12]
    path = Path(cache_dir) / f"{folder.name}-{key}.npz"
    if path.exists():
        with np.load(path) as z:
            return {k: z[k] for k in z.files}
    arrays = build_arrays(read_records(folder))
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)
    return arrays
