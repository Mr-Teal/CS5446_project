from dataclasses import asdict, replace
import gzip
import json
from time import perf_counter

import chess
import pytest

from pair_a_prep.zs21.agent import PaperAgent, nodes_below
from pair_a_prep.zs21.config import default_path, load
from pair_a_prep.zs21.engine import EnginePool, Estimate
from pair_a_prep.zs21.model import Referee, RefereeRules, SearchRules, PositionTracker, view_signature
from pair_a_prep.zs21.native_tracker import NativeTracker, FastRules, library
from pair_a_prep.zs21.rule_profile import RULES_ID, LEGACY_RULES_ID
from pair_a_prep.zs21 import match, replay
from pair_a_prep.zs21 import native_tracker
from pair_a_prep.zs21.ui import PlaySession


BLOCKED = "7k/8/8/8/1p6/pPp5/PRP5/KB6 w - - 0 1"
BEFORE = "7k/8/8/8/1pp5/pP6/PRP5/KB6 b - - 0 1"


def position(fen, mirror):
    board = chess.Board(fen)
    return board.mirror() if mirror else board


def finish_move(mirror):
    return "c5c6" if mirror else "c4c3"


def close(tracker):
    if hasattr(tracker, "close"):
        tracker.close()


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("backend", ["referee", "python", "native"])
def test_blocked_is_draw_in_both_private_views(backend, mirror):
    rules = {"referee": RefereeRules, "python": SearchRules,
             "native": lambda: FastRules(library())}[backend]()
    fen = position(BLOCKED, mirror).fen()
    state = rules.initial_state(fen)
    assert rules.terminal(state).winner == "draw"
    assert rules.terminal(state).reason == "no_legal_moves"
    assert rules.legal_moves(state) == ()
    oracle = Referee(fen)
    for player in ("white", "black"):
        view = rules.observe(state, player)
        assert view.terminal and view.outcome == 0.0 and not view.legal_moves
        assert view.halfmove_clock is None
        assert asdict(view) == asdict(oracle.observe(player))
        if backend == "native":
            assert rules.observe_signature(state, player) == view_signature(view)


@pytest.mark.parametrize("mirror", [False, True])
def test_capture_and_history_draws_keep_precedence(mirror):
    board = position(BLOCKED, mirror)
    board.halfmove_clock = 100
    ref = Referee(board.fen())
    assert ref._rules.terminal(ref._state).reason == "fifty_move"
    board.remove_piece_at(board.king(not board.turn))
    ref = Referee(board.fen())
    assert ref._rules.terminal(ref._state).reason == "king_capture"
    assert ref.winner() == ("white" if board.turn else "black")
    ref = Referee()
    for move in ("g1f3", "g8f6", "f3g1", "f6g8") * 2:
        ref.apply(move)
    assert ref._rules.terminal(ref._state).reason == "threefold_repetition"
    assert SearchRules().terminal(ref._state) is None
    state = SearchRules().initial_state(chess.STARTING_FEN.replace("0 1", "100 1"))
    assert SearchRules().terminal(state) is None


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("fen", [
    "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",
    "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
    "8/8/8/8/8/4k3/4q3/4K2R w K - 0 1",
    "4r1k1/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
])
def test_orthodox_mate_stalemate_castling_and_ep_remain_fow_moves(fen, mirror):
    board = position(fen, mirror)
    state = SearchRules().initial_state(board.fen(en_passant="fen"))
    expected = SearchRules().legal_moves(state)
    assert expected
    for rules in (SearchRules(), RefereeRules(), FastRules(library())):
        assert rules.terminal(state) is None
        assert rules.legal_moves(state) == expected


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("player", ["white", "black"])
@pytest.mark.parametrize("scale", [1., 6.])
def test_terminal_draw_bypasses_stockfish_in_both_value_scales(mirror, player, scale):
    class ForbiddenEngine:
        def analyse(self, *args, **kwargs):
            raise AssertionError("a terminal draw must not reach Stockfish")
    result = EnginePool._one(ForbiddenEngine(), position(BLOCKED, mirror), player, 1, None, scale)
    assert result.value == 0.0 and result.depth == 0
    assert result.source == "no_legal_moves_terminal"


class PreferDraw:
    def __init__(self):
        self.queries = 0

    def evaluate(self, boards, player, *, depth, deadline, scale):
        for board in boards:
            state = SearchRules().initial_state(board.fen(en_passant="fen"))
            assert SearchRules().terminal(state) is None
        self.queries += len(boards)
        return tuple(Estimate(-.6 * scale, "draw_regression", depth) for _ in boards)


@pytest.mark.parametrize("backend", ["python", "native"])
@pytest.mark.parametrize("baseline", [False, True])
@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("scale", [1., 6.])
def test_agent_selects_draw_and_never_expands_or_evaluates_it(backend, baseline, mirror, scale):
    fen = position(BEFORE, mirror).fen()
    ref, pool = Referee(fen), PreferDraw()
    player = ref.current_player()
    agent = PaperAgent(player, 281, pool, initial_fen=fen, baseline=baseline,
                       max_rounds=1, tracker_backend=backend, scale=scale)
    try:
        agent.observe(ref.observe(player))
        decision = agent.act(perf_counter() + 20)
        decision.validate_for(ref.observe(player))
        assert decision.move == finish_move(mirror)
        assert pool.queries > 0
        leaf = agent.gadget.roots[0].children[decision.move]
        assert leaf.base == leaf.payoff == 0.0 and leaf.sf_depth == 0
        assert not leaf.cutoff and not leaf.children
        for node in nodes_below(agent.gadget.roots):
            ended = agent.rules.terminal(node.state)
            if ended is not None and ended.winner == "draw":
                assert node.base == node.payoff == 0.0 and not node.children and not node.cutoff
        ref.apply(decision.move)
        agent.observe(ref.observe(player), decision.move)
        assert agent.tracker.previous.terminal
        with pytest.raises(ValueError, match="not an active own turn"):
            agent.act(perf_counter() + 20)
    finally:
        agent.close()


@pytest.mark.parametrize("tracker_type", [PositionTracker, NativeTracker])
@pytest.mark.parametrize("player", ["white", "black"])
@pytest.mark.parametrize("mirror", [False, True])
def test_terminal_notification_updates_both_players_without_another_decision(tracker_type, player, mirror):
    fen = position(BEFORE, mirror).fen()
    ref, tracker = Referee(fen), tracker_type(player, 28, fen)
    try:
        tracker.update(ref.observe(player))
        old_memory = tracker.memory
        mover = ref.current_player()
        ref.apply(finish_move(mirror))
        tracker.update(ref.observe(player), finish_move(mirror) if player == mover else None)
        assert tracker.previous.ply == 1 and tracker.previous.terminal
        assert tracker.previous.outcome == 0.0 and tracker.memory != old_memory
    finally:
        close(tracker)


@pytest.mark.parametrize("tracker_type", [PositionTracker, NativeTracker])
@pytest.mark.parametrize("player", ["white", "black"])
@pytest.mark.parametrize("mirror", [False, True])
def test_terminal_hypothesis_cannot_match_a_nonterminal_observation(tracker_type, player, mirror):
    fen = position(BLOCKED, mirror).fen()
    tracker, ref = tracker_type(player, 28, fen), Referee(fen)
    try:
        forged = replace(ref.observe(player), terminal=False, outcome=None)
        with pytest.raises(ValueError, match="empty full information set|initial observation mismatch"):
            tracker.update(forged)
        assert tracker.previous is None and tracker.memory == ""
    finally:
        close(tracker)


@pytest.mark.parametrize("tracker_type", [PositionTracker, NativeTracker])
@pytest.mark.parametrize("mirror", [False, True])
def test_off_turn_inference_rejects_blocked_successor_atomically(tracker_type, mirror):
    fen = position(BEFORE, mirror).fen()
    ref = Referee(fen)
    player = ref.current_player()
    tracker = tracker_type(player, 28, fen)
    try:
        tracker.update(ref.observe(player))
        previous, memory = tracker.previous, tracker.memory
        ref.apply(finish_move(mirror))
        forged = replace(ref.observe(player), terminal=False, outcome=None)
        with pytest.raises(ValueError, match="empty full information set"):
            tracker.update(forged, finish_move(mirror))
        assert tracker.previous is previous and tracker.memory == memory
        assert len(tracker.candidates) == 1
        tracker.update(ref.observe(player), finish_move(mirror))
        assert tracker.previous.terminal
    finally:
        close(tracker)


@pytest.mark.parametrize("tracker_type", [PositionTracker, NativeTracker])
@pytest.mark.parametrize("mirror", [False, True])
def test_off_turn_zero_moves_does_not_end_game(tracker_type, mirror):
    board = position(BLOCKED, mirror)
    player = "white" if board.turn else "black"
    board.turn = not board.turn
    ref, tracker = Referee(board.fen()), tracker_type(player, 28, board.fen())
    try:
        view = ref.observe(player)
        assert not view.terminal and not view.legal_moves and not ref.is_terminal()
        tracker.update(view)
        assert len(tracker.candidates) == 1
    finally:
        close(tracker)


def test_rule_version_and_configuration_prevent_silent_old_rule_reuse(tmp_path):
    assert library().zs_rules_id().decode() == RULES_ID
    assert load()["data"]["rules"]["profile"] == RULES_ID
    config = tmp_path / "runtime.toml"
    config.write_text(default_path().read_text().replace(RULES_ID, LEGACY_RULES_ID), encoding="utf-8")
    with pytest.raises(ValueError, match="rules.profile"):
        load(config)


@pytest.mark.parametrize("missing_id", [False, True])
def test_stale_native_library_requires_rebuild(monkeypatch, missing_id):
    class OldLibrary:
        @staticmethod
        def zs_rules_id():
            return LEGACY_RULES_ID.encode("ascii")
    monkeypatch.setattr(native_tracker.C, "CDLL", lambda _: object() if missing_id else OldLibrary())
    with pytest.raises(RuntimeError, match="outdated native inference library|rule version does not match"):
        library()


def test_replay_rejects_a_versioned_archive_without_rule_metadata(tmp_path):
    config = dict(source={"pair_a_prep/zs21/rule_profile.py": "unused"})
    (tmp_path / "manifest.json").write_text(json.dumps(dict(config=config)), encoding="utf-8")
    with pytest.raises(ValueError, match="missing its rules_id"):
        replay.validate(tmp_path)


def test_match_runner_records_genuine_zero_ply_draw(monkeypatch, tmp_path):
    monkeypatch.setattr(match, "Referee", lambda: Referee(BLOCKED))
    pool = PreferDraw()
    path = tmp_path / "game-000.jsonl.gz"
    result = match.play_game(pool, game=0, seed=28, paper_color="white", seconds=16,
                             path=path, agent_kwargs=dict(initial_fen=BLOCKED))
    assert result["status"] == "completed" and result["reason"] == "no_legal_moves"
    assert result["winner"] == result["paper_result"] == "draw" and result["plies"] == 0
    assert result["rules_id"] == RULES_ID and pool.queries == 0
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream]
    assert [r["event"] for r in records] == ["start", "position", "finish"]


@pytest.mark.parametrize("current", [False, True])
def test_replay_uses_recorded_rule_version(monkeypatch, tmp_path, current):
    ref = Referee(BLOCKED, no_move_draw=current)
    monkeypatch.setattr(replay, "Referee", lambda **kwargs: Referee(BLOCKED, **kwargs))
    result = dict(game=0, seed=28, paper_color="white", seconds_per_move=16., plies=0,
                  status="completed" if current else "failed")
    config = dict(source={})
    if current:
        config["rules_id"] = result["rules_id"] = RULES_ID
        result.update(winner="draw", paper_result="draw", reason="no_legal_moves")
    else:
        result.update(error_type="BoundaryError", error="legacy no-move policy")
    rows = [dict(event="start", **{**result, "status": "running"}),
            dict(event="position", ply=0, fen=ref._state.fen,
                 observations={p: asdict(ref.observe(p)) for p in ("white", "black")}),
            dict(event="finish", **result)]
    (tmp_path / "manifest.json").write_text(json.dumps(dict(config=config)), encoding="utf-8")
    (tmp_path / "summary.json").write_text(json.dumps(match.summarize([result])), encoding="utf-8")
    with gzip.open(tmp_path / "game-000.jsonl.gz", "wt", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    report = replay.validate(tmp_path)
    assert report["rules_id"] == (RULES_ID if current else LEGACY_RULES_ID)
    assert report["completed"] == int(current) and report["failed"] == int(not current)
    config["rules_id"] = "unknown-rules"
    (tmp_path / "manifest.json").write_text(json.dumps(dict(config=config)), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported recorded rule version"):
        replay.validate(tmp_path)


def test_human_and_spectator_views_finish_without_another_move():
    session = PlaySession(None, "human", "human")
    before = session.rules.initial_state(BEFORE)
    session.states = [before, session.rules.apply_move(before, "c4c3")]
    session.moves, session.cursor = ["c4c3"], 1
    for role in ("white", "black", "spectator"):
        payload = session.payload(role)
        assert payload["rules_id"] == RULES_ID and not payload["can_move"]
        for board in payload["boards"]:
            assert board["terminal"] and board["winner"] == "draw"
            assert board["reason"] == "no_legal_moves" and not board["legal_moves"]
            if board["view"] != "full":
                assert board["fen"] is None
    session.run()
    assert session.error is None and session.thinking is None
