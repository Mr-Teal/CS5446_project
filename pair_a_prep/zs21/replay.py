"""Recompute genuine outcomes and verify both private channels in saved matches."""

import argparse
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path

from fow_shared.contracts import Decision
from .model import Referee
from .match import summarize
from .rule_profile import RULES_ID, LEGACY_RULES_ID


def validate(directory, expected_games=None):
    directory = Path(directory)
    manifest = json.loads((directory/"manifest.json").read_text(encoding="utf-8"))
    config = manifest["config"]
    if "rules_id" not in config and any(
            Path(relative).as_posix() == "pair_a_prep/zs21/rule_profile.py" for relative in config["source"]):
        raise ValueError("versioned source archive is missing its rules_id")
    rules_id = config.get("rules_id", LEGACY_RULES_ID)
    if rules_id not in (RULES_ID, LEGACY_RULES_ID):
        raise ValueError("unsupported recorded rule version")
    for relative, digest in config["source"].items():
        assert hashlib.sha256((directory/"source"/relative).read_bytes()).hexdigest() == digest
    completed, errors, elapsed = [], [], []
    for path in sorted(directory.glob("game-*.jsonl.gz")):
        ref = Referee(no_move_draw=rules_id == RULES_ID)
        pending, plies, finish, start_record = None, 0, None, None
        with gzip.open(path,"rt",encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                event = record["event"]
                if event == "start":
                    assert record.get("rules_id", LEGACY_RULES_ID) == rules_id
                    start_record = record
                elif event == "position":
                    if pending is not None:
                        ref.apply(pending)
                        plies += 1
                        pending = None
                    assert record["ply"] == plies and record["fen"] == ref._state.fen
                    for player in ("white","black"):
                        observed = json.loads(json.dumps(asdict(ref.observe(player))))
                        assert observed == record["observations"][player]
                elif event == "decision":
                    assert pending is None and record["ply"] == plies
                    assert ref.current_player() == record["player"]
                    Decision(**record["decision"]).validate_for(ref.observe(record["player"]))
                    assert 0 <= record["elapsed_seconds"] <= start_record["seconds_per_move"]
                    assert record["trace"]["flow_error"] <= 1e-8
                    assert abs(record["trace"]["gap"]) <= 1e-8
                    if record["player"] != start_record["paper_color"]:
                        assert record["trace"]["max_fow_depth"] == 1
                    elapsed.append(record["elapsed_seconds"])
                    pending = record["decision"]["move"]
                elif event == "finish":
                    finish = record
        assert finish is not None
        assert finish.get("rules_id", LEGACY_RULES_ID) == rules_id
        if finish["status"] == "failed" and pending is not None:
            ref.apply(pending)
            plies += 1
            pending = None
        assert pending is None
        if finish["status"] == "completed":
            assert plies == finish["plies"] and ref.is_terminal()
            assert ref.winner() == finish["winner"]
            derived = "draw" if ref.winner()=="draw" else "win" if ref.winner()==finish["paper_color"] else "loss"
            assert derived == finish["paper_result"]
            assert finish["reason"] == ref._rules.terminal(ref._state).reason
            completed.append({key:value for key,value in finish.items() if key!="event"})
        else:
            errors.append(finish)
    report = summarize(completed)
    report.update(failed=len(errors), logs_verified=len(completed)+len(errors), failed_logs=len(errors),
                  decisions_verified=len(elapsed), max_submission_seconds=max(elapsed,default=0.),
                  source_archive_verified=True, rules_id=rules_id)
    saved = json.loads((directory/"summary.json").read_text(encoding="utf-8"))
    assert saved["wdl"] == report["wdl"] and saved["completed"] == report["completed"]
    assert saved["failed"] == len(errors)
    if expected_games is not None:
        assert len(completed) == expected_games and not errors
        assert sum(report["wdl"]["white"].values()) == (expected_games+1)//2
        assert sum(report["wdl"]["black"].values()) == expected_games//2
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--expected-games", type=int)
    args = parser.parse_args()
    result = validate(args.directory,args.expected_games)
    (Path(args.directory)/"replay-validation.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="games"}))
