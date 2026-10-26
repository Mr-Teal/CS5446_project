import ctypes as C
from dataclasses import asdict
from random import Random
from time import perf_counter

import chess
import pytest

from pair_a_prep.zs21.model import SearchRules, Referee, PositionTracker, position_key, BudgetError, view_signature
from pair_a_prep.zs21.native_tracker import NativeTracker, FastRules, library, pack, unpack, Packed, encode, decode


@pytest.mark.parametrize("fen", [chess.STARTING_FEN,
    "4r1k1/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
    "4k3/8/8/8/2b5/8/8/R3K2R w KQ - 0 1",
    "7k/P7/8/8/8/8/7p/K7 w - - 0 1",
    "8/8/8/8/8/4k3/4K3/8 w - - 0 1"])
def test_native_move_observation_and_transition_oracle(fen):
    dll, rules, rng = library(), SearchRules(), Random(103)
    fast = FastRules(dll)
    state = rules.initial_state(fen)
    for step in range(100):
        if rules.terminal(state):
            state = rules.initial_state()
        value = pack(state._board)
        fen = C.create_string_buffer(160)
        expected_fen = state._board.copy(stack=False)
        expected_fen.halfmove_clock, expected_fen.fullmove_number = step + 100, step + 70
        assert dll.zs_fen(C.byref(value), step + 100, step + 70, fen, len(fen)) > 0
        assert fen.value.decode("ascii") == expected_fen.fen(en_passant="fen")
        output = (C.c_int*512)()
        count = dll.zs_moves(C.byref(value), output)
        actions = tuple(sorted(decode(a) for a in output[:count]))
        assert actions == rules.legal_moves(state)
        for player in ("white", "black"):
            visible = dll.zs_visible(C.byref(value), int(player=="white"))
            assert tuple(sorted(chess.square_name(s) for s in chess.scan_forward(visible))) == rules.visible_squares(state, player)
            assert asdict(fast.observe(state, player)) == asdict(rules.observe(state, player))
            assert fast.observe_signature(state, player) == view_signature(rules.observe(state, player))
        for action in actions if step % 10 == 0 else rng.sample(actions, min(3,len(actions))):
            native, captured = Packed(), C.c_int()
            dll.zs_play(C.byref(value), encode(action), C.byref(native), C.byref(captured))
            expected = rules.apply_move(state, action)
            assert position_key(unpack(native)) == position_key(expected._board), (fen, state.fen, action)
        if not actions:
            break
        state = rules.apply_move(state, rng.choice(actions))


def test_native_full_population_equals_python_reference_and_replays_histories():
    ref = Referee()
    python = PositionTracker("black", 3)
    native = NativeTracker("black", 3)
    try:
        for action in (None, "e2e4", "d7d5", "e4d5", "g8f6", "g1f3", "f6d5"):
            mover = ref.current_player()
            if action:
                ref.apply(action)
            view = ref.observe("black")
            own = action if mover == "black" else None
            python.update(view, own)
            native.update(view, own)
            expected = {position_key(c.state._board) for c in python.candidates}
            actual = {position_key(c.state._board) for c in native.candidates}
            assert actual == expected
            for candidate in native.candidates:
                replay = SearchRules().initial_state()
                for move in candidate.moves:
                    replay = SearchRules().apply_move(replay, move)
                assert position_key(replay._board) == position_key(candidate.state._board)
        before = [position_key(c.state._board) for c in native.candidates]
        ref.apply("f1b5")
        with pytest.raises(BudgetError):
            native.update(ref.observe("black"), deadline=perf_counter()-1)
        assert before == [position_key(c.state._board) for c in native.candidates]
    finally:
        native.close()


def test_native_deadline_preserves_histories_indices_and_rng():
    trackers = [NativeTracker("black", 93) for _ in range(2)]
    ref = Referee()
    dll = trackers[0].dll
    dll.zs_same_state.argtypes = [C.c_void_p, C.c_void_p]
    dll.zs_same_state.restype = C.c_int
    try:
        for action in (None, "e2e4", "d7d5", "e4d5", "g8f6"):
            mover = ref.current_player()
            if action:
                ref.apply(action)
            for tracker in trackers:
                tracker.update(ref.observe("black"), action if mover == "black" else None)
        assert dll.zs_same_state(*(t.handle for t in trackers))
        ref.apply("g1f3")
        with pytest.raises(BudgetError):
            trackers[0].update(ref.observe("black"), deadline=perf_counter()-1)
        assert dll.zs_same_state(*(t.handle for t in trackers))
    finally:
        for tracker in trackers:
            tracker.close()
