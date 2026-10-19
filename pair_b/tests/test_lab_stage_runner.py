"""The stage runner of Fog Lab's Tests tab (pairb.lab.stage_runner): the stages merged one by one in a throwaway git
worktree, each stage's checks run there, and the last cleanly built stage's fog rules, harness reports and accuracy
files read before the worktree goes.

The run_stages tests never run against this repository. Each builds a scratch repository in tmp_path (main and the
branches a, which adds a.txt, b, which adds a different a.txt and so conflicts with a, and c, which adds c.txt) and
hands the runner a fake check_runner that runs nothing: it records each call and what the stage's folder held at that
moment, and passes. The run_check tests start real, tiny commands (this interpreter, a two-line pytest file) in
tmp_path, never a real suite.
"""
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from no_torch import PAIR_B
from pair_a_prep.fixtures import load_suite
from pairb.lab import stage_runner
from pairb.lab.accuracy import read_accuracy
from pairb.lab.stage_runner import CheckResult, StageResult, run_check, run_stages
from pairb.lab.stages import Check, Stage, stage_env

REPO = PAIR_B.parent
PYTEST = ("-m", "pytest", "-q", "-p", "no:cacheprovider")
EVAL = "pair_b/checkpoints/net1-v2/eval-d2-check-train.json"
NO_TORCH = "needs torch, which this machine does not have"
# The variables that tell git which repository, index or work tree to use (`git rev-parse --local-env-vars`, and two
# more). An inherited one would point these tests' own git commands somewhere else, so the helper drops them (the
# runner must too: one test checks it).
GIT_LOCATION = ("GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
                "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE",
                "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX", "GIT_SHALLOW_FILE",
                "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES")


# ---- scratch repositories ----

def git(where, *args) -> str:
    """git in `where`, as a person with a name who never signs, with the repository-location variables dropped and no
    optional locks (so `git status` here never rewrites an index the tests compare). Returns its stdout."""
    env = {name: value for name, value in os.environ.items() if name.upper() not in GIT_LOCATION}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    done = subprocess.run(["git", "-C", str(where), "-c", "user.name=Scratch", "-c", "user.email=scratch@localhost",
                           "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args],
                          env=env, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace",
                          timeout=120)
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed in {where}: {done.stderr}")
    return done.stdout


def commit(repo, files: dict[str, str], message: str) -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "add", "--", *files)
    git(repo, "commit", "-q", "--no-verify", "-m", message)


def branch(repo, name, files, base="main") -> None:
    """A branch `name` off `base` with one commit holding `files`; the checkout goes back to where it was."""
    was = git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    git(repo, "checkout", "-q", "-b", name, base)
    commit(repo, files, name)
    git(repo, "checkout", "-q", was)


def make_repo(path, main=None) -> Path:
    """A scratch repository on main, with the branches a, b (whose a.txt conflicts with a's) and c. Main holds a
    pair_b folder, so each stage gets Pair B's checks to run (and Pair A's, unavailable without Pair A's
    environment)."""
    path.mkdir(parents=True)
    git(path, "init", "-q")
    commit(path, main or {"README.md": "scratch\n", "pair_b/notes.txt": "main\n"}, "main")
    branch(path, "a", {"a.txt": "from a\n"})
    branch(path, "b", {"a.txt": "from b\n"})
    branch(path, "c", {"c.txt": "from c\n"})
    return path


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "checkout")


def rev(repo, ref) -> str:
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def worktrees(repo) -> set[Path]:
    listed = git(repo, "worktree", "list", "--porcelain")
    return {Path(line[len("worktree "):]).resolve() for line in listed.splitlines() if line.startswith("worktree ")}


def link_venv(repo) -> None:
    """Give the scratch checkout this interpreter's environment as its pair_b/.venv, where the runner looks for Pair B's
    interpreter, so the fog-rules check really runs. Skips where that cannot be done."""
    if sys.prefix == sys.base_prefix:
        pytest.skip("the tests are not running in a virtual environment")
    try:
        (repo / "pair_b" / ".venv").symlink_to(Path(sys.prefix), target_is_directory=True)
    except OSError as error:  # Windows without the right to make links
        pytest.skip(f"cannot link the environment here: {error}")


def stages_of(*refs) -> list[Stage]:
    return [Stage(ref if number == 0 else f"+ {ref}", ref) for number, ref in enumerate(refs)]


def run(checkout, refs, run_dir, runner, **options):
    options.setdefault("fetch", False)
    options.setdefault("torch", False)
    return run_stages(checkout, stages_of(*refs), run_dir, check_runner=runner, **options)


def merges(summary) -> list[tuple[str, str]]:
    return [(stage["label"], stage["merge"]) for stage in summary["stages"]]


@dataclasses.dataclass
class Call:
    index: int  # the stage's position, from the log file's name (<index>-<key>.txt)
    check: Check
    env: dict
    log_path: Path
    root: Path  # the stage's folder: the last entry of the PYTHONPATH the stage environment sets
    files: list[str]  # what the stage's folder held when the check was handed over


class FakeRunner:
    """A check_runner that runs nothing. It records each call, writes a one-line log as run_check would, and passes; an
    unavailable check stays unavailable, as run_check has it. `on_call(check, env, log_path)` runs first, on each call:
    a test uses it to look at the stage, to write a harness report, or to raise."""

    def __init__(self, on_call=None):
        self.calls: list[Call] = []
        self.on_call = on_call

    def __call__(self, check, env, log_path):
        root = Path(env["PYTHONPATH"].split(os.pathsep)[-1])
        files = sorted(p.name for p in root.iterdir() if p.name != ".git")
        index = int(Path(log_path).name.split("-", 1)[0])
        self.calls.append(Call(index, check, dict(env), Path(log_path), root, files))
        if self.on_call is not None:
            self.on_call(check, env, log_path)
        if check.unavailable is not None:
            return CheckResult(check.key, check.label, "unavailable", check.unavailable, {}, None)
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(f"ran {check.key}\n", encoding="utf-8")
        return CheckResult(check.key, check.label, "pass", "passed", {}, str(log_path))


PAIR_B_KEYS = ["imports_b", "pair_b", "imports_a", "shared"]  # what a stage with a pair_b folder gets


class StoppableRunner(FakeRunner):
    """A FakeRunner that takes the stop event the way run_stages hands it to a check runner (cancel=), keeping each one
    it got in `events`. A check that `hold(check, stage folder)` picks is held until the run is stopped, and then comes
    back failed, "stopped", as run_check has a stopped check (R29)."""

    def __init__(self, hold=lambda check, root: False, on_call=None):
        super().__init__(on_call)
        self.hold, self.events = hold, []

    def __call__(self, check, env, log_path, *, cancel):
        self.events.append(cancel)
        result = super().__call__(check, env, log_path)
        if self.hold(check, self.calls[-1].root):
            assert cancel.wait(60), "the run was never stopped"
            return CheckResult(check.key, check.label, "fail", "stopped", {}, str(log_path))
        return result


# ---- the records ----

# Catches: a field renamed, reordered or dropped. Task 16 saves these as JSON and Task 17 draws them.
def test_the_records_have_the_agreed_fields():
    assert [f.name for f in dataclasses.fields(CheckResult)] == ["key", "label", "status", "summary", "counts", "log"]
    assert [f.name for f in dataclasses.fields(StageResult)] == ["label", "ref", "sha", "merge", "conflicts", "checks",
                                                                  "title"]
    assert StageResult("main", "origin/main", None, "skipped", [], []).title == ""


# ---- merging the stages ----

# Catches: stages merged out of order or not at all, checks run in the checkout instead of the worktree, a worktree
# left behind, the stage environment not used, or the user's PYTEST_ADDOPTS reaching the stages (R27).
def test_merges_in_order_and_runs_checks(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "-qq")  # -qq prints no summary line, so the counts would all read 0
    runner = FakeRunner()
    summary = run(repo, ["main", "a", "c"], tmp_path / "run", runner)

    assert merges(summary) == [("main", "clean"), ("+ a", "clean"), ("+ c", "clean"), ("+ this checkout", "contained")]
    assert [stage["sha"] for stage in summary["stages"]] == [rev(repo, ref) for ref in ("main", "a", "c", "HEAD")]
    assert [(call.index, call.check.key) for call in runner.calls] == [
        (index, key) for index in range(3) for key in PAIR_B_KEYS]
    assert {call.index: call.files for call in runner.calls} == {
        0: ["README.md", "pair_b"], 1: ["README.md", "a.txt", "pair_b"], 2: ["README.md", "a.txt", "c.txt", "pair_b"]}

    roots = {call.root for call in runner.calls}
    assert len(roots) == 1, "every stage is built in the same worktree"
    root = roots.pop()
    assert root.name == "stage" and root.parent.name.startswith("fog-lab-")
    assert root.parent.parent == Path(tempfile.gettempdir()).resolve()

    def not_git(env):  # which git variables a stage keeps is the decoy test's business
        return {name: value for name, value in env.items() if not name.upper().startswith("GIT_")}

    expected_env = not_git(stage_env(root, os.environ))
    del expected_env["PYTEST_ADDOPTS"]
    for call in runner.calls:
        assert call.check.cwd in (root, root / "pair_b")
        assert not_git(call.env) == expected_env
        assert call.env["PYTHONPATH"] == os.pathsep.join((str(root / "pair_b" / "src"), str(root)))
        assert "PYTEST_ADDOPTS" not in call.env
    assert not root.parent.exists(), "the temporary folder is removed afterwards"
    assert worktrees(repo) == {repo.resolve()}


# Catches: a later stage merged after a conflict, the conflicting files not listed, or the merge left half done so the
# final sections read a broken tree instead of the last clean stage.
def test_conflict_stops_later_stages(repo, tmp_path):
    runner = FakeRunner()
    summary = run(repo, ["main", "a", "b", "c"], tmp_path / "run", runner)

    assert merges(summary) == [("main", "clean"), ("+ a", "clean"), ("+ b", "conflict"), ("+ c", "skipped"),
                               ("+ this checkout", "skipped")]
    conflict, skipped, final = summary["stages"][2:]
    assert (conflict["conflicts"], conflict["sha"], conflict["checks"]) == (["a.txt"], rev(repo, "b"), [])
    assert skipped == {"label": "+ c", "ref": "c", "sha": None, "merge": "skipped", "conflicts": [], "checks": [],
                       "title": ""}
    assert final["merge"] == "skipped" and final["checks"] == []
    assert {call.index for call in runner.calls} == {0, 1}
    assert summary["final"]["label"] == "+ a"
    assert worktrees(repo) == {repo.resolve()}


# Catches: the final sections read from anywhere but the last cleanly built stage, or a conflict left in the worktree
# (git merge --abort not run): the conflicting file would then hold conflict markers and could not be read.
def test_the_final_sections_use_the_last_clean_stage(repo, tmp_path):
    source = json.loads((REPO / EVAL).read_text(encoding="utf-8"))

    def eval_file(mae):
        return json.dumps({**source, "network": {**source["network"], "mae": mae}}, indent=2) + "\n"

    branch(repo, "a2", {EVAL: eval_file(0.111)})
    branch(repo, "b2", {EVAL: eval_file(0.222)})
    summary = run(repo, ["main", "a2", "b2"], tmp_path / "run", FakeRunner())

    assert merges(summary) == [("main", "clean"), ("+ a2", "clean"), ("+ b2", "conflict"),
                               ("+ this checkout", "skipped")]
    assert summary["stages"][2]["conflicts"] == [EVAL]
    final = summary["final"]
    assert final["label"] == "+ a2"
    assert not (repo / EVAL).exists(), "the checkout has no such file: the one read is the stage's"
    table = final["accuracy"]["tables"][0]
    assert table["title"] == "Network 1, on fresh games"
    assert [row["values"][0] for row in table["rows"] if row["key"] == "network"] == [0.111]
    assert final["accuracy"]["missing"] == ["belief-v1-d1/eval-d6-check-train.json",
                                            "belief-v1-d1/eval-children-d16.json"]


# Catches: the checkout's own commits never tested, tested twice, or tested with the user's uncommitted edits.
def test_this_checkout_contained_or_merged(repo, tmp_path):
    git(repo, "checkout", "-q", "c")
    runner = FakeRunner()
    summary = run(repo, ["main", "a", "c"], tmp_path / "run1", runner)
    assert summary["stages"][-1] == {"label": "+ this checkout", "ref": "HEAD", "sha": rev(repo, "c"),
                                     "merge": "contained", "conflicts": [], "checks": [], "title": "c"}
    assert {call.index for call in runner.calls} == {0, 1, 2}
    assert summary["final"]["label"] == "+ c"

    git(repo, "checkout", "-q", "-b", "mine", "main")
    commit(repo, {"mine.txt": "committed\n"}, "mine")
    (repo / "mine.txt").write_text("not committed\n", encoding="utf-8")
    seen = []

    def look(check, env, log_path):
        mine = Path(env["PYTHONPATH"].split(os.pathsep)[-1]) / "mine.txt"
        seen.append(mine.read_text(encoding="utf-8") if mine.exists() else None)

    runner = FakeRunner(on_call=look)
    summary = run(repo, ["main", "a", "c"], tmp_path / "run2", runner)
    last = summary["stages"][-1]
    assert (last["label"], last["ref"], last["sha"], last["merge"], last["title"]) == (
        "+ this checkout", "HEAD", rev(repo, "mine"), "clean", "mine")
    assert [check["key"] for check in last["checks"]] == PAIR_B_KEYS
    assert runner.calls[-1].files == ["README.md", "a.txt", "c.txt", "mine.txt", "pair_b"]
    assert seen == [None] * 12 + ["committed\n"] * 4, "the committed HEAD is tested, not the edit beside it"
    assert summary["final"]["label"] == "+ this checkout"


# Catches: a ref that is not there crashing the run, or the stages after it still merged.
def test_missing_ref_reported(repo, tmp_path):
    summary = run(repo, ["main", "origin/nope", "c"], tmp_path / "run1", FakeRunner())
    assert merges(summary) == [("main", "clean"), ("+ origin/nope", "missing-ref"), ("+ c", "skipped"),
                               ("+ this checkout", "skipped")]
    assert summary["stages"][1]["sha"] is None and summary["stages"][1]["checks"] == []
    assert summary["final"]["label"] == "main"

    runner = FakeRunner()
    summary = run(repo, ["nope", "a"], tmp_path / "run2", runner)
    assert merges(summary) == [("nope", "missing-ref"), ("+ a", "skipped"), ("+ this checkout", "skipped")]
    assert runner.calls == [] and summary["final"] is None
    assert worktrees(repo) == {repo.resolve()}

    # A ref that git would read as an option is never handed to it.
    summary = run(repo, ["main", "--all"], tmp_path / "run3", FakeRunner())
    assert merges(summary)[1] == ("+ --all", "missing-ref")


# Catches: an offline machine (or a checkout without the remote) unable to run at all.
def test_fetch_failure_is_a_warning(repo, tmp_path):
    messages = []
    summary = run(repo, ["main", "a"], tmp_path / "run", FakeRunner(), fetch=True, on_progress=messages.append)
    fetched = summary["fetch"]
    assert (fetched["requested"], fetched["ok"]) == (True, False)
    assert "origin" in fetched["message"]
    assert any("origin" in message for message in messages)
    assert merges(summary) == [("main", "clean"), ("+ a", "clean"), ("+ this checkout", "contained")]


# Catches: the fetch done after the refs are looked up (a branch just pushed would be missing), or done when the run
# was asked not to fetch.
def test_the_fetch_comes_first_and_only_when_asked(repo, tmp_path):
    upstream = tmp_path / "upstream"
    git(tmp_path, "clone", "-q", str(repo), str(upstream))
    branch(upstream, "fresh", {"fresh.txt": "pushed later\n"})
    git(repo, "remote", "add", "origin", str(upstream))

    summary = run(repo, ["main", "origin/fresh"], tmp_path / "run1", FakeRunner(), fetch=False)
    assert summary["fetch"] == {"requested": False, "ok": None, "message": "not fetched: the run was asked not to"}
    assert merges(summary)[1] == ("+ origin/fresh", "missing-ref")

    runner = FakeRunner()
    summary = run(repo, ["main", "origin/fresh"], tmp_path / "run2", runner, fetch=True)
    assert summary["fetch"] == {"requested": True, "ok": True, "message": "fetched from origin"}
    assert merges(summary)[:2] == [("main", "clean"), ("+ origin/fresh", "clean")]
    assert runner.calls[-1].files == ["README.md", "fresh.txt", "pair_b"]


def checkout_state(checkout, files=("README.md", "work.txt", "untracked.txt")) -> dict:
    """Everything of the user's that a run must leave alone: the status (untracked files included), the current branch
    and commit, the stash, every ref, the index, and the files the user is editing."""
    return {
        "status": git(checkout, "status", "--porcelain=v1", "--untracked-files=all"),
        "branch": git(checkout, "rev-parse", "--abbrev-ref", "HEAD"),
        "head": git(checkout, "rev-parse", "HEAD"),
        "stash": git(checkout, "stash", "list", "--format=%H %gs"),
        "branches": git(checkout, "branch", "--list", "--format=%(refname) %(objectname)"),
        "refs": git(checkout, "for-each-ref", "--format=%(refname) %(objectname)"),
        "index": (checkout / ".git" / "index").read_bytes(),
        "files": {name: (checkout / name).read_text(encoding="utf-8") for name in files},
    }


# Required test 4 (spec 6): the runner leaves the checkout alone. Run against a scratch clone in a lived-in state: on
# a branch of its own with a commit, a stash entry, a staged change, an unsaved edit and an untracked file.
# Catches: anything that merges, checks out, stashes, resets or cleans in the checkout instead of the worktree.
def test_checkout_untouched(tmp_path):
    origin = make_repo(tmp_path / "origin")
    checkout = tmp_path / "checkout"
    git(tmp_path, "clone", "-q", str(origin), str(checkout))
    git(checkout, "checkout", "-q", "-b", "work")
    commit(checkout, {"work.txt": "committed\n"}, "work")
    (checkout / "README.md").write_text("stashed edit\n", encoding="utf-8")
    git(checkout, "stash", "push", "-q", "-m", "the user's stash")
    (checkout / "README.md").write_text("unsaved edit\n", encoding="utf-8")
    (checkout / "work.txt").write_text("staged edit\n", encoding="utf-8")
    git(checkout, "add", "work.txt")
    (checkout / "untracked.txt").write_text("not in git\n", encoding="utf-8")
    seen = []
    runner = FakeRunner(on_call=lambda check, env, log_path: seen.append(
        (Path(env["PYTHONPATH"].split(os.pathsep)[-1]) / "README.md").read_text(encoding="utf-8")))

    for number, refs in enumerate((["origin/main", "origin/a", "origin/c"],  # "+ this checkout" merged
                                   ["origin/main", "origin/a", "origin/b", "origin/c"])):  # a conflict
        before = checkout_state(checkout)
        summary = run(checkout, refs, tmp_path / f"run{number}", runner, fetch=True)
        assert summary["fetch"]["ok"] is True
        assert merges(summary)[-1] == ("+ this checkout", "clean" if number == 0 else "skipped")
        assert checkout_state(checkout) == before
        assert worktrees(checkout) == {checkout.resolve()}
    assert merges(summary)[2] == ("+ origin/b", "conflict")
    assert set(seen) == {"scratch\n"}, "the stages saw the committed README, never the stash or the edit"
    assert git(checkout, "stash", "list", "--format=%gs").strip() == "On work: the user's stash"


# Review Focus 5: a worktree left behind by a killed run is removed at the next run's start, whether it is whole,
# locked (killed during `git worktree add`, which locks it as "initializing") or already deleted. The user's own
# worktrees stay: one in their own folder, one in the temporary folder under another name, one named fog-lab- but not
# in the temporary folder. Catches: a stale worktree kept, or anyone else's removed.
def test_stale_worktrees_are_cleaned(repo, tmp_path):
    left = [Path(tempfile.mkdtemp(prefix="fog-lab-")) / "stage" for _ in range(3)]
    other_temp = Path(tempfile.mkdtemp(prefix="not-fog-lab-")) / "stage"
    keep = [tmp_path / "my-worktree", other_temp, tmp_path / "fog-lab-mine" / "stage"]
    try:
        for path in [*left, *keep]:
            git(repo, "worktree", "add", "-q", "--detach", str(path), "main")
        git(repo, "worktree", "lock", "--reason", "initializing", str(left[1]))
        shutil.rmtree(left[2].parent)
        messages = []
        summary = run(repo, ["main"], tmp_path / "run", FakeRunner(), on_progress=messages.append)

        assert merges(summary) == [("main", "clean"), ("+ this checkout", "contained")]
        assert worktrees(repo) == {repo.resolve(), *(path.resolve() for path in keep)}
        assert [path.parent.exists() for path in left] == [False, False, False]
        assert all(path.is_dir() for path in keep)
        assert any("3 worktrees left by an earlier run" in message for message in messages)
    finally:
        for path in (*left, other_temp):
            shutil.rmtree(path.parent, ignore_errors=True)


# Catches: the stale-worktree clean-up deleting the checkout itself when the checkout lives in a fog-lab-* folder of
# the temporary folder (with a worktree of its own beside it, which is the user's, not a run's).
def test_a_checkout_in_a_fog_lab_folder_is_never_removed(tmp_path):
    home = Path(tempfile.mkdtemp(prefix="fog-lab-"))
    try:
        checkout = make_repo(home / "checkout")
        git(checkout, "worktree", "add", "-q", "--detach", str(home / "stage"), "main")
        before = checkout_state(checkout, files=("README.md",))
        summary = run(checkout, ["main", "a"], tmp_path / "run", FakeRunner())
        assert merges(summary) == [("main", "clean"), ("+ a", "clean"), ("+ this checkout", "contained")]
        assert checkout_state(checkout, files=("README.md",)) == before
        assert worktrees(checkout) == {checkout.resolve(), (home / "stage").resolve()}
    finally:
        shutil.rmtree(home, ignore_errors=True)


# Catches: git commands in the worktree that, once its .git has gone (a check deleted it), find the repository around
# it instead: with the temporary folder inside the checkout, that is the user's, and the next merge would land on
# their branch. GIT_CEILING_DIRECTORIES stops git's search at the run's temporary folder.
def test_a_damaged_worktree_never_reaches_the_repository_around_it(repo, tmp_path, monkeypatch):
    (repo / "tmp").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(repo / "tmp"))

    def damage(check, env, log_path):
        dot_git = Path(env["PYTHONPATH"].split(os.pathsep)[-1]) / ".git"
        if dot_git.exists():
            dot_git.unlink()

    before = checkout_state(repo, files=("README.md",))
    summary = run(repo, ["main", "a", "c"], tmp_path / "run", FakeRunner(on_call=damage))
    assert merges(summary) == [("main", "clean"), ("+ a", "conflict"), ("+ c", "skipped"),
                               ("+ this checkout", "skipped")]
    assert checkout_state(repo, files=("README.md",)) == before
    assert not (repo / "a.txt").exists()
    assert worktrees(repo) == {repo.resolve()} and list((repo / "tmp").iterdir()) == []


# Catches: a worktree or temporary folder left behind when a check runner raises, or when the run is stopped by
# something that is not an Exception (the cleanup must sit in a `finally`).
@pytest.mark.parametrize("error", [RuntimeError, KeyboardInterrupt])
def test_the_worktree_goes_on_every_exit(repo, tmp_path, error):
    def stop(check, env, log_path):
        if check.key == "pair_b" and "a.txt" in runner.calls[-1].files:
            raise error("stopped during + a")

    runner = FakeRunner(on_call=stop)
    with pytest.raises(error, match="stopped during"):
        run(repo, ["main", "a", "c"], tmp_path / "run", runner)
    assert not runner.calls[-1].root.parent.exists()
    assert worktrees(repo) == {repo.resolve()}


# Catches: an inherited GIT_DIR, GIT_WORK_TREE or GIT_INDEX_FILE (as git sets for a hook that runs the tests) sending
# the runner's worktree, merges and aborts to that repository instead of the checkout it was given.
def test_git_variables_in_the_environment_do_not_redirect_it(repo, tmp_path, monkeypatch):
    decoy = make_repo(tmp_path / "decoy", main={"decoy.txt": "another repository\n", "pair_b/notes.txt": "x\n"})

    def decoy_state():
        return {"refs": git(decoy, "for-each-ref", "--format=%(refname) %(objectname)"),
                "status": git(decoy, "status", "--porcelain=v1", "--untracked-files=all"),
                "head": git(decoy, "rev-parse", "HEAD"), "index": (decoy / ".git" / "index").read_bytes()}

    before = decoy_state()
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / ".git" / "index"))
    runner = FakeRunner()
    summary = run(repo, ["main", "a", "c"], tmp_path / "run", runner)

    assert merges(summary) == [("main", "clean"), ("+ a", "clean"), ("+ c", "clean"), ("+ this checkout", "contained")]
    assert runner.calls[-1].files == ["README.md", "a.txt", "c.txt", "pair_b"]
    assert all(name not in call.env for call in runner.calls for name in ("GIT_DIR", "GIT_WORK_TREE",
                                                                          "GIT_INDEX_FILE"))
    assert decoy_state() == before
    assert worktrees(decoy) == {decoy.resolve()} and worktrees(repo) == {repo.resolve()}


# Catches: merges that need the user's git identity (a teammate who never set one could not run the tab), or that are
# recorded under it.
def test_merges_are_made_as_fog_lab(repo, tmp_path, monkeypatch):
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
        monkeypatch.delenv(name, raising=False)
    authors = {}
    runner = FakeRunner(on_call=lambda check, env, log_path: authors.setdefault(
        int(Path(log_path).name.split("-")[0]),
        git(Path(env["PYTHONPATH"].split(os.pathsep)[-1]), "log", "-1", "--format=%an <%ae>, %cn <%ce>").strip()))
    summary = run(repo, ["main", "a", "c"], tmp_path / "run", runner)
    assert merges(summary)[:3] == [("main", "clean"), ("+ a", "clean"), ("+ c", "clean")]
    assert authors == {0: "Scratch <scratch@localhost>, Scratch <scratch@localhost>",
                       1: "Fog Lab <fog-lab@localhost>, Fog Lab <fog-lab@localhost>",
                       2: "Fog Lab <fog-lab@localhost>, Fog Lab <fog-lab@localhost>"}


# Catches: a run started with nothing to run, or on a folder that is not a checkout, going on to report nonsense.
def test_what_a_run_refuses(repo, tmp_path):
    with pytest.raises(ValueError, match="no stages"):
        run_stages(repo, [], tmp_path / "run", torch=False, check_runner=FakeRunner())
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(RuntimeError, match="not a git checkout"):
        run(plain, ["main"], tmp_path / "run", FakeRunner())
    bare = tmp_path / "bare.git"
    git(tmp_path, "clone", "-q", "--bare", str(repo), str(bare))
    with pytest.raises(RuntimeError, match="not a git checkout"):
        run(bare, ["main"], tmp_path / "run", FakeRunner())
    assert not (tmp_path / "run").exists(), "each was refused before anything was made"


# Every hook git 2.50 runs for `worktree add` (post-checkout, post-index-change, reference-transaction), a merge
# (prepare-commit-msg and post-merge besides those; --no-verify skips only pre-merge-commit and commit-msg) or
# `merge --abort`, measured with hooks that note their name, and a few that a merge's commit or gc could run.
HOOKS = ("pre-merge-commit", "prepare-commit-msg", "commit-msg", "post-commit", "post-checkout", "post-merge",
         "reference-transaction", "post-index-change", "pre-auto-gc", "post-rewrite")


def install_hooks(folder: Path, marker: Path) -> None:
    """Hooks that write their name to `marker` and then fail: each refuses what it is asked about, or, for a hook
    whose verdict git ignores (post-merge), shows by the marker that it ran."""
    folder.mkdir(parents=True, exist_ok=True)
    for hook in HOOKS:
        path = folder / hook
        path.write_text(f"#!/bin/sh\necho {hook} >> '{marker.as_posix()}'\nexit 1\n", encoding="utf-8")
        path.chmod(0o755)


# Catches: the user's git set-up reaching the throwaway worktree and its merges: a hook of theirs run there (a failing
# post-checkout made `worktree add` fail and the whole run raise; a failing prepare-commit-msg made a clean merge a
# "conflict" with no files; a post-merge hook ran in the worktree), whether the hooks are in the repository's own
# folder or in a global core.hooksPath; commits signed by a signing program (here one that does not exist, so signing
# fails); merge.verifySignatures refusing the unsigned commits as a "conflict"; or rerere recording the real conflict
# in the repository's shared cache. The global and system configuration are the test's own, so the user's cannot mask
# the hooks.
@pytest.mark.parametrize("where", ["in .git/hooks", "in a global core.hooksPath"])
def test_the_users_hooks_and_signing_stay_out_of_the_merges(repo, tmp_path, monkeypatch, where):
    marker = tmp_path / "hooks-that-ran.txt"
    global_config = tmp_path / "global.gitconfig"
    if where == "in .git/hooks":
        install_hooks(repo / ".git" / "hooks", marker)
        global_config.write_text("", encoding="utf-8")
    else:
        install_hooks(tmp_path / "global-hooks", marker)
        global_config.write_text(f"[core]\n\thooksPath = {(tmp_path / 'global-hooks').as_posix()}\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    git(repo, "config", "commit.gpgsign", "true")
    git(repo, "config", "gpg.program", str(tmp_path / "no-such-signer"))
    git(repo, "config", "merge.verifySignatures", "true")
    git(repo, "config", "rerere.enabled", "true")
    summary = run(repo, ["main", "a", "c", "b"], tmp_path / "run", FakeRunner())

    assert merges(summary) == [("main", "clean"), ("+ a", "clean"), ("+ c", "clean"), ("+ b", "conflict"),
                               ("+ this checkout", "skipped")]
    assert summary["stages"][3]["conflicts"] == ["a.txt"], "the real conflict, not one made by a hook or a signature"
    assert not marker.exists(), f"hooks ran: {marker.read_text(encoding='utf-8').split() if marker.exists() else ''}"
    assert not (repo / ".git" / "rr-cache").exists()


# ---- what a run reports ----

# Catches: a summary key missing or renamed, a value that cannot be saved as JSON, or a time without its zone.
def test_the_summary(repo, tmp_path):
    summary = run(repo, ["main", "a"], tmp_path / "run", FakeRunner(), torch=True)
    assert list(summary) == ["started", "finished", "machine", "fetch", "checkout_sha", "stages", "final", "stopped"]
    assert summary["stopped"] is False
    assert json.loads(json.dumps(summary)) == summary
    started, finished = (datetime.fromisoformat(summary[key]) for key in ("started", "finished"))
    assert started.tzinfo is not None and started <= finished
    assert set(summary["machine"]) == {"name", "system", "release", "arch", "python", "torch"}
    assert summary["machine"]["torch"] is True
    assert summary["checkout_sha"] == rev(repo, "HEAD")
    final = summary["final"]
    assert list(final) == ["label", "fixtures", "harness", "accuracy"]
    assert final["harness"] == {}, "this stage has no pair_b_prep, so no harness checks"
    assert final["accuracy"] == read_accuracy(tmp_path / "no-checkpoints")


# Catches: on_stage called late (all at the end), more than once, or with something other than what is saved.
def test_each_stage_is_reported_as_soon_as_it_is_done(repo, tmp_path):
    reported, marks = [], []
    runner = FakeRunner(on_call=lambda check, env, log_path: marks.append(len(reported)))
    summary = run(repo, ["main", "a", "nope", "c"], tmp_path / "run", runner, on_stage=reported.append)
    assert reported == summary["stages"] and len(reported) == 5
    assert all(sent is saved for sent, saved in zip(reported, summary["stages"]))
    assert marks == [0] * 4 + [1] * 4, "the checks of a stage run after the stage before it was reported"


# Catches: a log named after a key with a colon (illegal on Windows, R26), a log path that is not relative to the run
# folder, harness files shared between stages, or a harness report not carried into the final section.
def test_harness_checks_logs_and_reports(tmp_path):
    repo = make_repo(tmp_path / "checkout", main={"README.md": "x\n", "pair_b/notes.txt": "x\n",
                                                  "pair_b_prep/__init__.py": ""})
    report = {"metadata": {"warmups": 2, "repeats": 10, "tolerance": 1e-6, "config": {"source_commit": "abc"}},
              "checks": [*({"name": f"check {n}", "status": "pass"} for n in range(16)),
                         {"name": "by hand 1", "status": "manual", "detail": "look at it"},
                         {"name": "by hand 2", "status": "manual", "detail": "and at this"}]}

    def write_report(check, env, log_path):
        if check.key.startswith("harness:") and check.unavailable is None:
            out = Path(check.argv[check.argv.index("--out") + 1])
            out.mkdir(parents=True)
            (out / "report.json").write_text(json.dumps(report), encoding="utf-8")

    runner = FakeRunner(on_call=write_report)
    run_dir = tmp_path / "run"
    summary = run(repo, ["main", "a"], run_dir, runner, torch=False)

    first = summary["stages"][0]
    assert [check["key"] for check in first["checks"]] == [
        *PAIR_B_KEYS, "bryan_tests", "harness:material", "harness:stockfish-d1", "harness:stockfish-d11",
        "harness:network1", "harness:belief", "history"]
    logs = {check["key"]: check["log"] for check in first["checks"]}
    assert logs["harness:stockfish-d1"] == "logs/0-harness-stockfish-d1.txt"
    assert logs["harness:network1"] is None and logs["shared"] is None, "unavailable checks have no log"
    assert all((run_dir / log).is_file() for log in logs.values() if log is not None)
    assert not [path for path in run_dir.rglob("*") if ":" in path.name]
    for call in runner.calls:
        if call.check.config is not None:
            config = Path(call.check.argv[call.check.argv.index("--config") + 1])
            assert config.is_absolute() and config.parent == run_dir.resolve() / "stages" / str(call.index) / "harness"

    harness = summary["final"]["harness"]
    assert summary["final"]["label"] == "+ a"
    assert list(harness) == ["material", "stockfish-d1", "stockfish-d11", "network1", "belief"]
    assert harness["material"] == {"status": "pass", "summary": "passed",
                                   "counts": {"pass": 16, "manual": 2, "fail": 0},
                                   "checks": report["checks"], "metadata": report["metadata"],
                                   "log": "logs/1-harness-material.txt"}
    assert harness["network1"] == {"status": "unavailable", "summary": NO_TORCH, "counts": {}, "checks": [],
                                   "metadata": None, "log": None}


# Catches: the fog-rules check not run on the last stage, run from the stage instead of this checkout, or its JSON
# not passed on. The scratch stage holds Pair A's positions and our stand-in observe, copied from this checkout.
def test_fog_rules_are_checked_on_the_last_stage(tmp_path):
    files = {f"fow_shared/{path.name}": path.read_text(encoding="utf-8")
             for path in sorted((REPO / "fow_shared").glob("*.py"))}
    for name in ("__init__.py", "fixtures.py", "data/rules_cases.json"):
        files[f"pair_a_prep/{name}"] = (REPO / "pair_a_prep" / name).read_text(encoding="utf-8")
    files["pair_b/src/pairb/__init__.py"] = ""
    files["pair_b/src/pairb/observe.py"] = (PAIR_B / "src" / "pairb" / "observe.py").read_text(encoding="utf-8")
    repo = make_repo(tmp_path / "checkout", main=files)
    link_venv(repo)
    run_dir = tmp_path / "run"
    summary = run(repo, ["main", "a"], run_dir, FakeRunner())

    fixtures = summary["final"]["fixtures"]
    standin, teal = fixtures["standin"], fixtures["teal"]
    assert (standin["rules"], standin["available"], standin["status"]) == ("standin", True, "pass")
    assert [case["id"] for case in standin["cases"]] == [case["id"] for case in load_suite()["cases"]]
    assert not [case for case in standin["cases"] if case["errors"]]
    assert (teal["rules"], teal["available"], teal["status"], teal["cases"]) == ("teal", False, "unavailable", [])
    assert "rules_adapter" in teal["reason"]
    assert standin["log"] == "logs/1-fixtures-standin.txt" and (run_dir / standin["log"]).is_file()


# R21: a fog-rules check that crashes (here Pair A's fixtures are not in the stage, so its imports fail) is shown as
# a failure with the end of its error output. Catches: the section dropped, or the run stopped, by a crash.
def test_a_fog_rules_check_that_crashes_is_a_failure(repo, tmp_path):
    link_venv(repo)
    summary = run(repo, ["main"], tmp_path / "run", FakeRunner())
    for rules in ("standin", "teal"):
        entry = summary["final"]["fixtures"][rules]
        assert (entry["rules"], entry["available"], entry["status"], entry["cases"]) == (rules, False, "fail", [])
        assert "No module named 'pair_a_prep'" in entry["reason"]
        assert entry["log"] == f"logs/0-fixtures-{rules}.txt"


# R21: where Pair B's interpreter is missing the fog-rules check cannot even start; it is a failure, never a crash.
def test_a_fog_rules_check_that_cannot_start_is_a_failure(repo, tmp_path):
    summary = run(repo, ["main"], tmp_path / "run", FakeRunner())
    entry = summary["final"]["fixtures"]["standin"]
    assert (entry["available"], entry["status"]) == (False, "fail")
    assert entry["reason"].startswith("could not start: ")
    assert str(repo.resolve() / "pair_b" / ".venv") in entry["reason"]


# ---- stopping a run (R29) ----

# Catches: a stop that waits for the rest of the run, a check started or a stage merged after it, the checks it cut off
# left out of the card, the final sections run for a stopped run (the fog-rules checks take a while), a summary that
# does not say it was stopped, and the worktree left behind.
def test_a_stopped_run_skips_the_rest_and_still_removes_its_worktree(repo, tmp_path):
    cancel = threading.Event()

    def in_stage_a(check, root):  # held while it runs, and stopped from another thread, as RunManager.close() does
        if check.key == "pair_b" and (root / "a.txt").exists():
            threading.Timer(0.2, cancel.set).start()
            return True
        return False

    runner = StoppableRunner(hold=in_stage_a)
    messages = []
    summary = run(repo, ["main", "a", "c"], tmp_path / "run", runner, cancel=cancel, on_progress=messages.append)

    assert merges(summary) == [("main", "clean"), ("+ a", "clean"), ("+ c", "skipped"), ("+ this checkout", "skipped")]
    checks = summary["stages"][1]["checks"]
    assert [(check["key"], check["status"]) for check in checks] == [
        ("imports_b", "pass"), ("pair_b", "fail"), ("imports_a", "skipped"), ("shared", "skipped")]
    assert checks[1]["summary"] == "stopped"
    assert (checks[2]["summary"], checks[2]["counts"], checks[2]["log"]) == ("not run: the run was stopped", {}, None)
    assert [(call.index, call.check.key) for call in runner.calls] == [
        *((0, key) for key in PAIR_B_KEYS), (1, "imports_b"), (1, "pair_b")]
    assert all(event is cancel for event in runner.events)
    assert summary["final"] is None and summary["stopped"] is True
    assert messages[-1] == "Stopped"
    assert not runner.calls[-1].root.parent.exists(), "the worktree and its temporary folder are gone"
    assert worktrees(repo) == {repo.resolve()}


# Catches: a stop noticed only inside a check, so that one coming between two stages still lets the next be merged;
# and a run whose stop event is never set going any differently from one without, or not handing the event to every
# check.
def test_a_stop_between_stages_merges_nothing_more(repo, tmp_path):
    cancel = threading.Event()
    runner = StoppableRunner(on_call=lambda check, env, log_path: check.key == "shared" and cancel.set())
    summary = run(repo, ["main", "a", "c"], tmp_path / "run1", runner, cancel=cancel)
    assert merges(summary) == [("main", "clean"), ("+ a", "skipped"), ("+ c", "skipped"),
                               ("+ this checkout", "skipped")]
    assert [check["status"] for check in summary["stages"][0]["checks"]] == ["pass", "pass", "unavailable",
                                                                             "unavailable"]
    assert {call.index for call in runner.calls} == {0}
    assert summary["final"] is None and summary["stopped"] is True
    assert worktrees(repo) == {repo.resolve()}

    never = threading.Event()
    runner = StoppableRunner()
    summary = run(repo, ["main", "a", "c"], tmp_path / "run2", runner, cancel=never)
    assert merges(summary) == [("main", "clean"), ("+ a", "clean"), ("+ c", "clean"), ("+ this checkout", "contained")]
    assert summary["stopped"] is False and summary["final"]["label"] == "+ c"
    assert len(runner.events) == 12 and all(event is never for event in runner.events)


# Catches: a stop during the final sections that waits for the fog-rules checks (each starts Pair B's interpreter on
# Pair A's positions) or does not say they were stopped. The stage's interpreter is this test environment.
def test_a_stop_during_the_fog_rules_checks_stops_them(repo, tmp_path):
    link_venv(repo)
    cancel = threading.Event()

    def progress(message):
        if message.startswith("Fog rules:"):
            cancel.set()

    summary = run(repo, ["main"], tmp_path / "run", StoppableRunner(), cancel=cancel, on_progress=progress)
    for rules in ("standin", "teal"):
        entry = summary["final"]["fixtures"][rules]
        assert (entry["rules"], entry["status"], entry["reason"], entry["cases"]) == (rules, "fail", "stopped", [])
        assert "stopped" in (tmp_path / "run" / entry["log"]).read_text(encoding="utf-8")
    assert summary["stopped"] is True
    assert worktrees(repo) == {repo.resolve()}


# ---- run_check ----

def clean_env() -> dict:
    """This environment without the user's pytest options, writing no bytecode and UTF-8 output (as stage_env does)."""
    env = {name: value for name, value in os.environ.items() if name != "PYTEST_ADDOPTS"}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    return env


def python(code: str, *args: str) -> tuple[str, ...]:
    return (sys.executable, "-c", code, *args)


# Catches: a check or a git command left in the process group of the console that started Fog Lab on Windows, where
# a Ctrl+C in that window then reaches it as well: git is never to be stopped part way, and a check cut off that way
# would be saved as a red failure. On POSIX each command leads a session of its own (no terminal either). The choice is
# pure, so both platforms are checked on any machine.
def test_each_command_gets_a_process_group_of_its_own():
    choose = stage_runner.new_group_options
    assert choose(windows=False) == {"start_new_session": True}
    assert choose(windows=True) == {"creationflags": 0x00000200}  # CREATE_NEW_PROCESS_GROUP
    if os.name == "nt":
        assert subprocess.CREATE_NEW_PROCESS_GROUP == 0x00000200
    assert choose() == choose(windows=os.name == "nt")


# Catches: the options chosen above not reaching the commands the runner starts.
def test_commands_are_started_with_those_options(tmp_path, monkeypatch):
    started, real = [], subprocess.Popen

    def spy(*args, **kwargs):
        started.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy)
    result = run_check(Check("history", "History check", python("pass"), tmp_path, None), clean_env(),
                       tmp_path / "log.txt")
    assert result.status == "pass" and len(started) == 1
    assert started[0].items() >= stage_runner.new_group_options().items()


# Review Focus 5: a check that hangs is stopped at its timeout and marked failed "timed out".
def test_check_timeout_marks_failure(tmp_path):
    log_path = tmp_path / "logs" / "0-history.txt"
    check = Check("history", "History check", python("import time; time.sleep(5)"), tmp_path, None)
    start = time.monotonic()
    result = run_check(check, clean_env(), log_path, timeout=0.5)
    assert time.monotonic() - start < 4
    assert (result.status, result.summary, result.counts) == ("fail", "timed out after 0.5 s", {})
    assert "timed out after 0.5 s" in log_path.read_text(encoding="utf-8")


# Catches: a timed-out check stopped while what it started (a test's subprocess, an engine) runs on.
def test_a_timed_out_check_stops_what_it_started(tmp_path):
    started, survived = tmp_path / "started", tmp_path / "survived"
    grandchild = (f"import pathlib, time; pathlib.Path({str(started)!r}).touch(); time.sleep(2.5); "
                  f"pathlib.Path({str(survived)!r}).touch()")
    child = ("import pathlib, subprocess, sys, time\n"
             f"subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
             f"while not pathlib.Path({str(started)!r}).exists():\n    time.sleep(0.01)\n"
             "time.sleep(60)\n")
    result = run_check(Check("history", "History check", python(child), tmp_path, None), clean_env(),
                       tmp_path / "log.txt", timeout=1)
    assert (result.status, result.summary) == ("fail", "timed out after 1 s")
    assert started.exists(), "the grandchild had started before the timeout"
    time.sleep(2.5)
    assert not survived.exists(), "the grandchild was stopped with the check"


# R29. Catches: a stop that leaves the check, or what it started, running (a server's Ctrl+C never reaches them: they
# are in a process group of their own), one that waits for the timeout instead, and a stopped check reported as anything
# but failed, "stopped".
def test_a_stopped_check_dies_with_what_it_started(tmp_path):
    started, survived, pid_file = tmp_path / "started", tmp_path / "survived", tmp_path / "pid"
    grandchild = (f"import pathlib, time; pathlib.Path({str(started)!r}).touch(); time.sleep(2.5); "
                  f"pathlib.Path({str(survived)!r}).touch()")
    child = ("import os, pathlib, subprocess, sys, time\n"
             f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
             f"subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
             "time.sleep(120)\n")
    cancel = threading.Event()

    def stop_once_started():
        deadline = time.monotonic() + 60
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        cancel.set()

    threading.Thread(target=stop_once_started, daemon=True).start()
    log_path = tmp_path / "logs" / "0-history.txt"
    began = time.monotonic()
    result = run_check(Check("history", "History check", python(child), tmp_path, None), clean_env(), log_path,
                       timeout=300, cancel=cancel)
    assert time.monotonic() - began < 60
    assert (result.status, result.summary, result.counts, result.log) == ("fail", "stopped", {}, str(log_path))
    assert started.exists(), "the grandchild had started before the stop"
    assert "stopped" in log_path.read_text(encoding="utf-8")
    if os.name != "nt":
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text(encoding="utf-8")), 0)
    time.sleep(2.5)
    assert not survived.exists(), "the grandchild was stopped with the check"


# Catches: a check given a stop event that is never set judged differently (its exit code or output lost while the
# runner looks at the event), or kept past its timeout.
def test_a_check_whose_stop_never_comes_runs_as_before(tmp_path):
    never = threading.Event()
    code = "import sys; print('some output'); sys.stderr.write('it broke\\n'); sys.exit(3)"
    result = run_check(Check("history", "History check", python(code), tmp_path, None), clean_env(),
                       tmp_path / "log.txt", cancel=never)
    assert (result.status, result.summary) == ("fail", "exit code 3: it broke")
    assert "--- stdout ---\nsome output\n" in (tmp_path / "log.txt").read_text(encoding="utf-8")
    began = time.monotonic()
    result = run_check(Check("history", "History check", python("import time; time.sleep(5)"), tmp_path, None),
                       clean_env(), tmp_path / "log.txt", timeout=0.5, cancel=never)
    assert time.monotonic() - began < 4
    assert (result.status, result.summary) == ("fail", "timed out after 0.5 s")


# Catches: pytest's counts not read, or the run not done in the check's folder.
def test_run_check_reads_pytest_counts(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_tiny.py").write_text("def test_one():\n    assert True\n", encoding="utf-8")
    log_path = tmp_path / "logs" / "0-pair_b.txt"
    result = run_check(Check("pair_b", "Pair B", (sys.executable, *PYTEST), tmp_path, None), clean_env(), log_path)
    assert result == CheckResult("pair_b", "Pair B", "pass", "1 passed",
                                 {"passed": 1, "failed": 0, "errors": 0, "skipped": 0}, str(log_path))
    assert "1 passed" in log_path.read_text(encoding="utf-8")

    (tmp_path / "test_tiny.py").write_text("import pytest\n\ndef test_one():\n    assert True\n\n"
                                           "def test_two():\n    assert False\n\n"
                                           "def test_three():\n    pytest.skip('no')\n", encoding="utf-8")
    result = run_check(Check("pair_b", "Pair B", (sys.executable, *PYTEST), tmp_path, None), clean_env(), log_path)
    assert (result.status, result.summary, result.counts) == (
        "fail", "1 failed, 1 passed, 1 skipped", {"passed": 1, "failed": 1, "errors": 0, "skipped": 1})


# R27: pytest that passes without a summary line (-qq prints none) is a pass, not "0 passed".
def test_a_pytest_check_that_passes_without_counts(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_tiny.py").write_text("def test_one():\n    assert True\n", encoding="utf-8")
    check = Check("shared", "Shared + Pair A", (sys.executable, "-m", "pytest", "-qq", "-p", "no:cacheprovider"),
                  tmp_path, None)
    result = run_check(check, clean_env(), tmp_path / "log.txt")
    assert (result.status, result.summary) == ("pass", "passed (no counts reported)")


# Catches: an unavailable check started, logged or given its config file (its argv may be empty).
def test_an_unavailable_check_returns_at_once(tmp_path):
    config = tmp_path / "out" / "harness" / "network1.json"
    check = Check("harness:network1", "Harness, Network 1", (), tmp_path, NO_TORCH, {"kind": "network"})
    result = run_check(check, clean_env(), tmp_path / "log.txt")
    assert result == CheckResult("harness:network1", "Harness, Network 1", "unavailable", NO_TORCH, {}, None)
    assert not (tmp_path / "log.txt").exists() and not config.parent.exists()


# R25: a harness check's config is written, as UTF-8 JSON, to the file its argv names, before it runs.
def test_run_check_writes_the_config_first(tmp_path):
    config_path = tmp_path / "out" / "harness" / "material.json"
    config = {"kind": "material", "source_commit": "abc", "note": "é"}
    code = ("import json, pathlib, sys\n"
            "config = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding='utf-8'))\n"
            f"sys.exit(0 if config == {config!r} else 1)\n")
    check = Check("harness:material", "Harness, Piece values",
                  python(code, "--config", str(config_path), "--out", str(tmp_path / "out" / "harness" / "material")),
                  tmp_path, None, config)
    result = run_check(check, clean_env(), tmp_path / "log.txt")
    assert result.status == "pass"
    assert json.loads(config_path.read_text(encoding="utf-8")) == config
    assert result.summary == "passed, but it wrote no report.json"


# Catches: the harness summary not taken from its report.json, or its exit code ignored.
@pytest.mark.parametrize("statuses, code, status, summary", [
    (["pass"] * 16 + ["manual"] * 2, 0, "pass", "16 pass, 2 manual, 0 fail"),
    (["pass"] * 15 + ["manual"] * 2 + ["fail"], 1, "fail", "15 pass, 2 manual, 1 fail"),
])
def test_the_harness_summary_counts_its_report(tmp_path, statuses, code, status, summary):
    out = tmp_path / "out" / "harness" / "material"
    report = {"metadata": {}, "checks": [{"name": f"c{n}", "status": s} for n, s in enumerate(statuses)]}
    write = ("import json, pathlib, sys\n"
             "out = pathlib.Path(sys.argv[4]); out.mkdir(parents=True)\n"
             f"(out / 'report.json').write_text(json.dumps({report!r}))\n"
             f"sys.exit({code})\n")
    check = Check("harness:material", "Harness, Piece values",
                  python(write, "--config", str(tmp_path / "out" / "harness" / "material.json"), "--out", str(out)),
                  tmp_path, None, {"kind": "material"})
    result = run_check(check, clean_env(), tmp_path / "log.txt")
    assert (result.status, result.summary, result.counts) == (
        status, summary, {"pass": statuses.count("pass"), "manual": statuses.count("manual"),
                          "fail": statuses.count("fail")})


# Task 14's report: a missing interpreter makes subprocess raise OSError; it is a failed check with a readable reason.
def test_a_check_that_cannot_start_fails_readably(tmp_path):
    missing = tmp_path / "no" / ".venv" / "bin" / "python"
    log_path = tmp_path / "log.txt"
    result = run_check(Check("pair_b", "Pair B", (str(missing), *PYTEST), tmp_path, None), clean_env(), log_path)
    assert result.status == "fail" and result.summary.startswith("could not start: ")
    assert str(missing) in result.summary and result.log == str(log_path)
    assert result.summary in log_path.read_text(encoding="utf-8")

    result = run_check(Check("pair_b", "Pair B", (sys.executable, "-c", "pass"), tmp_path / "nowhere", None),
                       clean_env(), log_path)
    assert result.status == "fail" and str(tmp_path / "nowhere") in result.summary


# Catches: an import check passed on its exit code alone, so a stage tested against the app's own code goes green.
def test_import_checks_must_find_the_stage(tmp_path):
    stage = tmp_path / "stage"
    for package in (stage / "pair_b" / "src" / "pairb", stage / "fow_shared"):
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    env = stage_env(stage, clean_env())
    code = "import pairb, fow_shared; print(pairb.__file__); print(fow_shared.__file__)"
    result = run_check(Check("imports_b", "Imports, Pair B", python(code), stage / "pair_b", None), env,
                       tmp_path / "log.txt")
    assert (result.status, result.summary) == ("pass", "imports the stage's own code")

    elsewhere = tmp_path / "elsewhere" / "fow_shared" / "__init__.py"
    code = f"print({str(stage / 'pair_a_prep' / '__init__.py')!r}); print({str(elsewhere)!r})"
    result = run_check(Check("imports_a", "Imports, shared + Pair A", python(code), stage, None), env,
                       tmp_path / "log.txt")
    assert (result.status, result.summary) == ("fail", f"imported from outside the stage: {elsewhere}")

    result = run_check(Check("imports_a", "Imports, shared + Pair A", python("import no_such_module_here"), stage,
                             None), env, tmp_path / "log.txt")
    assert result.status == "fail"
    assert result.summary == "exit code 1: ModuleNotFoundError: No module named 'no_such_module_here'"


# Catches: unittest's verdict (on stderr) or another command's error not reaching the card.
def test_other_checks_are_judged_by_their_exit_code(tmp_path):
    (tmp_path / "tiny_unittest.py").write_text("import unittest\n\nclass T(unittest.TestCase):\n"
                                               "    def test_one(self):\n        pass\n", encoding="utf-8")
    result = run_check(Check("bryan_tests", "Bryan's tests", (sys.executable, "-m", "unittest", "tiny_unittest"),
                             tmp_path, None), clean_env(), tmp_path / "log.txt")
    assert (result.status, result.summary, result.counts) == ("pass", "Ran 1 test: OK", {})

    code = "import sys; print('some output'); sys.stderr.write('it broke\\n'); sys.exit(3)"
    result = run_check(Check("history", "History check", python(code), tmp_path, None), clean_env(),
                       tmp_path / "log.txt")
    assert (result.status, result.summary) == ("fail", "exit code 3: it broke")

    result = run_check(Check("history", "History check", python("print('{}')"), tmp_path, None), clean_env(),
                       tmp_path / "log.txt")
    assert (result.status, result.summary) == ("pass", "passed")


# Catches: output lost from the log (stderr especially, where unittest writes), or non-ASCII output garbled.
def test_the_log_holds_the_command_and_both_streams(tmp_path):
    code = "import sys; print('out: é ✓'); sys.stderr.write('err: ünïcode\\n')"
    log_path = tmp_path / "deep" / "logs" / "0-history.txt"
    run_check(Check("history", "History check", python(code), tmp_path, None), clean_env(), log_path)
    log = log_path.read_text(encoding="utf-8")
    assert sys.executable in log and str(tmp_path) in log
    assert "--- stdout ---\nout: é ✓\n" in log and "--- stderr ---\nerr: ünïcode\n" in log
    assert "exit code 0" in log
