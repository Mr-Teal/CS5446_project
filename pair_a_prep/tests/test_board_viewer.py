"""Authoritative moves, private responses, replay branches and local HTTP API."""

import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from pair_a_prep.board_viewer import BoardSession, DEMOS, StaleRevision, make_server


def act(session, action, view="full", **payload):
    return session.mutate(action, {"view": view, "revision": session.revision, **payload})


def test_manual_moves_and_history_are_backed_by_the_rules_adapter():
    session = BoardSession()
    before = session.snapshot()
    assert len(before["legal_moves"]) == 20 and before["pieces"]["e2"] == "P"
    with pytest.raises(ValueError):
        act(session, "move", move="e2e5")
    assert session.snapshot() == before
    after = act(session, "move", move="e2e4")
    assert after["pieces"]["e4"] == "P" and after["pieces"]["e2"] is None
    assert after["side_to_move"] == "black" and after["last_move"] == "e2e4"
    assert before["pieces"]["e2"] == "P"


def test_fog_responses_hide_board_fen_opponent_moves_and_actions():
    session = BoardSession()
    black = session.snapshot("black")
    assert "e2" not in black["pieces"] and black["fen"] is None and not black["legal_moves"]
    act(session, "move", move="e2e4")
    black = session.snapshot("black")
    assert black["last_move"] is None and black["history"][0]["move"] is None
    assert session.snapshot("white")["last_move"] == "e2e4"
    with pytest.raises(ValueError):
        act(session, "move", view="white", move="e7e5")
    assert act(session, "move", view="black", move="e7e5")["ply"] == 2


def test_replay_and_branch_preserve_previous_states():
    session = BoardSession()
    act(session, "demo", demo="king_capture")
    old_end = session.states[-1]
    assert act(session, "navigate", index=5)["winner"] == "white"
    act(session, "navigate", index=0)
    branch = act(session, "move", move="d2d4")
    assert branch["total_plies"] == 1 and session.moves == ["d2d4"]
    assert session.rules.terminal(old_end).winner == "white"
    with pytest.raises(StaleRevision):
        session.mutate("reset", {"revision": 0})


@pytest.mark.parametrize("demo", list(DEMOS))
def test_all_sample_replays_are_legal(demo):
    session = BoardSession()
    beginning = act(session, "demo", demo=demo)
    assert beginning["cursor"] == 0
    ending = act(session, "navigate", index=len(DEMOS[demo]["moves"]))
    if demo == "repetition":
        assert ending["terminal"] and ending["reason"] == "threefold_repetition"
    if demo == "king_capture":
        assert ending["winner"] == "white" and not ending["legal_moves"]
    if demo == "en_passant":
        captured = act(session, "navigate", view="black", index=1)
        assert captured["captured_square"] == "f5"


def test_underpromotion_and_bad_custom_start_are_validated():
    session = BoardSession()
    act(session, "reset", fen=DEMOS["promotion"]["fen"])
    assert {"a7a8q", "a7a8r", "a7a8b", "a7a8n"} <= set(session.snapshot()["legal_moves"])
    assert act(session, "move", move="a7a8n")["pieces"]["a8"] == "N"
    before = session.snapshot()
    with pytest.raises(ValueError):
        act(session, "reset", fen="not a FEN")
    assert session.snapshot() == before


def test_http_frontend_and_api_without_engine_or_neural_dependencies():
    server = make_server(0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:" + str(server.server_port)
    try:
        with urlopen(base + "/") as response:
            assert b'id="board"' in response.read()
        for asset in ("/app.js", "/style.css"):
            with urlopen(base + asset) as response:
                assert response.status == 200
        with urlopen(base + "/api/state?view=white") as response:
            state = json.load(response)
        request = Request(base + "/api/move", data=json.dumps({
            "move": "e2e4", "view": "white", "revision": state["revision"]}).encode(),
            headers={"Content-Type": "application/json"})
        with urlopen(request) as response:
            assert json.load(response)["side_to_move"] == "black"
        with pytest.raises(HTTPError) as exc:
            urlopen(request)
        assert exc.value.code == 409
        with pytest.raises(HTTPError) as exc:
            urlopen(Request(base + "/api/reset", data=b'[]'))
        assert exc.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
