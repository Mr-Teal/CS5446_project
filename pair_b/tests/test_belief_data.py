"""Belief records (fow_shared TrainingRecord) to flat per-board training arrays (D6)."""
import random

import chess
import numpy as np
import pytest

from fow_shared.contracts import AgentInput, Belief, Decision, Hypothesis, Observation, TrainingRecord
from fow_shared.features import encode_belief
from pairb.belief_data import build_arrays, opponent_visible
from pairb.standin_beliefs import make_turn, record_for

MIDDLEGAME = "r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N1PN2/PP3PPP/R2QKB1R w KQ - 2 9"
BLACK_TO_MOVE = "r2qkb1r/ppp2ppp/2n1bn2/3pp3/4P3/2NP1N2/PPP1BPPP/R1BQK2R b KQkq - 3 6"


def practice_record(fen, seed, game_id):
    turn = make_turn(chess.Board(fen), random.Random(seed), n_hypotheses=4, ply=12)
    n = len(turn.belief.hypotheses)
    values = tuple(round(0.1 * (i + 1), 1) for i in range(n))
    return record_for(turn, values, seed, game_id, "test", diagnostics={f"d1:{i}": -v for i, v in enumerate(values)})


# Catches: boards attached to the wrong belief, weights or labels shifted by one, or planes that
# differ from the shared encoder's.
def test_one_row_per_board_carrying_its_beliefs_weight_label_and_planes():
    records = [practice_record(MIDDLEGAME, 1, "g-000001"), practice_record(BLACK_TO_MOVE, 2, "g-000002")]
    a = build_arrays(records)
    sizes = [len(r.agent_input.belief.hypotheses) for r in records]
    assert a["planes"].shape == (sum(sizes), 32, 8, 8)
    assert a["belief"].tolist() == [0] * sizes[0] + [1] * sizes[1]
    for b, r in enumerate(records):
        rows = a["belief"] == b
        assert a["weight"][rows].sum() == pytest.approx(1.0)
        assert a["y"][rows].tolist() == pytest.approx(list(r.hypothesis_values))
        assert a["d1"][rows].tolist() == pytest.approx([-v for v in r.hypothesis_values])
        planes, _ = encode_belief(r.agent_input, opponent_visible)
        np.testing.assert_allclose(a["planes"][rows].astype(np.float32), planes, atol=1e-3)
    assert a["root"].tolist() == pytest.approx([r.root_value for r in records])
    assert a["game_id"].tolist() == ["g-000001", "g-000002"]


# Catches: a board the rules already decide being trained on as if Stockfish had scored it.
def test_boards_the_rules_decide_are_marked():
    obs = Observation(player="white", side_to_move="white", ply=4, visible_squares=(), visible_pieces={},
                      legal_moves=("e1d1",))
    boards = ("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1",   # White can take the king: decided (+1)
              "4k3/8/8/8/8/8/8/R3K3 w - - 0 1")     # nothing decided
    turn = AgentInput(obs, Belief("white", 4, tuple(Hypothesis(f, 0.5) for f in boards)), 1000)
    record = TrainingRecord(turn, Decision("e1d1", {"e1d1": 1.0}), 0.8, (1.0, 0.6), 0, "test", "test", "g-000003")
    arrays = build_arrays([record])
    assert arrays["rule"].tolist() == [True, False]
    # No d1 recorded: a rule board takes its rule value (as the evaluator feeds it), others stay unknown.
    assert arrays["d1"][0] == 1.0 and np.isnan(arrays["d1"][1])


# Catches: a training step that grows with belief size (Pair A plans 256+ boards per belief), or a
# batching that drops or repeats beliefs.
def test_batches_hold_whole_beliefs_up_to_a_board_cap():
    from pairb.belief_data import belief_batches
    sizes = np.array([3, 5, 2, 8, 1, 4])
    batches = belief_batches(sizes, np.arange(6), max_boards=8)
    assert [b.tolist() for b in batches] == [[0, 1], [2], [3], [4, 5]]
    assert sorted(np.concatenate(batches).tolist()) == list(range(6))
    assert belief_batches(np.array([20]), np.arange(1), max_boards=8)[0].tolist() == [0]  # one big belief alone


def _write(folder, name, records):
    from fow_shared.recording import write_records
    folder.mkdir(exist_ok=True)
    write_records(folder / name, records)


# Catches: a crash on an empty part file (a worker whose points were all rule-decided), on a folder
# without manifest.json, or on files named otherwise, which Pair A's label runs may well produce.
def test_loading_copes_with_empty_files_missing_manifests_and_other_names(tmp_path):
    import pytest as _pytest
    from pairb.belief_data import load_arrays
    records = [practice_record(MIDDLEGAME, 1, "g-000001"), practice_record(BLACK_TO_MOVE, 2, "g-000002")]
    _write(tmp_path / "a", "part-00.jsonl", records)
    _write(tmp_path / "a", "part-01.jsonl", [])
    assert len(load_arrays(tmp_path / "a", tmp_path / "cache", workers=1)["root"]) == 2
    _write(tmp_path / "b", "labels-pair-a.jsonl", records)
    assert len(load_arrays(tmp_path / "b", tmp_path / "cache", workers=1, pattern="*.jsonl")["root"]) == 2
    (tmp_path / "c").mkdir()
    with _pytest.raises(ValueError, match="no records"):
        load_arrays(tmp_path / "c", tmp_path / "cache", workers=1)
