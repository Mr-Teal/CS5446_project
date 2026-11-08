"""Self-play label collection: one validated part per game, no labels for openings or fallbacks."""

import json

import pytest

from fow_shared.recording import read_records
from pair_a_prep.anytime_agent import AnytimeConfig
from pair_a_prep.label_run import collect
from pair_a_prep.tests.test_chess_search import KINGS, ConstantLeaf


def small_config():
    return AnytimeConfig(growth="one_sided", rounds=4, final_rounds=1, stop_on_time=False,
                         max_nodes=2000, max_evaluator_calls=256)


def test_collect_writes_one_validated_part_per_game_and_resumes(tmp_path):
    from pairb.label_validation import validate
    settings = dict(games=2, seed=17, evaluator=ConstantLeaf(), config=small_config(), time_budget_ms=1000,
                    max_states=1000, sample_size=4, opening_range=(1, 1), max_plies=6,
                    initial_fen=KINGS, log=lambda *args: None)
    identity, proto, summaries = collect(tmp_path, **settings)
    parts = sorted(tmp_path.glob("part-*.jsonl"))
    assert [p.name for p in parts] == ["part-0000.jsonl", "part-0001.jsonl"]
    assert len(summaries) == 2
    for summary in summaries:
        # Every ply is one decision: an unlabelled opening move, a labelled solve, or a fallback.
        assert summary["opening_plies"] == 1
        assert summary["records"] + summary["fallbacks"] + summary["opening_plies"] == summary["plies"]
        assert summary["records"] > 0
    records = [record for part in parts for record in read_records(part)]
    assert len(records) == sum(s["records"] for s in summaries)
    for record in records:
        belief = record.agent_input.belief
        assert len(record.hypothesis_values) == len(belief.hypotheses)
        assert record.root_value == pytest.approx(sum(h.weight*v for h, v in zip(belief.hypotheses, record.hypothesis_values)))
        assert set(record.decision.root_policy) == set(record.agent_input.observation.legal_moves)
        assert record.game_id.startswith(identity) and record.config_id == identity
        assert any(k.startswith("played_policy:") for k in record.decision.diagnostics)
        assert record.agent_input.observation.ply >= 1  # the opening ply is never labelled
    report = validate(tmp_path, require_played_policy=True)
    assert report.errors == []
    progress = [json.loads(line) for line in (tmp_path / "progress.jsonl").read_text().splitlines()]
    assert [row["index"] for row in progress] == [0, 1]
    # A second run over the same folder finds both parts and plays nothing.
    assert collect(tmp_path, **settings)[2] == []
    assert proto["tracker"]["implementation"] == "tail-guarded-exact-v1"


def test_opening_length_comes_from_the_game_seed_and_both_colours_share_it(tmp_path):
    _, _, summaries = collect(tmp_path, games=3, seed=40, evaluator=ConstantLeaf(), config=small_config(),
                              time_budget_ms=1000, max_states=1000, sample_size=4, opening_range=(2, 8),
                              max_plies=4, initial_fen=KINGS, log=lambda *args: None)
    openings = [s["opening_plies"] for s in summaries]
    assert all(2 <= k <= 8 for k in openings)
    # With a 4-ply cap, every ply before the opening length is unlabelled.
    for summary in summaries:
        assert summary["records"] == max(0, summary["plies"] - summary["opening_plies"]) - summary["fallbacks"]


class DyingTracker:
    """Forwards to a real tracker and raises on one chosen update, as a guarded tracker
    does when a prune dropped the true history and a later view matches nothing."""

    def __init__(self, inner, dies_at):
        self._inner, self._dies_at, self.updates = inner, dies_at, 0

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def reset(self, *args, **kwargs):
        return self._inner.reset(*args, **kwargs)

    def update(self, observation, own_move=None):
        self.updates += 1
        if self.updates == self._dies_at:
            raise RuntimeError("no_candidate: stopped by None; no descendants of retained support")
        return self._inner.update(observation, own_move)


def test_a_game_that_dies_is_written_logged_and_the_run_continues(tmp_path, monkeypatch):
    from pairb.label_validation import validate
    from pair_a_prep import label_run
    real = label_run.make_tracker
    made = []

    def make_tracker(initial_fen, sample_size, max_states):
        made.append(1)
        # The third tracker built is White's for game 1; it dies on its fourth update,
        # the one after the third ply, so game 1 ends with three plies played.
        return DyingTracker(real(initial_fen, sample_size, max_states), dies_at=4 if len(made) == 3 else 0)
    monkeypatch.setattr(label_run, "make_tracker", make_tracker)
    settings = dict(games=3, seed=17, evaluator=ConstantLeaf(), config=small_config(), time_budget_ms=1000,
                    max_states=1000, sample_size=4, opening_range=(1, 1), max_plies=6,
                    initial_fen=KINGS, log=lambda *args: None)
    _, _, summaries = collect(tmp_path, **settings)
    assert [p.name for p in sorted(tmp_path.glob("part-*.jsonl"))] == ["part-0000.jsonl", "part-0001.jsonl", "part-0002.jsonl"]
    assert [s["error"] for s in summaries] == [None, "RuntimeError: no_candidate: stopped by None; no descendants of retained support", None]
    dead = summaries[1]
    assert dead["plies"] == 3 and dead["winner"] is None and dead["stopped_at_ply_limit"] is False
    assert dead["records"] + dead["fallbacks"] + dead["opening_plies"] == dead["plies"]
    # The decisions labelled before the death are labels and were written.
    assert len(list(read_records(tmp_path / "part-0001.jsonl"))) == dead["records"]
    assert summaries[0]["records"] > 0 and summaries[2]["records"] > 0
    assert validate(tmp_path, require_played_policy=True).errors == []
    progress = [json.loads(line) for line in (tmp_path / "progress.jsonl").read_text().splitlines()]
    assert [(row["index"], bool(row["error"])) for row in progress] == [(0, False), (1, True), (2, False)]
    # The dead game's part exists, so a resume does not replay it.
    assert collect(tmp_path, **settings)[2] == []


def test_label_rounds_a_decided_value_onto_the_unit_interval_and_rejects_more(monkeypatch):
    from fow_shared.contracts import Decision
    from pair_a_prep.chess_subgame_agent import ChessSubgameAgent, _unit
    from pair_a_prep.search_agent import SearchResult
    from pair_a_prep.tests.test_chess_search import turn_after

    assert _unit(1 + 1e-9) == 1.0 and _unit(-1 - 1e-9) == -1.0 and _unit(0.25) == 0.25
    for bad in (1.01, -1.01, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            _unit(bad)
    turn = turn_after()
    moves = turn.observation.legal_moves
    decision = Decision(moves[0], dict.fromkeys(moves, 1/len(moves)), {"played_policy:"+moves[0]: 1.})
    agent = ChessSubgameAgent(ConstantLeaf(), small_config(), KINGS)
    agent.reset("white", 1)
    count = len(turn.belief.hypotheses)
    monkeypatch.setattr(agent, "solve", lambda t: SearchResult(decision, (1 + 1e-9,)*count, 1 + 1e-9))
    record = agent.label(turn, "game")
    assert record.root_value == 1.0 and set(record.hypothesis_values) == {1.0}
    monkeypatch.setattr(agent, "solve", lambda t: SearchResult(decision, (1.01,)*count, 1.01))
    with pytest.raises(ValueError, match="outside"):
        agent.label(turn, "game")
