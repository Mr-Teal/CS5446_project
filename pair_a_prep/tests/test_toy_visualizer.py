"""The explorer embeds real solver snapshots with stable tree identities."""

import json

import pytest

from pair_a_prep.toy_visualizer import export, make_report


def test_export_contains_offline_report_and_both_knowledge_modes(tmp_path):
    output = tmp_path / "explorer.html"
    report = export(output, rounds=3)
    html = output.read_text(encoding="utf-8")
    assert "__REPORT_DATA__" not in html
    assert '<script src=' not in html and 'https://' not in html
    embedded = html.split('<script id="report" type="application/json">')[1].split('</script>')[0]
    decoded = json.loads(embedded)
    assert len(decoded["scenarios"]) == 6
    cases = {s["name"]: s for s in report["scenarios"]}
    assert cases["KLSS + Resolve"]["knowledge"]["frozen"] == ("outside",)
    assert cases["KLUSS + Resolve"]["knowledge"]["frozen"] == ()
    for scenario in report["scenarios"]:
        assert [f["round"] for f in scenario["frames"]] == [0, 1, 2, 3]
        assert scenario["frames"][-1]["metrics"]["schedule"] == "alternating"
        assert scenario["tree"]["id"] == "root"
    with pytest.raises(FileExistsError):
        export(output, rounds=1)


def test_report_requires_positive_round_count():
    with pytest.raises(ValueError):
        make_report(0)
