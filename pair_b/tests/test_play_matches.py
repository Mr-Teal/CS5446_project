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


# Catches: the true board recorded without the en passant square of a capture that only fog rules
# allow (python-chess's default FEN drops it), so the second scorer lacks a move the bot may play,
# value_lost raises and the whole run stops.
def test_the_true_board_keeps_an_en_passant_capture_only_fog_rules_allow():
    from pairb.material import MaterialEvaluator
    from pairb.rules import GameReferee, StandinRules
    referee = play_matches.WatchedReferee(GameReferee(StandinRules(), "7b/3p4/8/4P3/8/8/8/K6k b - - 0 1"))
    referee.reset(0)
    referee.apply("d7d5")
    referee.apply("e5d6")  # uncovers White's king on a1 to the bishop on h8: legal only under fog rules
    assert "e5d6" in MaterialEvaluator().evaluate_children(referee.before[1])


def run_main(monkeypatch, out, *extra):
    monkeypatch.setattr(sys, "argv", ["play_matches.py", "--a", "material", "--b", "material", "--games", "2",
                                      "--max-plies", "12", "--out", str(out), *map(str, extra)])
    play_matches.main()


# Catches: one failing game ending an unattended run with no summary, or a run where no game
# finished crashing on its last line instead of saying so.
def test_a_failing_game_is_recorded_and_the_run_still_writes_its_summary(tmp_path, monkeypatch):
    class Failing(play_matches.OnePlyBot):
        def act(self, turn):
            raise RuntimeError("boom")
    monkeypatch.setattr(play_matches, "OnePlyBot", Failing)
    with pytest.raises(SystemExit) as stopped:
        run_main(monkeypatch, tmp_path / "m")
    assert stopped.value.code == 1
    games = [json.loads(line) for line in (tmp_path / "m" / "games.jsonl").read_text().splitlines()]
    assert len(games) == 2 and all(g["error"] == "RuntimeError: boom" for g in games)
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    assert (summary["games"], summary["errors"], summary["score_a"]["mean"]) == (0, 2, None)


# Catches: an interrupted run (Ctrl-C) leaving no summary of the games it did finish.
def test_an_interrupted_run_writes_the_summary_of_the_games_it_finished(tmp_path, monkeypatch):
    real = play_matches.play_one

    def second_game_interrupted(rules, number, *args):
        if number == 1:
            raise KeyboardInterrupt
        return real(rules, number, *args)
    monkeypatch.setattr(play_matches, "play_one", second_game_interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_main(monkeypatch, tmp_path / "m")
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    assert (summary["games"], summary["errors"]) == (1, 0)


def sha256(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# Catches: rules that change with whatever happens to be importable, unrecorded, so two machines
# play the same command by different rules; or a request for Teal's rules quietly falling back.
def test_the_rules_are_chosen_on_the_command_line_and_recorded(tmp_path):
    from pairb.rules import pick_rules, teal_available
    pinned = play(tmp_path / "standin", "--games", "2", "--max-plies", "8", "--rules", "standin")
    assert pinned.returncode == 0, pinned.stderr
    summary = json.loads((tmp_path / "standin" / "summary.json").read_text())
    assert (summary["rules"], summary["settings"]["rules"]) == ("pairb-standin", "standin")
    auto = play(tmp_path / "auto", "--games", "2", "--max-plies", "8")
    assert json.loads((tmp_path / "auto" / "summary.json").read_text())["rules"] == pick_rules("auto").name
    if not teal_available():
        teal = play(tmp_path / "teal", "--games", "2", "--rules", "teal")
        assert teal.returncode != 0 and "Teal" in teal.stderr and not (tmp_path / "teal").exists()


# Catches: a run that cannot be traced to the code, engine and libraries that played it.
def test_the_summary_records_the_code_engine_and_libraries(two_games):
    import shutil
    from pairb import provenance
    record = two_games[1]["record"]
    assert (record["git_status"] is None) == (provenance.git_status() is None)  # None only without git
    assert not any("__pycache__" in line for line in record["git_status"] or [])
    assert record["source_sha256"]["pair_b/scripts/play_matches.py"] == sha256(ROOT / "scripts" / "play_matches.py")
    assert record["source_sha256"]["fow_shared/evaluation.py"] == sha256(ROOT.parent / "fow_shared" / "evaluation.py")
    assert {"python", "numpy", "python_chess", "torch"} <= set(record["packages"])
    engine = shutil.which("stockfish")
    assert record["stockfish"]["sha256"] == (sha256(engine) if engine else None)
    assert all(side["device"] is None for side in two_games[1]["sides"].values())


# Catches: the linear correction missing from the players, or played without its checkpoint's hash.
@pytest.mark.skipif(__import__("shutil").which("stockfish") is None, reason="needs Stockfish on PATH")
def test_the_linear_correction_can_play(tmp_path):
    result = play(tmp_path / "linear", "--games", "2", "--max-plies", "12", "--a", "linear")
    assert result.returncode == 0, result.stderr
    summary = json.loads((tmp_path / "linear" / "summary.json").read_text())
    side = summary["sides"]["a"]
    assert side["scorer"] == "linear" and side["name"].startswith("linear-v1")
    assert side["checkpoint_sha256"] == sha256(ROOT / "checkpoints" / "linear-v1" / "best.npz")
    assert math.isfinite(side["value_lost_mean"]) and side["value_lost_mean"] >= 0


# Catches: the device a network ran on recorded as "auto" instead of the one torch actually chose.
@pytest.mark.skipif(__import__("shutil").which("stockfish") is None, reason="needs Stockfish on PATH")
def test_the_summary_records_the_device_a_network_ran_on(tmp_path):
    pytest.importorskip("torch")
    from pairb.network_evaluator import pick_device
    result = play(tmp_path / "net", "--games", "2", "--max-plies", "12", "--a", "network1")
    assert result.returncode == 0, result.stderr
    summary = json.loads((tmp_path / "net" / "summary.json").read_text())
    assert summary["settings"]["device"] == "auto"
    assert (summary["sides"]["a"]["device"], summary["sides"]["b"]["device"]) == (pick_device(None), None)
    assert summary["sides"]["a"]["moves"] > 0


# Catches: a summary whose commit and code hash are read when the run ends, while its record of
# uncommitted changes and file hashes was read when it started: one summary, two code states.
def test_the_commit_is_read_once_when_the_run_starts(tmp_path, monkeypatch):
    commits = iter(["c1", "c2", "c3", "c4"])
    monkeypatch.setattr(play_matches, "git_commit", lambda: next(commits))
    run_main(monkeypatch, tmp_path / "m")
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    assert summary["git_commit"] == summary["record"]["git_commit"] == "c1"
    assert summary["runtime"] == summary["record"]["runtime"]


# Catches: the raw --stockfish path, home folder and all, written into the summary.
def test_the_settings_write_the_home_folder_as_a_tilde(tmp_path, monkeypatch):
    import shutil
    engine = shutil.which("stockfish") or "stockfish"
    monkeypatch.setattr(Path, "home", lambda: Path(engine).parent)
    run_main(monkeypatch, tmp_path / "m", "--stockfish", engine)
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    if engine != "stockfish":
        assert summary["settings"]["stockfish"] == f"~/{Path(engine).name}"
