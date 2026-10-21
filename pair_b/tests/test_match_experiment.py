import copy
import json

import pytest

from pairb import match_experiment as m
from pairb.rules import teal_available


@pytest.fixture(params=['standin', 'teal'])
def config(request):
    if request.param == 'teal' and not teal_available():
        pytest.skip("Pair A's rules adapter is not in this checkout")
    c = json.loads((m.ROOT/'pair_b/experiments/pilot.json').read_text())
    c.update(rules=request.param, candidates=[{'kind': 'material'}],
             opponent={'kind': 'material'}, seeds=[7],
             max_plies=4, tracker=dict(n_particles=4, n_hypotheses=2, rebuild_tries=20))
    return c


def test_schedule_balances_colors_and_preserves_seed(config):
    config['seeds'] = [7, 8]
    jobs = list(m.schedule(config))
    assert len(jobs) == 4
    for a, b in zip(jobs[::2], jobs[1::2]):
        assert a['pair_id'] == b['pair_id']
        assert a['seed'] == b['seed']
        assert a['initial_fen'] == b['initial_fen']
        assert (a['candidate_color'], b['candidate_color']) == ('white', 'black')


def test_real_match_repeats_moves_and_records_cap(config):
    job = next(m.schedule(config))
    a, b = m.run_game(config, job), m.run_game(config, job)
    assert a['status'] == b['status'] == 'completed'
    assert a['termination'] == 'ply_limit'
    assert a['score'] == .5
    assert [p['move'] for p in a['result']['plies']] == [p['move'] for p in b['result']['plies']]
    assert len(a['tracker_events']['white']) == 5
    assert all('elapsed_ms' in e for e in a['tracker_events']['white'])


def test_failure_is_not_draw_and_incomplete_pair_has_no_score(config, monkeypatch):
    jobs = list(m.schedule(config))
    good = m.run_game(config, jobs[0])
    def broken(*args):
        raise RuntimeError('engine unavailable')
    monkeypatch.setattr(m, 'scorer', broken)
    bad = m.run_game(config, jobs[1])
    assert bad['status'] == 'failed' and 'score' not in bad
    summary = m.summarize([good, bad])['candidates'][0]
    assert summary['failed_games'] == 1
    assert summary['draws'] == 1
    assert summary['complete_pairs'] == 0
    assert summary['paired_score'] is None


def test_score_is_from_candidate_perspective(config, monkeypatch):
    config['openings'] = ['7k/6Q1/8/8/8/8/8/K7 w - - 0 1']
    records = [m.run_game(config, j) for j in m.schedule(config)]
    assert [r['result']['winner'] for r in records] == ['white', 'white']
    assert [r['score'] for r in records] == [1, 0]
    assert m.summarize(records)['candidates'][0]['paired_score'] == .5


def test_fifty_move_draw_is_not_a_ply_limit(config):
    config['openings'] = ['7k/8/8/8/8/8/8/K7 w - - 99 80']
    records = [m.run_game(config, j) for j in m.schedule(config)]
    assert all(r['status'] == 'completed' for r in records)
    assert all(r['termination'] == 'fifty_move' and r['score'] == .5 for r in records)
    assert all(len(r['result']['plies']) == 1 for r in records)
    summary = m.summarize(records)['candidates'][0]
    assert summary['draws'] == 2
    assert summary['ply_limit_draws'] == 0
    assert summary['complete_pairs'] == 1
    assert summary['paired_score'] == .5


def test_output_cannot_overwrite_and_manifest_has_sources(config, tmp_path):
    out = tmp_path/'run'
    m.run(config, out)
    manifest = json.loads((out/'manifest.json').read_text())
    assert 'pair_b/src/pairb/match_experiment.py' in manifest['source_sha256']
    assert all('\\' not in path for path in manifest['source_sha256'])
    assert all(m.digest(m.ROOT/path) == digest
               for path, digest in manifest['source_sha256'].items())
    if config['rules'] == 'teal':
        assert 'pair_a_prep/rules_adapter.py' in manifest['source_sha256']
    assert len((out/'games.jsonl').read_text().splitlines()) == 2
    with pytest.raises(FileExistsError):
        m.run(config, out)


@pytest.mark.parametrize('key,value', [('rules', 'auto'), ('seeds', [7, 7]), ('max_plies', 0)])
def test_invalid_config_rejected(config, key, value):
    config[key] = value
    with pytest.raises(ValueError):
        m.validate(config)
