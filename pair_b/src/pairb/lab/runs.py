"""Fog Lab's test runs in the background, one at a time, each saved in a folder of its own, the newest ten kept (spec
5.5). The Tests tab starts a run, polls it while it goes, and shows the latest saved run when it opens.

A RunManager runs the staged runner (stage_runner.run_stages) in a thread of its own, so the request that starts a run
answers at once; start() raises RunBusy while a run is going. The stages file is read when each run starts, so editing
it changes the next run. While a run goes, status() has its progress lines and the stages it has finished (R7), so the
page can fill the cards in as it goes:

    {"running", "id", "started", "progress": [lines], "stages": [stage JSON, ...], "error"}

It describes the run that is going, or else the last one this manager ran (all None or empty before the first);
"error" is why that run failed, or None.

Storage, in the app's home (pair_b/.fog_lab, which git ignores):

    home/runs/<id>/summary.json   run_stages's summary, with "id" first and "error" (None) last
    home/runs/<id>/logs/          the checks' logs, as run_stages writes them (its harness files go beside, in stages/)

A run's id is its local start time, YYYYMMDD-HHMMSS-ffffff, so the folders sort by age. An id is always later than
every run folder there and every id given before, so a clock set back (or the end of summer time) cannot put a new run
before an old one. summary.json is written whole or not at all, as UTF-8. After each run only the newest `keep` run
folders are kept, by id: only folders directly in home/runs that are named like a run are counted or deleted, never a
link, a file or anything outside home/runs. latest() reads the newest summary.json there, so it survives a restart.

A run that raises (git missing, a stages file that cannot be read, a runner's bug) is saved too, with the same keys,
None for what it never got to, the stages it finished, and "error" saying what went wrong; the trace goes to the window
that started the app. Either way the manager is idle again afterwards.

close() stops a run that is going (R29): it sets the `cancel` event the runner was given, which stops the check in
progress with whatever it started, skips the rest and still removes the worktree, then waits a little for the run to be
saved. The run's thread is not a daemon: a run that is inside a git command (never stopped part way, since that could
leave locks in the user's repository) finishes that command and cleans up before the app exits.
"""
import json
import os
import re
import shutil
import sys
import threading
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from .paths import write_atomically
from .stage_runner import run_stages
from .stages import load_stages

ID_FORMAT = "%Y%m%d-%H%M%S-%f"
RUN_ID = re.compile(r"[0-9]{8}-[0-9]{6}-[0-9]{6}")  # ASCII digits only: \d would take others
LOG_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")  # one name, no folders or dot files, as run_stages makes
SUMMARY = "summary.json"
_OWN = ("fetch", "cancel", "on_progress", "on_stage")  # what the manager itself gives the runner


class RunBusy(RuntimeError):
    """No run can start now: one is going, or the manager is closing."""


def _clock() -> datetime:
    """Now, in local time: where run ids come from (a test sets it back)."""
    return datetime.now()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class RunManager:
    """The test runs of one checkout, saved under `home`/runs (see the module docstring).

    `checkout` is the checkout the app runs from, `stages_file` the stages to merge, `keep` how many run folders to
    keep. `runner` is called as runner(checkout, stages, run_dir, fetch=, cancel=, on_progress=, on_stage=,
    **runner_kwargs) and returns the summary: run_stages, with torch, stockfish and device in `runner_kwargs`; tests
    give a fake. Nothing is read or written until a run starts. Its methods may be called from many threads at once.
    """

    def __init__(self, checkout: Path, home: Path, stages_file: Path, *, keep: int = 10,
                 runner: Callable[..., dict] = run_stages, **runner_kwargs):
        if isinstance(keep, bool) or not isinstance(keep, int) or keep < 1:
            raise ValueError(f"keep must be a whole number of runs, 1 or more, not {keep!r}")
        clash = [name for name in _OWN if name in runner_kwargs]
        if clash:
            raise ValueError(f"the run manager gives the runner {', '.join(clash)} itself")
        self.checkout, self.home, self.stages_file = Path(checkout), Path(home), Path(stages_file)
        self.runs_dir = self.home / "runs"
        self.keep, self.runner, self.runner_kwargs = keep, runner, dict(runner_kwargs)
        self._cancel = threading.Event()  # set by close(); a run, once stopped, is never started again
        self._lock = threading.Lock()  # guards the fields below, and is never held while a run works
        self._closed = False
        self._thread: threading.Thread | None = None
        self._running = False
        self._id: str | None = None
        self._started: str | None = None
        self._error: str | None = None
        self._progress: list[str] = []
        self._stages: list[dict] = []
        self._last_id = ""  # the newest id this manager has given

    # ---- starting, and what the page sees ----

    def start(self, fetch: bool = True) -> str:
        """Start a run in the background and return its id. `fetch` asks for `git fetch origin` first. RunBusy when a
        run is going or the manager is closing; OSError when the run's folder cannot be made."""
        with self._lock:
            if self._closed:
                raise RunBusy("Fog Lab is closing, so no test run can start")
            if self._running:
                raise RunBusy(f"a test run is already going: {self._id}")
            run_id = self._next_id()
            run_dir = self.runs_dir / run_id
            run_dir.mkdir(parents=True)
            thread = threading.Thread(target=self._run, args=(run_id, run_dir, bool(fetch)),
                                      name=f"Fog Lab test run {run_id}")
            self._running, self._id, self._started, self._error = True, run_id, _now(), None
            self._progress, self._stages, self._last_id, self._thread = [], [], run_id, thread
            try:
                thread.start()
            except BaseException:  # no thread to be had: the run never was
                self._running, self._thread = False, None
                shutil.rmtree(run_dir, ignore_errors=True)
                raise
        return run_id

    def status(self) -> dict:
        """The run that is going, or the last one this manager ran: {"running", "id", "started", "progress",
        "stages", "error"} (the module docstring has them). Plain JSON data in lists of its own; the stage dicts in it
        are this manager's copies, which are never changed."""
        with self._lock:
            return {"running": self._running, "id": self._id, "started": self._started,
                    "progress": list(self._progress), "stages": list(self._stages), "error": self._error}

    def latest(self) -> dict | None:
        """The summary of the newest run folder that holds a readable one, read from disk; None when none does. A
        folder whose summary is missing (a run going, or one that was killed) or damaged is passed over. Its "id" is
        its folder's name, which the log routes go by."""
        for name in reversed(self._folders()):
            try:
                summary = json.loads((self.runs_dir / name / SUMMARY).read_text(encoding="utf-8"))
            except (OSError, ValueError, RecursionError):  # ValueError holds bad UTF-8 and bad JSON
                continue
            if isinstance(summary, dict):
                summary["id"] = name
                return summary
        return None

    def log_path(self, run_id: str, name: str) -> Path:
        """Where the log called `name` of run `run_id` is: a file directly inside home/runs/<id>/logs. ValueError for
        an id not shaped like one or a name that is not one plain file name (both checked before anything is looked
        at on disk), and for a path that a link would lead out of that folder. Whether the file is there is the
        caller's to find out."""
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise ValueError(f"{run_id!r} is not the id of a run")
        if not isinstance(name, str) or not LOG_NAME.fullmatch(name):
            raise ValueError(f"{name!r} is not the name of a log")
        path = self.runs_dir.resolve() / run_id / "logs" / name
        if path.resolve() != path:  # the run's folder, its logs folder or the file is a link
            raise ValueError(f"the log {name!r} of run {run_id} is not inside its logs folder")
        return path

    def close(self, timeout: float = 10.0) -> bool:
        """Stop the run that is going, if there is one, and wait up to `timeout` seconds for it to be saved; no run can
        start afterwards. True when no run is left going. Calling it again does no harm."""
        with self._lock:
            self._closed = True
            thread = self._thread
        self._cancel.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    # ---- the run's thread ----

    def _run(self, run_id: str, run_dir: Path, fetch: bool) -> None:
        """Run, save the summary, keep the newest folders, and be idle again, whatever happens."""
        error = None
        try:
            summary = self._outcome(run_id, run_dir, fetch)
            error = summary["error"]
            try:
                write_atomically(run_dir / SUMMARY, json.dumps(summary, ensure_ascii=False, indent=1))
            except (OSError, TypeError, ValueError) as failure:  # TypeError and ValueError: not JSON data
                error = f"could not save the run: {failure}"
                print(f"Fog Lab: test run {run_id} {error}", file=sys.stderr, flush=True)
            self._prune()
        finally:
            with self._lock:
                self._running, self._error = False, error

    def _outcome(self, run_id: str, run_dir: Path, fetch: bool) -> dict:
        """The summary to save: the runner's, or, when it (or reading the stages) raised, one with the same keys."""
        try:
            summary = self.runner(self.checkout, load_stages(self.stages_file), run_dir, fetch=fetch,
                                  cancel=self._cancel, on_progress=self._progressed, on_stage=self._staged,
                                  **self.runner_kwargs)
            saved = {"id": run_id, **summary}
        except BaseException as error:  # the top of the thread: nothing above it would show the page what happened
            print(f"Fog Lab: test run {run_id} failed:", file=sys.stderr)
            traceback.print_exc()
            sys.stderr.flush()
            with self._lock:
                started, stages = self._started, list(self._stages)
            return {"id": run_id, "started": started, "finished": _now(), "machine": None, "fetch": None,
                    "checkout_sha": None, "stages": stages, "final": None, "stopped": self._cancel.is_set(),
                    "error": f"{type(error).__name__}: {error}" if str(error) else type(error).__name__}
        saved.update(id=run_id, error=None)
        return saved

    def _progressed(self, message) -> None:
        with self._lock:
            self._progress.append(str(message))

    def _staged(self, stage: dict) -> None:
        copied = json.loads(json.dumps(stage))  # plain JSON data of its own: status() shares nothing with the runner
        with self._lock:
            self._stages.append(copied)

    # ---- the run folders ----

    def _folders(self) -> list[str]:
        """The names of the run folders, oldest first: folders directly in home/runs, not links (nor Windows
        junctions), named like a run id. An entry that cannot be looked at is left out."""
        names = []
        try:
            with os.scandir(self.runs_dir) as entries:
                for entry in entries:
                    try:
                        if RUN_ID.fullmatch(entry.name) and entry.is_dir(follow_symlinks=False) \
                                and not entry.is_junction():
                            names.append(entry.name)
                    except OSError:
                        continue
        except OSError:  # no runs folder yet, or one that cannot be read
            return []
        return sorted(names)

    def _next_id(self) -> str:
        """A new run's id: now, unless that is not later than every run folder and the last id given, and then the
        newest of those plus a microsecond."""
        run_id = _clock().strftime(ID_FORMAT)
        newest = max([self._last_id, *self._folders()])
        if run_id <= newest:
            try:
                run_id = (datetime.strptime(newest, ID_FORMAT) + timedelta(microseconds=1)).strftime(ID_FORMAT)
            except (ValueError, OverflowError):  # a folder named like a run that is no real time: go by the clock
                pass
        return run_id

    def _prune(self) -> None:
        """Delete every run folder but the newest `keep`. Never raises: a folder that cannot be deleted now is tried
        again after the next run."""
        for name in self._folders()[:-self.keep]:
            shutil.rmtree(self.runs_dir / name, ignore_errors=True)
