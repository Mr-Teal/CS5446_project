from dataclasses import asdict
import gzip
import json
import pytest

from pair_a_prep.zs21.model import Referee
from pair_a_prep.zs21.match import summarize
from pair_a_prep.zs21.replay import validate


@pytest.mark.parametrize("after_apply", [False, True])
def test_failed_log_is_counted_as_failure_not_draw(tmp_path, after_apply):
    ref = Referee()
    result = dict(game=0, seed=1, paper_color="white", seconds_per_move=8.,
                  status="failed", plies=int(after_apply), error_type="BudgetError")
    rows = [dict(event="start", **{**result, "status": "running", "plies": 0}),
            dict(event="position", ply=0, fen=ref._state.fen,
                 observations={p: asdict(ref.observe(p)) for p in ("white", "black")})]
    if after_apply:
        actions = ref.observe("white").legal_moves
        rows.append(dict(event="decision", ply=0, player="white", elapsed_seconds=1.,
                         decision=dict(move="e2e4", root_policy={a: float(a == "e2e4") for a in actions},
                                       diagnostics={}),
                         trace=dict(flow_error=0., gap=0., max_fow_depth=1)))
    rows.append(dict(event="finish", **result))
    (tmp_path / "manifest.json").write_text(json.dumps(dict(config=dict(source={}))), encoding="utf-8")
    (tmp_path / "summary.json").write_text(json.dumps(summarize([result])), encoding="utf-8")
    with gzip.open(tmp_path / "game-000.jsonl.gz", "wt", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    report = validate(tmp_path)
    assert report["failed"] == report["failed_logs"] == 1
    assert report["completed"] == 0
    assert report["wdl"]["total"] == dict(win=0, draw=0, loss=0)
    with pytest.raises(AssertionError):
        validate(tmp_path, 1)
