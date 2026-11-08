"""End-to-end smoke of Pair A's bot inside Fog Lab, driven over the app's HTTP API from the same container.

Expects the server on 127.0.0.1:8765 (started by the caller). Starts a game with the Pair A bot as White (human =
black), so the bot moves first; plays two legal human moves and reads each reply. Asserts on the state the page
receives: ply count, move list, no error, the bot panel's chosen move and belief. Exit non-zero on failure.
"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8765"


def api(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method="GET" if body is None else "POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{path} -> HTTP {e.code}: {e.read().decode(errors='replace')[:400]}")


def summary(state, label):
    bot = state.get("bot") or {}
    exp = bot.get("explanation") or {}
    print(f"[{label}] ply={state['ply']} to_move={state['to_move']} over={state['over']} error={state['error']} "
          f"tracker_error={state['tracker_error']} moves={state['moves']} legal={len((state.get('you') or {}).get('legal_moves') or [])}")
    print(f"        bot keys={sorted(bot)} | belief={len(bot.get('belief') or [])} population={bot.get('population_size')}"
          f" | chosen={exp.get('chosen')} app_inspection={exp.get('app_inspection')} exp_error={exp.get('error')}"
          f" | policy moves={len(exp.get('policy') or {})} | bot_name={state.get('bot_name')}")
    return bot, exp


for _ in range(30):
    try:
        cfg = api("/api/config")
        break
    except Exception as e:  # noqa: BLE001
        err = e
        time.sleep(1)
else:
    raise SystemExit(f"server did not come up: {err}")
print("rules:", cfg["rules"]["name"], "| bots:", [(b["id"], b["available"]) for b in cfg["bots"]])

scorer = sys.argv[1] if len(sys.argv) > 1 else "material"
t = time.time()
game = api("/api/games", {"human": "black", "bot": "pair-a-subgame", "scorer": scorer, "guesses": 8, "seed": 1,
                          "fair": False})
print(f"new game ({scorer}): {time.time() - t:.1f} s")
state = game["state"]
bot, exp = summary(state, "after bot's first move")
assert state["ply"] == 1 and len(state["moves"]) == 1 and state["error"] is None, "bot did not open the game"
assert exp.get("chosen") == state["moves"][-1]["move"], "panel's chosen move differs from the move played"
assert len(bot.get("belief") or []) >= 1 and exp.get("app_inspection") is True, "panel data missing"

timings = []
for n in range(2):
    legal = (state.get("you") or {}).get("legal_moves") or []
    assert legal, f"no legal moves for the human: you={str(state.get('you'))[:300]}"
    move = legal[0]
    t = time.time()
    state = api(f"/api/games/{game['id']}/move", {"move": move})
    timings.append(time.time() - t)
    bot, exp = summary(state, f"after human {move} and reply, {timings[-1]:.1f} s")
    if state["over"]:
        break
    assert state["error"] is None and state["tracker_error"] is None, "bot or tracker failed"
    assert state["ply"] == 3 + 2 * n and len(state["moves"]) == state["ply"], "ply count off"
    assert exp.get("chosen") == state["moves"][-1]["move"], "panel's chosen move differs from the move played"
    assert 0 < len(bot.get("belief") or []) <= 8, "belief hypotheses out of range"
print(f"reply times: {[f'{x:.1f}' for x in timings]} s (budget cap 5 s plus tracker and inspection)")
assert max(timings) < 15, "too slow"
print("SMOKE OK")
