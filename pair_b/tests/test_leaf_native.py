"""The native leaf data path (pair_a_prep/leaf_kernel.cpp) must reproduce BeliefNetworkEvaluator.evaluate_children's
Python path exactly.

Per parent: the child moves and their order (fog_legal_moves), the child FENs (standard_fen) and packed boards,
which children the fog-of-war rules decide and their White-view values (rule_value, compared by repr, so -0.0
would show), and every child's 32 x 8 x 8 planes as encode_belief makes them for the evaluator's one-board belief
(_alone), compared bit for bit. Parents: rule corner cases, the rule fixtures, and recorded games (every
hypothesis board, both sides to move, plus random children of them). Then evaluate_children end to end with the
trained checkpoint on CPU: same moves, values within 1e-6, and identical planes reaching the network. Skipped when
the kernel is not built.
"""
import glob
import os
from pathlib import Path
import random

import chess
import numpy as np
import pytest

torch = pytest.importorskip("torch")

from fow_shared.features import encode_belief
from fow_shared.values import fog_legal_moves, standard_fen, terminal_score
from pair_a_prep import _leaf_native
from pair_a_prep.zs21.native_tracker import pack
from pairb import belief_evaluator
from pairb.belief_data import opponent_visible
from pairb.belief_evaluator import BeliefNetworkEvaluator, _alone
from pairb.belief_net import BeliefNetwork
from pairb.values import rule_value

pytestmark = pytest.mark.skipif(_leaf_native.library() is None,
                                reason="native leaf kernel not built (python -m pair_a_prep.build_leaf_kernel)")

RECORDS = os.environ.get("FOW_TEST_RECORDS") or next(
    (p for p in ("/labels/solver-v2-sf8-g237", "/labels/solver-v2-sf8") if os.path.isdir(p)), "")
CHECKPOINT = Path(__file__).resolve().parents[1] / "checkpoints" / "belief-solver-v2-sf8-g237" / "best.pt"
needs_records = pytest.mark.skipif(not RECORDS or not glob.glob(f"{RECORDS}/part-*.jsonl"),
                                   reason="set FOW_TEST_RECORDS to a label folder")

CORNERS = [
    # (start FEN, moves played from it); every position on the way is a parent
    (chess.STARTING_FEN, ["e2e4", "d7d5", "e4d5", "c7c5", "d5c6", "g8f6"]),
    # en passant: used, unused, a capture only fog rules allow (it exposes the king), a FEN square nobody can use
    ("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1", ["e2e4"]),
    ("4k3/3p4/8/4P3/8/8/8/4K3 b - - 0 1", ["d7d5"]),
    ("k7/8/8/r2pP2K/8/8/8/8 w - d6 0 2", []),
    ("4k3/8/8/3p4/8/8/8/4K3 w - d6 0 2", []),
    # castling: allowed, into / through attacks (fog-only, appended last), rights lost, rights the FEN cannot have
    ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", ["e1g1"]),
    ("r3k2r/8/8/8/8/5q2/8/R3K2R w KQkq - 0 1", []),
    ("r3k2r/8/8/8/8/8/6q1/R3K2R w KQkq - 0 1", []),
    ("r3k2r/8/5Q2/8/8/8/8/R3K2R b KQkq - 0 1", []),
    ("r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1", ["e8e7"]),
    ("4k3/8/8/8/8/8/8/4K3 w KQkq - 0 1", []),
    ("r3k2r/8/8/8/8/8/8/1R2K1R1 w KQkq - 0 1", []),
    # promotions with and without capture
    ("1n2k3/P7/8/8/8/8/7p/4K3 w - - 0 1", ["a7b8q", "h2h1n"]),
    # king captures, a king left en prise (forced loss), a king missing (no children)
    ("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1", []),
    ("4k3/8/8/8/8/8/4q3/4K3 w - - 0 1", []),
    ("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1", []),
    ("8/8/8/8/8/8/4P3/4K3 w - - 0 1", []),
    # fifty-move rule: decided in the child, one move ahead, and at the parent (no children)
    ("4k3/8/8/8/8/8/8/4K2R w - - 99 60", []),
    ("4k3/8/8/8/8/8/8/4K2R w - - 98 60", []),
    ("4k3/8/8/8/8/8/8/4K2R b - - 98 60", []),
    ("4k3/8/8/8/8/8/8/4K2R w - - 100 60", []),
    # no fog-legal move (draw), reached by a move and at the parent
    ("7k/8/8/8/1pp5/pP6/PRP5/KB6 b - - 0 1", ["c4c3"]),
    ("7k/8/8/8/1p6/pPp5/PRP5/KB6 w - - 0 1", []),
    ("8/8/8/8/8/4k3/4q3/4K2R w K - 0 1", []),
]


def reference(fen):
    """The Python path's children: moves, standard FENs, packed boards, rule flags and values, all planes."""
    board = chess.Board(fen)
    out = {"moves": [], "fens": [], "boards": [], "rule": [], "white": [], "planes": []}
    if terminal_score(board) is not None:
        return out
    for move in fog_legal_moves(board):
        child = board.copy()  # as evaluate_children: with the history, for the rule checks
        child.push(move)
        rule = rule_value(child)
        flat = board.copy(stack=False)
        flat.push(move)
        planes, weights = encode_belief(_alone(flat), opponent_visible)
        assert planes.dtype == np.float32 and weights.tolist() == [1.0]
        out["moves"].append(move.uci())
        out["fens"].append(standard_fen(flat))
        out["boards"].append(bytes(pack(chess.Board(standard_fen(flat)))))
        out["rule"].append(rule is not None)
        out["white"].append(repr(rule[1]) if rule is not None else None)
        out["planes"].append(planes)
    return out


def check(fen, counts):
    expected = reference(fen)
    kids = _leaf_native.children(fen, all_planes=True, details=True)
    assert kids.moves == expected["moves"], fen
    assert kids.fens == expected["fens"], fen
    assert kids.boards == expected["boards"], fen
    assert kids.rule.tolist() == expected["rule"], fen
    assert [repr(w) if r else None for w, r in zip(kids.white, kids.rule)] == expected["white"], fen
    planes = np.concatenate(expected["planes"]) if expected["planes"] else np.zeros((0, 32, 8, 8), np.float32)
    assert kids.planes.dtype == np.float32 and kids.planes.shape == planes.shape, fen
    if not np.array_equal(kids.planes, planes):
        bad = sorted({int(p) for p in np.argwhere(kids.planes != planes)[:, 1]})
        raise AssertionError(f"{fen}: planes {bad} differ")
    compact = _leaf_native.children(fen)  # evaluate_children's call: planes of the undecided children only
    assert compact.moves == kids.moves and compact.rule.tolist() == kids.rule.tolist()
    assert np.array_equal(compact.planes, planes[~kids.rule]) and compact.planes.flags.c_contiguous
    counts["parents"] += 1
    counts["children"] += len(kids.moves)
    counts["decided"] += int(kids.rule.sum())
    counts["castling"] += sum(m in ("e1g1", "e1c1", "e8g8", "e8c8") for m in kids.moves)
    counts["promotion"] += sum(len(m) == 5 for m in kids.moves)
    counts["en_passant_plane"] += int(planes[:, 30].any(axis=(1, 2)).sum())
    counts["black_to_move"] += fen.split()[1] == "b"


def _positions(start, moves):
    board = chess.Board(start)
    yield standard_fen(board)
    for move in moves:
        board.push(chess.Move.from_uci(move))
        yield standard_fen(board)


def test_corners():
    from collections import Counter
    counts = Counter()
    for start, moves in CORNERS:
        for fen in _positions(start, moves):
            check(fen, counts)
    print(dict(counts))
    assert counts["decided"] > 0 and counts["castling"] > 0 and counts["promotion"] > 0


def test_rule_fixtures():
    from collections import Counter
    from pair_a_prep.fixtures import load_suite
    counts = Counter()
    for case in load_suite()["cases"]:
        for fen in _positions(case.get("initial_fen", case["fen"]), case.get("moves_uci", [])):
            check(fen, counts)
    print(dict(counts))


def _records(files, stride=1):
    from fow_shared.recording import read_records
    for path in sorted(glob.glob(f"{RECORDS}/part-*.jsonl"))[::stride][:files]:
        yield from read_records(path)


def _recorded_parents(limit, files=24, stride=10, seed=0):
    """Hypothesis boards of recorded turns (both players) and two random children of each, without repeats."""
    rng, seen = random.Random(seed), set()
    for record in _records(files, stride):
        for hypothesis in record.agent_input.belief.hypotheses:
            board = chess.Board(hypothesis.fen)
            fens = [hypothesis.fen]
            moves = fog_legal_moves(board)
            for move in rng.sample(moves, min(2, len(moves))):
                child = board.copy(stack=False)
                child.push(move)
                fens.append(standard_fen(child))
            for fen in fens:
                if fen not in seen:
                    seen.add(fen)
                    yield fen
                    if len(seen) >= limit:
                        return


@needs_records
def test_recorded_parents():
    from collections import Counter
    counts = Counter()
    for fen in _recorded_parents(4000):
        check(fen, counts)
    print(dict(counts))
    assert counts["parents"] >= 4000 and 0 < counts["black_to_move"] < counts["parents"]
    assert counts["decided"] > 0 and counts["castling"] > 0 and counts["en_passant_plane"] > 0


def _checkpoint_evaluators():
    return (BeliefNetworkEvaluator.from_checkpoint(CHECKPOINT, device="cpu", leaf_backend="python"),
            BeliefNetworkEvaluator.from_checkpoint(CHECKPOINT, device="cpu", leaf_backend="native"))


def _recording(ev):
    """Record every planes array the evaluator feeds the network."""
    fed, forward = [], ev._forward

    def record(planes, *args):
        fed.append(np.array(planes, dtype=np.float32))
        return forward(planes, *args)
    ev._forward = record
    return fed


@needs_records
@pytest.mark.skipif(not CHECKPOINT.exists(), reason="needs the belief-solver-v2-sf8-g237 checkpoint")
def test_evaluate_children_end_to_end():
    python, native = _checkpoint_evaluators()
    assert (python.leaf_backend, native.leaf_backend) == ("python", "native")
    fed_python, fed_native = _recording(python), _recording(native)
    parents = list(_recorded_parents(60, files=12, stride=19, seed=1))
    parents += [fen for start, moves in CORNERS for fen in _positions(start, moves)]
    largest = 0.0
    for fen in parents:
        expected, actual = python.evaluate_children(fen), native.evaluate_children(fen)
        assert list(actual) == list(expected), fen
        for move in expected:
            assert np.isfinite(actual[move]) and -1 <= actual[move] <= 1
            largest = max(largest, abs(actual[move] - expected[move]))
    assert len(fed_python) == len(fed_native) > 0
    for a, b in zip(fed_python, fed_native):
        assert np.array_equal(a, b)
    print("parents", len(parents), "network passes", len(fed_python), "largest difference", largest)
    assert largest <= 1e-6


def test_backend_selection(monkeypatch):
    net = BeliefNetwork(blocks=1, channels=8, embed=16)
    assert BeliefNetworkEvaluator(net, device="cpu", leaf_backend="python").leaf_backend == "python"
    assert BeliefNetworkEvaluator(net, device="cpu", leaf_backend="native").leaf_backend == "native"
    monkeypatch.setattr(BeliefNetworkEvaluator, "LEAF_BACKEND", "auto")
    assert BeliefNetworkEvaluator(net, device="cpu").leaf_backend == "native"
    monkeypatch.setattr(BeliefNetworkEvaluator, "LEAF_BACKEND", "python")
    assert BeliefNetworkEvaluator(net, device="cpu").leaf_backend == "python"
    with pytest.raises(ValueError):
        BeliefNetworkEvaluator(net, device="cpu", leaf_backend="fast")
    monkeypatch.setattr(belief_evaluator, "_leaf_kernel", lambda: None)
    assert BeliefNetworkEvaluator(net, device="cpu", leaf_backend="auto").leaf_backend == "python"
    with pytest.raises(RuntimeError):
        BeliefNetworkEvaluator(net, device="cpu", leaf_backend="native")
