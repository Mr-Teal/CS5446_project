"""Load independent FoW acceptance cases and compare a future adapter's output.

No FoW move generator lives here. Running without --adapter validates fixture
structure and replay history only; it does not certify the rules implementation.
"""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Mapping

import chess


DEFAULT_SUITE = Path(__file__).parent / "data" / "rules_cases.json"


def board_for_case(case: dict) -> chess.Board:
    board = chess.Board(case.get("initial_fen", case["fen"]))
    for uci in case.get("moves_uci", []):
        move = chess.Move.from_uci(uci)
        # Current replay fixtures use orthodox-legal reversible moves only.
        if move not in board.legal_moves:
            raise ValueError(f"invalid replay move in {case['id']}: {uci}")
        board.push(move)
    if board.fen(en_passant="fen") != chess.Board(case["fen"]).fen(en_passant="fen"):
        raise ValueError(f"replay disagrees with final FEN in {case['id']}")
    return board


def load_suite(path: Path = DEFAULT_SUITE) -> dict:
    suite = json.loads(path.read_text(encoding="utf-8"))
    ids = [case["id"] for case in suite["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate fixture ID")
    for case in suite["cases"]:
        board_for_case(case)
        if case["source"] not in suite["sources"] or case["player"] not in ("white", "black"):
            raise ValueError("unknown fixture source or player")
        expected = case["expect"]
        for key in ("legal_contains", "legal_excludes"):
            for move in expected.get(key, []):
                chess.Move.from_uci(move)
        for key in ("visible_contains", "visible_excludes"):
            for square in expected.get(key, []):
                chess.parse_square(square)
        for prefix in ("legal", "visible"):
            if set(expected.get(prefix + "_contains", [])) & set(expected.get(prefix + "_excludes", [])):
                raise ValueError("fixture has contradictory expectations")
    return suite


def compare_result(case: dict, result: Mapping) -> list:
    """Adapter result: legal_moves, visible_squares, visible_pieces, terminal, winner.

    Only listed expectations are asserted. Missing hidden fields or None both
    mean unknown; never fill a hidden observation field from the referee board.
    """
    errors = []
    expected = case["expect"]
    for prefix, field in (("legal", "legal_moves"), ("visible", "visible_squares")):
        if any(k in expected for k in (prefix + "_contains", prefix + "_excludes", prefix + "_count")):
            if field not in result:
                errors.append(f"missing {field}")
                continue
            items = set(result[field])
            missing = set(expected.get(prefix + "_contains", [])) - items
            unexpected = set(expected.get(prefix + "_excludes", [])) & items
            if missing:
                errors.append(f"{field} missing {sorted(missing)}")
            if unexpected:
                errors.append(f"{field} unexpectedly contains {sorted(unexpected)}")
            if prefix + "_count" in expected and len(items) != expected[prefix + "_count"]:
                errors.append(f"wrong {field} count: {len(items)}")
    for key in ("terminal", "winner"):
        if key in expected and result.get(key) != expected[key]:
            errors.append(f"{key}: expected {expected[key]!r}, got {result.get(key)!r}")
    for square, piece in expected.get("visible_pieces", {}).items():
        actual = result.get("visible_pieces", {})
        if square not in actual or actual[square] != piece:
            errors.append(f"wrong/missing observed piece at {square}")
    for key in expected.get("hidden_fields", []):
        if result.get(key) is not None:
            errors.append(f"hidden field exposed: {key}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--adapter", help="module:function; callable takes the full fixture and returns a mapping")
    args = parser.parse_args()
    suite = load_suite(args.suite)
    if not args.adapter:
        print(f"Validated {len(suite['cases'])} fixture definitions; no FoW adapter executed.")
        return
    module, attr = args.adapter.split(":", 1)
    inspect_case = getattr(importlib.import_module(module), attr)
    failed = 0
    for case in suite["cases"]:
        errors = compare_result(case, inspect_case(case))
        failed += bool(errors)
        print(case["id"] + (": PASS" if not errors else ": " + "; ".join(errors)))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
