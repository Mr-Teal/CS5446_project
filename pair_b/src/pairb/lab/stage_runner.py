"""The runner behind Fog Lab's Tests tab: the stages merged one by one in a throwaway git worktree, each stage's checks
run there as subprocesses, and the last cleanly built stage's fog rules, harness reports and accuracy files read before
the worktree goes (spec 5.1 to 5.4). stages.py holds the pure parts (the stages file, the commands each stage runs,
reading pytest's summary); this module is the half that calls git, starts processes and writes files.

A run (run_stages) goes like this:

1. Worktrees an earlier run left behind (it was killed before it could clean up) are removed: those registered in the
   checkout that lie in a fog-lab-* folder directly in the temporary folder, compared as resolved paths (macOS lists
   /var as /private/var), but never the checkout itself or a folder that holds it. Then `git worktree prune`.
2. If asked, `git fetch --quiet origin`, the run's only network call. A failure is a warning in the summary, and the run
   goes on with the refs the checkout already has.
3. The first stage's commit is checked out, detached, in a new worktree, tempfile.mkdtemp(prefix="fog-lab-")/stage,
   and its checks run. Each later stage's ref is merged on top (`merge --no-ff --no-edit`, made as Fog Lab
   <fog-lab@localhost>) and its checks run. A ref that names no commit is "missing-ref"; a merge that fails is
   "conflict", with the unmerged files listed and the merge aborted. Either way the stages after it are "skipped".
4. Last comes "+ this checkout", the checkout's committed HEAD: "contained" when the stages already hold it, and
   otherwise merged and checked like the others. Uncommitted changes are never part of a run.
5. On the last cleanly built stage: Pair A's fog-rules positions against both rules implementations (fixture_check.py,
   started by path from this checkout with Pair B's interpreter), the report.json of each of that stage's harness
   checks, and read_accuracy on the stage's pair_b/checkpoints.
6. However the run ends, the worktree is removed (`git worktree remove`), its temporary folder deleted and git's record
   of it pruned.

What a run never touches: the checkout's working tree, index, HEAD, branches and stash. Every merge happens in the
detached worktree, no branch is created, moved or deleted, and nothing is pushed. (The worktree shares the checkout's
object store, so a run's merge commits stay there as unreachable objects until git's garbage collection drops them, as
it does any abandoned commit.) Git gets an environment without the variables that name a repository, an index or a
work tree (GIT_DIR, GIT_INDEX_FILE, GIT_WORK_TREE and the rest of `git rev-parse --local-env-vars`), which git sets for
the hooks it runs: inherited, they would send the worktree and its merges to that repository. Commands in the worktree
also cannot find a repository above it (GIT_CEILING_DIRECTORIES is its temporary folder), and the merges sign nothing,
run no hooks, stash nothing and record no rerere resolutions, whatever the user's git configuration says.

Every command is an argument list. Its output goes to temporary files, not pipes, so that a process it leaves running
cannot keep the runner waiting. It runs in a process group of its own on POSIX (with no terminal, so nothing it starts
can stop to ask for a password) and is stopped as a process tree on Windows, so a check that times out is stopped along
with whatever it started.

The run summary, plain JSON data:

    {"started", "finished"   local times, ISO 8601 with their UTC offset
     "machine"               {"name", "system", "release", "arch", "python", "torch"}
     "fetch"                 {"requested", "ok" (None when not requested), "message"}
     "checkout_sha"          the checkout's HEAD commit (None in a checkout with no commits)
     "stages"                [StageResult as JSON, ...], "+ this checkout" last
     "final"                 None when no stage was built, else
                             {"label"     the last cleanly built stage, whose results these are
                              "fixtures"  {"standin": entry, "teal": entry}
                              "harness"   {scorer id: entry} for that stage's harness checks (empty without pair_b_prep)
                              "accuracy"  read_accuracy(<stage>/pair_b/checkpoints)}}

A fixtures entry is fixture_check.py's own JSON ({"rules", "available", "reason", "cases"}) with "status" ("pass" when
every position passes, "fail" when one does not, "unavailable" when those rules are not in the stage) and "log" added.
When the check itself fails (it exits non-zero, cannot start, times out, or prints something that is not its JSON
object), the entry is {"rules", "available": False, "status": "fail", "reason": the end of its error output, "cases":
[], "log"} (R21), so the section is never dropped. A harness entry is {"status", "summary", "counts" ({"pass",
"manual", "fail"}), "checks" and "metadata" (report.json's own), "log"}: an unavailable check has its reason as the
summary, and one that wrote no report.json has no checks and None metadata.

Files: logs go to run_dir/logs/<stage index>-<check key>.txt, any character but letters, digits, ".", "_" and "-"
turned into "-" (the colon of harness:<id> is not allowed in a Windows file name, R26); the fog-rules runs log to
<stage index>-fixtures-<rules>.txt. A CheckResult's log is that path relative to run_dir, with "/". Each stage's harness
files are under run_dir/stages/<stage index>/, so the stages that run the harness never share them.
"""
import json
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path

from .accuracy import read_accuracy
from .stages import Check, Stage, find_envs, imports_ok, parse_pytest_summary, stage_checks, stage_env

THIS_CHECKOUT = "+ this checkout"
FIXTURE_CHECK = Path(__file__).resolve().parent / "checks" / "fixture_check.py"  # run from this checkout, by path
RULES = ("standin", "teal")

_FETCH_TIMEOUT = 120  # seconds; GitHub answers in a few
_GIT_TIMEOUT = 600  # checking out or merging a stage
_FIXTURE_TIMEOUT = 600
# A merge needs no identity of the user's, and nothing in the user's configuration may sign it, stash for it or record
# its conflicts in the shared rerere cache.
_MERGE = ("-c", "user.name=Fog Lab", "-c", "user.email=fog-lab@localhost", "-c", "commit.gpgsign=false",
          "-c", "merge.autoStash=false", "-c", "rerere.enabled=false")
# `git rev-parse --local-env-vars` (git 2.50), the namespace, and where to stop looking for a repository.
_GIT_LOCATION = frozenset({
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE", "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX", "GIT_SHALLOW_FILE", "GIT_COMMON_DIR",
    "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES"})
_IMPORT_CHECKS = {"imports_b": 1, "imports_a": 0}  # how many folders below the stage's root each runs (stage_checks)
_NOT_IN_A_NAME = re.compile(r"[^A-Za-z0-9._-]")
_UNITTEST_RAN = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)
_NEW_GROUP = {} if os.name == "nt" else {"start_new_session": True}


@dataclass
class CheckResult:
    """How one check went. `status` is "pass", "fail" or "unavailable" (run_check gives no other; "skipped" is kept
    for callers that report a check they did not run). `summary` is the line the card shows, `counts` the numbers
    behind it: pytest's {"passed", "failed", "errors", "skipped"}, the harness's {"pass", "manual", "fail"}, or {}.
    `log` is where the check's output was saved (None when nothing ran): run_check gives the path it was handed, and
    run_stages makes it relative to the run folder."""

    key: str
    label: str
    status: str          # pass | fail | skipped | unavailable
    summary: str
    counts: dict
    log: str | None      # path relative to the run folder


@dataclass
class StageResult:
    """One stage card. `sha` is the commit its ref named (the checkout's HEAD for "+ this checkout"; None when it was
    missing or skipped); `merge` is "clean", "conflict", "missing-ref", "skipped" or "contained"; `conflicts` lists the
    unmerged files of a conflict; `checks` are the results of the stage's checks, in the order they ran (none unless
    the stage was built); `title` is the stages file's title for it (the checkout's branch for "+ this checkout")."""

    label: str
    ref: str
    sha: str | None
    merge: str           # clean | conflict | missing-ref | skipped | contained
    conflicts: list[str]
    checks: list[CheckResult]
    title: str = ""


# ---- running a command ----

@dataclass(frozen=True)
class _Outcome:
    """How a command went: its exit code (None when it did not start or was stopped), its output, its time, and, when
    it did not finish, why."""

    code: int | None
    stdout: str = ""
    stderr: str = ""
    seconds: float = 0.0
    timed_out: bool = False
    error: OSError | None = None  # why it could not be started


def _execute(argv: Sequence[str], cwd: Path | None, env: Mapping[str, str], timeout: float) -> _Outcome:
    """Run `argv` in `cwd` with exactly `env`, nothing on its stdin, for at most `timeout` seconds. Never raises for
    the command: one that cannot start comes back with the error, one that runs too long is stopped with what it
    started. Anything that interrupts the wait (Ctrl+C) stops the command too, and is passed on."""
    start = time.monotonic()
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            process = subprocess.Popen(list(argv), cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL, stdout=out,
                                       stderr=err, **_NEW_GROUP)
        except OSError as error:  # no such interpreter or folder, no permission
            return _Outcome(None, seconds=time.monotonic() - start, error=error)
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _stop(process)
        except BaseException:
            _stop(process)
            raise
        return _Outcome(None if timed_out else process.returncode, _text(out), _text(err), time.monotonic() - start,
                        timed_out)


def _stop(process: subprocess.Popen) -> None:
    """Stop `process` and everything it started, then wait for it: its process group on POSIX (it leads one of its
    own), its process tree on Windows."""
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:  # the group has already gone
            pass
    try:
        process.kill()
    except OSError:
        pass
    process.wait()


def _text(file) -> str:
    file.seek(0)
    return file.read().decode("utf-8", errors="replace").replace("\r\n", "\n")


def _why_not_started(error: OSError, argv: Sequence[str], cwd: Path | None) -> str:
    """Why a command could not start, naming the file it could not use: the interpreter, or the folder (POSIX names
    whichever it was; where the error names none, both are given)."""
    if error.filename is not None:
        return f"{error.strerror or error}: {error.filename}"
    return f"{error} (running {argv[0] if argv else 'nothing'} in {cwd})"


def _last_line(text: str, limit: int = 300) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:limit] if lines else ""


def _tail(text: str, lines: int = 15, limit: int = 4000) -> str:
    """The last `lines` non-empty lines of `text`, at most `limit` characters of them."""
    kept = [line.rstrip() for line in text.splitlines() if line.strip()][-lines:]
    return "\n".join(kept)[-limit:]


def _shown(argv: Sequence[str]) -> str:
    """The command as the log shows it, quoted the platform's way. For reading only: nothing ever runs this string."""
    return subprocess.list2cmdline(list(argv)) if os.name == "nt" else shlex.join(argv)


def _write_log(path: Path, argv: Sequence[str], cwd: Path | None, outcome: _Outcome, timeout: float, verdict: str,
               notes: Sequence[str] = ()) -> None:
    """Save the command, where it ran, both its streams and how it ended to `path` (UTF-8, folders made as needed)."""
    lines = [f"$ {_shown(argv)}", f"in {cwd}", *notes, ""]
    for name, text in (("stdout", outcome.stdout), ("stderr", outcome.stderr)):
        if text:
            lines += [f"--- {name} ---", text.rstrip("\n"), ""]
    if outcome.error is not None:
        ending = f"could not start: {_why_not_started(outcome.error, argv, cwd)}"
    elif outcome.timed_out:
        ending = f"timed out after {timeout:g} s, and was stopped with what it started"
    else:
        ending = f"exit code {outcome.code} after {outcome.seconds:.1f} s"
    lines += [f"--- {ending} ---", f"result: {verdict}"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- one check ----

def run_check(check: Check, env: Mapping[str, str], log_path: Path, timeout: float = 1200) -> CheckResult:
    """Run one check with `env` as its whole environment, save its output to `log_path` and say how it went.

    An unavailable check returns at once with its reason: nothing runs, no log, no config file (its argv may be empty).
    Otherwise a harness check's config is first written, as UTF-8 JSON, to the file after `--config` in its argv,
    folders made as needed (R25). Then:

    - a check that cannot start (no interpreter, no folder), times out ("timed out after <n> s"; it is stopped with
      whatever it started) or exits non-zero fails;
    - an import check (imports_b, imports_a) also fails unless every module path it printed lies in the stage, its own
      folder or, for imports_b, which runs in the stage's pair_b, the one above (imports_ok decides);
    - pytest's summary and counts come from parse_pytest_summary, and a pytest run that passes without a summary line
      is "passed (no counts reported)" (R27);
    - a harness check's summary is the pass, manual and fail counts of the report.json in the folder after `--out`;
    - unittest's (on stderr) is the number of tests and its verdict, as "Ran 11 tests: OK";
    - otherwise a pass is "passed" and a failure is its exit code and the last line it wrote to stderr (or stdout).

    The log holds the command, its folder, both its streams and how it ended, whatever the outcome."""
    if check.unavailable is not None:
        return CheckResult(check.key, check.label, "unavailable", check.unavailable, {}, None)
    log_path, notes = Path(log_path), []
    if check.config is not None:
        config = Path(_after(check.argv, "--config"))
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps(check.config), encoding="utf-8")
        notes.append(f"config written to {config}: {json.dumps(check.config)}")
    outcome = _execute(check.argv, check.cwd, env, timeout)
    status, summary, counts = _judge(check, outcome, timeout)
    _write_log(log_path, check.argv, check.cwd, outcome, timeout, f"{status} ({summary})", notes)
    return CheckResult(check.key, check.label, status, summary, counts, str(log_path))


def _after(argv: Sequence[str], flag: str) -> str:
    """The argument after `flag` in `argv`. ValueError when there is none."""
    position = list(argv).index(flag)
    if position + 1 == len(argv):
        raise ValueError(f"nothing follows {flag} in {list(argv)}")
    return argv[position + 1]


def _runs_module(argv: Sequence[str], module: str) -> bool:
    return any(argv[i] == "-m" and argv[i + 1] == module for i in range(len(argv) - 1))


def _failure(outcome: _Outcome) -> str:
    last = _last_line(outcome.stderr) or _last_line(outcome.stdout)
    return f"exit code {outcome.code}: {last}" if last else f"exit code {outcome.code}"


def _judge(check: Check, outcome: _Outcome, timeout: float) -> tuple[str, str, dict]:
    """(status, summary, counts) of a check that was run (see run_check)."""
    if outcome.error is not None:
        return "fail", f"could not start: {_why_not_started(outcome.error, check.argv, check.cwd)}", {}
    if outcome.timed_out:
        return "fail", f"timed out after {timeout:g} s", {}
    passed = outcome.code == 0
    status = "pass" if passed else "fail"
    if check.key.startswith("harness:"):
        report = _read_report(Path(_after(check.argv, "--out")))
        if report is None:
            return status, "passed, but it wrote no report.json" if passed else _failure(outcome), {}
        counts = _harness_counts(report)
        return status, f"{counts['pass']} pass, {counts['manual']} manual, {counts['fail']} fail", counts
    if check.key in _IMPORT_CHECKS:
        if not passed:
            return "fail", _failure(outcome), {}
        root = Path(check.cwd)
        for _ in range(_IMPORT_CHECKS[check.key]):
            root = root.parent
        if imports_ok(outcome.stdout, root):
            return "pass", "imports the stage's own code", {}
        outside = [line.strip() for line in outcome.stdout.splitlines()
                   if line.strip() and not imports_ok(line, root)]
        if not outside:
            return "fail", "it printed no module paths", {}
        return "fail", f"imported from outside the stage: {', '.join(outside)}", {}
    if _runs_module(check.argv, "pytest"):
        counts = parse_pytest_summary(outcome.stdout)
        said = _pytest_words(counts)
        if not said:
            return status, "passed (no counts reported)" if passed else _failure(outcome), counts
        if not passed and not (counts["failed"] or counts["errors"]):
            said += f" (exit code {outcome.code})"  # pytest failing after its tests, say on a plugin's error
        return status, said, counts
    if _runs_module(check.argv, "unittest"):
        ran = _UNITTEST_RAN.search(outcome.stderr)
        if ran:
            tests = int(ran.group(1))
            return status, f"Ran {tests} test{'' if tests == 1 else 's'}: {_last_line(outcome.stderr)}", {}
    return status, "passed" if passed else _failure(outcome), {}


def _pytest_words(counts: dict) -> str:
    """pytest's counts in its own words and order: "1 failed, 159 passed, 1 skipped, 2 errors"; "" when all are 0."""
    errors = counts["errors"]
    words = ((counts["failed"], "failed"), (counts["passed"], "passed"), (counts["skipped"], "skipped"),
             (errors, "error" if errors == 1 else "errors"))
    return ", ".join(f"{number} {word}" for number, word in words if number)


def _read_report(folder: Path) -> dict | None:
    """The report.json Bryan's harness wrote in `folder`, or None when it is not there or not a report."""
    try:
        report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):  # missing, unreadable, not UTF-8, not JSON
        return None
    return report if isinstance(report, dict) and isinstance(report.get("checks"), list) else None


def _harness_counts(report: dict) -> dict:
    counts = {"pass": 0, "manual": 0, "fail": 0}
    for item in report["checks"]:
        status = item.get("status") if isinstance(item, dict) else None
        if status in counts:
            counts[status] += 1
    return counts


# ---- git ----

def _without_git_location(env: Mapping[str, str]) -> dict[str, str]:
    return {name: value for name, value in env.items() if name.upper() not in _GIT_LOCATION}


def _git(where: Path, *args: str, timeout: float = _GIT_TIMEOUT, ceiling: Path | None = None) -> _Outcome:
    """`git -C <where> <args>`, with nothing pointing it at another repository and no prompts for credentials (a run
    has nobody to answer them). `ceiling` keeps git from looking for a repository above that folder. RuntimeError when
    git cannot be started at all; any other failure is in the outcome for the caller to read."""
    env = _without_git_location(os.environ)
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    if ceiling is not None:
        env["GIT_CEILING_DIRECTORIES"] = str(ceiling)
    outcome = _execute(("git", "-C", str(where), *args), None, env, timeout)
    if outcome.error is not None:
        raise RuntimeError(f"could not run git: {_why_not_started(outcome.error, ('git',), None)}")
    return outcome


def _resolve(checkout: Path, ref: str) -> str | None:
    """The commit `ref` names in the checkout, or None: no such ref, not a commit, or a ref git would read as an
    option."""
    if not ref or ref.startswith("-"):
        return None
    outcome = _git(checkout, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    sha = outcome.stdout.strip()
    return sha if outcome.code == 0 and sha else None


def _run_folder(path: Path, temp_root: Path) -> Path | None:
    """The fog-lab-* folder directly in the temporary folder that holds `path`, or None when `path` is elsewhere."""
    try:
        parts = path.resolve().relative_to(temp_root).parts
    except (OSError, ValueError):
        return None
    return temp_root / parts[0] if parts and parts[0].startswith("fog-lab-") else None


def _remove_stale_worktrees(checkout: Path, on_progress: Callable[[str], None]) -> None:
    """Remove the worktrees an earlier run left registered in the checkout (see the module docstring), however it left
    them: whole, locked by a `git worktree add` it was killed in, or with their folder gone; then prune. The checkout
    itself, listed first, is never one of them."""
    listed = _git(checkout, "worktree", "list", "--porcelain").stdout
    paths = [line[len("worktree "):] for line in listed.splitlines() if line.startswith("worktree ")]
    temp_root = Path(tempfile.gettempdir()).resolve()
    stale = []
    for path in paths[1:]:
        folder = _run_folder(Path(path), temp_root)
        if folder is not None and not checkout.is_relative_to(folder):
            stale.append((path, folder))
    if stale:
        on_progress(f"Removing {len(stale)} worktree{'' if len(stale) == 1 else 's'} left by an earlier run")
    for path, folder in stale:
        _git(checkout, "worktree", "remove", "--force", "--force", path)  # twice: removes a locked one too
        shutil.rmtree(folder, ignore_errors=True)
    _git(checkout, "worktree", "prune")


def _fetch(checkout: Path, fetch: bool, on_progress: Callable[[str], None]) -> dict:
    if not fetch:
        return {"requested": False, "ok": None, "message": "not fetched: the run was asked not to"}
    on_progress("Fetching from origin")
    outcome = _git(checkout, "fetch", "--quiet", "origin", timeout=_FETCH_TIMEOUT)
    if outcome.code == 0:
        return {"requested": True, "ok": True, "message": "fetched from origin"}
    if outcome.timed_out:
        message = f"git fetch origin timed out after {_FETCH_TIMEOUT} s"
    else:
        said = " ".join(line.strip() for line in outcome.stderr.splitlines() if line.strip())[:500]
        message = said or f"git fetch origin exited with code {outcome.code}"
    on_progress(f"Could not fetch, so the run uses the refs this checkout already has: {message}")
    return {"requested": True, "ok": False, "message": message}


def _clean_up(checkout: Path, temp: Path, worktree: Path) -> None:
    """Remove the run's worktree, then its temporary folder (whatever git could not), then git's record of it. Never
    raises: anything left (a git that stopped working, a file Windows holds open) goes at the next run's start."""
    try:
        _git(checkout, "worktree", "remove", "--force", "--force", str(worktree))
    except RuntimeError:
        pass
    shutil.rmtree(temp, ignore_errors=True)
    try:
        _git(checkout, "worktree", "prune")
    except RuntimeError:
        pass


# ---- the stages ----

def _stage_environment(worktree: Path) -> dict[str, str]:
    """stage_env for the worktree, without the user's pytest options (R27: PYTEST_ADDOPTS=-q would make a stage run
    -qq, which prints no summary line) and without the variables that name a git repository, so a stage's own tests
    that call git find their stage, not whatever repository started this process."""
    env = _without_git_location(stage_env(worktree, os.environ))
    return {name: value for name, value in env.items() if name.upper() != "PYTEST_ADDOPTS"}


def _log_name(index: int, key: str) -> str:
    return f"{index}-{_NOT_IN_A_NAME.sub('-', key)}.txt"


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


class _Run:
    """One run in progress: where it builds, what it runs the checks with, and the last stage it built cleanly."""

    def __init__(self, checkout: Path, run_dir: Path, temp: Path, *, torch: bool, stockfish: str, device: str | None,
                 check_runner: Callable[[Check, Mapping[str, str], Path], CheckResult],
                 on_progress: Callable[[str], None]):
        self.checkout, self.run_dir, self.temp, self.worktree = checkout, run_dir, temp, temp / "stage"
        self.envs = find_envs(checkout)
        self.options = {"torch": torch, "stockfish": stockfish, "device": device}
        self.check_runner, self.progress = check_runner, on_progress
        self.last: tuple[int, str, list[Check], list[CheckResult]] | None = None

    def in_worktree(self, *args: str) -> _Outcome:
        return _git(self.worktree, *args, ceiling=self.temp)

    @staticmethod
    def result(stage: Stage, sha: str | None, merge: str, conflicts=(), checks=()) -> StageResult:
        return StageResult(stage.label, stage.ref, sha, merge, list(conflicts), list(checks), stage.title)

    def stage(self, index: int, stage: Stage, head: str | None, final: bool) -> StageResult:
        """Build `stage` on top of the ones before it, then run its checks. The first stage makes the worktree;
        "+ this checkout" (`final`) merges the checkout's HEAD, `head`, unless the worktree already holds it."""
        if final:
            if head is None:
                return self.result(stage, None, "missing-ref")
            if self.in_worktree("merge-base", "--is-ancestor", head, "HEAD").code == 0:
                self.progress(f"{stage.label}: already in the stages before it")
                return self.result(stage, head, "contained")
            sha, what = head, f"this checkout's HEAD ({head[:7]})"
        else:
            sha = _resolve(self.checkout, stage.ref)
            if sha is None:
                self.progress(f"{stage.label}: {stage.ref} names no commit here")
                return self.result(stage, None, "missing-ref")
            what = f"{stage.ref} ({sha[:7]})"
        if index == 0:
            self.progress(f"{stage.label}: checking out {what}")
            added = _git(self.checkout, "worktree", "add", "--detach", str(self.worktree), sha)
            if added.code != 0:
                why = (f"git worktree add timed out after {_GIT_TIMEOUT} s" if added.timed_out else
                       _tail(added.stderr, 3) or f"git worktree add exited with code {added.code}")
                raise RuntimeError(f"could not make the worktree for {stage.label}: {why}")
        else:
            self.progress(f"{stage.label}: merging {what}")
            merged = self.in_worktree(*_MERGE, "merge", "--no-ff", "--no-edit", "--no-verify", sha)
            if merged.timed_out:
                raise RuntimeError(f"{stage.label}: git merge timed out after {_GIT_TIMEOUT} s")
            if merged.code != 0:
                unmerged = self.in_worktree("diff", "--name-only", "--diff-filter=U", "-z").stdout
                conflicts = list(dict.fromkeys(name for name in unmerged.split("\0") if name))
                self.in_worktree("merge", "--abort")
                self.progress(f"{stage.label}: merge conflict in {', '.join(conflicts)}" if conflicts else
                              f"{stage.label}: git could not merge it: {_tail(merged.stderr, 3)}")
                return self.result(stage, sha, "conflict", conflicts)
        return self.result(stage, sha, "clean", checks=self.run_checks(index, stage))

    def run_checks(self, index: int, stage: Stage) -> list[CheckResult]:
        """Run the checks of the stage now in the worktree, each with the stage's environment and a log of its own,
        and remember the stage as the last cleanly built one."""
        head = self.in_worktree("rev-parse", "HEAD").stdout.strip()  # the code under test: the stage's merge commit
        checks = stage_checks(self.worktree, self.envs, self.run_dir / "stages" / str(index), head, **self.options)
        env = _stage_environment(self.worktree)
        results = []
        for check in checks:
            self.progress(f"{stage.label}: {check.label}")
            log_path = self.run_dir / "logs" / _log_name(index, check.key)
            result = self.check_runner(check, dict(env), log_path)
            if result.log is not None:
                result = replace(result, log=_relative(log_path, self.run_dir))
            results.append(result)
        self.last = (index, stage.label, checks, results)
        return results

    def final(self) -> dict | None:
        """The fog-rules, harness and accuracy sections, from the last cleanly built stage (which the worktree holds:
        a merge that failed after it was aborted). None when no stage was built."""
        if self.last is None:
            return None
        index, label, checks, results = self.last
        env = _stage_environment(self.worktree)
        fixtures = {rules: self.fixtures(index, rules, env) for rules in RULES}
        harness = {check.key.split(":", 1)[1]: _harness_entry(check, result)
                   for check, result in zip(checks, results) if check.key.startswith("harness:")}
        self.progress("Reading the accuracy files")
        accuracy = read_accuracy(self.worktree / "pair_b" / "checkpoints")
        return {"label": label, "fixtures": fixtures, "harness": harness, "accuracy": accuracy}

    def fixtures(self, index: int, rules: str, env: Mapping[str, str]) -> dict:
        against = "our stand-in observe" if rules == "standin" else "Teal's rules adapter"
        self.progress(f"Fog rules: Pair A's positions against {against}")
        argv = (str(self.envs.pair_b_python), str(FIXTURE_CHECK), "--rules", rules)
        outcome = _execute(argv, self.worktree, env, _FIXTURE_TIMEOUT)
        entry = _fixtures_entry(rules, outcome, argv, self.worktree)
        cases = entry["cases"]
        failing = sum(1 for case in cases if not isinstance(case, dict) or case.get("errors"))
        verdict = (f"{entry['status']} ({entry['reason']})" if entry.get("reason") else
                   f"{entry['status']} ({failing} of {len(cases)} positions fail)")
        log_path = self.run_dir / "logs" / _log_name(index, f"fixtures-{rules}")
        _write_log(log_path, argv, self.worktree, outcome, _FIXTURE_TIMEOUT, verdict)
        return {**entry, "log": _relative(log_path, self.run_dir)}


def _fixtures_entry(rules: str, outcome: _Outcome, argv: Sequence[str], cwd: Path) -> dict:
    """fixture_check.py's report with its status, or, when the check itself failed, a failure entry (R21)."""
    if outcome.code == 0:
        try:
            report = json.loads(outcome.stdout)
        except ValueError:
            report = None
        if isinstance(report, dict) and isinstance(report.get("available"), bool) and \
                isinstance(report.get("cases"), list):
            failing = any(not isinstance(case, dict) or case.get("errors") for case in report["cases"])
            status = "unavailable" if not report["available"] else "fail" if failing else "pass"
            return {**report, "status": status}
        reason = "it exited 0 but did not print its JSON report"
    elif outcome.error is not None:
        reason = f"could not start: {_why_not_started(outcome.error, argv, cwd)}"
    elif outcome.timed_out:
        reason = f"timed out after {_FIXTURE_TIMEOUT} s"
    else:
        reason = _tail(outcome.stderr) or f"exit code {outcome.code}"
    return {"rules": rules, "available": False, "status": "fail", "reason": reason, "cases": []}


def _harness_entry(check: Check, result: CheckResult) -> dict:
    report = None if result.status == "unavailable" else _read_report(Path(_after(check.argv, "--out")))
    return {"status": result.status, "summary": result.summary,
            "counts": {} if report is None else _harness_counts(report),
            "checks": [] if report is None else report["checks"],
            "metadata": None if report is None else report.get("metadata"), "log": result.log}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_stages(checkout: Path, stages: list[Stage], run_dir: Path, *, fetch: bool = True,
               torch: bool, stockfish: str = "stockfish", device: str | None = None,
               check_runner: Callable[[Check, Mapping[str, str], Path], CheckResult] = run_check,
               on_progress: Callable[[str], None] = lambda message: None,
               on_stage: Callable[[dict], None] = lambda stage: None) -> dict:
    """Merge `stages` one by one in a throwaway worktree of `checkout`, run each stage's checks there, add
    "+ this checkout", and return the run summary (the module docstring has the steps and the summary's shape).

    `run_dir` is this run's folder: logs and harness files go in it (it is made if need be). `fetch` asks for
    `git fetch origin` first. `torch`, `stockfish` and `device` are passed to stage_checks. `check_runner` runs each
    check (`run_check` with its default timeout; tests pass a fake), handed the check, the stage's environment and the
    log path. `on_progress` gets a line of text at each step, and `on_stage` each finished stage's JSON as soon as the
    stage is done (R7): the same dict that goes into "stages", which is not changed afterwards.

    ValueError when there are no stages; RuntimeError when `checkout` is not a git checkout, git cannot be run, or a
    stage's worktree cannot be made. Whatever is raised, from here or from a callback or the check runner, the
    worktree and its temporary folder are removed first."""
    stages = list(stages)
    if not stages:
        raise ValueError("there are no stages to run")
    checkout, run_dir = Path(checkout).resolve(), Path(run_dir).resolve()  # the commands run in other folders
    started = _now()
    if _git(checkout, "rev-parse", "--is-inside-work-tree").stdout.strip() != "true":  # "false" in a bare one
        raise RuntimeError(f"{checkout} is not a git checkout")
    _remove_stale_worktrees(checkout, on_progress)
    fetched = _fetch(checkout, fetch, on_progress)
    head = _resolve(checkout, "HEAD")
    named = _git(checkout, "rev-parse", "--abbrev-ref", "HEAD")
    branch = named.stdout.strip() if named.code == 0 else ""
    planned = [*stages, Stage(THIS_CHECKOUT, "HEAD", "detached HEAD" if branch == "HEAD" else branch)]
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    reported: list[dict] = []
    temp = Path(tempfile.mkdtemp(prefix="fog-lab-")).resolve()
    try:
        run = _Run(checkout, run_dir, temp, torch=torch, stockfish=stockfish, device=device,
                   check_runner=check_runner, on_progress=on_progress)
        stopped = False
        for index, stage in enumerate(planned):
            if stopped:
                result = run.result(stage, None, "skipped")
            else:
                result = run.stage(index, stage, head, final=index == len(stages))
                stopped = result.merge in ("missing-ref", "conflict")
            reported.append(asdict(result))
            on_stage(reported[-1])
        final = run.final()
    finally:
        _clean_up(checkout, temp, temp / "stage")
    on_progress("Done")
    return {"started": started, "finished": _now(),
            "machine": {"name": platform.node(), "system": platform.system(), "release": platform.release(),
                        "arch": platform.machine(), "python": platform.python_version(), "torch": torch},
            "fetch": fetched, "checkout_sha": head, "stages": reported, "final": final}
