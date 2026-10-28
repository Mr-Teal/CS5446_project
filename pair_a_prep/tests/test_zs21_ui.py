import json
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from threading import Thread
from time import sleep

import pytest

from pair_a_prep.zs21.ui import PlaySession, make_server


def test_player_and_spectator_capabilities_keep_payloads_separate():
    session = PlaySession(None, "human", "human")
    private = session.payload("white")
    assert len(private["boards"]) == 1
    assert private["boards"][0]["fen"] is None
    assert "e8" not in private["boards"][0]["pieces"]
    spectator = session.payload("spectator")
    assert [b["view"] for b in spectator["boards"]] == ["white", "full", "black"]
    assert spectator["boards"][1]["pieces"]["e8"] == "k"
    with pytest.raises(ValueError):
        session.submit("spectator", dict(revision=0, move="e2e4"))


def test_http_ignores_requested_full_view_with_player_token():
    session = PlaySession(None, "human", "human")
    server = make_server(session, 0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        token = next(k for k, v in session.tokens.items() if v == "white")
        base = f"http://127.0.0.1:{server.server_port}"
        data = json.load(urlopen(base + f"/api/state?token={token}&view=full"))
        assert len(data["boards"]) == 1
        assert data["boards"][0]["view"] == "white"
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/state?token=invalid")
        assert error.value.code == 403
        request = Request(base+f"/api/move?token={token}",
                          data=json.dumps(dict(revision=0, move="e2e4")).encode(),
                          headers={"Content-Type": "application/json"})
        assert json.load(urlopen(request))["accepted"]
        assert session.commands.get_nowait() == (0, "e2e4")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.)
