"""Turning D2 records into training arrays, the split by game (D1 spec §6), and the array cache."""
import json
import os
import subprocess
import sys

import chess
import numpy as np
import pytest

from pairb.data import build_arrays, load_arrays, pack, split_of, unpack
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


def write_d2(folder, records, manifest):
    folder.mkdir(exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps(manifest))
    (folder / "part-00.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))


def touch_later(path):
    """Move a file's modification time on by a second, as a rewrite a moment later would (some file
    systems keep only whole seconds)."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


# Catches: a cache keyed on the manifest alone, which hands back the old arrays when the part files
# are rewritten under an unchanged manifest (a re-export of the same size into the same folder).
def test_load_arrays_rebuilds_when_a_part_file_changes_under_the_same_manifest(tmp_path):
    manifest = {"created": "2026-10-20T09:00:00", "records": 1}
    write_d2(tmp_path / "d2", [record(WHITE_TO_MOVE, "g-000000", 0.2, 0.3)], manifest)
    assert load_arrays(tmp_path / "d2", tmp_path / "cache")["y"].tolist() == pytest.approx([0.3])
    write_d2(tmp_path / "d2", [record(WHITE_TO_MOVE, "g-000000", 0.2, 0.7)], manifest)
    touch_later(tmp_path / "d2" / "part-00.jsonl")
    assert load_arrays(tmp_path / "d2", tmp_path / "cache")["y"].tolist() == pytest.approx([0.7])


# Catches: a key that changes between two loads of unchanged files, which would rebuild the arrays
# on every run.
def test_load_arrays_reuses_its_cache_while_the_files_are_unchanged(tmp_path, monkeypatch):
    write_d2(tmp_path / "d2", [record(WHITE_TO_MOVE, "g-000000", 0.2, 0.3)], {"created": "x", "records": 1})
    load_arrays(tmp_path / "d2", tmp_path / "cache")
    monkeypatch.setattr("pairb.data.build_arrays", lambda records: pytest.fail("rebuilt unchanged files"))
    assert load_arrays(tmp_path / "d2", tmp_path / "cache")["y"].tolist() == pytest.approx([0.3])
