"""Stable JSONL format for teacher labels and evaluation traces."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Iterator

from .contracts import AgentInput, Belief, Decision, HistoryEvent, Hypothesis, Observation, TrainingRecord


def write_records(path: Path, records: Iterable[TrainingRecord]) -> None:
    with Path(path).open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")


def read_records(path: Path) -> Iterator[TrainingRecord]:
    with Path(path).open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                ai = obj["agent_input"]
                o = ai["observation"]
                b = ai["belief"]
                obs = Observation(**{**o, "visible_squares": tuple(o["visible_squares"]),
                                     "legal_moves": tuple(o["legal_moves"])})
                belief = Belief(**{**b, "hypotheses": tuple(Hypothesis(**{**h,
                    "candidate_moves": tuple(h.get("candidate_moves", ()))})
                    for h in b["hypotheses"])})
                history = []
                for event in ai.get("history", []):
                    prior = event["observation"]
                    past_obs = Observation(**{**prior,
                        "visible_squares": tuple(prior["visible_squares"]),
                        "legal_moves": tuple(prior["legal_moves"])})
                    history.append(HistoryEvent(past_obs, event.get("own_move")))
                turn = AgentInput(obs, belief, ai["time_budget_ms"], tuple(history))
                decision = Decision(**obj["decision"])
                yield TrainingRecord(turn, decision, obj["root_value"],
                                     tuple(obj["hypothesis_values"]), obj["seed"],
                                     obj["agent_name"], obj["config_id"],
                                     obj.get("game_id", ""))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid record on line {line_no}") from exc
