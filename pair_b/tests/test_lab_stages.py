"""The stages Fog Lab merges one by one, and the commands each stage runs (pairb.lab.stages, the pure parts).

Nothing here calls git, and stage_checks only describes what to run, so the tests look at the argument lists, working
folders, environments, config data and "unavailable" reasons it gives. That is why paths with spaces and Windows-style
paths can be tested on any machine: the interpreters in these tests are made-up paths that nothing runs (one test runs
the import check for real, in this interpreter), and every expectation is a literal, copied from the 18 Oct staged run
(fog-lab-reference/ci_stages2.sh), from Bryan's harness, or from the design (spec 5.1).
"""
import dataclasses
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

from no_torch import PAIR_B, run_without_torch
from pairb.lab import scorers
from pairb.lab.paths import venv_python
from pairb.lab.scorers import CHECKPOINTS, LABELS, SCORER_IDS
from pairb.lab.stages import (Check, Envs, Stage, find_envs, harness_config, harness_paths, imports_ok, load_stages,
                              pair_a_setup_commands, parse_pytest_summary, stage_checks, stage_env)

STAGES_FILE = PAIR_B / "fog_lab_stages.json"
PY_B = Path("/x/pair_b/.venv/bin/python")  # made up: nothing here runs an interpreter
PY_A = Path("/x/pair_a_prep/.venv/bin/python")
NO_TORCH = "needs torch, which this machine does not have"
NO_PAIR_A = "Pair A's environment not set up here: "
NO_ADAPTER = "the belief network's adapter (pairb/harness_adapter.py) is not in this stage"
NO_PAIR_B = "Pair B's code is not in this stage yet (there is no pair_b folder)"
BRYAN = "pair_b_prep.real_adapter:build"
BELIEF = "pairb.harness_adapter:build"
IMPORTS_B = "import pairb, fow_shared; print(pairb.__file__); print(fow_shared.__file__)"
IMPORTS_A = "import fow_shared, pair_a_prep; print(fow_shared.__file__); print(pair_a_prep.__file__)"
PYTEST = ("-m", "pytest", "-q", "-p", "no:cacheprovider")
ALL_KEYS = ["imports_b", "pair_b", "imports_a", "shared", "bryan_tests", "harness:material", "harness:stockfish-d1",
            "harness:stockfish-d11", "harness:network1", "harness:belief", "history", "observe_vs_teal"]


def write_stages(tmp_path, document) -> Path:
    path = tmp_path / "stages.json"
    path.write_text(document if isinstance(document, str) else json.dumps(document), encoding="utf-8")
    return path


def make_stage(tmp_path, *, bryan=False, teal=False, adapter=True, pair_b=True) -> Path:
    """A stage folder holding what decides the checks: Pair B's folder (origin/main has none), Bryan's folder, Teal's
    rules adapter, and our belief-network adapter for his harness, which a stage has once this build's code is in it
    (the stages before that do not)."""
    stage = tmp_path / "stage"
    stage.mkdir(parents=True)
    if pair_b:
        (stage / "pair_b").mkdir()
    if adapter:
        (stage / "pair_b" / "src" / "pairb").mkdir(parents=True, exist_ok=True)
        (stage / "pair_b" / "src" / "pairb" / "harness_adapter.py").write_text("", encoding="utf-8")
    if bryan:
        (stage / "pair_b_prep").mkdir()
    if teal:
        (stage / "pair_a_prep").mkdir()
        (stage / "pair_a_prep" / "rules_adapter.py").write_text("", encoding="utf-8")
    return stage


def checks_of(stage, *, envs=Envs(PY_B, PY_A), out=None, sha="abc123", torch=True, stockfish="stockfish",
              device=None) -> dict[str, Check]:
    out = stage.parent / "run" if out is None else out
    checks = stage_checks(stage, envs, out, sha, torch=torch, stockfish=stockfish, device=device)
    assert len({c.key for c in checks}) == len(checks), "a key is used twice"
    return {c.key: c for c in checks}


# ---- the shapes Task 15's runner consumes ----

# Catches: a field renamed, reordered or made mutable. The runner, the run summary and the page all read these.
def test_the_records_have_the_agreed_fields():
    assert [(f.name, f.default) for f in dataclasses.fields(Stage)] == [("label", dataclasses.MISSING),
                                                                         ("ref", dataclasses.MISSING), ("title", "")]
    assert [f.name for f in dataclasses.fields(Envs)] == ["pair_b_python", "pair_a_python"]
    fields = dataclasses.fields(Check)
    assert [f.name for f in fields] == ["key", "label", "argv", "cwd", "unavailable", "config"]
    assert fields[-1].default is None
    for record in (Stage("a", "b"), Envs(PY_B, None), Check("k", "l", (), Path("."), None)):
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.extra = 1


# ---- the stages file ----

# Catches: a stage added, dropped or reordered in the file, or a ref, label or title that differs from spec 5.1 and
# the approved mockup (the first stage's title leaves out the mockup's commit hash, which would go stale).
def test_loads_the_repo_stages_file():
    stages = load_stages(STAGES_FILE)
    assert stages == [
        Stage("main", "origin/main", "after PR #2"),
        Stage("+ PR #4", "origin/pair-b/evaluators", "Scorers, Network 1"),
        Stage("+ PR #6", "origin/pair-b/belief-network", "Belief network"),
        Stage("+ PR #5", "origin/pair-b/label-definitions", "Label definitions"),
        Stage("+ PR #3", "origin/pair-b/evaluator-validation-prep", "Bryan's harness"),
        Stage("+ Teal's branch", "origin/pair-a/rules-interface", "Rules adapter, PCFR+"),
    ]
    assert (stages[0].ref, stages[-1].ref) == ("origin/main", "origin/pair-a/rules-interface")


# Catches: a ref git could read as an option (-x), or one that is several words, reaching `git worktree add` and
# `git merge`. Control characters are refused too: a NUL cannot be passed in an argument list at all.
@pytest.mark.parametrize("ref", ["-x", "--upload-pack=evil", "-", "a b", " origin/main", "origin/main ", "a\tb",
                                 "a\nb", "a\u00a0b", "a\x00b", "a\x1bb", "", " ", "\t"])
def test_rejects_bad_refs(tmp_path, ref):
    path = write_stages(tmp_path, {"stages": [{"label": "x", "ref": ref}]})
    with pytest.raises(ValueError):
        load_stages(path)


# Catches: a ref that is not text (a number, null, a list) reaching git.
@pytest.mark.parametrize("ref", [5, None, ["origin/main"], {"a": 1}, True])
def test_rejects_refs_that_are_not_text(tmp_path, ref):
    with pytest.raises(ValueError):
        load_stages(write_stages(tmp_path, {"stages": [{"label": "x", "ref": ref}]}))


# Catches: a stage that is hard to tell from the others, or a ref that is merely unusual, being refused.
@pytest.mark.parametrize("ref", ["origin/main", "origin/pair-b/evaluators", "pair-b/fog-lab", "a1b2c3d", "HEAD~1",
                                 "refs/remotes/origin/main", "v1.0", "a-b"])
def test_accepts_ordinary_refs(tmp_path, ref):
    assert load_stages(write_stages(tmp_path, {"stages": [{"label": "x", "ref": ref}]}))[0].ref == ref


GOOD = {"label": "x", "ref": "origin/x"}


# Catches: an unusable file giving an empty list or a stage with a hole in it, so a run would quietly do nothing.
@pytest.mark.parametrize("document", [
    [],  # a list, not an object
    "stages",
    {},  # no "stages"
    {"stages": []},  # empty
    {"stages": {"label": "x", "ref": "origin/x"}},  # an object, not a list
    {"stages": "origin/main"},
    {"stages": [5]},  # an entry that is not an object
    {"stages": [GOOD, "origin/main"]},
    {"stages": [{"ref": "origin/x"}]},  # no label
    {"stages": [{"label": "x"}]},  # no ref
    {"stages": [{"label": "", "ref": "origin/x"}]},
    {"stages": [{"label": "  ", "ref": "origin/x"}]},
    {"stages": [{"label": 5, "ref": "origin/x"}]},
    {"stages": [{"label": None, "ref": "origin/x"}]},
    {"stages": [{"label": "x", "ref": "origin/x", "title": 5}]},
    {"stages": [{"label": "x", "ref": "origin/x", "title": None}]},
    {"stages": [GOOD, {"label": "y"}]},  # one bad stage spoils the file
], ids=lambda document: json.dumps(document)[:60])
def test_rejects_unusable_files(tmp_path, document):
    with pytest.raises(ValueError):
        load_stages(write_stages(tmp_path, document))


# Catches: a half-written or hand-broken file giving an error that does not say which file it is (a JSONDecodeError
# is a ValueError already, but names only a line and a column).
@pytest.mark.parametrize("text", ["", "{", '{"stages": [', "not json", "\ufeff", '{"stages": [{"label": "x",]}'])
def test_rejects_text_that_is_not_json(tmp_path, text):
    with pytest.raises(ValueError, match="stages.json"):
        load_stages(write_stages(tmp_path, text))


# Catches: a file saved in another encoding raising a bare UnicodeDecodeError that names neither the file nor a stage.
def test_rejects_bytes_that_are_not_utf8(tmp_path):
    path = tmp_path / "stages.json"
    path.write_bytes(b'{"stages": [{"label": "\xff\xfe", "ref": "origin/x"}]}')
    with pytest.raises(ValueError, match="stages.json"):
        load_stages(path)


# Catches: the error not saying which file or which stage to fix. A teammate edits this file by hand.
def test_an_error_names_the_file_and_the_stage(tmp_path):
    path = write_stages(tmp_path, {"stages": [GOOD, GOOD, {"label": "z", "ref": "-bad"}]})
    with pytest.raises(ValueError) as error:
        load_stages(path)
    assert "stages.json" in str(error.value) and "stage 3" in str(error.value) and "-bad" in str(error.value)


def test_a_file_that_is_not_there_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_stages(tmp_path / "nope.json")


# Catches: a title being required, or an extra key being refused, which would make a later field in the file break
# an older loader.
def test_a_stage_needs_only_a_label_and_a_ref(tmp_path):
    path = write_stages(tmp_path, {"stages": [{"label": "a", "ref": "origin/a"},
                                              {"label": "b", "ref": "origin/b", "title": "Second", "note": 1}],
                                   "comment": "ignored"})
    assert load_stages(path) == [Stage("a", "origin/a", ""), Stage("b", "origin/b", "Second")]


# Catches: stages read in the machine's encoding (cp1252 on a Windows laptop turns "é" into two characters), and an
# editor's byte-order mark making a good file unreadable.
def test_reads_utf8_with_or_without_a_byte_order_mark(tmp_path):
    stage = {"label": "Café", "ref": "origin/x", "title": "Règles, ✓"}
    document = json.dumps({"stages": [stage]}, ensure_ascii=False)
    expected = [Stage("Café", "origin/x", "Règles, ✓")]
    (tmp_path / "plain.json").write_bytes(document.encode("utf-8"))
    (tmp_path / "bom.json").write_bytes(b"\xef\xbb\xbf" + document.encode("utf-8"))
    assert load_stages(tmp_path / "plain.json") == expected
    assert load_stages(tmp_path / "bom.json") == expected


# Catches: a stage folded into the previous one, or the list changed in place: stages come back in file order, as
# new objects each time, and a str path works as well as a Path.
def test_keeps_file_order_and_accepts_a_str_path(tmp_path):
    path = write_stages(tmp_path, {"stages": [{"label": name, "ref": f"origin/{name}"} for name in "dcba"]})
    first, second = load_stages(str(path)), load_stages(path)
    assert [s.label for s in first] == list("dcba") and first == second and first is not second


# ---- finding the two environments ----

# Catches: Pair B's interpreter read from the stage, or from somewhere else than the app's own checkout. Its path is
# not checked for existing: a missing interpreter shows up as a failed check, not as a missing card.
def test_find_envs_names_both_interpreters(tmp_path):
    (tmp_path / "pair_a_prep" / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / "pair_a_prep" / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    envs = find_envs(tmp_path, windows=False)
    assert envs == Envs(tmp_path / "pair_b" / ".venv" / "bin" / "python",
                        tmp_path / "pair_a_prep" / ".venv" / "bin" / "python")
    assert find_envs(tmp_path / "other", windows=False).pair_b_python == tmp_path / "other/pair_b/.venv/bin/python"


# Catches: a missing Pair A environment being a made-up path (then "shared" would fail) instead of None (then it is
# unavailable). A folder where the interpreter should be, or a venv with the other platform's layout, is not one.
def test_find_envs_says_none_when_pair_a_has_no_environment(tmp_path):
    assert find_envs(tmp_path, windows=False).pair_a_python is None
    folder = tmp_path / "pair_a_prep" / ".venv" / "bin" / "python"
    folder.mkdir(parents=True)
    assert find_envs(tmp_path, windows=False).pair_a_python is None
    assert find_envs(tmp_path, windows=True).pair_a_python is None  # a Windows lookup does not find bin/python


def test_find_envs_with_a_windows_layout(tmp_path):
    scripts = tmp_path / "pair_a_prep" / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_text("", encoding="utf-8")
    envs = find_envs(tmp_path, windows=True)
    assert envs.pair_b_python.parts[-3:] == (".venv", "Scripts", "python.exe")
    assert envs.pair_b_python == venv_python(tmp_path / "pair_b", windows=True)
    assert envs.pair_a_python == scripts / "python.exe"
    assert find_envs(tmp_path, windows=False).pair_a_python is None


# Catches: the platform being fixed at import time, or ignored. None means the machine this runs on.
def test_find_envs_defaults_to_this_machine(tmp_path):
    assert find_envs(tmp_path).pair_b_python == venv_python(tmp_path / "pair_b")
    assert find_envs(tmp_path).pair_b_python == find_envs(tmp_path, windows=os.name == "nt").pair_b_python


# ---- the environment variables of a stage ----

# Catches: the app's own checkout staying importable ahead of the stage (an old PYTHONPATH kept), the stage's code
# not first, or bytecode / the locale's encoding leaking into the stage's files and logs.
def test_stage_env_puts_the_stage_first():
    stage = Path("/tmp/fog-lab-1/stage")
    base = {"PATH": "/usr/bin", "HOME": "/home/me", "PYTHONPATH": "/the/app/checkout", "PYTHONUTF8": "0",
            "PYTHONDONTWRITEBYTECODE": ""}
    env = stage_env(stage, base)
    assert env == {"PATH": "/usr/bin", "HOME": "/home/me", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": str(stage / "pair_b" / "src") + os.pathsep + str(stage)}
    assert base["PYTHONPATH"] == "/the/app/checkout" and base["PYTHONUTF8"] == "0"  # the caller's mapping is as it was
    assert "/the/app/checkout" not in env["PYTHONPATH"]


def test_stage_env_needs_no_pythonpath_to_start_from():
    assert stage_env(Path("/s"), {})["PYTHONPATH"] == os.pathsep.join([str(Path("/s/pair_b/src")), str(Path("/s"))])


# Catches: a path with a space, or a Windows one, being split or quoted inside PYTHONPATH. The two entries are
# separated by os.pathsep (";" on Windows), and each is a whole path.
def test_stage_env_keeps_paths_whole():
    stage = Path("/x/with space/stage")
    entries = stage_env(stage, {})["PYTHONPATH"].split(os.pathsep)
    assert entries == [str(stage / "pair_b" / "src"), str(stage)]


def test_stage_env_accepts_any_mapping_and_returns_a_dict():
    env = stage_env(Path("/s"), MappingProxyType({"A": "1"}))
    assert type(env) is dict and env["A"] == "1"


# ---- Pair A's setup commands, shown when its environment is missing ----

# Catches: a Mac user being told to run Windows' Scripts/python (it does not exist there), or Windows' `python`
# being spelled python3 (a Store stub on Windows). Both start from the repository's root, as Pair A's README does.
def test_setup_commands_in_each_platforms_spelling():
    mac = pair_a_setup_commands(windows=False)
    windows = pair_a_setup_commands(windows=True)
    assert "python3 -m venv pair_a_prep/.venv" in mac
    assert "pair_a_prep/.venv/bin/python -m pip install -r pair_a_prep/requirements.txt" in mac
    assert "Scripts" not in mac
    assert "python -m venv pair_a_prep/.venv" in windows and "python3" not in windows
    assert "pair_a_prep/.venv/Scripts/python.exe -m pip install -r pair_a_prep/requirements.txt" in windows
    assert "bin/python" not in windows
    assert "repository" in mac and "repository" in windows
    assert pair_a_setup_commands() == pair_a_setup_commands(windows=os.name == "nt")


# ---- which checks a stage gets ----

# Catches: a stage losing one of the checks every stage gets, or the order changing. The order is the order they run in
# and the order the cards fill in; the import checks come just before the tests they guard.
def test_every_stage_gets_four_checks(tmp_path):
    assert list(checks_of(make_stage(tmp_path))) == ["imports_b", "pair_b", "imports_a", "shared"]


# Catches: Bryan's checks run on a stage that lacks his folder (main has none), Teal's observe test on a stage with no
# rules adapter, or either missing from a stage that has the files.
@pytest.mark.parametrize("bryan, teal, extra", [
    (False, False, []),
    (True, False, ALL_KEYS[4:11]),
    (False, True, ["observe_vs_teal"]),
    (True, True, ALL_KEYS[4:]),
])
def test_checks_follow_what_the_stage_contains(tmp_path, bryan, teal, extra):
    assert list(checks_of(make_stage(tmp_path, bryan=bryan, teal=teal))) == ALL_KEYS[:4] + extra


def test_the_full_list_is_in_the_documented_order(tmp_path):
    assert list(checks_of(make_stage(tmp_path, bryan=True, teal=True))) == ALL_KEYS


# Catches: a leftover file named like Bryan's folder, or a folder named like Teal's adapter, counting as the real
# thing.
def test_only_a_folder_and_a_file_count(tmp_path):
    stage = make_stage(tmp_path)
    (stage / "pair_b_prep").write_text("", encoding="utf-8")  # a file, not a folder
    (stage / "pair_a_prep").mkdir()
    (stage / "pair_a_prep" / "rules_adapter.py").mkdir()  # a folder, not a file
    assert list(checks_of(stage)) == ALL_KEYS[:4]


# Catches: a command that differs from the 18 Oct staged run's (ci_stages2.sh) in interpreter, folder, flag or test
# selection. One literal per check. What the script did not have: -p no:cacheprovider (a throwaway folder stays clean),
# the two import checks, and --stockfish-path for the history check (a Windows user keeps the engine anywhere).
def test_every_command_is_the_one_from_the_18_oct_run(tmp_path):
    stage, out = make_stage(tmp_path, bryan=True, teal=True), tmp_path / "run"
    b, a, harness = str(PY_B), str(PY_A), out / "harness"
    checks = checks_of(stage, out=out, sha="1234abc", stockfish="stockfish", device=None)
    expected = {
        "imports_b": ((b, "-c", IMPORTS_B), stage / "pair_b"),
        "pair_b": ((b, *PYTEST), stage / "pair_b"),
        "imports_a": ((a, "-c", IMPORTS_A), stage),
        "shared": ((a, *PYTEST, "tests", "pair_a_prep/tests"), stage),
        "bryan_tests": ((b, "-m", "unittest", "pair_b_prep.test_harness"), stage),
        "history": ((b, "-m", "pair_b_prep.check_repetition", "--stockfish-path", "stockfish",
                     "--source-commit", "1234abc"), stage),
        "observe_vs_teal": ((b, *PYTEST, "tests/test_observe.py", "-k", "pair_as_observe"), stage / "pair_b"),
    }
    for scorer_id, adapter in zip(SCORER_IDS, (BRYAN, BRYAN, BRYAN, BRYAN, BELIEF)):
        expected[f"harness:{scorer_id}"] = ((b, "-m", "pair_b_prep.harness", "--adapter", adapter,
                                             "--config", str(harness / f"{scorer_id}.json"),
                                             "--out", str(harness / scorer_id)), stage)
    assert {key: (check.argv, check.cwd) for key, check in checks.items()} == expected
    for check in checks.values():
        assert type(check.argv) is tuple and all(type(arg) is str for arg in check.argv)
        assert type(check.cwd) is type(stage)


# Catches: a label changed on one side only. The page prints these, and Task 17 draws the cards from them. They are
# the mockup's words ("History check", "Our observe = Teal's") and the plan's.
def test_labels(tmp_path):
    labels = {key: check.label for key, check in checks_of(make_stage(tmp_path, bryan=True, teal=True)).items()}
    assert labels == {
        "imports_b": "Imports, Pair B", "pair_b": "Pair B", "imports_a": "Imports, shared + Pair A",
        "shared": "Shared + Pair A", "bryan_tests": "Bryan's tests", "history": "History check",
        "observe_vs_teal": "Our observe = Teal's", "harness:material": "Harness, Piece values",
        "harness:stockfish-d1": "Harness, Quick Stockfish", "harness:stockfish-d11": "Harness, Careful Stockfish",
        "harness:network1": "Harness, Network 1", "harness:belief": "Harness, Belief network"}


# Catches: the harness checks drifting from the scorer list the Play tab uses (ids, order, labels).
def test_one_harness_check_per_scorer_in_the_scorers_order(tmp_path):
    checks = checks_of(make_stage(tmp_path, bryan=True))
    harness = [check for key, check in checks.items() if key.startswith("harness:")]
    assert [c.key for c in harness] == [f"harness:{scorer_id}" for scorer_id in SCORER_IDS]
    assert [c.label for c in harness] == [f"Harness, {LABELS[scorer_id]}" for scorer_id in SCORER_IDS]


# Catches: the sha reaching only some of the places that record it. Bryan's report and his history check both name
# the revision they are about, and he says it must be given by the caller and never guessed.
def test_the_commit_reaches_the_history_check_and_every_harness_config(tmp_path):
    checks = checks_of(make_stage(tmp_path, bryan=True), sha="deadbeef")
    history = checks["history"].argv
    assert history[history.index("--source-commit") + 1] == "deadbeef"
    for scorer_id in SCORER_IDS:
        assert checks[f"harness:{scorer_id}"].config["source_commit"] == "deadbeef"


# ---- what is unavailable, and why (never failed) ----

# Catches: a missing Pair A environment failing the shared tests, or its import check, instead of greying them out
# with the commands that set it up. Everything that does not need that interpreter still runs.
def test_no_pair_a_env_is_unavailable_not_failed(tmp_path):
    checks = checks_of(make_stage(tmp_path, bryan=True, teal=True), envs=Envs(PY_B, None))
    reason = NO_PAIR_A + pair_a_setup_commands()
    assert checks["shared"].unavailable == reason and checks["imports_a"].unavailable == reason
    assert "pair_a_prep/requirements.txt" in reason and "-m venv pair_a_prep/.venv" in reason
    assert [key for key, check in checks.items() if check.unavailable] == ["imports_a", "shared"]
    assert checks["shared"].argv == () and checks["imports_a"].argv == ()  # no interpreter, so no command
    assert checks["shared"].cwd == tmp_path / "stage" and checks["imports_a"].cwd == tmp_path / "stage"
    assert checks["pair_b"].argv[0] == str(PY_B) and checks["bryan_tests"].argv[0] == str(PY_B)


def test_with_a_pair_a_env_nothing_is_unavailable(tmp_path):
    checks = checks_of(make_stage(tmp_path, bryan=True, teal=True))
    assert [check.unavailable for check in checks.values()] == [None] * len(ALL_KEYS)
    assert checks["shared"].argv[0] == str(PY_A) and checks["imports_a"].argv[0] == str(PY_A)


# Catches: the networks' harness runs failing on a machine with no torch (an Intel Mac) when they should be greyed
# out, or Stockfish's and piece values' runs being held back too. Pair B's tests stay available: they skip
# themselves without torch, and pytest says how many.
def test_networks_unavailable_without_torch(tmp_path):
    checks = checks_of(make_stage(tmp_path, bryan=True, teal=True), torch=False)
    assert {key: check.unavailable for key, check in checks.items() if check.unavailable} == {
        "harness:network1": NO_TORCH, "harness:belief": NO_TORCH}


# Catches: the Tests tab and the Play tab giving different words for the same missing torch. Each module spells the
# reason once (the scorers' constant is private), so this is what keeps the two equal.
def test_the_torch_reason_is_the_one_the_scorer_list_gives(tmp_path, monkeypatch):
    monkeypatch.setattr(scorers, "torch_available", lambda: False)
    listed = {info.id: info.reason for info in scorers.available_scorers(scorers.ScorerOptions(checkpoints=tmp_path))}
    checks = checks_of(make_stage(tmp_path, bryan=True), torch=False)
    for scorer_id in CHECKPOINTS:
        assert listed[scorer_id] == checks[f"harness:{scorer_id}"].unavailable == NO_TORCH


def test_networks_available_with_torch(tmp_path):
    checks = checks_of(make_stage(tmp_path, bryan=True), torch=True)
    assert checks["harness:network1"].unavailable is None and checks["harness:belief"].unavailable is None


# Catches: Pair B's checks being run, and ending in "No such file or directory" for their working folder, at the first
# stage, origin/main, which has no pair_b folder at all (Pair B's code arrives with PR #4). Its card in the mockup shows
# Shared + Pair A and nothing else. The Pair B checks stay in the list, greyed out; nothing else is held back.
def test_pair_b_checks_are_unavailable_in_a_stage_without_pair_b(tmp_path):
    stage = make_stage(tmp_path, adapter=False, pair_b=False)
    checks = checks_of(stage)
    assert list(checks) == ["imports_b", "pair_b", "imports_a", "shared"]
    assert {key: check.unavailable for key, check in checks.items() if check.unavailable} == {
        "imports_b": NO_PAIR_B, "pair_b": NO_PAIR_B}
    assert checks["pair_b"].argv == (str(PY_B), *PYTEST) and checks["pair_b"].cwd == stage / "pair_b"
    (stage / "pair_b").write_text("", encoding="utf-8")  # a file of that name is not Pair B either
    assert checks_of(stage)["pair_b"].unavailable == NO_PAIR_B
    (stage / "pair_b").unlink()
    (stage / "pair_b").mkdir()  # PR #4 arrives
    assert [check.unavailable for check in checks_of(stage).values()] == [None] * 4


# Catches: Teal's observe test (it runs in pair_b too) being left out of that rule, and the reason replacing another:
# a missing Pair A environment is still said for the checks that need it.
def test_the_observe_test_needs_pair_b_too(tmp_path):
    stage = make_stage(tmp_path, teal=True, adapter=False, pair_b=False)
    assert checks_of(stage)["observe_vs_teal"].unavailable == NO_PAIR_B
    checks = checks_of(stage, envs=Envs(PY_B, None))
    assert {key: check.unavailable for key, check in checks.items() if check.unavailable} == {
        "imports_b": NO_PAIR_B, "pair_b": NO_PAIR_B, "observe_vs_teal": NO_PAIR_B,
        "imports_a": NO_PAIR_A + pair_a_setup_commands(), "shared": NO_PAIR_A + pair_a_setup_commands()}


# Catches: the belief network's harness run failing, with "No module named pairb.harness_adapter", at every stage that
# has Bryan's harness but not our adapter for it (all the stages before this build's code, since that file is added by
# this build). That would turn their cards red for a reason that has nothing to do with their pull requests. The check
# stays in the list, greyed out with the reason, and the other four harness runs are untouched.
def test_the_belief_harness_is_unavailable_in_a_stage_without_its_adapter(tmp_path):
    stage = make_stage(tmp_path, bryan=True, adapter=False)
    checks = checks_of(stage)
    assert list(checks) == ALL_KEYS[:11]
    unavailable = {key: check.unavailable for key, check in checks.items() if check.unavailable}
    assert unavailable == {"harness:belief": NO_ADAPTER}
    assert checks["harness:belief"].config is not None and checks["harness:belief"].argv[0] == str(PY_B)
    (stage / "pair_b" / "src" / "pairb").mkdir(parents=True)  # the stage gets the adapter
    (stage / "pair_b" / "src" / "pairb" / "harness_adapter.py").write_text("", encoding="utf-8")
    assert [check.unavailable for check in checks_of(stage).values()] == [None] * 11


# Catches: the adapter's file being looked for somewhere other than where its module name says (the module is
# pairb.harness_adapter, in the stage's pair_b/src), or a folder of that name counting as the file.
def test_the_belief_adapter_is_looked_for_where_its_module_is(tmp_path):
    module = harness_config("belief", tmp_path, "abc", "stockfish", None)[0].split(":")[0]
    assert module == "pairb.harness_adapter"
    stage = make_stage(tmp_path, bryan=True, adapter=False)
    (stage / "pair_b" / "src" / "pairb" / "harness_adapter.py").mkdir(parents=True)  # a folder, not a file
    assert checks_of(stage)["harness:belief"].unavailable == NO_ADAPTER
    (stage / "pair_b" / "src" / "pairb" / "harness_adapter.py").rmdir()
    (stage / "pair_b" / "harness_adapter.py").write_text("", encoding="utf-8")  # the right name, the wrong folder
    assert checks_of(stage)["harness:belief"].unavailable == NO_ADAPTER


# Catches: a machine with no torch being told about the stage instead: the machine's own lack comes first, as in the
# scorer list (the stage's contents are not something the user can change on the spot).
def test_a_missing_torch_is_said_before_a_missing_adapter(tmp_path):
    checks = checks_of(make_stage(tmp_path, bryan=True, adapter=False), torch=False)
    assert checks["harness:belief"].unavailable == NO_TORCH and checks["harness:network1"].unavailable == NO_TORCH


# Catches: one reason hiding the other when both are missing: no torch and no Pair A environment are independent.
def test_both_kinds_of_unavailable_at_once(tmp_path):
    checks = checks_of(make_stage(tmp_path, bryan=True, teal=True), envs=Envs(PY_B, None), torch=False)
    assert {key: check.unavailable for key, check in checks.items() if check.unavailable} == {
        "imports_a": NO_PAIR_A + pair_a_setup_commands(), "shared": NO_PAIR_A + pair_a_setup_commands(),
        "harness:network1": NO_TORCH, "harness:belief": NO_TORCH}


# ---- the harness configs ----

# Catches: a key renamed, dropped or misspelt in the JSON Bryan's real_adapter and our belief adapter read
# (kind, depth, checkpoint, device, stockfish_path, source_commit). One literal per scorer. "device": None is a
# real key, null in the JSON: Bryan's adapter treats a missing key as "cpu" and a null as "pick the best".
def test_harness_configs_use_the_adapters_keys(tmp_path):
    stage, checkpoints = tmp_path / "stage", tmp_path / "stage" / "pair_b" / "checkpoints"

    def config(scorer_id):
        return harness_config(scorer_id, stage, "abc", "stockfish", None)

    assert config("material") == (BRYAN, {"kind": "material", "source_commit": "abc"})
    assert config("stockfish-d1") == (BRYAN, {"kind": "stockfish", "depth": 1, "stockfish_path": "stockfish",
                                              "source_commit": "abc"})
    assert config("stockfish-d11") == (BRYAN, {"kind": "stockfish", "depth": 11, "stockfish_path": "stockfish",
                                               "source_commit": "abc"})
    assert config("network1") == (BRYAN, {"kind": "network", "checkpoint": str(checkpoints / "net1-v2" / "best.pt"),
                                          "device": None, "stockfish_path": "stockfish", "source_commit": "abc"})
    assert config("belief") == (BELIEF, {"checkpoint": str(checkpoints / "belief-v1-d1" / "best.pt"),
                                         "device": None, "stockfish_path": "stockfish", "source_commit": "abc"})


# Catches: the device being dropped or forced for some scorers. Only the networks use it.
@pytest.mark.parametrize("device", [None, "cpu", "mps", "cuda"])
def test_the_device_reaches_only_the_networks(tmp_path, device):
    for scorer_id in SCORER_IDS:
        _, config = harness_config(scorer_id, tmp_path, "abc", "stockfish", device)
        if scorer_id in CHECKPOINTS:
            assert "device" in config and config["device"] == device
        else:
            assert "device" not in config


# Catches: a Stockfish path given at start-up being ignored by the harness (a Windows user keeps stockfish.exe
# anywhere), or being sent to piece values, which have no engine.
def test_a_custom_stockfish_path_reaches_the_scorers_that_use_an_engine(tmp_path):
    for scorer_id in SCORER_IDS:
        _, config = harness_config(scorer_id, tmp_path, "abc", "C:/Program Files/Stockfish/stockfish.exe", None)
        if scorer_id == "material":
            assert "stockfish_path" not in config
        else:
            assert config["stockfish_path"] == "C:/Program Files/Stockfish/stockfish.exe"


# Catches: a checkpoint path that is not the one the Play tab opens, or one taken from the app's checkout instead of
# the stage (the stage's own checkpoint is what its harness run is about).
def test_checkpoints_are_the_stages_own_and_the_play_tabs(tmp_path):
    stage = tmp_path / "a stage"
    for scorer_id, relative in CHECKPOINTS.items():
        _, config = harness_config(scorer_id, stage, "abc", "stockfish", None)
        assert Path(config["checkpoint"]) == stage / "pair_b" / "checkpoints" / relative


# Catches: a value that cannot be written as JSON (a Path, a tuple, a numpy number): the runner writes the file.
def test_a_config_survives_json(tmp_path):
    for scorer_id in SCORER_IDS:
        adapter, config = harness_config(scorer_id, tmp_path / "s", "abc", "stockfish", None)
        assert json.loads(json.dumps(config)) == config and type(adapter) is str


def test_an_unknown_scorer_is_refused(tmp_path):
    with pytest.raises(ValueError, match="nope"):
        harness_config("nope", tmp_path, "abc", "stockfish", None)


# Catches: a misspelt module name for our own adapter. Bryan's real_adapter cannot be looked for here (it arrives with
# PR #3); its name and keys were read from origin/pair-b/evaluator-validation-prep.
def test_the_belief_adapter_module_exists():
    module, factory = harness_config("belief", PAIR_B, "abc", "stockfish", None)[0].split(":")
    assert factory == "build" and importlib.util.find_spec(module) is not None


# ---- files: only the runner writes any ----

# Catches: stage_checks writing the config files (or making folders) itself. The runner does that, before each harness
# check, from Check.config; describing the checks must leave the disk alone (Ruling R25).
def test_stage_checks_writes_nothing(tmp_path):
    stage, out = make_stage(tmp_path, bryan=True, teal=True), tmp_path / "somewhere" / "run"
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    checks_of(stage, out=out)
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before
    assert not out.exists()


# Catches: a second check carrying a config (the brief: "no other check writes files"), a harness check without one,
# or the argument list naming a different file than the one the runner is told to write.
def test_harness_checks_carry_their_config_and_name_where_it_goes(tmp_path):
    stage, out = make_stage(tmp_path, bryan=True, teal=True), tmp_path / "run"
    checks = checks_of(stage, out=out, sha="abc", stockfish="sf", device="mps")
    assert [key for key, check in checks.items() if check.config is not None] == [f"harness:{s}" for s in SCORER_IDS]
    configs = []
    for scorer_id in SCORER_IDS:
        check = checks[f"harness:{scorer_id}"]
        adapter, config = harness_config(scorer_id, stage, "abc", "sf", "mps")
        config_file, report_dir = harness_paths(out, scorer_id)
        assert check.config == config
        assert check.argv[check.argv.index("--adapter") + 1] == adapter
        assert check.argv[check.argv.index("--config") + 1] == str(config_file)
        assert check.argv[check.argv.index("--out") + 1] == str(report_dir)
        configs.append(config_file)
    assert len(set(configs)) == 5  # one file each: a shared file would be overwritten by the next scorer
    assert all(out in path.parents for path in configs)


# Catches: the config sitting inside the report folder (Bryan's harness replaces what is in --out), or the two
# kinds of file of different scorers sharing a folder name.
def test_harness_paths(tmp_path):
    seen = set()
    for scorer_id in SCORER_IDS:
        config_file, report_dir = harness_paths(tmp_path / "run", scorer_id)
        assert config_file == tmp_path / "run" / "harness" / f"{scorer_id}.json"
        assert report_dir == tmp_path / "run" / "harness" / scorer_id
        assert report_dir not in config_file.parents
        seen |= {config_file, report_dir}
    assert len(seen) == 10


# ---- Windows paths and paths with spaces ----

# From the plan, verbatim: the interpreter path is one argument, spaces intact.
def test_windows_and_space_paths(tmp_path):
    out = tmp_path / "run"
    envs = Envs(Path("/x/with space/pair_b/.venv/Scripts/python.exe"), None)
    p = venv_python(Path("/x/with space/pair_b"), windows=True)
    assert p.parts[-3:] == (".venv", "Scripts", "python.exe")
    c = next(c for c in stage_checks(Path("/x/with space/stage"), envs, out, "abc", torch=True,
             stockfish="C:/Stockfish/stockfish.exe", device=None) if c.key == "pair_b")
    assert str(envs.pair_b_python) in c.argv   # one argument, spaces intact


# Catches: any path or command with a space in it being split, quoted or joined into a string. The stage, the output
# folder, both interpreters and the engine all have spaces here, and the engine is a Windows path.
def test_spaces_never_split_an_argument(tmp_path):
    stage = tmp_path / "with space" / "stage dir"
    (stage / "pair_b_prep").mkdir(parents=True)
    out = tmp_path / "out folder" / "run 1"
    py_b = Path("/x/with space/pair_b/.venv/Scripts/python.exe")
    py_a = Path("/x/with space/pair_a_prep/.venv/Scripts/python.exe")
    stockfish = "C:/Program Files/Stockfish/stockfish.exe"
    checks = checks_of(stage, envs=Envs(py_b, py_a), out=out, stockfish=stockfish, sha="abc")
    assert checks["pair_b"].argv == (str(py_b), *PYTEST) and checks["pair_b"].cwd == stage / "pair_b"
    assert checks["shared"].argv[0] == str(py_a) and checks["shared"].cwd == stage
    history = checks["history"].argv
    assert history[history.index("--stockfish-path") + 1] == stockfish
    for scorer_id in SCORER_IDS:
        check = checks[f"harness:{scorer_id}"]
        assert check.argv[check.argv.index("--config") + 1] == str(out / "harness" / f"{scorer_id}.json")
        assert check.argv[check.argv.index("--out") + 1] == str(out / "harness" / scorer_id)
        assert check.cwd == stage
        if scorer_id in CHECKPOINTS:
            assert Path(check.config["checkpoint"]) == stage / "pair_b" / "checkpoints" / CHECKPOINTS[scorer_id]
        if scorer_id != "material":
            assert check.config["stockfish_path"] == stockfish
    for check in checks.values():  # no quoting or padding was added to any argument
        for arg in check.argv:
            assert arg == arg.strip() and not arg.startswith(('"', "'")) and not arg.endswith(('"', "'")), arg


# Catches: a function that only works for Path arguments. Callers hand over what they have (the CLI gives strings).
def test_str_paths_work_as_well_as_paths(tmp_path):
    stage = make_stage(tmp_path, bryan=True, teal=True)
    kwargs = dict(torch=True, stockfish="stockfish", device=None)
    assert (stage_checks(str(stage), Envs(PY_B, PY_A), str(tmp_path / "run"), "abc", **kwargs)
            == stage_checks(stage, Envs(PY_B, PY_A), tmp_path / "run", "abc", **kwargs))
    assert find_envs(str(tmp_path)) == find_envs(tmp_path)
    assert stage_env(str(stage), {}) == stage_env(stage, {})
    assert harness_paths(str(tmp_path), "belief") == harness_paths(tmp_path, "belief")
    assert harness_config("belief", str(stage), "abc", "stockfish", None) == harness_config("belief", stage, "abc",
                                                                                              "stockfish", None)


# Catches: a Windows layout found by find_envs not reaching the commands.
def test_a_windows_layout_flows_through(tmp_path):
    scripts = tmp_path / "pair_a_prep" / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_text("", encoding="utf-8")
    envs = find_envs(tmp_path, windows=True)
    checks = checks_of(make_stage(tmp_path / "s", bryan=True), envs=envs)
    for key in ("imports_b", "pair_b", "bryan_tests", "history", "harness:material"):
        assert Path(checks[key].argv[0]).parts[-3:] == (".venv", "Scripts", "python.exe")
        assert checks[key].argv[0] == str(envs.pair_b_python)
    assert checks["shared"].argv[0] == str(scripts / "python.exe")


# ---- reading pytest's last line ----

# Catches: a count read from the wrong word, or a missing one not being zero. The first three lines are the plan's. The
# last block is pytest 9's subtests: it counts them apart from tests, as an item of their own ("4 subtests passed", and
# "1 subtests passed" for one), and the parser must neither give up on the line (all zeros, so a failing run showed
# 0 failed) nor add them to a count. The first two of those are the lines the review found; the next five are what the
# pinned pytest 9.1.1 printed with -q for scratch files (a failed or skipped subtest is counted under plain "failed" or
# "skipped" there); then its colored form and its -v form; the last three use keys pytest declares but 9.1.1 never
# printed, or an error beside subtests.
@pytest.mark.parametrize("line, counts", [
    ("160 passed, 1 skipped in 49.87s", {"passed": 160, "skipped": 1, "failed": 0, "errors": 0}),
    ("1 failed, 159 passed in 3.20s", {"passed": 159, "failed": 1, "skipped": 0, "errors": 0}),
    ("2 errors in 0.50s", {"passed": 0, "failed": 0, "skipped": 0, "errors": 2}),
    ("1 error in 0.10s", {"passed": 0, "failed": 0, "skipped": 0, "errors": 1}),
    ("1 failed, 2 passed, 3 skipped, 4 errors in 5.67s", {"passed": 2, "failed": 1, "skipped": 3, "errors": 4}),
    ("1 failed, 1 passed, 1 error in 0.60s", {"passed": 1, "failed": 1, "skipped": 0, "errors": 1}),
    ("717 passed, 3 skipped, 2 warnings in 85.30s", {"passed": 717, "skipped": 3, "failed": 0, "errors": 0}),
    ("1 passed, 4 deselected in 0.01s", {"passed": 1, "failed": 0, "skipped": 0, "errors": 0}),
    ("3 passed, 1 xfailed, 2 xpassed in 0.02s", {"passed": 3, "failed": 0, "skipped": 0, "errors": 0}),
    ("1 skipped in 0.01s", {"passed": 0, "failed": 0, "skipped": 1, "errors": 0}),
    ("160 passed in 61.00s (0:01:01)", {"passed": 160, "failed": 0, "skipped": 0, "errors": 0}),
    ("2 passed in 3601.5s (1:00:01)", {"passed": 2, "failed": 0, "skipped": 0, "errors": 0}),
    ("=========== 5 passed, 1 skipped in 0.30s ===========", {"passed": 5, "skipped": 1, "failed": 0, "errors": 0}),
    ("no tests ran in 0.01s", {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}),
    ("\x1b[32m160 passed\x1b[0m\x1b[32m in 49.87s\x1b[0m", {"passed": 160, "failed": 0, "skipped": 0, "errors": 0}),
    ("\x1b[31m\x1b[1m1 failed\x1b[0m, \x1b[32m159 passed\x1b[0m\x1b[31m in 3.20s\x1b[0m",
     {"passed": 159, "failed": 1, "skipped": 0, "errors": 0}),
    ("2 passed, 4 subtests passed in 0.01s", {"passed": 2, "failed": 0, "skipped": 0, "errors": 0}),
    ("1 failed, 3 passed, 1 skipped, 1 warning, 2 subtests passed in 0.01s",
     {"passed": 3, "failed": 1, "skipped": 1, "errors": 0}),
    ("3 passed, 4 subtests passed in 0.01s", {"passed": 3, "failed": 0, "skipped": 0, "errors": 0}),
    ("1 failed, 4 passed, 1 skipped, 1 warning, 2 subtests passed in 0.01s",
     {"passed": 4, "failed": 1, "skipped": 1, "errors": 0}),
    ("1 passed, 1 subtests passed in 0.00s", {"passed": 1, "failed": 0, "skipped": 0, "errors": 0}),
    ("2 failed, 1 passed, 2 subtests passed in 0.01s", {"passed": 1, "failed": 2, "skipped": 0, "errors": 0}),
    ("2 passed, 1 skipped, 2 subtests passed in 0.01s", {"passed": 2, "failed": 0, "skipped": 1, "errors": 0}),
    ("\x1b[31m\x1b[31m\x1b[1m1 failed\x1b[0m, \x1b[32m4 passed\x1b[0m, \x1b[33m1 skipped\x1b[0m, "
     "\x1b[33m1 warning\x1b[0m, \x1b[32m2 subtests passed\x1b[0m\x1b[31m in 0.02s\x1b[0m\x1b[0m",
     {"passed": 4, "failed": 1, "skipped": 1, "errors": 0}),
    ("===== 1 failed, 4 passed, 1 skipped, 1 warning, 2 subtests passed in 0.01s =====",
     {"passed": 4, "failed": 1, "skipped": 1, "errors": 0}),
    ("1 passed, 2 subtests failed in 0.01s", {"passed": 1, "failed": 0, "skipped": 0, "errors": 0}),
    ("1 passed, 1 subtests skipped in 0.01s", {"passed": 1, "failed": 0, "skipped": 0, "errors": 0}),
    ("2 errors, 3 passed, 2 subtests passed in 0.50s (0:00:00)", {"passed": 3, "failed": 0, "skipped": 0, "errors": 2}),
])
def test_parse_pytest_summary(line, counts):
    assert parse_pytest_summary(line) == counts
    assert parse_pytest_summary("some output\n" + line + "\n") == counts  # as the last line of real output
    assert parse_pytest_summary(line + "\r\n") == counts  # a Windows line ending


ZEROS = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}


# Catches: output with no summary (a crash before pytest finished, or a check that is not pytest) raising, or
# inventing counts from a line that only looks like one.
@pytest.mark.parametrize("text", [
    "", "\n\n", "Traceback (most recent call last):\n  File \"x.py\", line 1\nImportError: no module named x\n",
    "tests/test_a.py::test_x PASSED\n", "FAILED tests/test_a.py::test_x - assert 3 passed == 4\n",
    "5 passed", "5 passed in", "passed in 3s", "in 3.2s", "Ran 11 tests in 0.002s\n\nOK\n",
    "2 passed, 4 subtests passed", "4 subtests passed in",
    "the run went well: 5 passed in 1.0s, honest\n",  # a sentence that contains one
])
def test_parse_pytest_summary_finds_nothing(text):
    assert parse_pytest_summary(text) == ZEROS


# Catches: the first summary-like line winning (a test that prints its own), a dict that misses a key, or the
# counts of two lines being added together.
def test_parse_pytest_summary_takes_the_last_line_of_a_real_output():
    text = ("....F.s...                                                               [100%]\n"
            "=================================== FAILURES ===================================\n"
            "___________________________________ test_x ___________________________________\n"
            "    print('5 passed in 1.0s')\n"
            "E   assert 3 passed == 4\n"
            "----------------------------- Captured stdout call -----------------------------\n"
            "5 passed in 1.0s\n"
            "=========================== short test summary info ============================\n"
            "FAILED tests/test_a.py::test_x - assert 3 passed == 4\n"
            "1 failed, 7 passed, 1 skipped in 0.31s\n")
    assert parse_pytest_summary(text) == {"passed": 7, "failed": 1, "skipped": 1, "errors": 0}
    assert set(parse_pytest_summary(text)) == {"passed", "failed", "errors", "skipped"}
    assert parse_pytest_summary(text + "Exception ignored in: <something>\n") == parse_pytest_summary(text)
    assert parse_pytest_summary("2 passed in 1s\n3 failed in 2s\n") == {"passed": 0, "failed": 3, "skipped": 0,
                                                                         "errors": 0}


# A scratch test file for the real pytest: four plain tests (two pass, one fails, one skips), a test that passes with
# three subtests and a unittest test that passes with two, so pytest 9 has plain results and five passing subtests.
SUBTESTS_SAMPLE = """\
import unittest

import pytest


def test_passes():
    pass


def test_also_passes():
    pass


def test_fails():
    assert False


def test_skips():
    pytest.skip("not today")


def test_loops_with_subtests(subtests):
    for i in range(3):
        with subtests.test(i=i):
            assert True


class TestUnittestStyle(unittest.TestCase):
    def test_loops_with_subTest(self):
        for i in range(2):
            with self.subTest(i=i):
                self.assertTrue(True)
"""


# Catches: a summary line the parser has only seen written down by hand. This one is printed by the pinned pytest
# itself, run as the stage commands run it (-m pytest -q -p no:cacheprovider) on a scratch folder of its own: pytest 9
# gives passing subtests an item of their own ("5 subtests passed"), the parser once read any line with one as no
# summary and so showed 0 failed for a failing run, and a subtest must not be added to "passed". Skipped where pytest
# has no subtests (it is then not the pinned one).
@pytest.mark.skipif(pytest.version_tuple < (9,), reason="needs pytest 9, which reports subtests")
def test_parse_pytest_summary_on_a_real_run_with_subtests(tmp_path):
    (tmp_path / "pytest.ini").write_text("", encoding="utf-8")  # this folder is the root: no other settings apply
    (tmp_path / "test_sample.py").write_text(SUBTESTS_SAMPLE, encoding="utf-8")
    env = {name: value for name, value in os.environ.items() if name != "PYTEST_ADDOPTS"}
    ran = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--color=no"], cwd=tmp_path,
                         env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=120)
    assert ran.returncode == 1, ran.stdout + ran.stderr  # the sample has a failing test
    assert "5 subtests passed" in ran.stdout, ran.stdout  # the item this test is about, as this pytest words it
    assert parse_pytest_summary(ran.stdout) == {"passed": 4, "failed": 1, "errors": 0, "skipped": 1}, ran.stdout


# ---- the import check ----

# From the plan: paths under the stage pass, one under the checkout fails.
def test_imports_ok(tmp_path):
    stage, checkout = tmp_path / "stage", tmp_path / "checkout"
    inside = [stage / "pair_b" / "src" / "pairb" / "__init__.py", stage / "fow_shared" / "__init__.py"]
    stdout = "".join(f"{path}\n" for path in inside)
    assert imports_ok(stdout, stage)
    assert not imports_ok(stdout + f"{checkout / 'pair_b' / 'src' / 'pairb' / '__init__.py'}\n", stage)
    assert not imports_ok(f"{checkout / 'fow_shared' / '__init__.py'}\n" + stdout, stage)


# Catches: an import check that printed nothing counting as a pass. Nothing printed proves nothing.
@pytest.mark.parametrize("stdout", ["", "\n", "  \n\n \r\n"])
def test_imports_ok_needs_at_least_one_path(tmp_path, stdout):
    assert not imports_ok(stdout, tmp_path / "stage")


# Catches: blank lines, indentation and Windows line endings in the printed output failing a good stage.
def test_imports_ok_ignores_blank_lines_and_line_endings(tmp_path):
    stage = tmp_path / "stage"
    first, second = stage / "pair_b" / "src" / "pairb" / "__init__.py", stage / "fow_shared" / "__init__.py"
    assert imports_ok(f"\n{first}\r\n\r\n  {second}  \r\n", stage)


# Catches: a prefix test on strings: "stage-old" starts with "stage" but is another folder; and a path that climbs out
# of the stage with ".." (python can print one when a path entry is relative).
def test_imports_ok_compares_whole_folders(tmp_path):
    stage = tmp_path / "stage"
    assert not imports_ok(f"{tmp_path / 'stage-old' / 'fow_shared' / '__init__.py'}\n", stage)
    assert not imports_ok(f"{stage / '..' / 'checkout' / 'fow_shared' / '__init__.py'}\n", stage)
    assert not imports_ok(f"{tmp_path / 'fow_shared' / '__init__.py'}\n", stage)
    assert imports_ok(f"{stage / 'a' / '..' / 'fow_shared' / '__init__.py'}\n", stage)  # still inside


# Catches: a printed "None" (a package with no file) or any relative path being read as inside the stage when the
# process happens to run there. Module paths are absolute.
@pytest.mark.parametrize("line", ["None", "fow_shared/__init__.py", "./pairb/__init__.py", "<frozen os>",
                                  "Traceback (most recent call last):"])
def test_imports_ok_refuses_what_is_not_an_absolute_path(tmp_path, line, monkeypatch):
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.chdir(stage)
    assert not imports_ok(line + "\n", stage)
    assert not imports_ok(f"{stage / 'fow_shared' / '__init__.py'}\n{line}\n", stage)


# Catches: a stage folder given in another spelling than python prints it: with a ".." in it, or as a str.
def test_imports_ok_resolves_the_stage_folder(tmp_path):
    (tmp_path / "elsewhere").mkdir()
    stage = tmp_path / "elsewhere" / ".." / "stage"
    assert imports_ok(f"{tmp_path / 'stage' / 'fow_shared' / '__init__.py'}\n", stage)
    assert not imports_ok(f"{tmp_path / 'elsewhere' / 'fow_shared' / '__init__.py'}\n", stage)
    assert imports_ok(f"{tmp_path / 'stage' / 'fow_shared' / '__init__.py'}\n", str(stage))


# Catches: the import check really passing on the code it is meant to guard: the argument list of imports_b, run for
# real with the stage's PYTHONPATH, prints paths under the stage. Here the "stage" is a copy of the packages, so the
# check must see the copy and not this checkout, which also has them installed. Needs nothing but this interpreter.
def test_the_import_check_sees_the_stage_not_the_checkout(tmp_path):
    stage = tmp_path / "a stage"
    skip = shutil.ignore_patterns("__pycache__")
    shutil.copytree(PAIR_B / "src" / "pairb", stage / "pair_b" / "src" / "pairb", ignore=skip)
    shutil.copytree(PAIR_B.parent / "fow_shared", stage / "fow_shared", ignore=skip)
    check = checks_of(stage, envs=Envs(Path(sys.executable), None))["imports_b"]
    ran = subprocess.run(check.argv, cwd=check.cwd, env=stage_env(stage, os.environ), capture_output=True,
                         encoding="utf-8", errors="replace", timeout=120)
    assert ran.returncode == 0, ran.stderr
    assert len(ran.stdout.splitlines()) == 2  # one path each for pairb and fow_shared
    assert imports_ok(ran.stdout, stage)
    # The same command without the stage first on the path finds the checkout's copies, and the check says so.
    plain = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    ran = subprocess.run(check.argv, cwd=check.cwd, env=plain, capture_output=True, encoding="utf-8",
                         errors="replace", timeout=120)
    assert ran.returncode == 0, ran.stderr
    assert not imports_ok(ran.stdout, stage)


# ---- importing the module ----

# Catches: stages.py reaching for torch (through the scorers or anything else) and so failing to import on an Intel
# Mac. run_without_torch makes `import torch` raise, which is what shows as a crash here; the block is also still the
# None it put in sys.modules, so nothing imported a real torch and swapped it out.
def test_the_module_imports_without_torch():
    ran = run_without_torch("import sys; import pairb.lab.stages; print(sys.modules['torch'] is None)", PAIR_B)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip() == "True"
