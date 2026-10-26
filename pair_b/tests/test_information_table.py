"""experiments/small_games/make_information_table.py: the table in information_example.md, from Pair A's toy values.

The script reads pair_a_prep/results/toy_reference.json with the standard library only, so these tests need
neither SciPy nor Pair A's code.
"""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parents[1] / "experiments" / "small_games"


@pytest.fixture(scope="module")
def script():
    """experiments/ is not a package: load the file by its path."""
    spec = importlib.util.spec_from_file_location("make_information_table", FOLDER / "make_information_table.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def report(script):
    return json.loads(script.REFERENCE.read_text(encoding="utf-8"))


def test_values_and_strategies_come_from_the_reference(script, report):
    assert report["payoff_perspective"] == "player_0"
    rows = {row[0]: row[2:] for row in script.rows(report)}
    assert rows == {
        "Matching pennies, hidden": ("0.0", "p0: H 0.5, T 0.5", "p1_hidden: H 0.5, T 0.5"),
        "Matching pennies, revealed": ("-1.0", "p0: H", "p1_after_H: T; p1_after_T: H"),
        "Coin game, hidden": ("0.5", "guess_hidden: H", "no move"),
        "Coin game, revealed": ("1.0", "guess_H: H; guess_T: T", "no move"),
    }


def test_markdown_table_is_exactly_what_the_script_prints(script, capsys):
    script.main([])
    printed = capsys.readouterr().out.rstrip("\n")
    text = (FOLDER / "information_example.md").read_text(encoding="utf-8")
    in_doc = "\n".join(line for line in text.splitlines() if line.startswith("|"))
    assert in_doc == printed


def test_strategy_is_shown_per_information_set(script):
    policies = [{"a": "H", "b": "H"}, {"a": "H", "b": "T"}, {"a": "T", "b": "H"}, {"a": "T", "b": "T"}]
    assert script.strategy(policies, [0.25, 0.25, 0.5, 0.0]) == "a: H 0.5, T 0.5; b: H 0.75, T 0.25"
    assert script.strategy(policies, [0.0, 0.0, 1.0, 0.0]) == "a: T; b: H"
    assert script.strategy([{}], [1.0]) == "no move"
    assert script.number(-0.0) == "0.0"
    with pytest.raises(ValueError, match="one weight"):
        script.strategy(policies, [1.0])


def test_rejects_another_perspective_or_an_unsolved_game(script, report):
    with pytest.raises(ValueError, match="player 0"):
        script.rows({**report, "payoff_perspective": "player_1"})
    for field, value in (("profile_value", 0.4), ("nash_gap", 0.1)):
        bad = copy.deepcopy(report)
        bad["games"]["coin_hidden"][field] = value
        with pytest.raises(ValueError, match="coin_hidden"):
            script.rows(bad)


def test_reference_option_reads_another_file(script, report, tmp_path, capsys):
    other = copy.deepcopy(report)
    other["games"]["coin_hidden"].update(profile_value=0.25, expected_value=0.25)
    path = tmp_path / "toy.json"
    path.write_text(json.dumps(other), encoding="utf-8")
    script.main(["--reference", str(path)])
    assert "| Coin game, hidden | Player 0 cannot see the coin | 0.25 |" in capsys.readouterr().out
