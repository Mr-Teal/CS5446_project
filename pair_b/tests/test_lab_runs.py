"""Fog Lab's background test runs (pairb.lab.runs) and the Tests tab's routes on the server.

No test here starts a real staged run. Each RunManager gets a FakeRunner, which records how it was called, sends some
progress and one finished stage, writes a log where run_stages would, and returns a summary of run_stages's shape. A
fake can be told to hold until the test lets it go (or the manager asks it to stop), or to raise. Every home is under
tmp_path, and every manager and server a test makes is closed at its end, so no run's thread outlives its test.
"""
import contextlib
import dataclasses
import http.client
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pytest

from fow_shared.contracts import Decision
from no_torch import PAIR_B
from pairb.lab import paths, runs
from pairb.lab.runs import RunBusy, RunManager
from pairb.lab.scorers import ScorerOptions
from pairb.lab.server import LabApp, make_server
from pairb.lab.session import BOTS, BotSpec, Session, default_tracker
from pairb.lab.stages import load_stages
from pairb.rules import StandinRules

REPO = PAIR_B.parent
RUN_ID = re.compile(r"[0-9]{8}-[0-9]{6}-[0-9]{6}")
LOG_NAME = "0-pair_b.txt"
LOG = "1 passed \u2713 \u00e9\n"  # not ASCII: a log is sent as the UTF-8 it was written in
STAGE = {"label": "main", "ref": "origin/main", "sha": "c0ffee", "merge": "clean", "conflicts": [],
         "checks": [{"key": "pair_b", "label": "Pair B", "status": "pass", "summary": "1 passed",
                     "counts": {"passed": 1, "failed": 0, "errors": 0, "skipped": 0}, "log": f"logs/{LOG_NAME}"}],
         "title": "Pair B \u265f\ufe0e"}
SUMMARY_KEYS = ["id", "started", "finished", "machine", "fetch", "checkout_sha", "stages", "final", "stopped", "error"]
IDLE = {"running": False, "id": None, "started": None, "progress": [], "stages": [], "error": None}


class FakeRunner:
    """A runner that runs nothing (see the module docstring). `calls` records each call; `entered` is set once the
    call has sent its progress and its stage; with hold=True it then waits until `release` is set or the manager stops
    the run (a minute at most); `error`, when given, is raised at the end instead of returning the summary."""

    def __init__(self, hold=False, error=None, progress=("stage 1",)):
        self.hold, self.error, self.progress = hold, error, progress
        self.calls = []
        self.entered, self.release = threading.Event(), threading.Event()

    def __call__(self, checkout, stages, run_dir, *, fetch, cancel, on_progress, on_stage, **options):
        self.calls.append({"checkout": checkout, "stages": stages, "run_dir": run_dir, "fetch": fetch,
                           "cancel": cancel, "options": options})
        started = datetime.now().astimezone().isoformat(timespec="microseconds")
        for message in self.progress:
            on_progress(message)
        logs = Path(run_dir) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / LOG_NAME).write_text(LOG, encoding="utf-8")
        on_stage(STAGE)
        self.entered.set()
        deadline = time.monotonic() + 60
        while self.hold and not (self.release.is_set() or cancel.is_set()) and time.monotonic() < deadline:
            time.sleep(0.01)
        if self.error is not None:
            raise self.error
        return {"started": started, "finished": datetime.now().astimezone().isoformat(timespec="seconds"),
                "machine": {"name": "test", "system": "Test", "release": "1", "arch": "x", "python": "3.14",
                            "torch": False},
                "fetch": {"requested": fetch, "ok": None, "message": "not fetched"}, "checkout_sha": "c0ffee",
                "stages": [STAGE], "final": None, "stopped": cancel.is_set()}


@pytest.fixture
def stages_file(tmp_path):
    path = tmp_path / "fog_lab_stages.json"
    path.write_text(json.dumps({"stages": [{"label": "main", "ref": "origin/main", "title": "after PR #2"},
                                           {"label": "+ PR #4", "ref": "origin/pair-b/evaluators"}]}),
                    encoding="utf-8")
    return path


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


@pytest.fixture
def make_manager(tmp_path, home, stages_file):
    """make_manager(runner, **options) -> a RunManager on the test's home; each one made is closed at the end, which
    stops a fake that is still holding."""
    made = []

    def make(runner, **options):
        manager = RunManager(tmp_path / "checkout", home, stages_file, runner=runner, **options)
        made.append(manager)
        return manager

    yield make
    for manager in made:
        assert manager.close(timeout=60), "a run was still going a minute after it was told to stop"


def finish(manager, timeout=60) -> None:
    """Wait until the manager is idle: its run, if any, is saved and the folders pruned."""
    deadline = time.monotonic() + timeout
    while manager.status()["running"]:
        assert time.monotonic() < deadline, "the run did not finish"
        time.sleep(0.005)


def run_once(manager, fetch=False) -> str:
    run_id = manager.start(fetch=fetch)
    finish(manager)
    return run_id


def run_folders(home) -> list[str]:
    return sorted(path.name for path in (home / "runs").iterdir())


# ---- talking to a server ----

@dataclasses.dataclass
class Answer:
    status: int
    content_type: str
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")

    def data(self):
        return json.loads(self.body)

    def error(self, status: int) -> str:
        """The message of an {"error": ...} answer with this status."""
        assert self.status == status, self.body
        assert self.content_type == "application/json; charset=utf-8"
        data = self.data()
        assert set(data) == {"error"} and isinstance(data["error"], str) and data["error"]
        return data["error"]


class Server:
    """A running server on a free port. Every request opens its own connection."""

    def __init__(self, app, httpd):
        self.app, self.httpd, self.port = app, httpd, httpd.server_address[1]

    def send(self, method, path, body=None, headers=None) -> Answer:
        """A dict or list body goes as JSON; bytes go as they are."""
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return Answer(response.status, response.headers.get("Content-Type", ""), response.read())
        finally:
            connection.close()


@pytest.fixture
def serve(tmp_path, home):
    """serve(runs) -> a Server whose app has `runs` as its run manager; every one started is stopped at the end."""
    started = []

    def start(manager):
        app = LabApp(REPO, ScorerOptions(tmp_path / "no-checkpoints"), StandinRules(), runs=manager, home=home)
        httpd = make_server(app, port=0)
        thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        started.append((app, httpd, thread))
        return Server(app, httpd)

    yield start
    for app, httpd, thread in started:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=30)
        app.close()


# ---- one run at a time ----

# Catches: a second run started while one is going (two runs would share the tab and race on their folders), the
# refusal not reaching the page as a 409, a refused start that still calls the runner, and a manager that stays busy
# after its run.
def test_one_run_at_a_time(make_manager, serve):
    runner = FakeRunner(hold=True)
    manager = make_manager(runner)
    first = manager.start(fetch=False)
    assert runner.entered.wait(30)
    with pytest.raises(RunBusy, match=first):
        manager.start()
    lab = serve(manager)
    assert first in lab.send("POST", "/api/tests/run", {"fetch": False}).error(409)
    assert manager.status()["running"] is True and manager.status()["id"] == first
    assert len(runner.calls) == 1
    runner.release.set()
    finish(manager)
    runner.entered.clear()  # the second run's thread sets it again once it has called the runner
    answer = lab.send("POST", "/api/tests/run", {"fetch": False})
    assert answer.status == 202, answer.body
    second = answer.data()["id"]
    assert runner.entered.wait(30), "the second run never called the runner"
    assert second > first and len(runner.calls) == 2


# ---- storage ----

# Catches: runs piling up for ever, the newest deleted instead of the oldest, a kept folder without its summary or its
# log, and ids that do not sort in the order the runs were made.
def test_keeps_last_ten(make_manager, home):
    manager = make_manager(FakeRunner())
    ids = [run_once(manager) for _ in range(12)]
    assert all(RUN_ID.fullmatch(run_id) for run_id in ids)
    assert ids == sorted(ids) and len(set(ids)) == 12
    assert run_folders(home) == ids[2:]
    for run_id in ids[2:]:
        summary = json.loads((home / "runs" / run_id / "summary.json").read_text(encoding="utf-8"))
        assert summary["id"] == run_id
        assert (home / "runs" / run_id / "logs" / LOG_NAME).is_file()


# Catches: a keep that is not honoured, and a clean-up that deletes anything but the run folders, or counts anything
# else as one: a file, a folder of another name, a link named like a run (and what it leads to), or whatever lies
# outside home/runs. The file and the link have ids newer than any run, so counting them would cost real runs.
def test_only_old_run_folders_are_deleted(make_manager, home, tmp_path):
    folder = home / "runs"
    (folder / "20000101-000000-000000" / "logs").mkdir(parents=True)  # older than any run made below
    (folder / "notes").mkdir()
    (folder / "notes.txt").write_text("mine", encoding="utf-8")
    (folder / "29990101-000000-000001").write_text("a file with a run's name", encoding="utf-8")
    outside = tmp_path / "outside"
    (outside / "logs").mkdir(parents=True)
    (outside / "logs" / "keep.txt").write_text("not the lab's", encoding="utf-8")
    link = folder / "29990101-000000-000002"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        link = None  # this machine cannot make links: the rest still holds
    manager = make_manager(FakeRunner(), keep=2)
    ids = [run_once(manager) for _ in range(3)]
    assert all(run_id < "2999" for run_id in ids), "the ids went past a file or link taken for a run"
    names = {path.name for path in folder.iterdir()}
    assert names == {*ids[1:], "notes", "notes.txt", "29990101-000000-000001"} | (
        {"29990101-000000-000002"} if link is not None else set())
    assert (outside / "logs" / "keep.txt").read_text(encoding="utf-8") == "not the lab's"
    with pytest.raises(ValueError, match="keep"):
        RunManager(tmp_path, home, tmp_path / "stages.json", keep=0)


# Catches: a summary that is not readable after a restart (kept only in memory), a restart that loses which run is the
# newest, and a new manager whose status claims the old one's run.
def test_latest_survives_restart(make_manager, home):
    manager = make_manager(FakeRunner())
    assert manager.latest() is None
    run_once(manager)
    newest = run_once(manager)
    latest = manager.latest()
    assert latest["id"] == newest
    assert manager.close()
    again = make_manager(FakeRunner())
    assert again.latest()["started"] == latest["started"]
    assert again.latest() == latest
    assert again.status() == IDLE


# Catches: a summary written in the machine's own encoding (Windows: cp1252) or with escapes, one written in place (a
# reader could see half of it), a temporary file left behind, and keys missing or out of their agreed order.
def test_the_summary_is_saved_whole_as_utf_8(make_manager, home, monkeypatch):
    renames, real_replace = [], os.replace

    def replace(source, target):
        renames.append((Path(source), Path(target)))
        return real_replace(source, target)

    monkeypatch.setattr(paths.os, "replace", replace)
    run_id = run_once(make_manager(FakeRunner()))
    folder = home / "runs" / run_id
    assert sorted(path.name for path in folder.iterdir()) == ["logs", "summary.json"]
    raw = (folder / "summary.json").read_bytes()
    assert STAGE["title"].encode("utf-8") in raw and b"\\u" not in raw
    summary = json.loads(raw.decode("utf-8"))
    assert list(summary) == SUMMARY_KEYS
    assert (summary["id"], summary["error"], summary["stages"]) == (run_id, None, [STAGE])
    saved = [(source, target) for source, target in renames if target.name == "summary.json"]
    assert len(saved) == 1 and saved[0][0].parent == folder and saved[0][1] == folder / "summary.json"


# Catches: a newest summary that cannot be read (a run killed before it saved one, a damaged file) hiding the runs
# before it, or crashing the route; and a link named like a run, leading out of home/runs, taken for the newest run.
def test_latest_skips_summaries_that_cannot_be_read(make_manager, home, tmp_path):
    manager = make_manager(FakeRunner())
    good = run_once(manager)
    for name, text in (("29990101-000000-000001", "{not json"), ("29990101-000000-000002", "[1, 2]")):
        (home / "runs" / name).mkdir()
        (home / "runs" / name / "summary.json").write_text(text, encoding="utf-8")
    (home / "runs" / "29990101-000000-000003").mkdir()  # a run that never saved one
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "summary.json").write_text(json.dumps({"started": "not a run of this lab"}), encoding="utf-8")
    with contextlib.suppress(OSError, NotImplementedError):  # a machine that cannot make links still checks the rest
        (home / "runs" / "29990101-000000-000004").symlink_to(elsewhere, target_is_directory=True)
    assert manager.latest()["id"] == good


# Catches: a clock set back (by hand, or at the end of summer time, since ids are local time) giving a new run an id
# before the old ones: the new run would be shown as older, and pruned first.
def test_a_clock_set_back_cannot_put_a_new_run_before_an_old_one(make_manager, home, monkeypatch):
    manager = make_manager(FakeRunner())
    first = run_once(manager)
    monkeypatch.setattr(runs, "_clock", lambda: datetime(2001, 2, 3, 4, 5, 6, 7))
    second = run_once(manager)
    third = run_once(manager)
    assert RUN_ID.fullmatch(second) and first < second < third
    assert manager.latest()["id"] == third


# ---- what the runner gets, and what the page sees while it goes ----

# Catches: the stages file read once (editing it would not change the next run), the run's folder not handed over,
# fetch or the runner's options not passed on, and options that would clash with the manager's own.
def test_the_runner_gets_the_stages_its_folder_and_the_options(make_manager, tmp_path, home, stages_file):
    runner = FakeRunner()
    manager = make_manager(runner, torch=False, stockfish="sf", device="cpu")
    run_id = run_once(manager, fetch=False)
    call = runner.calls[0]
    assert call["checkout"] == tmp_path / "checkout"
    assert call["stages"] == load_stages(stages_file) and len(call["stages"]) == 2
    assert Path(call["run_dir"]) == home / "runs" / run_id
    assert call["fetch"] is False and call["options"] == {"torch": False, "stockfish": "sf", "device": "cpu"}
    assert isinstance(call["cancel"], threading.Event) and not call["cancel"].is_set()
    stages_file.write_text(json.dumps({"stages": [{"label": "only", "ref": "main"}]}), encoding="utf-8")
    manager.start()
    finish(manager)
    assert runner.calls[1]["fetch"] is True, "a run fetches unless told not to"
    assert [stage.label for stage in runner.calls[1]["stages"]] == ["only"]
    for own in ("fetch", "cancel", "on_progress", "on_stage"):
        with pytest.raises(ValueError, match=own):
            RunManager(tmp_path, home, stages_file, runner=runner, **{own: None})


# R7. Catches: progress kept from the page until the run ends, stages that are not there until the end (the cards
# could not fill in as it goes), and a new run that starts with the last one's lines.
def test_status_reports_progress(make_manager):
    runner = FakeRunner(hold=True, progress=("stage 1", "stage 2: \u2713"))
    manager = make_manager(runner)
    assert manager.status() == IDLE
    run_id = manager.start(fetch=False)
    assert runner.entered.wait(30)
    status = manager.status()
    assert list(status) == list(IDLE)
    assert (status["running"], status["id"], status["error"]) == (True, run_id, None)
    assert status["progress"] == ["stage 1", "stage 2: \u2713"]
    assert status["stages"] == [STAGE]
    assert datetime.fromisoformat(status["started"]).tzinfo is not None
    assert json.loads(json.dumps(status)) == status
    runner.release.set()
    finish(manager)
    after = manager.status()
    assert (after["running"], after["id"], after["stages"]) == (False, run_id, [STAGE])
    assert after["progress"][:2] == ["stage 1", "stage 2: \u2713"]
    runner.progress = ("again",)
    manager.start(fetch=False)
    assert runner.entered.wait(30)
    finish(manager)
    assert manager.status()["progress"] == ["again"]


# ---- runs that fail or are stopped ----

# Catches: a run that raises leaving nothing on the page (no summary saved), a manager that stays busy for ever after
# it, the trace lost, or the stages already finished thrown away.
@pytest.mark.parametrize("error, message", [(RuntimeError("git broke"), "RuntimeError: git broke"),
                                            (KeyboardInterrupt(), "KeyboardInterrupt")])
def test_a_run_that_raises_is_saved_with_its_error(make_manager, capsys, error, message):
    manager = make_manager(FakeRunner(error=error))
    run_id = run_once(manager)
    latest = manager.latest()
    assert list(latest) == SUMMARY_KEYS
    assert (latest["id"], latest["error"], latest["stages"], latest["final"]) == (run_id, message, [STAGE], None)
    assert datetime.fromisoformat(latest["started"]) <= datetime.fromisoformat(latest["finished"])
    assert manager.status()["running"] is False and manager.status()["error"] == message
    assert type(error).__name__ in capsys.readouterr().err
    assert manager.start(fetch=False) > run_id, "the manager is idle again"


# Catches: a stages file that cannot be read stopping the manager or vanishing without a trace on the page.
def test_a_stages_file_that_cannot_be_read_is_a_failed_run(make_manager, stages_file, capsys):
    stages_file.write_text("{not json", encoding="utf-8")
    runner = FakeRunner()
    manager = make_manager(runner)
    run_once(manager)
    assert runner.calls == []
    assert "not UTF-8 JSON" in manager.latest()["error"] and "not UTF-8 JSON" in manager.status()["error"]
    capsys.readouterr()


# Catches: a summary that cannot be saved crashing the run's thread (the manager would stay busy) or leaving a half
# written or temporary file behind.
def test_a_summary_that_cannot_be_saved_is_reported(make_manager, home, capsys):
    class Unsaveable(FakeRunner):
        def __call__(self, *args, **kwargs):
            return {**super().__call__(*args, **kwargs), "final": {1, 2}}  # a set: not JSON

    manager = make_manager(Unsaveable())
    run_id = run_once(manager)
    assert "could not save" in manager.status()["error"]
    assert sorted(path.name for path in (home / "runs" / run_id).iterdir()) == ["logs"]
    assert manager.latest() is None
    assert "could not save" in capsys.readouterr().err


# R29. Catches: a close that leaves the run going (its checks would run on as orphans), one that does not wait for it to
# be saved, a run started after close, and a second close that fails.
def test_close_stops_the_run_and_waits_for_it(make_manager):
    runner = FakeRunner(hold=True)
    manager = make_manager(runner)
    run_id = manager.start(fetch=False)
    assert runner.entered.wait(30)
    began = time.monotonic()
    assert manager.close(timeout=30) is True
    assert time.monotonic() - began < 10
    assert runner.calls[0]["cancel"].is_set()
    assert manager.status()["running"] is False
    assert (manager.latest()["id"], manager.latest()["stopped"]) == (run_id, True)
    with pytest.raises(RunBusy, match="closing"):
        manager.start()
    assert manager.close() is True


# R29. Catches: a run's thread that dies with the app (a daemon thread): a run that is inside a git command when the app
# leaves (git is never stopped part way, and close() waits only a little) would then leave its worktree behind and its
# summary unsaved. The runner here is such a command: it does not look at the stop event.
def test_a_run_inside_a_git_command_finishes_before_the_app_exits(home, stages_file):
    code = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from pairb.lab.runs import RunManager\n"
        "def runner(checkout, stages, run_dir, *, fetch, cancel, on_progress, on_stage):\n"
        "    time.sleep(1.5)\n"
        "    return {'started': 'then', 'stopped': cancel.is_set()}\n"
        "manager = RunManager(Path(sys.argv[1]), Path(sys.argv[1]), Path(sys.argv[2]), runner=runner)\n"
        "print(manager.start(), manager.close(timeout=0.1))\n")
    done = subprocess.run([sys.executable, "-c", code, str(home), str(stages_file)], cwd=PAIR_B, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=300)
    assert done.returncode == 0, done.stderr
    run_id, finished = done.stdout.split()
    assert finished == "False", "close() gave up waiting while the run was in its command"
    summary = json.loads((home / "runs" / run_id / "summary.json").read_text(encoding="utf-8"))
    assert summary == {"id": run_id, "started": "then", "stopped": True, "error": None}


# R29. Catches: the app's close (the start command's exit path) leaving a run going, and a run started through the page
# after it.
def test_closing_the_app_stops_the_run(make_manager, serve):
    runner = FakeRunner(hold=True)
    manager = make_manager(runner)
    lab = serve(manager)
    assert lab.send("POST", "/api/tests/run", {"fetch": False}).status == 202
    assert runner.entered.wait(30)
    lab.app.close()
    assert runner.calls[0]["cancel"].is_set() and manager.status()["running"] is False
    assert "closing" in lab.send("POST", "/api/tests/run", {}).error(409)


class SlowBot:
    """An Agent whose turn lasts until `go_on` is set (a minute at most), having set `thinking`; then it plays its
    first legal move."""

    name = "slow-bot"
    thinking, go_on = threading.Event(), threading.Event()

    def __init__(self, scorer=None):
        pass

    def reset(self, player, seed):
        pass

    def act(self, turn):
        self.thinking.set()
        self.go_on.wait(60)
        moves = turn.observation.legal_moves
        return Decision(moves[0], {move: float(move == moves[0]) for move in moves})


# Catches: a run that starts while the app closes. A Ctrl+C that comes during the bot's turn finds the live game busy:
# closing it waits for the turn to end, and a run asked for in that gap started, with its fetch and its worktree, on the
# way out. The run manager is closed first, so such a request is refused.
def test_no_run_starts_while_the_app_closes(make_manager, serve, monkeypatch):
    runner = FakeRunner()
    lab = serve(make_manager(runner))
    monkeypatch.setitem(BOTS, "slow", BotSpec("slow", SlowBot, default_tracker))
    monkeypatch.setattr(SlowBot, "thinking", threading.Event())
    monkeypatch.setattr(SlowBot, "go_on", threading.Event())
    closing_game, real_close = threading.Event(), Session.close

    def close(self):
        closing_game.set()
        real_close(self)  # waits for the bot's turn, which holds the game

    monkeypatch.setattr(Session, "close", close)
    created = lab.send("POST", "/api/games", {"scorer": "material", "particles": 16, "guesses": 2, "bot": "slow"})
    assert created.status == 200, created.body
    game = created.data()["id"]
    threads = [threading.Thread(target=lab.send, args=("POST", f"/api/games/{game}/move", {"move": "e2e4"})),
               threading.Thread(target=lab.app.close)]
    threads[0].start()
    try:
        assert SlowBot.thinking.wait(60)
        threads[1].start()
        assert closing_game.wait(60)
        assert "closing" in lab.send("POST", "/api/tests/run", {"fetch": False}).error(409)
        assert runner.calls == []
    finally:
        SlowBot.go_on.set()
        for thread in threads:
            if thread.ident is not None:  # started
                thread.join(60)


# ---- logs ----

# Catches: a log name or run id that reaches a file outside the run's logs folder (here the run's own summary, which
# exists, so a 404 shows the guard and not an absent file), a link out of the folder followed, an id or name looked at
# on disk before its shape is checked, and a real log not served as the UTF-8 text it is.
def test_log_paths_stay_inside(make_manager, serve, home, tmp_path, monkeypatch):
    manager = make_manager(FakeRunner())
    run_id = run_once(manager)
    logs = home / "runs" / run_id / "logs"
    assert manager.log_path(run_id, LOG_NAME) == logs / LOG_NAME
    lab = serve(manager)
    answer = lab.send("GET", f"/api/tests/runs/{run_id}/logs/{LOG_NAME}")
    assert (answer.status, answer.content_type, answer.text) == (200, "text/plain; charset=utf-8", LOG)

    names = ["../summary.json", "/etc/hosts", "a/../../x", "..", ".", "", "..\\summary.json", "C:summary.json",
             "x\x00.txt", ".hidden", "sub/x.txt", "a" * 129, "\u00e9.txt"]
    ids = ["", "..", "../x", "20261019", "20261019-120000-00000a", "20261019-120000-0000001", f"{run_id}/..",
           "\u0661" * 8 + "-120000-000000"]  # Arabic-Indic digits: \d would take them

    def touched(*args, **kwargs):
        raise AssertionError("the file system was looked at")

    with monkeypatch.context() as patched:
        for owner, name in ((Path, "resolve"), (os, "stat"), (os, "lstat"), (os, "scandir")):
            patched.setattr(owner, name, touched)
        for name in names:
            with pytest.raises(ValueError):
                manager.log_path(run_id, name)
        for bad in ids:
            with pytest.raises(ValueError):
                manager.log_path(bad, LOG_NAME)
    for name in names:
        lab.send("GET", f"/api/tests/runs/{run_id}/logs/{quote(name, safe='')}").error(404)
    for bad in ids:
        lab.send("GET", f"/api/tests/runs/{quote(bad, safe='')}/logs/{LOG_NAME}").error(404)
    for path in (f"/api/tests/runs/{run_id}/logs/../summary.json", f"/api/tests/runs/{run_id}/logs//etc/hosts",
                 f"/api/tests/runs/{run_id}/summary.json", f"/api/tests/runs/{run_id}/logs/",
                 f"/api/tests/runs/{run_id}/logs/missing.txt", "/api/tests/runs/20990101-000000-000000/logs/x.txt"):
        lab.send("GET", path).error(404)  # an error object and nothing else: no file's text

    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "logs").mkdir(parents=True)
    (elsewhere / "logs" / LOG_NAME).write_text("outside", encoding="utf-8")
    try:
        (logs / "link.txt").symlink_to(tmp_path / "secret.txt")
        (home / "runs" / "20000101-000000-000000").symlink_to(elsewhere, target_is_directory=True)
    except (OSError, NotImplementedError):
        return  # this machine cannot make links
    for bad_id, name in ((run_id, "link.txt"), ("20000101-000000-000000", LOG_NAME)):
        with pytest.raises(ValueError):
            manager.log_path(bad_id, name)
        lab.send("GET", f"/api/tests/runs/{bad_id}/logs/{name}").error(404)


# ---- the routes ----

# Catches: a start that is not a 202 with the run's id, fetch taken from anything but a JSON true or false (or
# defaulting to off), unknown options ignored, a page on another site starting a run, status and latest not being
# what the manager says, and latest answering 200 before any run was saved.
def test_the_test_routes(make_manager, serve):
    runner = FakeRunner(hold=True)
    manager = make_manager(runner)
    lab = serve(manager)
    assert (lab.send("GET", "/api/tests/status").data()) == IDLE
    assert "no test run" in lab.send("GET", "/api/tests/latest").error(404)
    for body in ({"fetch": "yes"}, {"fetch": 1}, {"fetch": None}, {"fetch": True, "ref": "main"}, [True], b"{"):
        lab.send("POST", "/api/tests/run", body).error(400)
    lab.send("POST", "/api/tests/run", {}, {"Origin": "http://evil.example"}).error(403)
    assert runner.calls == []

    answer = lab.send("POST", "/api/tests/run", {"fetch": False})
    assert answer.status == 202 and answer.content_type == "application/json; charset=utf-8"
    assert list(answer.data()) == ["id"] and RUN_ID.fullmatch(answer.data()["id"])
    run_id = answer.data()["id"]
    assert runner.entered.wait(30)
    status = lab.send("GET", "/api/tests/status").data()
    assert (status["running"], status["id"], status["progress"], status["stages"]) == (True, run_id, ["stage 1"],
                                                                                        [STAGE])
    runner.release.set()
    finish(manager)
    latest = lab.send("GET", "/api/tests/latest")
    assert latest.status == 200 and latest.data() == manager.latest() and latest.data()["id"] == run_id
    assert runner.calls[0]["fetch"] is False

    assert lab.send("POST", "/api/tests/run", b"").status == 202
    finish(manager)
    assert runner.calls[1]["fetch"] is True
    lab.send("GET", "/api/tests/run").error(404)
    lab.send("POST", "/api/tests/status").error(404)
    lab.send("POST", "/api/tests/latest").error(404)


# Catches: a run that cannot have its folder (home/runs is a file here) crashing the route with no message, calling the
# runner anyway, or leaving the manager busy.
def test_a_run_that_cannot_have_its_folder_is_refused_with_a_message(make_manager, serve, home):
    home.mkdir(parents=True)
    (home / "runs").write_text("a file where the folder should be", encoding="utf-8")
    runner = FakeRunner()
    manager = make_manager(runner)
    lab = serve(manager)
    assert "could not start the test run" in lab.send("POST", "/api/tests/run", {}).error(500)
    assert manager.status() == IDLE and runner.calls == [] and manager.latest() is None
