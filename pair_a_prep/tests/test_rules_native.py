"""The native rules backend (rules_kernel.cpp) must reproduce the Python RulesAdapter exactly.

Every comparison runs the Python adapter and the native one side by side on states made by each: the legal move
list (set and order), observe() for both players (every field, visible_pieces in order), the observation key,
terminal(), the successor's FEN, side to move, ply and capture notice, and finally the replayed python-chess board.
Positions: the rule fixtures, hand-made rule corner cases, and the recorded games (every hypothesis path from ply
zero, and every fog-legal child of its end position). The subgame trees of recorded turns are built and grown
under both backends and compared node by node. Skipped when the kernel is not built.
"""
import glob
import os

import chess
import pytest

from pair_a_prep import _rules_native
from pair_a_prep.chess_search import build_chess_tree, expand_chess_tree, observation_key
from pair_a_prep.rules_adapter import RulesAdapter, RuleState

pytestmark = pytest.mark.skipif(_rules_native.library() is None,
                                reason="native rules kernel not built (python -m pair_a_prep.build_rules_kernel)")

PY = RulesAdapter(backend="python")
NA = RulesAdapter(backend="native") if _rules_native.library() is not None else None
PLAYERS = ("white", "black")
RECORDS = os.environ.get("FOW_TEST_RECORDS") or next(
    (p for p in ("/labels/solver-v2-sf8-g237", "/labels/solver-v2-sf8") if os.path.isdir(p)), "")


def _same(python: RuleState, native: RuleState, counts=None) -> None:
    """Every RulesAdapter answer agrees; the native state is never turned into a python-chess board."""
    assert native.fen == python.fen
    assert (native.ply, native.captured_player, native.captured_square) == (
        python.ply, python.captured_player, python.captured_square)
    assert NA.current_player(native) == PY.current_player(python)
    ended = PY.terminal(python)
    assert NA.terminal(native) == ended
    moves = PY.legal_moves(python)
    assert NA.legal_moves(native) == moves
    for player in PLAYERS:
        expected = PY.observe(python, player)
        actual = NA.observe(native, player)
        assert actual == expected, (python.fen, player)
        assert list(actual.visible_pieces.items()) == list(expected.visible_pieces.items())
        assert NA.visible_squares(native, player) == PY.visible_squares(python, player)
        assert NA.observation_key(native, player) == observation_key(expected) == PY.observation_key(python, player)
    if "_native" in native.__dict__ and native.__dict__["_native"].parent is not None:
        assert "_board" not in native.__dict__
    if counts is not None:
        counts["states"] += 1
        if ended is not None:
            counts[ended.reason] += 1
        counts["castling"] += sum(m in ("e1g1", "e1c1", "e8g8", "e8c8") for m in moves)
        counts["promotion"] += sum(len(m) == 5 for m in moves)


def _same_children(python, native, counts=None):
    board = python.board_copy()
    for move in PY.legal_moves(python):
        child_python, child_native = PY.apply_move(python, move), NA.apply_move(native, move)
        _same(child_python, child_native, counts)
        if counts is not None:
            counts["en_passant"] += board.is_en_passant(chess.Move.from_uci(move))
    with pytest.raises(ValueError):
        NA.apply_move(native, "a1a1")


def _replay(start, moves, counts=None):
    python, native = PY.initial_state(start), NA.initial_state(start)
    _same(python, native, counts)
    for move in moves:
        python, native = PY.apply_move(python, move), NA.apply_move(native, move)
        _same(python, native, counts)
    # The board built on demand equals the Python one, history included.
    board = native.board_copy()
    assert board.move_stack == python.board_copy().move_stack
    assert board.fen(en_passant="fen") == python.fen
    return python, native


def test_backend_selection(monkeypatch):
    assert RulesAdapter(backend="python").backend == "python"
    assert RulesAdapter(backend="native").backend == "native"
    monkeypatch.setattr(RulesAdapter, "BACKEND", "auto")
    assert RulesAdapter().backend == "native"

    class Custom(RulesAdapter):
        pass
    assert Custom().backend == "python"  # a subclass may override single rules
    monkeypatch.setattr(_rules_native, "library", lambda: None)
    assert RulesAdapter().backend == "python"
    with pytest.raises(RuntimeError):
        RulesAdapter(backend="native")
    with pytest.raises(ValueError):
        RulesAdapter(backend="fast")


def test_rule_fixtures():
    from pair_a_prep.fixtures import load_suite
    for case in load_suite()["cases"]:
        python, native = _replay(case.get("initial_fen", case["fen"]), case.get("moves_uci", []))
        _same_children(python, native)


CORNERS = [
    # repetition, by the knights, then a mixed chain: Python states continue natively
    (None, ["g1f3", "g8f6", "f3g1", "f6g8"] * 2),
    # en passant both ways, including a capture that only fog rules allow and an unused right
    ("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1", ["e2e4"]),
    ("4k3/3p4/8/4P3/8/8/8/4K3 b - - 0 1", ["d7d5", "e5d6"]),
    ("8/8/8/8/3p4/8/4P3/4K2k w - - 0 1", ["e2e4", "d4e3"]),
    ("k7/8/8/r2pP2K/8/8/8/8 w - d6 0 2", ["e5d6"]),
    # castling into, out of and through attacks; rights lost by rook capture and by a king move
    ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", ["e1g1", "e8c8"]),
    ("r3k2r/8/8/8/8/5q2/8/R3K2R w KQkq - 0 1", ["e1c1"]),
    ("r3k2r/8/8/8/8/8/6q1/R3K2R w KQkq - 0 1", ["a1a8", "e8g8"]),
    ("r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1", ["e8e7", "e1e2"]),
    # castling rights the FEN states but the position does not support (no stack: python-chess cleans them)
    ("4k3/8/8/8/8/8/8/4K3 w KQkq - 0 1", ["e1e2"]),
    ("r3k2r/8/8/8/8/8/8/1R2K1R1 w KQkq - 0 1", []),
    # promotions, with and without capture, and a promoted piece moving on
    ("1n2k3/P7/8/8/8/8/7p/4K3 w - - 0 1", ["a7b8q", "h2h1n", "b8b7", "h1g3"]),
    # king captures: by either side, on the back rank with castling rights, and the views after it
    ("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1", ["e2e8"]),
    ("r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1", ["a8a1", "e1d1", "a1d1"]),
    # fifty-move rule and its boundary
    ("4k3/8/8/8/8/8/8/4K2R w - - 98 60", ["h1h2", "e8e7"]),
    # no fog-legal move (the #17 draw), reached by a move and as a start; fog moves out of orthodox mate
    ("7k/8/8/8/1pp5/pP6/PRP5/KB6 b - - 0 1", ["c4c3"]),
    ("7k/8/8/8/1p6/pPp5/PRP5/KB6 w - - 0 1", []),
    ("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1", []),
    ("8/8/8/8/8/4k3/4q3/4K2R w K - 0 1", []),
    # a king missing from the start position
    ("8/8/8/8/8/8/4P3/4K3 w - - 0 1", []),
]


@pytest.mark.parametrize("start,moves", CORNERS)
def test_rule_corners(start, moves):
    python, native = _replay(start, moves)
    _same_children(python, native)


def test_mixed_histories_repetition():
    """Native successors of a Python state see its history (repetition), and the other way round."""
    python = PY.initial_state()
    for move in ["g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6"]:
        python = PY.apply_move(python, move)
    native = python
    for move in ["f3g1", "f6g8"]:
        python, native = PY.apply_move(python, move), NA.apply_move(native, move)
        _same(python, native)
    assert NA.terminal(native).reason == "threefold_repetition"
    back = PY.apply_move(NA.apply_move(PY.initial_state(), "g1f3"), "g8f6")
    assert back.board_copy().move_stack == [chess.Move.from_uci("g1f3"), chess.Move.from_uci("g8f6")]
    # A FEN restart has no history, in either backend.
    assert NA.terminal(NA.initial_state(native.fen)) is None


def _records(files, stride=1):
    from fow_shared.recording import read_records
    for path in sorted(glob.glob(f"{RECORDS}/part-*.jsonl"))[::stride][:files]:
        yield from read_records(path)


@pytest.mark.skipif(not RECORDS or not glob.glob(f"{RECORDS}/part-*.jsonl"), reason="set FOW_TEST_RECORDS to a label folder")
def test_recorded_paths_and_children():
    """Every state on the hypotheses' paths, every child of their ends, and the grandchildren of some."""
    from collections import Counter
    counts = Counter()
    seen, ends, records = set(), 0, 0
    for record in _records(24, stride=10):
        for hypothesis in record.agent_input.belief.hypotheses[:4]:
            path = tuple(hypothesis.candidate_moves)
            python, native = PY.initial_state(), NA.initial_state()
            for ply, move in enumerate(path):
                python, native = PY.apply_move(python, move), NA.apply_move(native, move)
                if path[:ply + 1] not in seen:
                    seen.add(path[:ply + 1])
                    _same(python, native, counts)
            assert native.fen == python.fen == hypothesis.fen
            if (python.fen, path[-4:]) in seen:
                continue
            seen.add((python.fen, path[-4:]))
            ends += 1
            _same_children(python, native, counts)
            if ends % 4 == 0:
                for move in PY.legal_moves(python)[::3]:
                    _same_children(PY.apply_move(python, move), NA.apply_move(native, move), counts)
        records += 1
        if counts["states"] >= 60000:
            break
    print(dict(counts), "ends", ends, "records", records)
    assert counts["states"] >= 20000
    # Promotions are rare in the recorded openings; the fixtures and CORNERS cover them.
    for case in ("king_capture", "castling", "en_passant"):
        assert counts[case] > 0, case


def _same_tree(a, b, path=()):
    assert (a.player, a.infoset, a.payoff) == (b.player, b.infoset, b.payoff), path
    assert list(a.children) == list(b.children), path
    assert a.probabilities == b.probabilities, path
    for action in a.children:
        _same_tree(a.children[action], b.children[action], path + (action,))


def _same_chess_trees(a, b):
    _same_tree(a.root, b.root)
    assert (a.root_infoset, a.nodes, a.frontier_leaves, a.terminal_leaves, a.evaluator_calls, a.viewer) == (
        b.root_infoset, b.nodes, b.frontier_leaves, b.terminal_leaves, b.evaluator_calls, b.viewer)
    assert list(a.frontiers) == list(b.frontiers)
    for key in a.frontiers:
        x, y = a.frontiers[key], b.frontiers[key]
        assert x.memories == y.memories and x.state.fen == y.state.fen and x.state.ply == y.state.ply
        assert (x.state.captured_player, x.state.captured_square) == (y.state.captured_player, y.state.captured_square)
    for x, y in zip(a.history_roots, b.history_roots):
        assert x.memories == y.memories and x.state.fen == y.state.fen


@pytest.mark.skipif(not RECORDS or not glob.glob(f"{RECORDS}/part-*.jsonl"), reason="set FOW_TEST_RECORDS to a label folder")
def test_subgame_trees_agree_through_growth(monkeypatch):
    from pair_a_prep.pcfr import PCFRPlus
    from pairb.material import MaterialEvaluator

    leaf = MaterialEvaluator()
    checked = nodes = 0
    for record in _records(30, stride=8):
        turn = record.agent_input
        if turn.observation.ply < 4 or len(turn.belief.hypotheses) < 4 or checked >= 6:
            continue
        trees = {}
        for backend in ("python", "native"):
            monkeypatch.setattr(RulesAdapter, "BACKEND", backend)
            tree = build_chess_tree(turn, leaf, depth=2 if checked % 2 else 1, max_nodes=200000)
            solver = PCFRPlus(tree.root, schedule="alternating", backend="python")
            for _ in range(3):  # grow selected frontiers, as the growth loop does
                if not tree.frontiers:
                    break
                solver.step()
                selected = tuple(sorted(tree.frontiers)[::7][:6])
                tree = expand_chess_tree(tree, solver, leaf, max_nodes=200000, selected_paths=selected,
                                         initialize_best=True)
            trees[backend] = tree
        _same_chess_trees(trees["python"], trees["native"])
        checked += 1
        nodes += trees["python"].nodes
    print("trees", checked, "nodes", nodes)
    assert checked >= 6
