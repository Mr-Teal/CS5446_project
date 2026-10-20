"""The accuracy section of Fog Lab's Tests tab: its tables and paired differences, read from the evaluation files
saved in pair_b/checkpoints.

Nothing is measured here. The numbers were measured earlier, by scripts that saved them as JSON, and read_accuracy only
reads them back: "Run again" never recomputes them, and a machine with no torch and no Stockfish can still draw them.
Only the standard library is used, so this works on an Intel Mac.

Each of three files gives one table and one paired difference:

    net1-v2/eval-d2-check-train.json        "Network 1, on fresh games"               regret_difference
    belief-v1-d1/eval-d6-check-train.json   "Belief network, on fresh games"          root_mae_difference
    belief-v1-d1/eval-children-d16.json     "Per-move values, as a search uses them"  belief_children - net1_children

read_accuracy returns plain JSON data (dicts, lists, strings, numbers, booleans, None), because the stage runner stores
it in the run summary:

    {"tables": [table, ...], "differences": [difference, ...], "missing": [path, ...], "why_missing": {path: reason}}

    table       {"title", "source", "sizes", "columns", "rows"}, and "data", "split", "created" and "target_depth"
                for whichever of those the file holds. "source" is the file's path inside the checkpoints folder,
                with "/". "sizes" is {name: count} of what the file was measured on (games, positions, ...), for the
                counts the file has. A column is {"key", "label", "unit"}, its unit "%" or None. A row is {"key",
                "label", "highlight", "values"}: one number per column, and "highlight" marks the row the table is
                about, which the mockup draws in bold.
    difference  {"key", "label", "source", "mean", "ci95": [low, high], "verdict"}. It is the first-named scorer's
                error minus the second's, so below zero means the first errs less (see verdict()).

A file that is not there, cannot be read, or lacks a number its table or difference needs gives neither. Its path goes
in "missing", in the order of the tables above, and "why_missing" says why in a few words ("not found", "no
'regret_difference.mean' in the file", ...), so the page need not call a file that is there but damaged "not found".
Nothing here raises for a bad file. Dates and counts are only "where present": a file without them still gives its
table.

The headings, labels and marked rows are those of the Tests-tab mockup Colin approved.
"""
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


def verdict(ci95: Sequence[float]) -> str:
    """What a paired difference's 95% interval says: "better" when all of it is below zero, "worse" when all of it is
    above, and "tie" when it reaches zero, because then the saved games do not show a difference. The difference is
    the first scorer's error minus the second's (pairb.belief_eval.paired_difference), so below zero is the first
    scorer erring less. ValueError unless `ci95` holds exactly two numbers, [low, high]."""
    low, high = ci95
    if high < 0:
        return "better"
    if low > 0:
        return "worse"
    return "tie"


@dataclass(frozen=True)
class _Column:
    key: str  # the column's key in the file, under its row's; "*" in it stands for the row's key
    label: str
    percent: bool = False  # the file holds a fraction (0.424) and the page shows a percentage (42.4)


@dataclass(frozen=True)
class _Row:
    key: str
    label: str
    highlight: bool = False  # the row the table is about


@dataclass(frozen=True)
class _Source:
    """One saved file: the table drawn from it and the paired difference it holds."""

    path: str  # inside the checkpoints folder, always with "/"
    title: str
    cell: str  # where the number of a row and a column is in the file: {row} and {column} are filled with their keys
    columns: tuple[_Column, ...]
    rows: tuple[_Row, ...]
    sizes: tuple[tuple[str, str], ...]  # (what is counted, where its count is in the file)
    difference_key: str
    difference_label: str


# The titles, labels, keys and marked rows are those of the design (section 5.4) and of the approved mockup.
_SOURCES = (
    _Source(
        path="net1-v2/eval-d2-check-train.json",
        title="Network 1, on fresh games",
        cell="{row}.{column}",
        columns=(_Column("mae", "Value error"),
                 _Column("choice.top1", "Picks careful SF's move", percent=True),
                 _Column("choice.regret", "Value lost by its pick")),
        rows=(_Row("material", "Piece values"),
              _Row("baseline", "Quick Stockfish"),
              _Row("network", "Network 1", highlight=True)),
        sizes=(("games", "regret_difference.games"), ("positions", "n"), ("decisions", "network.choice.parents")),
        difference_key="regret_difference",
        difference_label="Network 1 vs quick Stockfish: value lost by its move pick",
    ),
    _Source(
        path="belief-v1-d1/eval-d6-check-train.json",
        title="Belief network, on fresh games",
        cell="{row}.{column}",
        columns=(_Column("board_mae", "Board error"),
                 _Column("root_mae", "Position error")),
        rows=(_Row("baseline", "Quick Stockfish alone"),
              _Row("network", "Belief network", highlight=True)),
        sizes=(("games", "root_mae_difference.games"), ("beliefs", "network.beliefs"), ("boards", "network.boards")),
        difference_key="root_mae_difference",
        difference_label="Belief network vs quick Stockfish: position error",
    ),
    _Source(
        path="belief-v1-d1/eval-children-d16.json",
        title="Per-move values, as a search uses them",
        cell="mae.{column}",  # this file names a number belief_children, net1_boards, ...: the row, then the column
        columns=(_Column("*_children", "All moves in one call"),
                 _Column("*_boards", "Each move on its own")),
        rows=(_Row("belief", "Belief network", highlight=True),
              _Row("net1", "Network 1"),
              _Row("sf", "Quick Stockfish")),
        sizes=(("games", "belief_children - net1_children.games"), ("positions", "parents"), ("moves", "children")),
        difference_key="belief_children - net1_children",
        difference_label="Belief network vs Network 1: per-move error",
    ),
)
_PROVENANCE = ("data", "split", "created", "target_depth")  # copied from a file when it has them
_ABSENT = object()


class _Unusable(Exception):
    """A file that cannot give its table. The message is the reason read_accuracy reports."""


def _load(path: Path):
    """The parsed content of the JSON file at `path`, or _Unusable saying why it cannot be had."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise _Unusable("not found") from None
    except json.JSONDecodeError as error:  # before ValueError, which it is a kind of
        raise _Unusable(f"not valid JSON: {error}") from None
    except (OSError, ValueError, RecursionError) as error:
        # A folder in its place, no permission, bytes that are not UTF-8, a number too long to convert, or arrays
        # nested too deep for the parser (which raises RecursionError, a RuntimeError).
        raise _Unusable(f"could not be read: {error}") from None


def _lookup(data, where: str):
    """What is at `where` (keys joined by dots) in the parsed file, or _ABSENT when any step is not there."""
    for key in where.split("."):
        if not isinstance(data, dict) or key not in data:
            return _ABSENT
        data = data[key]
    return data


def _as_float(value) -> float | None:
    """`value` as a float, or None when it is not a finite number: a string, true, null, NaN, or an integer too big for
    a float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _number(data, where: str) -> float:
    """The number at `where`, or _Unusable saying it is not there or not a number."""
    value = _lookup(data, where)
    if value is _ABSENT:
        raise _Unusable(f"no '{where}' in the file")
    number = _as_float(value)
    if number is None:
        raise _Unusable(f"'{where}' is not a number")
    return number


def _cell(source: _Source, row: _Row, column: _Column, data) -> float:
    number = _number(data, source.cell.format(row=row.key, column=column.key.replace("*", row.key)))
    # A fraction shown as a percentage: 0.277108 * 100 is 27.710800000000003 in floating point, and ten decimals take
    # that noise off without touching any digit a file holds (the files give six).
    return round(number * 100, 10) if column.percent else number


def _provenance(source: _Source, data) -> dict:
    """The data set, split, date and depth, and the counts, that the file has, for the note under the table."""
    found = {}
    for key in _PROVENANCE:
        value = _lookup(data, key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            found[key] = value
    sizes = {}
    for name, where in source.sizes:
        count = _lookup(data, where)
        if isinstance(count, int) and not isinstance(count, bool):
            sizes[name] = count
    return {**found, "sizes": sizes}


def _difference(source: _Source, data) -> dict:
    key, where = source.difference_key, f"{source.difference_key}.ci95"
    mean = _number(data, f"{key}.mean")
    bounds = _lookup(data, where)
    if bounds is _ABSENT:
        raise _Unusable(f"no '{where}' in the file")
    pair = [_as_float(bound) for bound in bounds] if isinstance(bounds, list) else []
    if len(pair) != 2 or None in pair:
        raise _Unusable(f"'{where}' is not a pair of numbers")
    return {"key": key, "label": source.difference_label, "source": source.path, "mean": mean, "ci95": pair,
            "verdict": verdict(pair)}


def _read(source: _Source, data) -> tuple[dict, dict]:
    """The table and the paired difference that `data`, the parsed content of source's file, gives. _Unusable when it
    lacks a number either needs."""
    rows = [{"key": row.key, "label": row.label, "highlight": row.highlight,
             "values": [_cell(source, row, column, data) for column in source.columns]} for row in source.rows]
    difference = _difference(source, data)
    table = {"title": source.title, "source": source.path, **_provenance(source, data),
             "columns": [{"key": c.key, "label": c.label, "unit": "%" if c.percent else None} for c in source.columns],
             "rows": rows}
    return table, difference


def read_accuracy(checkpoints: Path) -> dict:
    """The three tables and three paired differences of the accuracy section, read from the evaluation files in the
    `checkpoints` folder (pair_b/checkpoints), in the shape the module's docstring gives. A file that is absent,
    unreadable or lacking a number is listed in "missing" with its reason in "why_missing" and gives no table and no
    difference; the others are still read. Never raises for a bad file."""
    checkpoints = Path(checkpoints)
    result = {"tables": [], "differences": [], "missing": [], "why_missing": {}}
    for source in _SOURCES:
        try:
            table, difference = _read(source, _load(checkpoints / source.path))
        except _Unusable as problem:
            result["missing"].append(source.path)
            result["why_missing"][source.path] = str(problem)
            continue
        result["tables"].append(table)
        result["differences"].append(difference)
    return result
