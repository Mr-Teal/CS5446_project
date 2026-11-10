"""Optional __main__ smoke check; no model/engine or actual games are launched."""
import json
from pathlib import Path
import tempfile
from settings import config, SOURCE
import run


def main():
    with tempfile.TemporaryDirectory() as name:
        folder = Path(name)
        c = config(folder, folder / 'sf.exe', 'engine', 'cuda:0', folder, 200)
        assert c['player_a']['tracker_policy'] == 'bounded-history'
        assert c['player_b']['tracker_backend'] == 'native'
        assert c['player_a']['search_mode'] == 'anytime'
        assert c['player_a']['device'] == 'cuda:0'
        assert SOURCE == 'aaa000a034ae5275afe981402891596e660312a4'
        rows = [dict(game=i+1, seed=1001, player_a_color=color, status='completed',
                     winner='white', termination='king_capture', plies=[dict(
                         elapsed_ms=1, over_budget=False, diagnostics=dict(
                             solver_rounds=16, fallback=0, over_budget=0,
                             search_depth=1, evaluator_calls=1))])
                for i, color in enumerate(('white', 'black'))]
        (folder / 'games.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        trackers = [dict(game=i, player=color, policy='bounded-history-replay-v1',
                         outcome='returned', expansion_complete=True, retained_count=8192,
                         support_complete=False, elapsed_ms=1)
                    for i in (1, 2) for color in ('white', 'black')]
        (folder / 'tracker_updates.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in trackers))
        result = run.inspect_pair(folder, 1001)
        assert result['problems'] == [], result
        assert result['paired_score'] == 0.5
        rows[1]['status'] = 'failed'
        (folder / 'games.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        assert run.inspect_pair(folder, 1001)['paired_score'] is None
        answer = run.analysis([dict(stage='batch', seed=1001, inspection=result)], 50)
        assert answer['unplayed_pairs'] == 49
        assert answer['recorded_attempts'] == 2
    print('Smoke checks passed; no real games executed.')


if __name__ == '__main__':
    main()
