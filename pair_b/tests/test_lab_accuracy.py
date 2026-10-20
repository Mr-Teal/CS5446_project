"""The accuracy reader (Fog Lab): the tables and paired differences of the Tests tab's accuracy section, read from the
three evaluation files saved in pair_b/checkpoints.

Two kinds of test. Those that read the repository's real files check the numbers the page is to show (Network 1's
row, the three verdicts, the sizes in the approved mockup). The others write small files of their own in which every
number is different, so a row or a column read from the wrong key shows up, and check what the reader does with a file
that is absent, unreadable or missing a key. Every expected value is a literal, never worked out by
pairb.lab.accuracy.
"""
import json
import subprocess
import sys

import pytest

from no_torch import PAIR_B
from pairb.lab.accuracy import read_accuracy, verdict

REAL = PAIR_B / "checkpoints"  # the repository's own saved evaluations
NET1 = "net1-v2/eval-d2-check-train.json"
BELIEF = "belief-v1-d1/eval-d6-check-train.json"
CHILDREN = "belief-v1-d1/eval-children-d16.json"
FILES = [NET1, BELIEF, CHILDREN]
TITLES = ["Network 1, on fresh games", "Belief network, on fresh games", "Per-move values, as a search uses them"]
KEYS = ["regret_difference", "root_mae_difference", "belief_children - net1_children"]
LABELS = ["Network 1 vs quick Stockfish: value lost by its move pick",
          "Belief network vs quick Stockfish: position error",
          "Belief network vs Network 1: per-move error"]


# ---- files of our own: every number different ----

def net1_file() -> dict:
    # 0.277108 * 100 is 27.710800000000003 in floating point: the percentage must come out as 27.7108
    return {"run": "net1-x", "data": "d-net1", "split": "train", "n": 1000, "created": "2026-01-02T03:04:05+08:00",
            "material": {"mae": 0.31, "choice": {"top1": 0.277108, "regret": 0.11, "parents": 41}},
            "baseline": {"mae": 0.32, "choice": {"top1": 0.22, "regret": 0.12, "parents": 42}},
            "network": {"mae": 0.33, "choice": {"top1": 0.23, "regret": 0.13, "parents": 40}},
            "regret_difference": {"mean": -0.015, "ci95": [-0.025, -0.005], "parents": 40, "games": 12,
                                  "resampled": "games"}}


def belief_file() -> dict:
    return {"run": "belief-x", "data": "d-belief", "split": "train", "created": "2026-02-03T04:05:06+08:00",
            "network": {"board_mae": 0.43, "board_mse": 0.9, "root_mae": 0.44, "beliefs": 30, "boards": 240},
            "baseline": {"board_mae": 0.41, "board_mse": 0.9, "root_mae": 0.42, "beliefs": 31, "boards": 241},
            "root_mae_difference": {"mean": 0.0, "ci95": [-0.01, 0.01], "beliefs": 30, "games": 12,
                                    "resampled": "games"}}


def children_file() -> dict:
    other = {"mean": 0.0, "ci95": [0.0, 0.0], "beliefs": 200, "games": 9, "resampled": "games"}
    return {"data": "d-children", "split": "train", "seed": 7, "parents": 20, "children": 200, "target_depth": 16,
            "created": "2026-03-04T05:06:07+08:00",
            "mae": {"belief_children": 0.51, "belief_boards": 0.52, "net1_children": 0.53, "net1_boards": 0.54,
                    "sf_children": 0.55, "sf_boards": 0.56},
            "belief_children - net1_children": {"mean": 0.02, "ci95": [0.01, 0.03], "beliefs": 200, "games": 9,
                                                "resampled": "games"},
            "belief_children - belief_boards": other, "net1_boards - net1_children": other}


def write(folder, relative: str, content) -> None:
    path = folder / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content), encoding="utf-8")


def fake_folder(folder):
    """A checkpoints folder holding all three files, written by this test file. Returns it."""
    write(folder, NET1, net1_file())
    write(folder, BELIEF, belief_file())
    write(folder, CHILDREN, children_file())
    return folder


# ---- the verdict ----

@pytest.mark.parametrize("ci95, expected", [
    ([-0.009357117053786671, -0.006999568198660082], "better"),  # root_mae_difference in the real file
    ([-0.001664771359269205, 0.0010548869247829823], "tie"),  # regret_difference in the real file
    ([0.002, 0.01], "worse"),
    ([-0.5, -1e-9], "better"),
    ([1e-9, 0.5], "worse"),
    ([-0.1, 0.0], "tie"),  # an interval that touches zero has not cleared it
    ([0.0, 0.1], "tie"),
    ([0.0, 0.0], "tie"),  # belief_children - belief_boards in the per-move file: the same numbers twice
    ((-0.2, -0.1), "better"),  # a tuple works as well as the list a file gives
])
def test_verdict_is_better_when_the_interval_is_below_zero_and_worse_when_above(ci95, expected):
    assert verdict(ci95) == expected


@pytest.mark.parametrize("ci95", [[], [0.1], [0.1, 0.2, 0.3]])
def test_verdict_wants_exactly_two_numbers(ci95):
    with pytest.raises(ValueError):
        verdict(ci95)


# ---- the real files ----

def test_the_real_files_all_give_a_table_in_order():
    got = read_accuracy(REAL)
    assert got["missing"] == [] and got["why_missing"] == {}
    assert [t["title"] for t in got["tables"]] == TITLES
    assert [t["source"] for t in got["tables"]] == FILES


def test_network_1_row_on_fresh_games():
    table = read_accuracy(REAL)["tables"][0]
    assert [c["key"] for c in table["columns"]] == ["mae", "choice.top1", "choice.regret"]
    assert [r["label"] for r in table["rows"]] == ["Piece values", "Quick Stockfish", "Network 1"]
    mae, top1, regret = table["rows"][2]["values"]
    assert [round(mae, 4), round(top1, 1), round(regret, 4)] == [0.0757, 42.4, 0.0352]  # 0.075671, 42.4306, 0.035205


def test_the_verdicts_of_the_real_files_are_tie_better_tie():
    differences = read_accuracy(REAL)["differences"]
    assert [d["key"] for d in differences] == KEYS
    assert [d["verdict"] for d in differences] == ["tie", "better", "tie"]


# Catches: a size read from the wrong key. The notes under the cards in the approved mockup show these sizes and the
# depth (959 games, 94,963 positions, 3,818 decisions; 3,818 beliefs; 100 positions, 2,849 moves, depth 16).
def test_the_sizes_of_the_real_files():
    tables = read_accuracy(REAL)["tables"]
    assert (tables[0]["data"], tables[0]["sizes"]) == (
        "d2-check", {"games": 959, "positions": 94963, "decisions": 3818})
    assert (tables[1]["data"], tables[1]["sizes"]) == ("d6-check", {"games": 959, "beliefs": 3818, "boards": 30406})
    assert (tables[2]["data"], tables[2]["sizes"]) == ("d2-check", {"games": 95, "positions": 100, "moves": 2849})
    assert tables[2]["target_depth"] == 16


# ---- every number from its own key ----

# Catches: a row or a column read from the wrong key (children for boards, baseline for network), or a percentage
# left as a fraction.
def test_every_number_is_read_from_its_own_key(tmp_path):
    tables = read_accuracy(fake_folder(tmp_path))["tables"]
    assert [[row["values"] for row in table["rows"]] for table in tables] == [
        [[0.31, 27.7108, 0.11], [0.32, 22.0, 0.12], [0.33, 23.0, 0.13]],
        [[0.41, 0.42], [0.43, 0.44]],
        [[0.51, 0.52], [0.53, 0.54], [0.55, 0.56]],
    ]


# Catches: a heading, a row label or the marked row changed from the approved mockup.
def test_columns_and_rows_are_the_ones_of_the_mockup(tmp_path):
    tables = read_accuracy(fake_folder(tmp_path))["tables"]
    assert [[(c["key"], c["label"], c["unit"]) for c in t["columns"]] for t in tables] == [
        [("mae", "Value error", None), ("choice.top1", "Picks careful SF's move", "%"),
         ("choice.regret", "Value lost by its pick", None)],
        [("board_mae", "Board error", None), ("root_mae", "Position error", None)],
        [("*_children", "All moves in one call", None), ("*_boards", "Each move on its own", None)],
    ]
    assert [[(r["key"], r["label"], r["highlight"]) for r in t["rows"]] for t in tables] == [
        [("material", "Piece values", False), ("baseline", "Quick Stockfish", False), ("network", "Network 1", True)],
        [("baseline", "Quick Stockfish alone", False), ("network", "Belief network", True)],
        [("belief", "Belief network", True), ("net1", "Network 1", False), ("sf", "Quick Stockfish", False)],
    ]


def test_each_table_says_where_its_numbers_come_from(tmp_path):
    tables = read_accuracy(fake_folder(tmp_path))["tables"]
    assert [(t["source"], t["data"], t["split"], t["created"]) for t in tables] == [
        (NET1, "d-net1", "train", "2026-01-02T03:04:05+08:00"),
        (BELIEF, "d-belief", "train", "2026-02-03T04:05:06+08:00"),
        (CHILDREN, "d-children", "train", "2026-03-04T05:06:07+08:00"),
    ]
    assert [t["sizes"] for t in tables] == [{"games": 12, "positions": 1000, "decisions": 40},
                                            {"games": 12, "beliefs": 30, "boards": 240},
                                            {"games": 9, "positions": 20, "moves": 200}]
    assert [t.get("target_depth") for t in tables] == [None, None, 16]


# Catches: a difference that goes missing, comes in twice, or is read from a neighbour. The per-move file also holds two
# differences the page does not draw.
def test_the_three_differences_with_label_mean_interval_and_verdict(tmp_path):
    differences = read_accuracy(fake_folder(tmp_path))["differences"]
    assert differences == [
        {"key": KEYS[0], "label": LABELS[0], "source": NET1, "mean": -0.015, "ci95": [-0.025, -0.005],
         "verdict": "better"},
        {"key": KEYS[1], "label": LABELS[1], "source": BELIEF, "mean": 0.0, "ci95": [-0.01, 0.01], "verdict": "tie"},
        {"key": KEYS[2], "label": LABELS[2], "source": CHILDREN, "mean": 0.02, "ci95": [0.01, 0.03],
         "verdict": "worse"},
    ]


# ---- files that are absent, unreadable or damaged ----

def test_with_no_files_all_three_are_missing(tmp_path):
    got = read_accuracy(tmp_path)
    assert got["missing"] == FILES
    assert got["tables"] == [] and got["differences"] == []
    assert got["why_missing"] == dict.fromkeys(FILES, "not found")


def test_a_folder_that_does_not_exist_is_the_same_as_an_empty_one(tmp_path):
    assert read_accuracy(tmp_path / "nowhere") == read_accuracy(tmp_path)


def test_a_missing_file_leaves_the_others(tmp_path):
    write(tmp_path, NET1, net1_file())
    write(tmp_path, CHILDREN, children_file())
    got = read_accuracy(tmp_path)
    assert got["missing"] == [BELIEF] and got["why_missing"] == {BELIEF: "not found"}
    assert [t["title"] for t in got["tables"]] == [TITLES[0], TITLES[2]]
    assert [d["key"] for d in got["differences"]] == [KEYS[0], KEYS[2]]


def put_a_folder_in_place_of_the_file(folder):
    (folder / BELIEF).unlink()
    (folder / BELIEF).mkdir()


@pytest.mark.parametrize("content, reason", [
    pytest.param(b"", "not valid JSON", id="empty"),
    pytest.param(b"{not json", "not valid JSON", id="not json"),
    pytest.param(b"\xff\xfe\x00\x00", "could not be read", id="not utf-8"),
    pytest.param(b"[" * 100000, "could not be read", id="nested too deep"),  # the parser raises RecursionError
    pytest.param(b"1" * 5000, "could not be read", id="number too long"),  # more digits than Python will convert
    pytest.param(b"[1, 2, 3]", "baseline.board_mae", id="a list"),  # JSON, but not an object holding what is needed
    pytest.param(b"null", "baseline.board_mae", id="null"),
    pytest.param(put_a_folder_in_place_of_the_file, "could not be read", id="a folder"),
])
def test_a_file_that_cannot_be_read_is_missing_with_its_reason(tmp_path, content, reason):
    fake_folder(tmp_path)
    if callable(content):
        content(tmp_path)
    else:
        (tmp_path / BELIEF).write_bytes(content)
    got = read_accuracy(tmp_path)
    assert got["missing"] == [BELIEF]
    assert reason in got["why_missing"][BELIEF]
    assert [t["title"] for t in got["tables"]] == [TITLES[0], TITLES[2]]
    assert [d["key"] for d in got["differences"]] == [KEYS[0], KEYS[2]]


def drop(*path):
    """A damage: remove the entry at this path from a file's content."""
    def damage(content):
        for key in path[:-1]:
            content = content[key]
        del content[path[-1]]
    return damage


def set_to(value, *path):
    """A damage: put `value` at this path in a file's content."""
    def damage(content):
        for key in path[:-1]:
            content = content[key]
        content[path[-1]] = value
    return damage


# A file that is there but lacks something its table or its difference needs is left out whole: half a card would show
# numbers that do not belong together.
@pytest.mark.parametrize("damage, reason", [
    (drop("regret_difference"), "no 'regret_difference.mean' in the file"),
    (drop("network", "choice", "top1"), "no 'network.choice.top1' in the file"),
    (drop("material"), "no 'material.mae' in the file"),
    (set_to("n/a", "material", "mae"), "'material.mae' is not a number"),
    (set_to(None, "network", "choice", "regret"), "'network.choice.regret' is not a number"),
    (set_to(True, "regret_difference", "mean"), "'regret_difference.mean' is not a number"),
    (set_to(float("nan"), "baseline", "mae"), "'baseline.mae' is not a number"),
    (set_to(10 ** 400, "material", "mae"), "'material.mae' is not a number"),  # too big for a float: must not raise
    (drop("regret_difference", "ci95"), "no 'regret_difference.ci95' in the file"),
    (set_to([0.1], "regret_difference", "ci95"), "'regret_difference.ci95' is not a pair of numbers"),
    (set_to([0.1, "x"], "regret_difference", "ci95"), "'regret_difference.ci95' is not a pair of numbers"),
    (set_to(-0.1, "regret_difference", "ci95"), "'regret_difference.ci95' is not a pair of numbers"),
])
def test_a_file_missing_what_it_needs_is_left_out_whole_with_the_reason(tmp_path, damage, reason):
    fake_folder(tmp_path)
    content = net1_file()
    damage(content)
    write(tmp_path, NET1, content)
    got = read_accuracy(tmp_path)
    assert got["missing"] == [NET1] and got["why_missing"] == {NET1: reason}
    assert [t["title"] for t in got["tables"]] == TITLES[1:]
    assert [d["key"] for d in got["differences"]] == KEYS[1:]


# "Where present": a file that lacks its date or a count still gives its table, and the note just has less in it.
def test_provenance_a_file_lacks_is_left_out_not_an_error(tmp_path):
    content = net1_file()
    del content["created"], content["n"]
    write(tmp_path, NET1, content)
    got = read_accuracy(tmp_path)
    table = got["tables"][0]
    assert got["missing"] == [BELIEF, CHILDREN]
    assert "created" not in table and table["sizes"] == {"games": 12, "decisions": 40}
    assert (table["data"], table["split"]) == ("d-net1", "train")


# ---- what is returned ----

# Catches: anything but plain data in the result (a Path, a numpy float, a tuple), which the run summary could not
# store.
def test_the_result_is_plain_json(tmp_path):
    for folder in (REAL, fake_folder(tmp_path / "all three"), tmp_path / "none"):
        got = read_accuracy(folder)
        assert json.loads(json.dumps(got)) == got, folder


def test_a_folder_given_as_text_works_too(tmp_path):
    assert read_accuracy(str(fake_folder(tmp_path))) == read_accuracy(tmp_path)


# Catches: a torch import in the reader, which would stop the Tests tab on an Intel Mac, or cost seconds on a machine
# that has torch. Run in a fresh interpreter, so it is not fooled by what an earlier test imported.
def test_reading_does_not_import_torch():
    code = ("import sys, pathlib, pairb.lab.accuracy as a; "
            "got = a.read_accuracy(pathlib.Path('checkpoints')); "
            "print(len(got['tables']), 'torch' in sys.modules)")
    r = subprocess.run([sys.executable, "-c", code], cwd=PAIR_B, capture_output=True, encoding="utf-8",
                       errors="replace", timeout=300)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "3 False"
