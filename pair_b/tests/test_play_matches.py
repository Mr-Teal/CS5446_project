"""scripts/play_matches.py: bot-against-bot fog-of-war games, each bot on its own tracker."""
import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("play_matches", ROOT / "scripts" / "play_matches.py")
play_matches = importlib.util.module_from_spec(spec)
spec.loader.exec_module(play_matches)


def play(out, *extra):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "play_matches.py"), "--a", "material", "--b", "material",
                           "--max-plies", "20", "--seed", "0", "--out", str(out), *map(str, extra)],
                          capture_output=True, text=True)


@pytest.fixture(scope="module")
def two_games(tmp_path_factory):
    out = tmp_path_factory.mktemp("matches") / "material"
    result = play(out, "--games", "2")
    assert result.returncode == 0, result.stderr
    games = [json.loads(line) for line in (out / "games.jsonl").read_text().splitlines()]
    return games, json.loads((out / "summary.json").read_text())


# Catches: a match that loses a game, plays one side as one colour only, reports a score that its
# own interval does not cover, or a value lost that is negative or not a number.
def test_two_games_give_two_records_and_a_summary_with_both_colours(two_games):
    games, summary = two_games
    assert len(games) == 2 and summary["games"] == 2 and summary["openings"] == 1
    assert sorted(g["colours"]["white"] for g in games) == ["a", "b"]
    a, b = summary["sides"]["a"], summary["sides"]["b"]
    assert a["wins"] + a["draws"] + a["losses"] == 2 and (a["wins"], a["draws"]) == (b["losses"], b["draws"])
    score = summary["score_a"]
    assert score["mean"] == (a["wins"] + 0.5 * a["draws"]) / 2
    assert score["ci95"][0] <= score["mean"] <= score["ci95"][1]
    chosen = [m for g in games for m in g["moves"] if not m["opening"]]
    assert chosen and all(math.isfinite(m["value_lost"]) and m["value_lost"] >= 0 for m in chosen)
    assert all(m["value_lost"] == m["best"] - m["played"] for m in chosen)
    for side in (a, b):
        assert math.isfinite(side["value_lost_mean"]) and side["value_lost_mean"] >= 0 and side["moves"] > 0
    assert all(len(g["moves"]) == g["plies"] <= 20 for g in games)


# Catches: the two games of an opening starting from different moves, or with the colours not
# swapped, which would leave the first move's advantage in the score.
def test_the_two_games_of_an_opening_play_the_same_moves_with_colours_swapped(two_games):
    first, second = two_games[0]
    assert first["opening"]["id"] == second["opening"]["id"] == 0
    assert first["opening"]["moves"] == second["opening"]["moves"]
    assert 2 <= len(first["opening"]["moves"]) <= 8
    assert first["colours"] == {"white": second["colours"]["black"], "black": second["colours"]["white"]}
    for game in (first, second):
        k = len(game["opening"]["moves"])
        assert [m["move"] for m in game["moves"][:k]] == game["opening"]["moves"]
        assert [m["opening"] for m in game["moves"]] == [i < k for i in range(game["plies"])]


# Catches: each bot's tracker state not recorded with its moves, or missing for some ply.
def test_each_move_carries_the_tracker_state_its_belief_came_from(two_games):
    for game in two_games[0]:
        for colour in ("white", "black"):
            assert [u["ply"] for u in game["trackers"][colour]] == list(range(game["plies"] + 1))
        for move in game["moves"]:
            assert move["tracker"] == game["trackers"][move["player"]][move["ply"]]
            assert move["tracker"]["particles"] >= 1


# Catches: a finished run overwritten, or an odd number of games, which cannot swap colours.
def test_refuses_an_existing_folder_and_an_odd_number_of_games(tmp_path):
    (tmp_path / "taken").mkdir()
    taken = play(tmp_path / "taken", "--games", "2")
    assert taken.returncode != 0 and "exists" in taken.stderr
    odd = play(tmp_path / "odd", "--games", "3")
    assert odd.returncode != 0 and "even" in odd.stderr and not (tmp_path / "odd").exists()


class Judge:
    def __init__(self, values):
        self.values = values

    def evaluate_children(self, fen):
        return dict(self.values)


# Catches: value lost with the wrong sign or measured from anything but the best move on the true
# board, or a played move the true board does not have passing silently.
def test_value_lost_is_the_best_true_value_minus_the_played_move_s():
    judge = Judge({"e2e4": 0.5, "d2d4": 0.25, "g1f3": -0.25})
    assert play_matches.value_lost(judge, "fen", "g1f3") == {"best": 0.5, "played": -0.25, "value_lost": 0.75}
    assert play_matches.value_lost(judge, "fen", "e2e4")["value_lost"] == 0
    with pytest.raises(ValueError, match="a2a4"):
        play_matches.value_lost(judge, "fen", "a2a4")
