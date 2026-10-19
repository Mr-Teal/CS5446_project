"""Fog Lab's fog-rules check: Pair A's 17 rules positions, run against one rules implementation and handed to the Tests
tab as JSON.

Teal's adapter is not on every branch, so the tests that need one put a small fake of it in sys.modules (or a real file
in a folder added to pair_a_prep's path), and one test asks for the real answer in this checkout. The stage runner
starts the file by path, in a throwaway worktree, with that stage's code first on PYTHONPATH; the by-path tests start it
the same way, from where it lives and then from a copy in another folder, against small made-up stages: one whose pairb
is not this checkout's, and one with no pairb at all (the environment still has this checkout's installed).
"""
import importlib
import json
import os
import shutil
import subprocess
import sys
import types

import chess
import pytest

import pair_a_prep
from no_torch import PAIR_B
from pair_a_prep.fixtures import compare_result, load_suite
from pairb.lab.checks.fixture_check import main, run_fixtures

REPO = PAIR_B.parent
CHECK = PAIR_B / "src" / "pairb" / "lab" / "checks" / "fixture_check.py"
ADAPTER = "pair_a_prep.rules_adapter"
CASE_KEYS = {"id", "player", "fen", "history", "visible", "expect", "errors"}


def failing(report):
    return {c["id"]: c["errors"] for c in report["cases"] if c["errors"]}


def fake_adapter(monkeypatch, **attributes):
    """Make `import pair_a_prep.rules_adapter` give a module with these attributes, whether Teal's is here or not."""
    module = types.ModuleType(ADAPTER)
    for name, value in attributes.items():
        setattr(module, name, value)
    monkeypatch.setitem(sys.modules, ADAPTER, module)


def wrong_answer(case=None):
    """What a bad adapter says: two squares seen (out of order), no moves and no end. Fails most of the 17 positions."""
    return {"legal_moves": (), "visible_squares": ("e2", "a1"), "visible_pieces": {"e2": "P", "a1": "R"},
            "terminal": False, "winner": None, "halfmove_clock": None}


def run_by_path(script, rules, pythonpath, cwd):
    """Start `script` as the stage runner does: by path, in a fresh interpreter, with PYTHONPATH set to `pythonpath`,
    from a folder that holds none of the code."""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(p) for p in pythonpath), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(script), "--rules", rules], cwd=cwd, env=env, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=300)


def make_stage(root, observe_source=None):
    """The least of a stage worktree that the check needs: Pair A's fixtures and, when `observe_source` is given, a
    pairb holding just that observe. Returns the PYTHONPATH the stage runner sets for it: pair_b/src, then the root."""
    pair_a = REPO / "pair_a_prep"
    (root / "pair_a_prep" / "data").mkdir(parents=True)
    for name in ("__init__.py", "fixtures.py", "data/rules_cases.json"):
        shutil.copy2(pair_a / name, root / "pair_a_prep" / name)
    if observe_source is not None:
        (root / "pair_b" / "src" / "pairb").mkdir(parents=True)
        (root / "pair_b" / "src" / "pairb" / "__init__.py").write_text("", encoding="utf-8")
        (root / "pair_b" / "src" / "pairb" / "observe.py").write_text(observe_source, encoding="utf-8")
    return [root / "pair_b" / "src", root]


# An observe that sees every square: what reaches the report shows which pairb was called.
SEES_EVERYTHING = (
    "import chess\n"
    "from fow_shared.contracts import Observation\n"
    "\n"
    "def observe(board, player, ply=0):\n"
    "    squares = tuple(sorted(chess.square_name(sq) for sq in chess.SQUARES))\n"
    "    return Observation(player=player, side_to_move='white' if board.turn else 'black', ply=ply,\n"
    "                       visible_squares=squares, visible_pieces={sq: None for sq in squares}, legal_moves=())\n")


# ---- the stand-in ----

# Catches: a stand-in path that replays a position wrongly, maps the winner the wrong way round or compares the wrong
# fields. All 17 passed on the 18 Oct mockup run; every other test leans on this baseline.
def test_standin_passes_all_17():
    r = run_fixtures("standin")
    assert r["available"] and len(r["cases"]) == 17 and not any(c["errors"] for c in r["cases"]), failing(r)
    assert (r["rules"], r["reason"]) == ("standin", None)


# Catches: a case that lacks what the Tests tab draws or carries it wrong: the position after its moves are replayed
# (not the one they start from), how many moves were replayed, the squares seen (sorted, each once), and the fixture's
# own expectations, which give the rings.
def test_each_case_carries_what_the_tests_tab_draws():
    suite = load_suite()["cases"]
    got = run_fixtures("standin")["cases"]
    assert [c["id"] for c in got] == [case["id"] for case in suite]
    for c, case in zip(got, suite):
        assert set(c) == CASE_KEYS
        assert (c["player"], c["expect"]) == (case["player"], case["expect"])
        assert c["fen"] == chess.Board(case["fen"]).fen(en_passant="fen")
        assert c["history"] == len(case.get("moves_uci", []))
        assert c["visible"] == sorted(set(c["visible"]))
        assert set(case["expect"].get("visible_contains", [])) <= set(c["visible"])
        assert not set(case["expect"].get("visible_excludes", [])) & set(c["visible"])
    assert {c["id"]: c["history"] for c in got}["threefold_needs_history"] == 8  # the one replayed position


# Catches: a stage without Pair B's code crashing the check instead of reporting that the stand-in is not available.
# Blocks the import, so it holds in this checkout too.
def test_standin_that_is_not_here_is_unavailable_with_a_reason(monkeypatch):
    monkeypatch.setitem(sys.modules, "pairb.observe", None)  # `import` now fails
    r = run_fixtures("standin")
    assert (r["rules"], r["available"], r["cases"]) == ("standin", False, [])
    assert "pairb.observe" in r["reason"] and "not in this checkout" in r["reason"]


# Catches: a stage with no pairb of its own being checked with the one installed for this checkout (the editable
# install is found after PYTHONPATH, so the import succeeds), which would show the app's stand-in under the stage's
# name. The fixtures come from the stage (pair_a_prep is never installed), so the stand-in must be in that same tree.
def test_standin_found_outside_the_fixtures_tree_is_not_the_stages(monkeypatch, tmp_path):
    monkeypatch.setattr(pair_a_prep, "__file__", str(tmp_path / "stage" / "pair_a_prep" / "__init__.py"))
    r = run_fixtures("standin")
    assert (r["available"], r["cases"]) == (False, [])
    assert "pairb.observe" in r["reason"] and "not in this checkout" in r["reason"]


# ---- Teal's adapter ----

# Catches: a missing adapter raising (the Tests tab would get nothing at all), or one that is here being called
# missing. Without Teal's adapter this reads "unavailable, with a reason, and no cases"; with it, all 17 pass.
def test_teal_reports_unavailable_or_passes():
    r = run_fixtures("teal")
    try:
        bridge = getattr(importlib.import_module(ADAPTER), "fixture_result", None)
    except ImportError:
        bridge = None
    assert r["rules"] == "teal" and r["available"] == (bridge is not None)
    if r["available"]:
        assert len(r["cases"]) == 17 and r["reason"] is None and not failing(r), failing(r)
    else:
        assert r["reason"] and r["cases"] == []


# Catches: the bridge not being asked about every position in order, its answer not going through compare_result, or
# the squares seen not being read from its answer (these arrive as a tuple, out of order).
def test_teal_path_asks_the_bridge_and_compares_its_answers(monkeypatch):
    asked = []

    def bridge(case):
        asked.append(case["id"])
        return wrong_answer(case)

    fake_adapter(monkeypatch, fixture_result=bridge)
    r = run_fixtures("teal")
    suite = load_suite()["cases"]
    assert (r["rules"], r["available"], r["reason"]) == ("teal", True, None)
    assert asked == [case["id"] for case in suite]
    for c, case in zip(r["cases"], suite):
        assert c["errors"] == compare_result(case, wrong_answer())
        assert c["visible"] == ["a1", "e2"]
    assert len(failing(r)) > 5  # the fake is wrong for most positions; a check that never failed would show nothing


# Catches: a missing adapter raising ImportError. Blocks the import, so it holds where Teal's adapter is present too.
def test_missing_adapter_is_unavailable_with_a_reason(monkeypatch):
    monkeypatch.setitem(sys.modules, ADAPTER, None)  # `import` now fails
    r = run_fixtures("teal")
    assert (r["rules"], r["available"], r["cases"]) == ("teal", False, [])
    assert "pair_a_prep.rules_adapter" in r["reason"] and "not in this checkout" in r["reason"]


# Catches: an adapter that is here but cannot load (a stage with an older fow_shared, say) raising, or being reported as
# missing, when what the Tests tab needs is the error. The file is a real one on pair_a_prep's path.
def test_adapter_that_fails_to_import_says_why(monkeypatch, tmp_path):
    (tmp_path / "rules_adapter.py").write_text("from fow_shared.values import no_such_name\n", encoding="utf-8")
    monkeypatch.setattr(pair_a_prep, "__path__", [str(tmp_path), *pair_a_prep.__path__])
    monkeypatch.delitem(sys.modules, ADAPTER, raising=False)
    r = run_fixtures("teal")
    assert (r["available"], r["cases"]) == (False, [])
    assert "could not be imported" in r["reason"] and "no_such_name" in r["reason"]
    assert "not in this checkout" not in r["reason"]


# Catches: an early adapter without the fixture_result bridge raising AttributeError instead of being unavailable.
def test_adapter_without_the_bridge_is_unavailable(monkeypatch):
    fake_adapter(monkeypatch)  # a module with a name and nothing else
    r = run_fixtures("teal")
    assert (r["available"], r["cases"]) == (False, [])
    assert "fixture_result" in r["reason"]


# Catches: one position the adapter cannot answer (it raises) stopping the other 16 from being reported: the Tests tab
# draws all 17 boards, and a case that cannot be answered is a failing one with the reason as its error.
def test_a_position_the_rules_cannot_answer_is_a_failing_case(monkeypatch):
    def bridge(case):
        if case["id"] == "fifty_move_draw":
            raise ValueError("unavailable UCI move: 'e2e5'")
        return wrong_answer(case)

    fake_adapter(monkeypatch, fixture_result=bridge)
    r = run_fixtures("teal")
    assert r["available"] and len(r["cases"]) == 17
    broken = next(c for c in r["cases"] if c["id"] == "fifty_move_draw")
    assert len(broken["errors"]) == 1 and "ValueError" in broken["errors"][0]
    assert "unavailable UCI move" in broken["errors"][0] and broken["visible"] == []
    suite = {case["id"]: case for case in load_suite()["cases"]}
    for c in r["cases"]:
        if c is not broken:
            assert c["errors"] == compare_result(suite[c["id"]], wrong_answer()) and c["visible"] == ["a1", "e2"]


# ---- the command ----

# Catches: a rules name that is neither accepted nor refused: run_fixtures guessing, or the command taking free text.
def test_unknown_rules_are_refused(capsys):
    with pytest.raises(ValueError, match="standin"):
        run_fixtures("fast")
    with pytest.raises(SystemExit) as stop:
        main(["--rules", "fast"])
    assert stop.value.code == 2 and "--rules" in capsys.readouterr().err


# Catches: failing cases turning into a non-zero exit (the stage runner would show a crash, not the boards), or anything
# but one JSON document reaching stdout.
def test_main_prints_the_json_and_exits_zero_when_cases_fail(monkeypatch, capsys):
    fake_adapter(monkeypatch, fixture_result=wrong_answer)
    assert main(["--rules", "teal"]) == 0
    out, err = capsys.readouterr()
    report = json.loads(out)  # all of stdout
    assert report == run_fixtures("teal")
    assert failing(report) and err == ""


# Catches: "this checkout does not have Teal's adapter" ending in a non-zero exit, which would show red where grey is
# meant.
def test_main_exits_zero_when_the_rules_are_not_here(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, ADAPTER, None)
    assert main(["--rules", "teal"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["available"], report["cases"]) == (False, []) and report["reason"]


# Catches: something the rules print (a debug line in an adapter, a banner) landing in the JSON the stage runner parses.
def test_main_keeps_whatever_the_rules_print_out_of_the_json(monkeypatch, capsys):
    def chatty(case):
        print("adapter says hello")
        return wrong_answer(case)

    fake_adapter(monkeypatch, fixture_result=chatty)
    assert main(["--rules", "teal"]) == 0
    out, err = capsys.readouterr()
    json.loads(out)
    assert "hello" not in out and "adapter says hello" in err


# Catches: a command with no --rules failing, or checking something other than the stand-in, which every checkout has.
def test_main_checks_the_stand_in_when_no_rules_are_named(capsys):
    assert main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["rules"], report["available"], len(report["cases"])) == ("standin", True, 17)


# ---- by path, as the stage runner starts it ----

# Catches: the file working only inside its package (a relative import, a sibling module, the working directory), which
# a by-path start meets as an ImportError; and stdout holding anything but the JSON. Same report as importing it.
@pytest.mark.parametrize("rules", ["standin", "teal"])
def test_runs_by_path_with_stage_code_first(rules, tmp_path):
    r = run_by_path(CHECK, rules, [REPO, REPO / "pair_b" / "src"], tmp_path)
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)  # all of stdout
    assert report == run_fixtures(rules)
    if rules == "standin":
        assert report["available"] and len(report["cases"]) == 17 and not failing(report)


# Catches: the file importing the app's own pairb (its package folder, the installed copy, or a path it adds to
# sys.path from where it lives) instead of the code the stage runner puts first, or needing pairb.lab, which a stage
# need not have, or a module beside it, which only the in-place start can find. The stage's pairb holds only an observe
# that sees every square, so what reaches the report shows which pairb was called.
@pytest.mark.parametrize("where", ["in place", "a copy elsewhere"])
def test_by_path_checks_the_code_first_on_pythonpath(where, tmp_path):
    pythonpath = make_stage(tmp_path / "stage", SEES_EVERYTHING)
    script = CHECK
    if where == "a copy elsewhere":
        (tmp_path / "elsewhere").mkdir()
        script = tmp_path / "elsewhere" / "fixture_check.py"
        shutil.copy2(CHECK, script)
    r = run_by_path(script, "standin", pythonpath, tmp_path)
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)
    assert report["available"] and len(report["cases"]) == 17, report["reason"]
    assert all(len(c["visible"]) == 64 for c in report["cases"])  # the stage's view, not the checkout's
    assert len(failing(report)) > 5  # and the fixtures caught it


# Catches: the false green found on 19 Oct against origin/main, which has no pairb: the environment's editable install
# supplied this checkout's, and 17 positions passed that the stage never had a stand-in for. Teal's adapter is installed
# nowhere, so a stage without it is told by the plain import; this keeps that covered by path once this checkout has it.
def test_by_path_in_a_stage_without_pairb_is_unavailable(tmp_path):
    r = run_by_path(CHECK, "standin", make_stage(tmp_path / "stage"), tmp_path)
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)
    assert (report["available"], report["cases"]) == (False, [])
    assert "pairb.observe" in report["reason"] and "not in this checkout" in report["reason"]
    r = run_by_path(CHECK, "teal", make_stage(tmp_path / "stage2"), tmp_path)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["available"] is False
