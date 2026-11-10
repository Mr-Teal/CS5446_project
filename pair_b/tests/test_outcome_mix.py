"""The outcome mix of train_belief_net.py: game results from label_run's progress.jsonl, turned into the
acting player's side and blended into the training targets."""
import json

import numpy as np
import pytest

from pairb.belief_ablation import collapse
from pairb.belief_data import game_outcomes, load_arrays, mixed_targets, record_outcomes
from test_belief_data import BLACK_TO_MOVE, MIDDLEGAME, _write, practice_record


def write_progress(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def progress_row(game_id, winner, error=None, capped=False):
    return {"game_id": game_id, "winner": winner, "stopped_at_ply_limit": capped, "error": error, "records": 1}


@pytest.fixture
def labelled(tmp_path):
    """One White and one Black decision per game: White wins g1, Black wins g2, g3 hits the ply limit,
    g4 is a "draw", g5 died, g6 has no progress row."""
    records = []
    for i, g in enumerate(["g-000001", "g-000002", "g-000003", "g-000004", "g-000005", "g-000006"]):
        records += [practice_record(MIDDLEGAME, 2 * i, g), practice_record(BLACK_TO_MOVE, 2 * i + 1, g)]
    _write(tmp_path / "run", "part-00.jsonl", records)
    write_progress(tmp_path / "run" / "progress.jsonl", [
        progress_row("g-000001", "white"), progress_row("g-000002", "black"),
        progress_row("g-000003", None, capped=True), progress_row("g-000004", "draw"),
        progress_row("g-000005", None, error="BeliefBudgetError: no hypothesis left")])
    arrays = load_arrays(tmp_path / "run", tmp_path / "cache", workers=1)
    return records, arrays, game_outcomes([tmp_path / "run" / "progress.jsonl"])


# Catches: a result taken from White's side for a Black decision, a draw or ply-limit game read as
# unknown, or a dead or unlisted game given a made-up result.
def test_each_record_gets_its_games_result_from_the_acting_players_side(labelled):
    records, arrays, results = labelled
    assert [r.agent_input.observation.player for r in records[:2]] == ["white", "black"]
    got = record_outcomes(arrays, results)
    want = [1, -1, -1, 1, 0, 0, 0, 0, np.nan, np.nan, np.nan, np.nan]
    np.testing.assert_array_equal(got, np.array(want, dtype=np.float32))


# Catches: an input ablation that loses the acting player, so its outcomes would be wrong or missing.
@pytest.mark.parametrize("mode", ["marginals", "alone"])
def test_collapsed_inputs_keep_the_acting_player(labelled, mode):
    _, arrays, results = labelled
    collapsed = collapse(arrays, mode)
    per_record = record_outcomes(arrays, results)
    want = per_record if mode == "marginals" else per_record[arrays["belief"]]
    np.testing.assert_array_equal(record_outcomes(collapsed, results), want)


# Catches: mixing the wrong way round, mixing beliefs that have no result, or a mix that does not
# carry over to the position value.
def test_mixed_targets_blend_search_values_with_the_result(labelled):
    _, arrays, results = labelled
    outcome = record_outcomes(arrays, results)
    lam = 0.3
    got = mixed_targets(arrays, outcome, lam)
    o = outcome[arrays["belief"]]
    has = ~np.isnan(o)
    assert has.any() and (~has).any()
    np.testing.assert_allclose(got[has], (1 - lam) * arrays["y"][has] + lam * o[has], rtol=1e-6)
    np.testing.assert_array_equal(got[~has], arrays["y"][~has])
    root = np.bincount(arrays["belief"], weights=arrays["weight"] * got)
    want = np.where(np.isnan(outcome), arrays["root"], (1 - lam) * arrays["root"] + lam * np.nan_to_num(outcome))
    np.testing.assert_allclose(root, want, atol=1e-5)
    np.testing.assert_array_equal(mixed_targets(arrays, outcome, 0.0), arrays["y"])


# Catches: two progress files that disagree on a game being silently resolved one way.
def test_conflicting_results_for_one_game_are_refused(tmp_path):
    write_progress(tmp_path / "a.jsonl", [progress_row("g-000001", "white")])
    write_progress(tmp_path / "b.jsonl", [progress_row("g-000001", "black")])
    with pytest.raises(ValueError, match="g-000001"):
        game_outcomes([tmp_path / "a.jsonl", tmp_path / "b.jsonl"])


def metrics(out):
    return [{k: row[k] for k in ("train_mse", "val")} for row in map(json.loads, (out / "metrics.jsonl").read_text().splitlines())]


# Catches: the new code path changing training when the mix is 0 (a progress.jsonl in the folder must not
# matter), the mix not reaching the training loss, or a summary that does not say what was mixed.
def test_mix_zero_trains_as_before_and_a_mix_changes_the_training_loss(tmp_path):
    pytest.importorskip("torch")
    from test_train_belief_net import game_ids, tiny_dataset, train
    records = tiny_dataset(tmp_path / "d6")
    assert train(tmp_path / "d6", tmp_path / "plain", "--seed", "3").returncode == 0
    winners = ["white", "black", None]
    write_progress(tmp_path / "d6" / "progress.jsonl",
                   [progress_row(g, winners[i % 3]) for i, g in enumerate(game_ids()[:-1])])  # the last game unlisted
    result = train(tmp_path / "d6", tmp_path / "zero", "--seed", "3")
    assert result.returncode == 0, result.stderr[-500:]
    assert metrics(tmp_path / "zero") == metrics(tmp_path / "plain")
    result = train(tmp_path / "d6", tmp_path / "mixed", "--seed", "3", "--outcome-mix", "0.5")
    assert result.returncode == 0, result.stderr[-500:]
    plain, mixed = metrics(tmp_path / "plain"), metrics(tmp_path / "mixed")
    assert mixed[0]["train_mse"] != plain[0]["train_mse"]
    summary = json.loads((tmp_path / "mixed" / "summary.json").read_text())
    unlisted = sum(r.game_id == game_ids()[-1] for r in records)
    assert unlisted > 0
    assert summary["outcome_mix"] == 0.5
    assert summary["outcomes"] == {"records_with_outcome": len(records) - unlisted, "records_without": unlisted,
                                   "files": [str(tmp_path / "d6" / "progress.jsonl")]}
    assert json.loads((tmp_path / "plain" / "summary.json").read_text())["outcomes"]["files"] == []
