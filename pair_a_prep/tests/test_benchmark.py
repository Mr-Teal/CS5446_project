import json

import chess
import chess.engine
import pytest

from pair_a_prep.benchmark_stockfish import DEFAULT_CORPUS, load_positions, raw_lines, summarize


def test_engine_corpus_has_both_sides_and_no_unsafe_positions():
    positions = load_positions(DEFAULT_CORPUS)
    assert {chess.Board(p["fen"]).turn for p in positions} == {chess.WHITE, chess.BLACK}
    assert {p["category"] for p in positions} == {"opening", "endgame"}


def test_engine_corpus_rejects_king_capture_board(tmp_path):
    path = tmp_path / "unsafe.json"
    path.write_text(json.dumps({"positions": [{"id": "capturable_king", "category": "unsafe",
        "fen": "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe"):
        load_positions(path)


def test_raw_score_preserves_root_perspective_and_mate_distance():
    board = chess.Board()
    board.push_uci("e2e4")
    infos = [{"score": chess.engine.PovScore(chess.engine.Cp(-20), chess.BLACK)},
             {"score": chess.engine.PovScore(chess.engine.Mate(3), chess.BLACK)}]
    lines = raw_lines(infos, board)
    assert lines[0]["cp"] == -20 and lines[0]["mate"] is None
    assert lines[1]["mate"] == 3 and lines[1]["cp"] is None


def test_latency_summary_excludes_failed_trials():
    rows = [{"type": "trial", "status": "ok", "depth": 1, "mode": "all", "wall_ms": t}
            for t in [1, 2, 9]]
    rows.append({"type": "trial", "status": "error"})
    summary = summarize(rows)[0]
    assert summary["trials"] == 3 and summary["median_ms"] == 2
    assert summary["p95_ms_nearest_rank"] == 9
