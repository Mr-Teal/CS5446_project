"""Read-only acceptance checks for TrainingRecord label exports; no torch or engine calls.

Pair A runs this on Python 3.9, so this module and everything it imports must stay 3.9-safe: a
module with `X | None` in an annotation needs `from __future__ import annotations`. A test checks it.
"""
from collections import Counter
from dataclasses import dataclass, field
import json
from math import fsum, isfinite
from pathlib import Path
import re

import chess

from fow_shared.features import encode_belief
from fow_shared.recording import read_records
from fow_shared.values import rule_score

from .belief_data import opponent_visible
from .data import split_of

TOLERANCE = 1e-6


@dataclass
class Report:
    files: int = 0
    records: int = 0
    games: set[str] = field(default_factory=set)
    configs: set[str] = field(default_factory=set)
    splits: Counter = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_played: int = 0
    first_missing_played: str = ""


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def check_record(record, *, require_d1=False):
    """Return field-specific errors after shared-schema construction has succeeded."""
    errors = []
    for name in ("game_id", "agent_name", "config_id"):
        value = getattr(record, name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{name}: must be a nonblank string")
    turn = record.agent_input
    expected = fsum(h.weight * v for h, v in zip(turn.belief.hypotheses, record.hypothesis_values))
    if abs(record.root_value - expected) > TOLERANCE:
        errors.append(f"root_value: {record.root_value!r} differs from weighted hypothesis values "
                      f"{expected:.12g} by more than {TOLERANCE:g}")
    diagnostics = record.decision.diagnostics
    played = {key[len("played_policy:"):]: value for key, value in diagnostics.items()
              if key.startswith("played_policy:")}
    if played:
        if set(played) != set(turn.observation.legal_moves):
            errors.append("decision.diagnostics.played_policy: must cover exactly the legal moves")
        if any(not _number(p) or not 0 <= p <= 1 for p in played.values()):
            errors.append("decision.diagnostics.played_policy: probabilities must be finite and in [0, 1]")
        elif abs(fsum(played.values()) - 1) > TOLERANCE:
            errors.append("decision.diagnostics.played_policy: probabilities must sum to one")
        if played.get(record.decision.move, 0) <= 0:
            errors.append("decision.move: has no positive probability in played_policy")
    for key, value in diagnostics.items():
        if not key.startswith("d1:"):
            continue
        if not re.fullmatch(r"d1:(0|[1-9][0-9]*)", key) or int(key[3:]) >= len(turn.belief.hypotheses):
            errors.append(f"decision.diagnostics.{key}: invalid hypothesis index")
        if not _number(value) or not -1 <= value <= 1:
            errors.append(f"decision.diagnostics.{key}: must be finite and in [-1, 1]")
    try:
        # The same encoder/callback as the training loader, only one belief in memory.
        encode_belief(turn, opponent_visible)
        if require_d1:
            for i, hypothesis in enumerate(turn.belief.hypotheses):
                if f"d1:{i}" not in diagnostics and rule_score(chess.Board(hypothesis.fen)) is None:
                    errors.append(f"decision.diagnostics.d1:{i}: required for a non-rule-decided board")
    except (ValueError, TypeError, IndexError, OverflowError) as exc:
        errors.append(f"agent_input.belief: encoder/rule check failed: {exc}")
    return errors, not bool(played)


def _manifest(folder, report, *, full_scope):
    path = folder / "manifest.json"
    if not path.exists():
        report.warnings.append(f"{path}: absent; accepted by the training loader")
        return
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("must be an object")
        for key in ("created", "records", "config_id"):
            if key not in manifest:
                report.warnings.append(f"{path}: missing recommended {key}")
        if "records" in manifest:
            count = manifest["records"]
            if type(count) is not int or count < 0:
                raise ValueError("records must be a nonnegative integer")
            if full_scope and not report.errors and count != report.records:
                raise ValueError(f"records={count} but read {report.records}")
            if not full_scope:
                report.warnings.append(f"{path}: record count not compared for a file/custom pattern selection")
        if "config_id" in manifest and report.configs and report.configs != {manifest["config_id"]}:
            raise ValueError("config_id does not match all selected records")
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        report.errors.append(f"{path}: {exc}")


def _splits(path, report):
    """Accept the training script's splits.json, plus an optional explicit test list."""
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(obj, dict) or not {"train", "val"} <= obj.keys():
            raise ValueError("expected an object containing train and val game-ID lists")
        seen = set()
        for name in ("train", "val", "test"):
            if name not in obj:
                continue
            ids = obj[name]
            if not isinstance(ids, list) or any(not isinstance(g, str) or not g.strip() for g in ids):
                raise ValueError(f"{name}: expected a list of nonblank game IDs")
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name}: duplicate game IDs")
            if seen.intersection(ids):
                raise ValueError(f"{name}: game appears in more than one split")
            seen.update(ids)
            for game in ids:
                if game not in report.games:
                    raise ValueError(f"{name}: unknown game ID {game!r} in selected data")
                if split_of(game) != name:
                    raise ValueError(f"{name}: {game!r} belongs to {split_of(game)} under split_of")
        if "test_held_out_games" in obj:
            count = obj["test_held_out_games"]
            if type(count) is not int or count != report.splits["test"]:
                raise ValueError("test_held_out_games differs from selected data's test game count")
        if "test" not in obj:
            report.warnings.append(f"{path}: no explicit test game list; only hash assignments/count can be checked")
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        report.errors.append(f"{path}: {exc}")


def validate(source, *, pattern="part-*.jsonl", require_d1=False, require_played_policy=False, splits=None):
    """Stream files without writing caches or changing data. A parse error stops that file.
    Records without played_policy give one warning, or one error with require_played_policy."""
    source = Path(source)
    report = Report()
    folder = source if source.is_dir() else source.parent
    paths = sorted(source.glob(pattern)) if source.is_dir() else ([source] if source.is_file() else [])
    paths = [p for p in paths if p.is_file()]
    report.files = len(paths)
    for path in paths:
        try:
            # read_records preserves physical line numbers in parse errors. Count blank
            # lines separately so successful records also have physical source locations.
            with path.open(encoding="utf-8") as lines:
                line_numbers = (n for n, line in enumerate(lines, 1) if line.strip())
                for record in read_records(path):
                    line = next(line_numbers)
                    report.records += 1
                    errors, missing = check_record(record, require_d1=require_d1)
                    report.errors.extend(f"{path}:{line}: {error}" for error in errors)
                    report.missing_played += missing
                    if missing and not report.first_missing_played:
                        report.first_missing_played = f"{path}:{line}"
                    if isinstance(record.game_id, str) and record.game_id.strip():
                        report.games.add(record.game_id)
                    if isinstance(record.config_id, str) and record.config_id.strip():
                        report.configs.add(record.config_id)
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError, OverflowError) as exc:
            cause = str(exc.__cause__) if exc.__cause__ else ""
            report.errors.append(f"{path}: schema/read error: {exc}" + (f": {cause}" if cause else ""))
    report.splits.update(split_of(g) for g in report.games)
    if not report.records:
        report.errors.append(f"{source}: no records found matching {pattern!r}")
    if report.missing_played:
        absent = (f"decision.diagnostics.played_policy: absent in {report.missing_played} records "
                  f"(first at {report.first_missing_played}); ")
        if require_played_policy:
            report.errors.append(absent + "--require-played-policy requires it on every record")
        else:
            report.warnings.append(absent + "recommended by the solver-label specification")
    _manifest(folder, report, full_scope=source.is_dir() and pattern == "part-*.jsonl")
    if splits is not None:
        _splits(splits, report)
    return report
