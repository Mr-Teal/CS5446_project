"""Pair A's fog-rules positions (pair_a_prep.fixtures), run against one rules implementation, for Fog Lab's Tests tab.

    python fixture_check.py [--rules standin|teal]

prints one JSON object on stdout and exits 0 whatever the positions found: a failing position is data, and so is a rules
implementation the checkout does not have.

    {"rules": "standin", "available": true, "reason": null,
     "cases": [{"id", "player", "fen", "history", "visible", "expect", "errors"}, ...]}

"standin" is Pair B's observe (pairb.observe). "teal" is Teal's RulesAdapter, through the fixture_result bridge in
pair_a_prep.rules_adapter, once the checkout has it. When the chosen rules cannot be imported, "available" is false,
"reason" says why and "cases" is empty. Per position, "fen" is the board drawn (after its moves are replayed), "history"
the number of moves replayed, "visible" the squares the rules show the player, sorted, "expect" the fixture's own
expectations, and "errors" what pair_a_prep.fixtures.compare_result found wrong (empty when the position passes). A
position the rules cannot answer at all (they raise) is a failing one, with the exception as its error.

The stage runner starts this file by path in a throwaway worktree, with that worktree's code first on PYTHONPATH. So it
imports only absolute modules (pair_a_prep, pairb, fow_shared), never the app's pairb.lab, which a stage need not have,
nor anything from its own folder, and it leaves sys.path alone: whatever is first on PYTHONPATH is what gets checked.
The stand-in is available only if pairb.observe lives in the same tree as the fixtures (pair_a_prep): a stage without a
pairb would otherwise be checked with the one the environment has installed for the app's own checkout.
"""
import argparse
import contextlib
import importlib
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import pair_a_prep
from pair_a_prep.fixtures import board_for_case, compare_result, load_suite

RULES = ("standin", "teal")


class _Unavailable(Exception):
    """The chosen rules cannot be used in this checkout. The message says why."""


def _import(module: str, label: str):
    """The module, or _Unavailable saying why `label` cannot be used: it is missing, or it fails to import."""
    try:
        return importlib.import_module(module)
    except ImportError as error:
        if error.name == module:  # the module itself is missing, not something it imports
            raise _Unavailable(f"{label} ({module}) is not in this checkout") from None
        raise _Unavailable(f"{label} ({module}) could not be imported: {error}") from None


def _standin_bridge() -> Callable[[dict], Mapping]:
    """Pair B's observe, answering a fixture the way pair_a_prep.fixtures.compare_result wants it."""
    module = _import("pairb.observe", "Pair B's stand-in")
    # The environment has the checkout's own pairb installed, and it is found after PYTHONPATH, so a stage with no
    # pairb would be checked with that one. pair_a_prep is installed nowhere: it, and so the fixtures, come from the
    # stage, and the stand-in counts only when it comes from that same tree.
    tree, found = Path(pair_a_prep.__file__).resolve().parents[1], Path(module.__file__).resolve()
    if tree not in found.parents:
        raise _Unavailable(f"Pair B's stand-in (pairb.observe) is not in this checkout: the one that can be imported "
                           f"is {found}, outside {tree}")
    observe = module.observe

    def bridge(case: dict) -> dict:
        board = board_for_case(case)
        obs = observe(board, case["player"], ply=len(board.move_stack))
        winner = None
        if obs.terminal:  # the observation gives the outcome from the player's side; the fixtures name the colour
            other = "black" if obs.player == "white" else "white"
            winner = {1.0: obs.player, -1.0: other, 0.0: "draw"}[obs.outcome]
        return {"legal_moves": obs.legal_moves, "visible_squares": obs.visible_squares,
                "visible_pieces": obs.visible_pieces, "terminal": obs.terminal, "winner": winner,
                "halfmove_clock": obs.halfmove_clock}  # as it is: the fixtures check that the clock stays hidden

    return bridge


def _teal_bridge() -> Callable[[dict], Mapping]:
    """Teal's fixture_result, which does the replay and the observing itself."""
    bridge = getattr(_import("pair_a_prep.rules_adapter", "Teal's rules adapter"), "fixture_result", None)
    if not callable(bridge):
        raise _Unavailable("Teal's rules adapter (pair_a_prep.rules_adapter) has no fixture_result function "
                           "in this checkout")
    return bridge


def run_fixtures(rules: str) -> dict:
    """Pair A's positions against `rules` ("standin" or "teal"), as the dict the module docstring describes.

    ValueError for any other name. A rules implementation the checkout lacks is reported ("available": False), never
    raised, and a position it fails is a case with errors, never an exception."""
    if rules not in RULES:
        raise ValueError(f"rules must be 'standin' or 'teal', not {rules!r}")
    try:
        bridge = _standin_bridge() if rules == "standin" else _teal_bridge()
    except _Unavailable as why:
        return {"rules": rules, "available": False, "reason": str(why), "cases": []}
    cases = []
    for case in load_suite()["cases"]:
        board = board_for_case(case)
        try:
            result = bridge(case)
            errors, visible = compare_result(case, result), sorted(result.get("visible_squares") or ())
        except Exception as error:  # a position the rules cannot answer fails alone; the others still report
            errors, visible = [f"the rules raised {type(error).__name__}: {error}"], []
        cases.append({"id": case["id"], "player": case["player"], "fen": board.fen(en_passant="fen"),
                      "history": len(board.move_stack), "visible": visible, "expect": case["expect"],
                      "errors": errors})
    return {"rules": rules, "available": True, "reason": None, "cases": cases}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Pair A's fog-rules positions against one rules implementation "
                                     "and print the results as JSON. Exits 0 whatever they find.")
    parser.add_argument("--rules", choices=RULES, default="standin", help="Pair B's stand-in observe, or Teal's "
                        "RulesAdapter when this checkout has it (default: standin)")
    args = parser.parse_args(argv)
    with contextlib.redirect_stdout(sys.stderr):  # anything the rules print must not get into the JSON
        report = run_fixtures(args.rules)
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
