"""Turning D2 records into training arrays, and the split by game (D1 spec §6)."""
import subprocess
import sys

import chess
import numpy as np
import pytest

from pairb.data import build_arrays, pack, split_of, unpack
from pairb.encode import encode_board

WHITE_TO_MOVE = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
BLACK_TO_MOVE = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/2N2N2/PPPP1PPP/R1BQKB1R b KQkq - 3 3"


def record(fen, game_id, d1=None, d11=None, rule=None, parent_fen="parent"):
    return {"id": f"{game_id}-{fen[:8]}", "game_id": game_id, "fen": fen, "rule": rule, "parent_fen": parent_fen,
            "d1": None if d1 is None else {"cp": None, "mate": None, "v": d1},
            "d11": None if d11 is None else {"cp": None, "mate": None, "v": d11}}


# Expected buckets were worked out once with sha1, independently of the code under test.
@pytest.mark.parametrize("game_id, want", [("g-000000", "train"), ("g-000002", "val"), ("g-000013", "test")])
def test_split_of_follows_the_sha1_bucket_rule(game_id, want):
    assert split_of(game_id) == want


# Catches: using Python's hash(), which changes between processes and would reshuffle the splits.
def test_split_of_is_the_same_in_every_process():
    code = "from pairb.data import split_of; print([split_of(f'g-{i:06d}') for i in range(50)])"
    runs = [subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                           env={"PYTHONHASHSEED": seed}).stdout for seed in ("1", "2")]
    assert runs[0] == runs[1]


def test_pack_and_unpack_keep_the_planes():
    x = encode_board(chess.Board("8/8/8/4k3/8/8/3Q4/4K3 w - - 37 80"))
    assert np.allclose(unpack(pack(x[None]))[0], x)


# Catches: Black-to-move labels left in White's view, and rule records leaking into training.
def test_build_arrays_puts_values_in_the_movers_view_and_skips_rule_records():
    recs = [record(WHITE_TO_MOVE, "g-000000", 0.2, 0.3),
            record(BLACK_TO_MOVE, "g-000002", 0.2, 0.3),
            record("7k/5Q2/6K1/8/8/8/8/8 b - - 3 60", "g-000002", rule={"name": "stalemate", "v": 1.0})]
    a = build_arrays(recs)
    assert a["d1"].tolist() == pytest.approx([0.2, -0.2])
    assert a["y"].tolist() == pytest.approx([0.3, -0.3])
    assert a["sign"].tolist() == [1.0, -1.0]
    assert a["game_id"].tolist() == ["g-000000", "g-000002"]
    assert np.allclose(unpack(a["planes"])[1], encode_board(chess.Board(BLACK_TO_MOVE)))


# Catches: children of different parents merged (or one parent split) when measuring move choice.
def test_build_arrays_keys_each_row_by_its_game_and_parent():
    recs = [record(WHITE_TO_MOVE, "g-000000", 0.2, 0.3, parent_fen="P1"),
            record(BLACK_TO_MOVE, "g-000000", 0.2, 0.3, parent_fen="P2"),
            record(WHITE_TO_MOVE, "g-000002", 0.2, 0.3, parent_fen="P1")]
    keys = build_arrays(recs)["parent"].tolist()
    assert len(set(keys)) == 3
