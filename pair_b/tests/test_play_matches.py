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
    assert (score["complete_pairs"], score["incomplete_pairs"]) == (1, 0)
    assert score["ci95"] is None  # one opening: no interval to speak of
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
    assert (summary["score_a"]["complete_pairs"], summary["score_a"]["incomplete_pairs"]) == (0, 1)
    assert summary["errors_no_legal_move"] == 0  # these failed for another reason


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


def _teal_available():
    from pairb.rules import teal_available
    return teal_available()


# Catches: `--rules teal` failing on a checkout that has Teal's adapter, or playing (and recording) the
# stand-in instead. Without the adapter the test above checks the refusal instead.
@pytest.mark.skipif(not _teal_available(), reason="Teal's rules adapter is not in this checkout")
def test_rules_teal_plays_and_records_teals_adapter(tmp_path):
    teal = play(tmp_path / "teal", "--games", "2", "--max-plies", "8", "--rules", "teal")
    assert teal.returncode == 0, teal.stderr
    summary = json.loads((tmp_path / "teal" / "summary.json").read_text())
    assert (summary["rules"], summary["settings"]["rules"]) == ("teal-rules-adapter", "teal")
    assert "pair_a_prep/rules_adapter.py" in summary["record"]["source_sha256"]


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
        assert summary["settings"]["stockfish"] == str(Path("~") / Path(engine).name)


def synthetic(number, opening, white, winner=None, error=None, reason=None, capped=False):
    """A finished (or failed) game record with only what summarise reads."""
    colours = {"white": white, "black": "b" if white == "a" else "a"}
    game = {"game": number, "opening": {"id": opening, "moves": []}, "colours": colours, "seconds": 1.0}
    if error:
        return {**game, "error": error}
    return {**game, "winner": winner, "winner_side": colours.get(winner), "reason": reason, "plies": 10,
            "stopped_at_ply_limit": capped, "moves": []}


def summary_of(games, **extra):
    import argparse
    args = argparse.Namespace(a="material", b="material", games=len(games), max_plies=20, seed=0, particles=256,
                              guesses=8, device="auto", rules="standin", stockfish="stockfish", time_budget_ms=60000,
                              opening_plies=[2, 8], out="m")
    return play_matches.summarise(games, args, {"a": "m", "b": "m"}, {"a": None, "b": None}, 1.0,
                                  play_matches.pick_rules("standin"), **extra)


# Catches: a lone surviving game of an opening counted in a score labelled "both colours together"
# (Bryan's case on #16: 0.667 where the complete pairs give 0.5), or raw results lost.
def test_the_score_counts_complete_colour_pairs_only():
    games = [synthetic(0, 0, "a", winner="white"), synthetic(1, 0, "b", error="TrackerLost: x"),
             synthetic(2, 1, "a", winner="white"), synthetic(3, 1, "b", winner="white")]
    summary = summary_of(games)
    score = summary["score_a"]
    assert score["mean"] == 0.5 and (score["complete_pairs"], score["incomplete_pairs"]) == (1, 1)
    assert score["ci95"] is None
    assert (summary["sides"]["a"]["wins"], summary["sides"]["a"]["losses"], summary["games"]) == (2, 1, 3)
    # Pairs of 0.5 and 1.0: two pairs are too few for a bootstrap interval, so none is given; the
    # Wilson interval on the pair-level proportion is, and it contains the mean.
    two = summary_of(games + [synthetic(4, 2, "a", winner="white"), synthetic(5, 2, "b", winner="black")])["score_a"]
    assert (two["complete_pairs"], two["mean"], two["ci95"], two["degenerate"]) == (2, 0.75, None, True)
    assert two["wilson95"][0] < 0.75 < two["wilson95"][1]


# Catches: a pair with one draw scored as anything but a quarter point (Bryan's #18 review: a win and a
# draw is 0.75, a loss and a draw 0.25; the protocol used to list only 0, 0.5 and 1).
def test_a_pair_with_one_draw_scores_a_quarter_point():
    win_and_draw = summary_of([synthetic(0, 0, "a", winner="white"), synthetic(1, 0, "b", winner="draw")])
    loss_and_draw = summary_of([synthetic(0, 0, "a", winner="black"), synthetic(1, 0, "b", winner="draw")])
    assert (win_and_draw["score_a"]["mean"], loss_and_draw["score_a"]["mean"]) == (0.75, 0.25)


def pairs_of(outcomes):
    """Synthetic complete colour pairs: one winner string per pair ('a', 'b' or 'draw'), played as both colours."""
    games = []
    for i, who in enumerate(outcomes):
        for white in ("a", "b"):
            winner = "draw" if who == "draw" else ("white" if white == who else "black")
            games.append(synthetic(len(games), i, white, winner=winner))
    return games


# Catches: a percentile bootstrap over identical pair scores presented as a 95% interval (the pilot:
# five pairs all won gave "1.00 to 1.00"), which Bryan's #16 review asked not to present; the Wilson
# interval on 5 of 5 pairs runs from about 0.57 to 1.
def test_identical_pairs_give_no_bootstrap_interval_but_a_wilson_one():
    score = summary_of(pairs_of(["a"] * 5))["score_a"]
    assert (score["complete_pairs"], score["mean"], score["ci95"], score["degenerate"]) == (5, 1.0, None, True)
    assert 0.56 < score["wilson95"][0] < 0.58 and score["wilson95"][1] == 1.0
    assert "fewer than 20" in score["note"]
    same = summary_of(pairs_of(["a"] * 25))["score_a"]
    assert same["ci95"] is None and "scored the same" in same["note"] and 0.86 < same["wilson95"][0] < 0.87


# Catches: a bootstrap interval printed from too few pairs to resample meaningfully (the floor is 20
# complete pairs), or a Wilson interval missing when the bootstrap is fine.
def test_the_bootstrap_interval_needs_twenty_varied_pairs():
    nineteen = summary_of(pairs_of(["a", "b", "draw"] * 6 + ["a"]))["score_a"]
    assert nineteen["complete_pairs"] == 19 and nineteen["ci95"] is None and nineteen["degenerate"] is True
    twenty = summary_of(pairs_of(["a", "b", "draw"] * 6 + ["a", "a"]))["score_a"]
    assert twenty["complete_pairs"] == 20 and twenty["degenerate"] is False
    assert twenty["ci95"][0] <= twenty["mean"] <= twenty["ci95"][1]
    assert twenty["wilson95"][0] <= twenty["mean"] <= twenty["wilson95"][1]
    assert twenty["note"] is None
    same = summary_of(pairs_of(["draw"] * 20))["score_a"]
    assert same["mean"] == 0.5 and same["ci95"] is None and same["degenerate"] is True


# Catches: the console line printing a collapsed bootstrap as a 95% CI (the pilot printed
# "95% CI 1.000 to 1.000"); with no bootstrap interval it must say so and give the Wilson one.
def test_the_console_names_the_wilson_interval_when_the_bootstrap_is_degenerate(two_games, capsys, tmp_path):
    result = play(tmp_path / "console", "--games", "2")
    assert result.returncode == 0, result.stderr
    last = result.stdout.strip().splitlines()[-1]
    assert "95% CI" not in last and "no bootstrap interval" in last and "Wilson" in last


# Catches: a failing value-lost measurement erasing a game that was played to its end, or a run in
# which some measurements fail and the rest are lost with them. The failure is injected in the second
# copy of the scorer (the judge), where Bryan's probe put it, not in the runner's helper.
def test_a_failing_measurement_keeps_the_game_and_reports_it_apart(tmp_path, monkeypatch):
    opened, real_open = [], play_matches.open_side

    class FlakyJudge:
        """Every second measurement fails; the bot's own copy is untouched."""
        def __init__(self, inner):
            self.inner, self.name, self.calls = inner, inner.name, 0

        def evaluate_children(self, fen):
            self.calls += 1
            if self.calls % 2:
                raise RuntimeError("judge died")
            return self.inner.evaluate_children(fen)

        def close(self):
            self.inner.close()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    def open_side(sid, opts):
        opened.append(sid)
        scorer = real_open(sid, opts)
        return FlakyJudge(scorer) if opened.count(sid) % 2 == 0 else scorer  # the second copy is the judge
    monkeypatch.setattr(play_matches, "open_side", open_side)
    with pytest.raises(SystemExit) as stopped:
        run_main(monkeypatch, tmp_path / "m")
    assert stopped.value.code == 1
    games = [json.loads(line) for line in (tmp_path / "m" / "games.jsonl").read_text().splitlines()]
    assert all("error" not in g and g["winner"] in ("white", "black", "draw") for g in games)
    chosen = [m for g in games for m in g["moves"] if not m["opening"]]
    failed = [m for m in chosen if "diagnostic_error" in m]
    measured = [m for m in chosen if "diagnostic_error" not in m]
    assert failed and measured, "both outcomes must occur for the partial-failure case"
    assert all(m["diagnostic_error"] == "RuntimeError: judge died" and m["value_lost"] is None for m in failed)
    assert all(math.isfinite(m["value_lost"]) for m in measured)
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    assert (summary["games"], summary["errors"], summary["diagnostic_errors"]) == (2, 0, len(failed))
    assert all(math.isfinite(side["value_lost_mean"]) for side in summary["sides"].values())
    assert summary["reopened"] == 0  # a failing judge is not a dead engine


# Catches: a game's scorer state (a Stockfish hash) depending on the games played before it, so
# the same game gives different values depending on where it falls in a run; seen in both the bot's
# own averages and the second copy's measurements.
@pytest.mark.skipif(__import__("shutil").which("stockfish") is None, reason="needs Stockfish on PATH")
def test_a_game_does_not_depend_on_the_games_before_it(monkeypatch):
    import argparse
    from pairb.lab.scorers import ScorerOptions
    averages = []

    class Recording(play_matches.OnePlyBot):
        def act(self, turn):
            decision = super().act(turn)
            averages.append(dict(self.last_explanation.averages))
            return decision
    monkeypatch.setattr(play_matches, "OnePlyBot", Recording)
    args = argparse.Namespace(a="stockfish-d1", b="material", seed=0, particles=64, guesses=4, max_plies=16)
    rules = play_matches.pick_rules("standin")
    opts = ScorerOptions(ROOT / "checkpoints")

    def run(numbers):
        sides = {s: (play_matches.open_side(getattr(args, s), opts), play_matches.open_side(getattr(args, s), opts))
                 for s in ("a", "b")}
        try:
            scorers, judges = {s: v[0] for s, v in sides.items()}, {s: v[1] for s, v in sides.items()}
            out = []
            for n in numbers:
                averages.clear()
                out.append(play_matches.play_one(rules, n, play_matches.opening(rules, 0, n // 2),
                                                 {"white": "a", "black": "b"}, scorers, judges, args))
        finally:
            for pair in sides.values():
                for scorer in pair:
                    scorer.close()
        return [(m["move"], m["best"], m["played"]) for m in out[-1]["moves"]], list(averages)
    assert run([0, 2]) == run([2])


# Catches: a run that clears only some engines at a game's start (the second copies but not the
# bots, or a bare Stockfish but not the one inside the linear correction or a network), or clears
# them after the game's first search, so a game still depends on the games before it.
@pytest.mark.skipif(__import__("shutil").which("stockfish") is None, reason="needs Stockfish on PATH")
@pytest.mark.parametrize("a, b", [("linear", "stockfish-d1"),
                                  pytest.param("network1", "belief", marks=pytest.mark.skipif(
                                      importlib.util.find_spec("torch") is None, reason="needs torch"))])
def test_every_engine_of_every_scorer_is_cleared_before_each_game(monkeypatch, a, b):
    import argparse
    from pairb.lab.scorers import ScorerOptions
    from pairb.stockfish import StockfishEvaluator
    events = []
    real_new_game, real_search = StockfishEvaluator.new_game, StockfishEvaluator.children_scores
    monkeypatch.setattr(StockfishEvaluator, "new_game", lambda self: (events.append(id(self)), real_new_game(self)))
    monkeypatch.setattr(StockfishEvaluator, "children_scores",
                        lambda self, board: (events.append("search"), real_search(self, board))[1])
    args = argparse.Namespace(a=a, b=b, seed=0, particles=16, guesses=2, max_plies=6)
    rules, opts = play_matches.pick_rules("standin"), ScorerOptions(ROOT / "checkpoints")
    scorers = {s: play_matches.open_side(getattr(args, s), opts) for s in ("a", "b")}
    judges = {s: play_matches.open_side(getattr(args, s), opts) for s in ("a", "b")}
    try:
        engines = {id(e) for d in (scorers, judges) for x in d.values() for e in play_matches.engines_of(x)}
        assert len(engines) == 4
        for number in (0, 1):
            events.clear()
            play_matches.play_one(rules, number, play_matches.opening(rules, 0, 0, (2, 2)), {"white": "a", "black": "b"},
                                  scorers, judges, args)
            assert set(events[:4]) == engines, "all four engines are cleared first"
            assert "search" in events[4:] and "search" not in events[:4], "and before the game's first search"
    finally:
        for scorer in (*scorers.values(), *judges.values()):
            scorer.close()


# Catches: a Stockfish process dying mid-batch (a crash) turning every later game of a pairing into an
# error, instead of that side's scorer and second copy being reopened and the run going on.
@pytest.mark.skipif(__import__("shutil").which("stockfish") is None, reason="needs Stockfish on PATH")
def test_a_dead_engine_is_reopened_and_the_run_goes_on(tmp_path, monkeypatch):
    from test_stockfish import kill
    real = play_matches.play_one

    def kill_a_before_game_1(rules, number, moves, colours, scorers, judges, args):
        if number == 1:
            kill(scorers["a"])
        return real(rules, number, moves, colours, scorers, judges, args)
    monkeypatch.setattr(play_matches, "play_one", kill_a_before_game_1)
    monkeypatch.setattr(sys, "argv", ["play_matches.py", "--a", "stockfish-d1", "--b", "material", "--games", "4",
                                      "--max-plies", "10", "--rules", "standin", "--out", str(tmp_path / "m")])
    with pytest.raises(SystemExit) as stopped:
        play_matches.main()
    assert stopped.value.code == 1  # one game did fail
    games = [json.loads(line) for line in (tmp_path / "m" / "games.jsonl").read_text().splitlines()]
    assert len(games) == 4
    assert "EngineTerminatedError" in games[1]["error"] and games[1]["reopened"] == ["a"]
    assert all("error" not in g and g["diagnostic_errors"] == 0 for g in (games[0], games[2], games[3]))
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    assert (summary["games"], summary["errors"], summary["reopened"]) == (3, 1, 1)


# Catches: an engine that stops answering (Bryan's probe on #18) hanging the whole run, instead of its
# game failing with a TimeoutError and that side being reopened, as after a crash.
@pytest.mark.skipif(__import__("shutil").which("stockfish") is None, reason="needs Stockfish on PATH")
def test_an_engine_that_stops_answering_is_reopened_and_the_run_goes_on(tmp_path, monkeypatch):
    from pairb.stockfish import StockfishEvaluator
    from test_stockfish import HUNG_ENGINE, within
    real = play_matches.play_one
    hung = []

    def hang_a_in_game_1(rules, number, moves, colours, scorers, judges, args):
        if number == 1:  # side a's scorer now never answers; its old engine is closed first
            scorers["a"].close()
            scorers["a"] = StockfishEvaluator(depth=1, path=HUNG_ENGINE, call_timeout_s=0.5)
            hung.append(scorers["a"])
        return real(rules, number, moves, colours, scorers, judges, args)
    monkeypatch.setattr(play_matches, "play_one", hang_a_in_game_1)
    monkeypatch.setattr(sys, "argv", ["play_matches.py", "--a", "stockfish-d1", "--b", "material", "--games", "4",
                                      "--max-plies", "10", "--rules", "standin", "--out", str(tmp_path / "m")])
    try:
        outcome = within(60, play_matches.main)
    finally:
        for ev in hung:
            ev.engine.close()  # frees a call that is still waiting, so the suite can exit
    assert outcome is not None, "the run was still waiting on the stuck engine after 60 s"
    stopped = outcome.get("error")
    assert isinstance(stopped, SystemExit) and stopped.code == 1, outcome  # one game did fail
    games = [json.loads(line) for line in (tmp_path / "m" / "games.jsonl").read_text().splitlines()]
    assert len(games) == 4
    assert games[1]["error"].startswith("TimeoutError") and games[1]["reopened"] == ["a"]
    assert all("error" not in g and g["diagnostic_errors"] == 0 for g in (games[0], games[2], games[3]))
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    assert (summary["games"], summary["errors"], summary["reopened"]) == (3, 1, 1)


# Catches: an unattended run spending its whole budget on games that all fail the same way.
def test_five_consecutive_failed_games_stop_the_run(tmp_path, monkeypatch):
    class Failing(play_matches.OnePlyBot):
        def act(self, turn):
            raise RuntimeError("boom")
    monkeypatch.setattr(play_matches, "OnePlyBot", Failing)
    with pytest.raises(SystemExit) as stopped:
        run_main(monkeypatch, tmp_path / "m", "--games", "20", "--rules", "standin")
    assert stopped.value.code == 1
    games = [json.loads(line) for line in (tmp_path / "m" / "games.jsonl").read_text().splitlines()]
    assert len(games) == 5 and all("error" in g for g in games)
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    assert summary["errors"] == 5 and summary["stopped_early"] == "5 consecutive games failed"


# Catches: a batch played under whatever rules happen to be importable (`auto` is Teal's adapter
# wherever the checkout has it), so two machines, or two halves of one table, play by different rules.
def test_a_batch_must_pin_its_rules(tmp_path):
    batch = play(tmp_path / "auto4", "--games", "4")
    assert batch.returncode != 0 and "pin --rules" in batch.stderr and not (tmp_path / "auto4").exists()
    smoke = play(tmp_path / "auto2", "--games", "2")  # a two-game smoke run may still use auto
    assert smoke.returncode == 0, smoke.stderr


# Catches: no way to play from the standard start (for the cross-check against Bryan's runner), or an
# opening length that is not recorded with the run.
def test_opening_plies_can_be_pinned_and_zero_means_the_standard_start(tmp_path):
    standard = play(tmp_path / "std", "--games", "2", "--opening-plies", "0", "0")
    assert standard.returncode == 0, standard.stderr
    games = [json.loads(line) for line in (tmp_path / "std" / "games.jsonl").read_text().splitlines()]
    assert all(g["opening"]["moves"] == [] for g in games)
    summary = json.loads((tmp_path / "std" / "summary.json").read_text())
    assert summary["settings"]["opening_plies"] == [0, 0] and "randint(0, 0)" in summary["openings_rule"]
    three = play(tmp_path / "three", "--games", "2", "--opening-plies", "3", "3")
    assert three.returncode == 0, three.stderr
    games = [json.loads(line) for line in (tmp_path / "three" / "games.jsonl").read_text().splitlines()]
    assert all(len(g["opening"]["moves"]) == 3 for g in games)
    assert "randint(3, 3)" in json.loads((tmp_path / "three" / "summary.json").read_text())["openings_rule"]
    bad = play(tmp_path / "bad", "--games", "2", "--opening-plies", "5", "3")
    assert bad.returncode != 0 and not (tmp_path / "bad").exists()


# Catches: the time budget hard-wired and the runner's over-budget flag dropped from the record, so
# a slow scorer's overruns are invisible.
def test_each_move_records_whether_it_overran_the_budget(two_games, tmp_path):
    games, summary = two_games
    assert summary["settings"]["time_budget_ms"] == 60000
    assert all(m["over_budget"] is False for g in games for m in g["moves"])
    tight = play(tmp_path / "tight", "--games", "2", "--time-budget-ms", "1")
    assert tight.returncode == 0, tight.stderr
    games = [json.loads(line) for line in (tmp_path / "tight" / "games.jsonl").read_text().splitlines()]
    summary = json.loads((tmp_path / "tight" / "summary.json").read_text())
    assert summary["settings"]["time_budget_ms"] == 1
    assert any(m["over_budget"] is True for g in games for m in g["moves"])


# Catches: a run file that does not say which engine policy played it (Bryan's runner resets the engine
# every call; this one once per game), or which folder it was written to.
def test_the_settings_name_the_engine_policy_and_the_output_folder(two_games):
    settings = two_games[1]["settings"]
    assert settings["engine"] == {"threads": 1, "hash_mb": 16, "new_game": "before every game",
                                  "within_game": "hash kept between calls", "call_timeout_s": 60.0}
    assert settings["out"].endswith("material")
    # the home folder is written as ~ (summarise directly, since pytest's tmp_path is not under the home folder)
    import argparse
    args = argparse.Namespace(a="material", b="material", games=0, max_plies=20, seed=0, particles=256, guesses=8,
                              device="auto", rules="standin", stockfish="stockfish", time_budget_ms=60000,
                              opening_plies=[2, 8], out=str(Path.home() / "x" / "material"))
    home = play_matches.summarise([], args, {"a": "m", "b": "m"}, {"a": None, "b": None}, 1.0,
                                  play_matches.pick_rules("standin"))["settings"]["out"]
    assert home == str(Path("~") / "x" / "material")


# Catches: a judge (the second copy used for value lost) dying mid-batch: the game it died in must be
# kept with its diagnostic errors, the side reopened, and the next games measured again.
@pytest.mark.skipif(__import__("shutil").which("stockfish") is None, reason="needs Stockfish on PATH")
def test_a_dead_judge_keeps_its_game_and_is_reopened(tmp_path, monkeypatch):
    from test_stockfish import kill
    real = play_matches.play_one

    def kill_judge_a_before_game_1(rules, number, moves, colours, scorers, judges, args):
        if number == 1:
            kill(judges["a"])
        return real(rules, number, moves, colours, scorers, judges, args)
    monkeypatch.setattr(play_matches, "play_one", kill_judge_a_before_game_1)
    monkeypatch.setattr(sys, "argv", ["play_matches.py", "--a", "stockfish-d1", "--b", "material", "--games", "4",
                                      "--max-plies", "10", "--rules", "standin", "--out", str(tmp_path / "m")])
    with pytest.raises(SystemExit) as stopped:
        play_matches.main()
    assert stopped.value.code == 1  # measurements failed in game 2
    games = [json.loads(line) for line in (tmp_path / "m" / "games.jsonl").read_text().splitlines()]
    assert "error" not in games[1] and games[1]["diagnostic_errors"] > 0 and games[1]["reopened"] == ["a"]
    assert all("error" not in g and g["diagnostic_errors"] == 0 for g in (games[0], games[2], games[3]))
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    assert (summary["games"], summary["errors"], summary["reopened"]) == (4, 0, 1)


# Catches: a reopen that fails (no engine to open) losing the game that triggered it, or ending the run
# with a traceback and no reason in the summary.
@pytest.mark.skipif(__import__("shutil").which("stockfish") is None, reason="needs Stockfish on PATH")
def test_a_failed_reopen_keeps_the_game_and_stops_the_run_with_a_reason(tmp_path, monkeypatch):
    from test_stockfish import kill
    real_play = play_matches.play_one

    def no_engine(sid, opts):
        raise OSError("no engine")

    def kill_a_before_game_1(rules, number, moves, colours, scorers, judges, args):
        if number == 1:
            kill(scorers["a"])
            monkeypatch.setattr(play_matches, "open_side", no_engine)
        return real_play(rules, number, moves, colours, scorers, judges, args)
    monkeypatch.setattr(play_matches, "play_one", kill_a_before_game_1)
    monkeypatch.setattr(sys, "argv", ["play_matches.py", "--a", "stockfish-d1", "--b", "material", "--games", "4",
                                      "--max-plies", "10", "--rules", "standin", "--out", str(tmp_path / "m")])
    with pytest.raises(SystemExit) as stopped:
        play_matches.main()
    assert stopped.value.code == 1
    games = [json.loads(line) for line in (tmp_path / "m" / "games.jsonl").read_text().splitlines()]
    assert len(games) == 2 and "EngineTerminatedError" in games[1]["error"] and "no engine" in games[1]["reopen_error"]
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    assert "reopen" in summary["stopped_early"] and summary["games"] == 1


# Catches: a run stopping after five failures in total instead of five in a row.
def test_a_success_resets_the_consecutive_failure_count(tmp_path, monkeypatch):
    real = play_matches.play_one

    def fail_some(rules, number, moves, colours, scorers, judges, args):
        if number in (0, 1, 2, 3, 5, 6, 7, 8):  # four, a success, four more: never five in a row
            return {"game": number, "opening": {"id": number // 2, "moves": moves}, "seed": 0, "colours": colours,
                    "scorers": {}, "error": "RuntimeError: boom", "plies_played": 0, "seconds": 0.0}
        return real(rules, number, moves, colours, scorers, judges, args)
    monkeypatch.setattr(play_matches, "play_one", fail_some)
    with pytest.raises(SystemExit) as stopped:
        run_main(monkeypatch, tmp_path / "m", "--games", "12", "--rules", "standin")
    assert stopped.value.code == 1
    games = [json.loads(line) for line in (tmp_path / "m" / "games.jsonl").read_text().splitlines()]
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    assert len(games) == 12 and summary["errors"] == 8 and summary["stopped_early"] is None


# Catches: a table that cannot say how its games ended (a pairing that wins only at the ply cap reads
# the same as one that captures kings), or failed games counted among the endings.
def test_the_summary_counts_how_the_finished_games_ended():
    games = [synthetic(0, 0, "a", winner="white", reason="king_capture"),
             synthetic(1, 0, "b", winner="draw", reason="fifty_move"),
             synthetic(2, 1, "a", winner="draw", reason="threefold_repetition"),
             synthetic(3, 1, "b", winner="draw", reason="no_legal_moves"),
             synthetic(4, 2, "a", winner="draw", capped=True),
             synthetic(5, 2, "b", winner="white", reason="king_capture"),
             synthetic(6, 3, "a", winner="draw", reason="some_new_rule"),
             synthetic(7, 3, "b", error="TrackerLost: x")]
    assert summary_of(games)["end_reasons"] == {"king_capture": 2, "fifty_move": 1, "threefold_repetition": 1,
                                                "no_legal_moves": 1, "ply_limit": 1, "some_new_rule": 1}
    # the five usual endings are always listed, so two rows compare key by key
    assert summary_of(games[:1])["end_reasons"] == {"king_capture": 1, "fifty_move": 0, "threefold_repetition": 0,
                                                    "no_legal_moves": 0, "ply_limit": 0}


def tracker_update(capped, rebuilt):
    return {"ply": 0, "exact": not (capped or rebuilt), "capped": capped, "rebuilt": rebuilt, "particles": 1}


def timed(side, ms, over=False, opening=False):
    return {"side": side, "opening": opening, "elapsed_ms": ms, "over_budget": over, "value_lost": None}


# Catches: a methods table that asks for the median time per move when the run file has only the mean and
# the 95th percentile, overruns that cannot be totalled per side without reading every game, or tracker
# health counted for the wrong side when the colours swap.
def test_each_side_has_its_median_time_overruns_and_tracker_health():
    first = synthetic(0, 0, "a", winner="white")  # a is White
    first["moves"] = [timed("a", 0.0, over=True, opening=True), timed("b", 0.0, opening=True), timed("a", 1.0),
                      timed("b", 10.0, over=True), timed("a", 2.0), timed("b", 20.0, over=True), timed("a", 9.0, over=True)]
    first["trackers"] = {"white": [tracker_update(False, False), tracker_update(True, False), tracker_update(True, True)],
                         "black": [tracker_update(False, True)]}
    second = synthetic(1, 0, "b", winner="black")  # b is White
    second["trackers"] = {"white": [tracker_update(True, True)], "black": [tracker_update(False, False)]}
    sides = summary_of([first, second, synthetic(2, 1, "a", error="RuntimeError: boom")])["sides"]
    a, b = sides["a"], sides["b"]
    assert (a["ms_per_move_median"], b["ms_per_move_median"]) == (2.0, 15.0)
    assert (a["over_budget_plies"], b["over_budget_plies"]) == (1, 2)
    assert (a["tracker_capped"], a["tracker_rebuilt"]) == (2, 1)
    assert (b["tracker_capped"], b["tracker_rebuilt"]) == (1, 2)


# Catches: a run file that does not say how long a Stockfish call may take before it counts as stuck,
# so two rows run with different limits look alike.
def test_the_engine_settings_record_the_call_time_limit():
    import inspect
    from pairb.stockfish import StockfishEvaluator
    default = inspect.signature(StockfishEvaluator).parameters["call_timeout_s"].default
    nobody = {"a": None, "b": None}
    assert play_matches.engine_policy(nobody, nobody)["call_timeout_s"] == default == 60.0

    class Opened(StockfishEvaluator):
        def __init__(self):  # no engine process: only the settings engine_policy reads
            self.new_game_each_call, self.call_timeout_s = False, 5.0
    assert play_matches.engine_policy({"a": Opened(), "b": None}, nobody)["call_timeout_s"] == 5.0


BLOCKED = "7k/8/8/8/1p6/pPp5/PRP5/KB6 w - - 0 1"  # White to move, and no fog-legal move


def without_the_draw_rule(monkeypatch):
    """This code as it was before the draw rule decided on #17, whichever checkout runs the test."""
    import pairb.rules
    real = pairb.rules.terminal_score
    monkeypatch.setattr(pairb.rules, "terminal_score",
                        lambda board: None if (real(board) or ("",))[0] == "no-moves" else real(board))


def with_the_draw_rule(monkeypatch):
    """The draw rule decided on #17 (Teal's #28), applied by hand: a side with no fog-legal move draws."""
    import pairb.rules
    from fow_shared.values import fog_legal_moves
    real = pairb.rules.terminal_score
    monkeypatch.setattr(pairb.rules, "terminal_score",
                        lambda board: real(board) or (None if fog_legal_moves(board) else ("no-moves", 0.0)))
    monkeypatch.setitem(pairb.rules._REASONS, "no-moves", "no_legal_moves")


def start_blocked(monkeypatch):
    """Every game of the run starts from BLOCKED, the referee and both trackers alike."""
    import functools
    from pairb.rules import GameReferee
    from pairb.tracker import ParticleTracker
    monkeypatch.setattr(play_matches, "GameReferee", lambda rules: GameReferee(rules, BLOCKED))
    monkeypatch.setattr(play_matches, "ParticleTracker", functools.partial(ParticleTracker, initial_fen=BLOCKED))


# Catches: a table whose rule for a side with no fog-legal move is not written down. --rules standin does
# not pin it, only the commit does, so the run must find out what its own code does and record it.
def test_the_run_finds_out_what_its_rules_do_when_a_side_has_no_move(monkeypatch):
    import chess
    from fow_shared.values import terminal_score
    rules = play_matches.pick_rules("standin")
    assert play_matches.BLOCKED_FEN == BLOCKED
    assert play_matches.no_move_rule(rules) == ("unresolved" if terminal_score(chess.Board(BLOCKED)) is None else "draw")
    without_the_draw_rule(monkeypatch)
    assert play_matches.no_move_rule(rules) == "unresolved"
    with_the_draw_rule(monkeypatch)
    assert play_matches.no_move_rule(rules) == "draw"


# Catches: a random side failing with a different error (IndexError) from a bot side (ValueError) in the
# same position, so a pre-rule table cannot count its no-move failures with one test.
def test_random_fails_with_the_bots_error_when_there_is_no_move():
    from types import SimpleNamespace
    from pairb.bot import OnePlyBot
    turn = SimpleNamespace(observation=SimpleNamespace(legal_moves=()), belief=None)
    errors = []
    for agent in (play_matches.RandomAgent(), OnePlyBot(scorer=None)):
        agent.reset("white", 0)
        with pytest.raises(ValueError) as raised:
            agent.act(turn)
        errors.append(str(raised.value))
    assert errors[0] == errors[1] == "the observation has no legal move to choose from"


# Catches: before the draw rule lands, a side with no fog-legal move failing its game in a way the summary
# cannot count apart from other failures, or failing differently for a random side and a bot side.
def test_before_the_draw_rule_a_side_with_no_move_fails_and_is_counted(tmp_path, monkeypatch, capsys):
    start_blocked(monkeypatch)
    without_the_draw_rule(monkeypatch)
    with pytest.raises(SystemExit) as stopped:  # standin pinned: the patch reaches the stand-in only
        run_main(monkeypatch, tmp_path / "m", "--a", "random", "--opening-plies", "0", "0", "--rules", "standin")
    assert stopped.value.code == 1
    games = [json.loads(line) for line in (tmp_path / "m" / "games.jsonl").read_text().splitlines()]
    assert [g["scorers"]["white"] for g in games] == ["random", "material"]  # each kind of side is the blocked one
    assert [g["error"] for g in games] == ["ValueError: the observation has no legal move to choose from"] * 2
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    assert (summary["errors"], summary["errors_no_legal_move"], summary["no_move_rule"]) == (2, 2, "unresolved")
    assert "rules: pairb-standin; no_move_rule: unresolved" in capsys.readouterr().out


# Catches: once the draw rule is in the code, a blocked side's game not ending as a draw by no_legal_moves,
# or the summary still saying the rule is unresolved.
def test_after_the_draw_rule_a_side_with_no_move_draws(tmp_path, monkeypatch, capsys):
    start_blocked(monkeypatch)
    with_the_draw_rule(monkeypatch)  # standin pinned: the patch reaches the stand-in only
    run_main(monkeypatch, tmp_path / "m", "--a", "random", "--opening-plies", "0", "0", "--rules", "standin")
    games = [json.loads(line) for line in (tmp_path / "m" / "games.jsonl").read_text().splitlines()]
    assert [(g["winner"], g["reason"], g["plies"]) for g in games] == [("draw", "no_legal_moves", 0)] * 2
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    assert (summary["errors"], summary["errors_no_legal_move"], summary["no_move_rule"]) == (0, 0, "draw")
    assert summary["end_reasons"]["no_legal_moves"] == 2
    assert "no_move_rule: draw" in capsys.readouterr().out


# Catches: a run file that does not say how it was started, or a finished run that cannot be told
# apart from a partial one without counting its games.
def test_a_full_run_is_marked_completed_and_records_its_command(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    run_main(monkeypatch, tmp_path / "m")
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    assert summary["completed"] is True and summary["stopped_early"] is None
    assert summary["command"] == ["play_matches.py", "--a", "material", "--b", "material", "--games", "2",
                                  "--max-plies", "12", "--out", "~/m"]


# Catches: a run stopped early on its last planned game (five failures in a row, or a dead engine that
# would not reopen) marked completed because every planned game has a record.
def test_a_run_stopped_early_is_not_completed_even_with_every_game_recorded():
    two = [synthetic(0, 0, "a", winner="white"), synthetic(1, 0, "b", winner="white")]
    assert summary_of(two)["completed"] is True
    assert summary_of(two, stopped_early="5 consecutive games failed")["completed"] is False


# Catches: a Ctrl-C'd run writing a summary that looks clean (errors 0, stopped_early null), or the
# process exiting with status 0 after it, so a batch wrapper takes a partial row for a finished one.
def test_ctrl_c_marks_the_summary_interrupted_and_not_completed(tmp_path, monkeypatch, capsys):
    real = play_matches.play_one

    def interrupted_in_game_2(rules, number, *args):
        if number == 1:
            raise KeyboardInterrupt
        return real(rules, number, *args)
    monkeypatch.setattr(play_matches, "play_one", interrupted_in_game_2)
    with pytest.raises(KeyboardInterrupt):
        run_main(monkeypatch, tmp_path / "m", "--games", "4", "--rules", "standin")
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    assert (summary["games"], summary["errors"], summary["settings"]["games"]) == (1, 0, 4)
    assert summary["stopped_early"] == "interrupted" and summary["completed"] is False
    assert "interrupted" in capsys.readouterr().err
    # the same in a real process: the summary is written and the exit status is not 0
    script = (f"import importlib.util, sys\n"
              f"spec = importlib.util.spec_from_file_location('pm', {str(ROOT / 'scripts' / 'play_matches.py')!r})\n"
              f"pm = importlib.util.module_from_spec(spec); spec.loader.exec_module(pm)\n"
              f"real = pm.play_one\n"
              f"def stop(rules, number, *a):\n"
              f"    if number == 1: raise KeyboardInterrupt\n"
              f"    return real(rules, number, *a)\n"
              f"pm.play_one = stop\n"
              f"sys.argv = ['play_matches.py', '--a', 'material', '--b', 'material', '--games', '4', '--max-plies', '12',"
              f" '--rules', 'standin', '--out', {str(tmp_path / 'p')!r}]\n"
              f"pm.main()\n")
    process = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert process.returncode != 0
    assert json.loads((tmp_path / "p" / "summary.json").read_text())["stopped_early"] == "interrupted"


# Catches: the runner itself failing between games (not a game that raises, which is recorded) and still
# leaving a summary with stopped_early null.
def test_a_runner_failure_between_games_is_not_summarised_as_a_clean_run(tmp_path, monkeypatch):
    real = play_matches.play_one

    def broken_in_game_2(rules, number, *args):
        if number == 1:
            raise OSError("disk full")
        return real(rules, number, *args)
    monkeypatch.setattr(play_matches, "play_one", broken_in_game_2)
    with pytest.raises(OSError):
        run_main(monkeypatch, tmp_path / "m", "--games", "4", "--rules", "standin")
    summary = json.loads((tmp_path / "m" / "summary.json").read_text())
    assert summary["stopped_early"] == "the run failed: OSError: disk full" and summary["completed"] is False


# Catches: rules that refuse the blocked position stopping the run before its first game, or a rule that
# scores the blocked side as losing being recorded as a draw.
def test_no_move_rule_reports_other_answers_as_they_are():
    class Rules:
        def __init__(self, ended=None, refuse=False):
            self.ended, self.refuse = ended, refuse

        def initial_state(self, fen):
            if self.refuse:
                raise ValueError("not a position these rules accept")
            return fen

        def terminal(self, state):
            return self.ended
    assert play_matches.no_move_rule(Rules(("black", "no_legal_moves"))) == "black wins (no_legal_moves)"
    assert play_matches.no_move_rule(Rules(refuse=True)) == "unknown (ValueError: not a position these rules accept)"
