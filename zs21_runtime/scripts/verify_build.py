"""Compare a separate rebuilt engine/kernel with the shipped verified artifacts."""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
from random import Random
import sys

RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME.parent))

import chess
from pair_a_prep.zs21.config import load
from pair_a_prep.zs21.engine import EnginePool
from pair_a_prep.zs21.native_tracker import Packed, library, pack
from pair_a_prep.zs21.rule_profile import RULES_ID


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, default=RUNTIME / "out/rebuild-verification.json")
    args = parser.parse_args()
    rng, board, boards = Random(210606068), chess.Board(), []
    for _ in range(80):
        boards.append(board.copy(stack=False))
        if board.is_game_over():
            board = chess.Board()
        else:
            board.push(rng.choice(list(board.legal_moves)))
    boards += [chess.Board(fen) for fen in (
        "7k/8/8/8/1p6/pPp5/PRP5/KB6 w - - 0 1",
        "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",
        "4r1k1/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
        "8/8/8/8/8/8/4k3/4K3 w - - 0 1")]
    with EnginePool(load()["engine"]) as pool:
        expected = pool.evaluate(boards, "white", depth=1)
    with EnginePool(args.directory / "stockfish13.exe") as pool:
        actual = pool.evaluate(boards, "white", depth=1)
    assert actual == expected
    original, rebuilt = library(), C.CDLL(str((args.directory / "inference.dll").resolve()))
    rebuilt.zs_rules_id.argtypes, rebuilt.zs_rules_id.restype = [], C.c_char_p
    assert rebuilt.zs_rules_id().decode() == RULES_ID
    rebuilt.zs_moves.argtypes, rebuilt.zs_moves.restype = [C.POINTER(Packed), C.POINTER(C.c_int)], C.c_int
    rebuilt.zs_has_moves.argtypes, rebuilt.zs_has_moves.restype = [C.POINTER(Packed)], C.c_int
    for board in boards:
        packed, old, new = pack(board), (C.c_int*512)(), (C.c_int*512)()
        old_count = original.zs_moves(C.byref(packed), old)
        new_count = rebuilt.zs_moves(C.byref(packed), new)
        assert list(old[:old_count]) == list(new[:new_count])
        assert rebuilt.zs_has_moves(C.byref(packed)) == original.zs_has_moves(C.byref(packed))
    report = dict(status="passed", positions=len(boards), rules_id=RULES_ID,
                  engine_comparison_fields=["value", "source", "depth", "nodes"],
                  native_actions_equal=True, native_terminal_probe_equal=True,
                  rebuilt_hashes={name: hashlib.sha256((args.directory / name).read_bytes()).hexdigest()
                                  for name in ("stockfish13.exe", "inference.dll")})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
