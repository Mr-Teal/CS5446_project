"""The stages Fog Lab's Tests tab merges one by one, and the commands each stage runs: the pure parts.

Everything here is a plain function of its arguments. Nothing starts a process, calls git or writes a file, so the
commands a stage would run can be checked for any layout, Windows-style paths and paths with spaces included, on any
machine. The runner (git worktree, merges, subprocesses) is the other half of this module.

The stages file (pair_b/fog_lab_stages.json) lists the stages in merge order:

    {"stages": [{"label": "+ PR #4", "ref": "origin/pair-b/evaluators", "title": "Scorers, Network 1"}, ...]}

Each stage is a git ref merged on top of the one before. A ref may be a remote branch, a local branch, a tag or a
commit. The page never takes a ref from the browser: editing this file is how the stages change. A ref that is empty,
has whitespace in it or starts with "-" (git would read it as an option) is refused when the file is loaded.

Two Python environments run the checks, both belonging to the checkout the app runs from, not to the stage (a
stage's worktree has none, because .venv is not in git): Pair B's `pair_b/.venv`, and Pair A's `pair_a_prep/.venv`
as Pair A's README sets it up. Each stage's own code is put first on PYTHONPATH (stage_env), and an import check per
environment prints where the packages really came from (imports_ok decides), so a stage cannot quietly be tested
against the checkout's code. Checks that need Pair A's environment are "unavailable" where there is none, with the
commands that make one. They are never failures.

stage_checks lists the checks a stage gets, in the order they run. Every stage gets:

    imports_b        Pair B's environment imports pairb and fow_shared from the stage
    pair_b           pytest in the stage's pair_b
    imports_a        Pair A's environment imports fow_shared and pair_a_prep from the stage
    shared           pytest tests pair_a_prep/tests from the stage's root, with Pair A's environment

and, where the stage has a pair_b_prep/ folder (Bryan's, PR #3):

    bryan_tests      Bryan's own tests
    harness:<id>     Bryan's harness on each scorer (five, those of scorers.py)
    history          Bryan's history check

and, where it has pair_a_prep/rules_adapter.py (Teal's):

    observe_vs_teal  our observe against Teal's adapter

A stage may lack what a check needs, and then the check is "unavailable", not failed, because it would only fail on the
missing file. origin/main has no pair_b folder (Pair B's code arrives with PR #4), so the checks that run in pair_b
(imports_b, pair_b, observe_vs_teal) cannot start there. And Bryan's harness reaches the belief network through our own
adapter, pairb/harness_adapter.py, which this build adds: a stage without that file (every stage before one that holds
this build's code) cannot run it.

A harness check carries the JSON config its adapter reads as data (Check.config), and its argument list names the file
where the runner writes it before running the check, and the folder the harness writes its report.json into. Both are
under the `out_dir` the runner gives (harness_paths): out_dir/harness/<scorer id>.json and out_dir/harness/<scorer id>/.
Describing the checks creates neither, and no other check has a config.
"""
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .paths import venv_python
from .scorers import CHECKPOINTS, LABELS, SCORER_IDS

_NO_TORCH = "needs torch, which this machine does not have"  # the words the scorer list uses for the same thing
_BRYANS_ADAPTER = "pair_b_prep.real_adapter:build"  # material, Stockfish and Network 1 (PR #3)
_BELIEF_ADAPTER = "pairb.harness_adapter:build"  # the belief network (this build adds it, not PR #3)
_BELIEF_ADAPTER_FILE = Path("pair_b", "src", *_BELIEF_ADAPTER.split(":")[0].split(".")).with_suffix(".py")
_NO_BELIEF_ADAPTER = "the belief network's adapter (pairb/harness_adapter.py) is not in this stage"
_NO_PAIR_B = "Pair B's code is not in this stage yet (there is no pair_b folder)"
_STOCKFISH_DEPTHS = {"stockfish-d1": 1, "stockfish-d11": 11}
_PYTEST = ("-m", "pytest", "-q", "-p", "no:cacheprovider")  # no cache folder in a stage that is thrown away


@dataclass(frozen=True)
class Stage:
    """One entry of the stages file: `label` and `title` are what the card shows (for example "+ PR #4" and "Scorers,
    Network 1"), `ref` is the git ref to merge."""

    label: str
    ref: str
    title: str = ""


@dataclass(frozen=True)
class Envs:
    """The interpreters that run the checks. `pair_b_python` is Pair B's, found where the app's own environment is
    and not checked for existing: a missing one makes the checks that use it fail, loudly. `pair_a_python` is Pair
    A's, or None when `pair_a_prep/.venv` has not been set up."""

    pair_b_python: Path
    pair_a_python: Path | None


@dataclass(frozen=True)
class Check:
    """One command of a stage. `key` names it (imports_b, pair_b, imports_a, shared, bryan_tests, harness:<scorer id>,
    history, observe_vs_teal) and `label` is what the page shows.

    `argv` is the argument list, which is never joined into a string: every path, spaces included, is one argument.
    `cwd` is the folder to run it in. `unavailable` is None when the check can run here, and otherwise says why not, in
    words the page shows as they are. A check that is unavailable for lack of Pair A's environment has an empty `argv`,
    because there is no interpreter to put in it. `config` is for the harness checks only: the data of the JSON file
    named after `--config` in `argv`, which the runner writes before running the check. It is set whether or not the
    check can run here."""

    key: str
    label: str
    argv: tuple[str, ...]
    cwd: Path
    unavailable: str | None
    config: dict | None = None


def load_stages(path: Path) -> list[Stage]:
    """The stages in the file at `path`, in file order. Only "label" and "ref" are needed; "title" defaults to "" and
    other keys are ignored. The file is read as UTF-8, with or without a byte-order mark.

    ValueError, naming the file and the stage, when it is not UTF-8 JSON of the form {"stages": [...]}, has no
    stages, or has a stage that is not an object, lacks a label or a ref, or has a ref that is not text, has
    whitespace or a control character in it, or starts with "-". A file that is not there raises FileNotFoundError.
    """
    path = Path(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(f"{path}: not UTF-8 JSON ({error})") from error
    entries = document.get("stages") if isinstance(document, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError(f'{path}: expected {{"stages": [one or more stages]}}')
    return [_stage(path, number, entry) for number, entry in enumerate(entries, start=1)]


def _stage(path: Path, number: int, entry) -> Stage:
    where = f"{path}: stage {number}"
    if not isinstance(entry, dict):
        raise ValueError(f"{where} is not an object")
    for key in ("label", "ref"):
        value = entry.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'{where} needs a "{key}", some text')
    ref = entry["ref"]
    if ref.startswith("-"):
        raise ValueError(f'{where}: ref {ref!r} starts with "-", which git would read as an option')
    if any(c.isspace() or not c.isprintable() for c in ref):
        raise ValueError(f"{where}: ref {ref!r} has whitespace or a control character in it")
    title = entry.get("title", "")
    if not isinstance(title, str):
        raise ValueError(f'{where}: "title" must be text')
    return Stage(entry["label"], ref, title)


def find_envs(checkout: Path, windows: bool | None = None) -> Envs:
    """The two environments of `checkout`, the folder the app runs from: Pair B's `pair_b/.venv` interpreter, and Pair
    A's `pair_a_prep/.venv` interpreter if that file exists (None if not, or if it is a broken link). `windows` None
    means the machine this runs on, as in venv_python."""
    pair_a = venv_python(Path(checkout) / "pair_a_prep", windows)
    return Envs(venv_python(Path(checkout) / "pair_b", windows), pair_a if pair_a.is_file() else None)


def stage_env(stage_dir: Path, base: Mapping[str, str]) -> dict[str, str]:
    """The environment variables for a stage's commands: `base` without its PYTHONPATH (which might name the app's own
    checkout), then PYTHONPATH = the stage's pair_b/src and the stage's root, in that order, so the stage's
    `pairb` and `fow_shared` are found first; and no bytecode files in the stage, and UTF-8 for python's text I/O
    whatever the machine's locale is. `base` itself is not changed."""
    stage = Path(stage_dir)
    env = {name: value for name, value in base.items() if name != "PYTHONPATH"}
    env["PYTHONPATH"] = os.pathsep.join((str(stage / "pair_b" / "src"), str(stage)))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    return env


def pair_a_setup_commands(windows: bool | None = None) -> str:
    """Pair A's setup commands (pair_a_prep/README.md, "Setup and execution"), in this platform's spelling: the
    interpreter is `.venv/bin/python` here and `.venv/Scripts/python.exe` on Windows, and Windows has `python` where
    a Mac has `python3`. `windows` None means the machine this runs on."""
    if windows is None:
        windows = os.name == "nt"
    python = venv_python(Path("pair_a_prep"), windows).as_posix()
    make = "python" if windows else "python3"
    return (f"from the repository root, run {make} -m venv pair_a_prep/.venv, "
            f"then {python} -m pip install -r pair_a_prep/requirements.txt")


def harness_paths(out_dir: Path, scorer_id: str) -> tuple[Path, Path]:
    """Where a harness check keeps its files: (the JSON file the runner writes the config to, the folder the harness
    writes its report.json, samples.jsonl and summary.csv into). They are kept apart because the harness replaces
    what is in its folder."""
    folder = Path(out_dir) / "harness"
    return folder / f"{scorer_id}.json", folder / scorer_id


def harness_config(scorer_id: str, stage_dir: Path, sha: str, stockfish: str, device: str | None) -> tuple[str, dict]:
    """The `--adapter` and the config data of Bryan's harness for one scorer in a stage: the adapter as
    "module:factory", and the dict that becomes its JSON config.

    Piece values, Stockfish and Network 1 use Bryan's `pair_b_prep.real_adapter:build`, with its keys: kind
    ("material", "stockfish" or "network"), depth (Stockfish), checkpoint (the network), device (the network),
    stockfish_path (Stockfish and the network) and source_commit. The belief network uses
    `pairb.harness_adapter:build` with checkpoint, device, stockfish_path and source_commit. Checkpoints are the
    stage's own, in its pair_b/checkpoints. `device` None is kept as a null in the JSON, which both adapters read as
    "pick the best": a missing key would not be, since Bryan's adapter then uses the CPU. `sha` is the revision the
    run is about, which his harness records and never guesses. ValueError for a scorer id that is not one of
    scorers.SCORER_IDS."""
    if scorer_id not in SCORER_IDS:
        raise ValueError(f"unknown scorer {scorer_id!r}; the scorers are {', '.join(SCORER_IDS)}")
    if scorer_id == "material":
        return _BRYANS_ADAPTER, {"kind": "material", "source_commit": sha}
    if scorer_id in _STOCKFISH_DEPTHS:
        return _BRYANS_ADAPTER, {"kind": "stockfish", "depth": _STOCKFISH_DEPTHS[scorer_id],
                                 "stockfish_path": stockfish, "source_commit": sha}
    checkpoint = str(Path(stage_dir, "pair_b", "checkpoints", CHECKPOINTS[scorer_id]))
    config = {"checkpoint": checkpoint, "device": device, "stockfish_path": stockfish, "source_commit": sha}
    if scorer_id == "network1":
        return _BRYANS_ADAPTER, {"kind": "network", **config}
    return _BELIEF_ADAPTER, config


def _harness_unavailable(scorer_id: str, stage: Path, torch: bool) -> str | None:
    """Why Bryan's harness cannot be run on this scorer here, or None. The machine's own lack comes first, as in the
    scorer list: no torch for the two networks. Then the stage's: the belief network goes through our own adapter, which
    only a stage holding this build's code has, and in the others the run would fail with "No module named
    pairb.harness_adapter", turning the card red for a reason that has nothing to do with its pull request."""
    if scorer_id in CHECKPOINTS and not torch:
        return _NO_TORCH
    if scorer_id == "belief" and not (stage / _BELIEF_ADAPTER_FILE).is_file():
        return _NO_BELIEF_ADAPTER
    return None


def _imports_code(*modules: str) -> str:
    """A `python -c` program that imports `modules` and prints the file each came from, one path per line."""
    return "; ".join([f"import {', '.join(modules)}", *(f"print({module}.__file__)" for module in modules)])


def stage_checks(stage_dir: Path, envs: Envs, out_dir: Path, sha: str, *, torch: bool, stockfish: str,
                 device: str | None) -> list[Check]:
    """The checks for the stage built in `stage_dir`, in the order they run (see the module docstring for what each
    is). `sha` is the stage's head commit, `out_dir` is where the runner keeps this stage's harness files, `torch` says
    whether this machine has torch, `stockfish` is the engine (a command on the PATH, or a path) and `device` is for
    the networks (None lets them pick). The commands are those of the 18 Oct staged run (fog-lab-reference/
    ci_stages2.sh), as argument lists.

    What the stage holds decides which checks it gets: Bryan's checks where `pair_b_prep/` is a folder, and the
    observe test where `pair_a_prep/rules_adapter.py` is a file. What is missing makes a check unavailable and never
    failed: Pair A's environment (imports_a and shared), torch (the two networks' harness checks), and what a stage
    may not have yet: Pair B itself (origin/main has no pair_b folder, so imports_b, pair_b and observe_vs_teal, which
    run in it, cannot start), and, in a stage that does not hold this build's code, our belief-network adapter (that
    scorer's harness check). This looks at the stage's folders and writes nothing."""
    stage, pair_b_dir = Path(stage_dir), Path(stage_dir) / "pair_b"
    no_pair_b = None if pair_b_dir.is_dir() else _NO_PAIR_B  # origin/main has no pair_b folder: it comes with PR #4
    python_b = str(envs.pair_b_python)
    python_a = None if envs.pair_a_python is None else str(envs.pair_a_python)
    no_pair_a = None if python_a is not None else f"Pair A's environment not set up here: {pair_a_setup_commands()}"

    def with_pair_a(key: str, label: str, args: tuple[str, ...], cwd: Path) -> Check:
        return Check(key, label, () if python_a is None else (python_a, *args), cwd, no_pair_a)

    checks = [
        Check("imports_b", "Imports, Pair B", (python_b, "-c", _imports_code("pairb", "fow_shared")), pair_b_dir,
              no_pair_b),
        Check("pair_b", "Pair B", (python_b, *_PYTEST), pair_b_dir, no_pair_b),
        with_pair_a("imports_a", "Imports, shared + Pair A", ("-c", _imports_code("fow_shared", "pair_a_prep")), stage),
        with_pair_a("shared", "Shared + Pair A", (*_PYTEST, "tests", "pair_a_prep/tests"), stage),
    ]
    if (stage / "pair_b_prep").is_dir():
        checks.append(Check("bryan_tests", "Bryan's tests", (python_b, "-m", "unittest", "pair_b_prep.test_harness"),
                            stage, None))
        for scorer_id in SCORER_IDS:
            adapter, config = harness_config(scorer_id, stage, sha, stockfish, device)
            config_file, report_dir = harness_paths(out_dir, scorer_id)
            argv = (python_b, "-m", "pair_b_prep.harness", "--adapter", adapter, "--config", str(config_file),
                    "--out", str(report_dir))
            checks.append(Check(f"harness:{scorer_id}", f"Harness, {LABELS[scorer_id]}", argv, stage,
                                _harness_unavailable(scorer_id, stage, torch), config))
        checks.append(Check("history", "History check", (python_b, "-m", "pair_b_prep.check_repetition",
                                                         "--stockfish-path", stockfish, "--source-commit", sha),
                            stage, None))
    if (stage / "pair_a_prep" / "rules_adapter.py").is_file():
        checks.append(Check("observe_vs_teal", "Our observe = Teal's",
                            (python_b, *_PYTEST, "tests/test_observe.py", "-k", "pair_as_observe"), pair_b_dir,
                            no_pair_b))
    return checks


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# pytest's last line: "160 passed, 1 skipped in 49.87s", "1 failed, 159 passed in 3.20s", "2 errors in 0.50s",
# "no tests ran in 0.01s"; the time may be followed by "(0:01:01)", and the line may sit between "=" signs. pytest 9
# counts passing subtests apart from tests, as an item of its own with two words: "2 passed, 4 subtests passed in 0.01s"
# (and "1 subtests passed" for one). An item is a number and a word, with "subtests " before the word for those.
_ITEM = r"\d+ (?:subtests )?[a-z]+"
_SUMMARY = re.compile(rf"(?:no tests ran|({_ITEM}(?:, {_ITEM})*)) in \d+(?:\.\d+)?s(?: \(\d+:\d\d:\d\d\))?")
_COUNT = re.compile(r"(\d+) (subtests )?([a-z]+)")
_COUNTED = {"passed": "passed", "failed": "failed", "error": "errors", "errors": "errors", "skipped": "skipped"}


def parse_pytest_summary(text: str) -> dict[str, int]:
    """The counts in the last summary line of pytest's output: {"passed", "failed", "errors", "skipped"}, each 0 if
    the line does not mention it. Other words in the line (warnings, deselected, xfailed, ...) are not counted, and
    neither are pytest 9's subtests items ("4 subtests passed"): they are not tests, and pytest counts them apart from
    the tests they ran in. When there is no summary line (pytest never got that far, or the command was not pytest)
    every count is 0. Never raises."""
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for line in reversed(_ANSI.sub("", text).splitlines()):
        match = _SUMMARY.fullmatch(line.strip(" =\t"))
        if match:
            for number, subtests, word in _COUNT.findall(match.group(1) or ""):
                if not subtests and word in _COUNTED:
                    counts[_COUNTED[word]] = int(number)
            break
    return counts


def imports_ok(stdout: str, stage_dir: Path) -> bool:
    """Whether an import check's output (the module paths it printed, one per line, as `_imports_code` prints them)
    shows the stage's own code: True only when there is at least one path, every one is absolute, and every one lies
    under `stage_dir` (compared as whole folders, after resolving "..", links and the like on both sides). Anything
    else on a line, such as "None" for a package with no file, makes it False. Odd output never raises."""
    paths = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not paths:
        return False
    try:
        root = Path(stage_dir).resolve()
        return all(Path(line).is_absolute() and Path(line).resolve().is_relative_to(root) for line in paths)
    except (OSError, RuntimeError, ValueError):  # a line that cannot be a path (a NUL byte), a link loop
        return False
