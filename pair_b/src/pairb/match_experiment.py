"""Serial, colour-paired fixed-planner experiments. Run with python -m pairb.match_experiment."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from time import perf_counter

from fow_shared.evaluation import MatchConfig, play_game
from .bot import OnePlyBot
from .rules import GameReferee, pick_rules
from .tracker import ParticleTracker

ROOT = Path(__file__).resolve().parents[3]
KINDS = {'material', 'stockfish-d1', 'stockfish-d11', 'linear', 'net1'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(config):
    required = {'rules', 'seeds', 'openings', 'candidates', 'opponent', 'tracker',
                'max_plies', 'time_budget_ms', 'stockfish_path', 'device'}
    if set(config) != required:
        raise ValueError(f'config keys must be {sorted(required)}')
    if config['rules'] not in ('standin', 'teal'):
        raise ValueError('pin rules explicitly: standin or teal')
    for key in ('seeds', 'openings', 'candidates'):
        if not isinstance(config[key], list) or not config[key]:
            raise ValueError(f'{key} must be a nonempty list')
    if any(type(s) is not int or s < 0 for s in config['seeds']) or len(set(config['seeds'])) != len(config['seeds']):
        raise ValueError('seeds must be distinct nonnegative integers')
    if len(set(config['openings'])) != len(config['openings']):
        raise ValueError('duplicate openings')
    for fen in config['openings']:
        rules = pick_rules(config['rules'])
        if rules.terminal(rules.initial_state(fen)):
            raise ValueError('opening is already terminal')
    for key in ('max_plies', 'time_budget_ms'):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f'{key} must be a positive integer')
    for spec in [*config['candidates'], config['opponent']]:
        if spec.get('kind') not in KINDS or set(spec) != ({'kind', 'checkpoint'} if spec.get('kind') in ('linear', 'net1') else {'kind'}):
            raise ValueError('invalid evaluator specification')
        if 'checkpoint' in spec and not (ROOT / spec['checkpoint']).is_file():
            raise ValueError(f"missing checkpoint: {spec['checkpoint']}")
    if len({json.dumps(s, sort_keys=True) for s in config['candidates']}) != len(config['candidates']):
        raise ValueError('duplicate candidates')
    if set(config['tracker']) != {'n_particles', 'n_hypotheses', 'rebuild_tries'}:
        raise ValueError('pin all tracker settings')
    ParticleTracker(pick_rules(config['rules']), **config['tracker'])


def scorer(spec, config, stack):
    kind = spec['kind']
    if kind == 'material':
        from .material import MaterialEvaluator
        return MaterialEvaluator()
    kwargs = dict(stockfish_path=config['stockfish_path'], new_game_each_call=True)
    if kind.startswith('stockfish-'):
        from .stockfish import StockfishEvaluator
        value = StockfishEvaluator(int(kind.split('-d')[1]), path=config['stockfish_path'], new_game_each_call=True)
    elif kind == 'linear':
        from .linear_evaluator import LinearEvaluator
        value = LinearEvaluator.from_checkpoint(ROOT / spec['checkpoint'], **kwargs)
    else:
        from .network_evaluator import NetworkEvaluator
        value = NetworkEvaluator.from_checkpoint(ROOT / spec['checkpoint'], device=config['device'], **kwargs)
    stack.callback(value.close)
    return value


class RecordedTracker:
    def __init__(self, inner):
        self.inner, self.events = inner, []

    def reset(self, player, seed):
        self.inner.reset(player, seed)

    def update(self, observation, own_move=None):
        start = perf_counter()
        event = {'ply': observation.ply, 'player': observation.player}
        try:
            belief = self.inner.update(observation, own_move)
            event.update(hypotheses=len(belief.hypotheses), rebuilt=self.inner.rebuilt,
                         capped=self.inner.capped, exact=self.inner.exact)
            return belief
        except Exception as error:
            event['error'] = f'{type(error).__name__}: {error}'
            raise
        finally:
            event['elapsed_ms'] = (perf_counter() - start) * 1000
            self.events.append(event)


class RecordedAgent:
    name = 'pairb-one-ply'

    def __init__(self, leaf):
        self.inner, self.events = OnePlyBot(leaf), []

    def reset(self, player, seed):
        self.inner.reset(player, seed)

    def act(self, turn):
        start = perf_counter()
        event = {'ply': turn.observation.ply, 'player': turn.observation.player}
        try:
            decision = self.inner.act(turn)
            event.update(move=decision.move, diagnostics=dict(decision.diagnostics))
            return decision
        except Exception as error:
            event['error'] = f'{type(error).__name__}: {error}'
            raise
        finally:
            event['elapsed_ms'] = (perf_counter() - start) * 1000
            self.events.append(event)


def schedule(config):
    for index, candidate in enumerate(config['candidates']):
        for opening, fen in enumerate(config['openings']):
            for seed in config['seeds']:
                for color in ('white', 'black'):
                    yield {'candidate_index': index, 'candidate': candidate, 'opening_index': opening,
                           'initial_fen': fen, 'seed': seed, 'candidate_color': color,
                           'pair_id': f'c{index}-o{opening}-s{seed}'}


def run_game(config, job):
    record = dict(job, status='failed')
    trackers, agents = {}, {}
    start = perf_counter()
    try:
        rules = pick_rules(config['rules'])
        referee = GameReferee(rules, job['initial_fen'])
        with ExitStack() as stack:
            names = {}
            for color in ('white', 'black'):
                spec = job['candidate'] if color == job['candidate_color'] else config['opponent']
                leaf = scorer(spec, config, stack)
                names[color] = leaf.name
                agents[color] = RecordedAgent(leaf)
                trackers[color] = RecordedTracker(ParticleTracker(rules, initial_fen=job['initial_fen'], **config['tracker']))
            record['evaluator_names'] = names
            match = MatchConfig(config['time_budget_ms'], config['max_plies'], job['seed'], rules.name,
                                'see evaluator_names; one thread, 16 MiB hash, reset each call', 0)
            result = play_game(referee, agents, trackers, match)
            record.update(status='completed', result=asdict(result),
                          termination='ply_limit' if result.stopped_at_ply_limit else referee.result()[1],
                          score=0.5 if result.winner == 'draw' else float(result.winner == job['candidate_color']))
    except Exception as error:
        record.update(status='failed', error=f'{type(error).__name__}: {error}')
        record.pop('score', None)
    finally:
        record['wall_ms'] = (perf_counter() - start) * 1000
        record['agent_events'] = {p: a.events for p, a in agents.items()}
        record['tracker_events'] = {p: t.events for p, t in trackers.items()}
    return record


def summarize(records):
    summaries = []
    for index in sorted({r['candidate_index'] for r in records}):
        rows = [r for r in records if r['candidate_index'] == index]
        completed = [r for r in rows if r['status'] == 'completed']
        pairs = {}
        for r in rows:
            pairs.setdefault(r['pair_id'], []).append(r)
        usable = [rs for rs in pairs.values() if len(rs) == 2 and
                  {r['candidate_color'] for r in rs} == {'white', 'black'} and
                  all(r['status'] == 'completed' for r in rs)]
        scores = [sum(r['score'] for r in rs) / 2 for rs in usable]
        summaries.append(dict(candidate_index=index, candidate=rows[0]['candidate'],
            attempted_games=len(rows), completed_games=len(completed), failed_games=len(rows)-len(completed),
            wins=sum(r['score'] == 1 for r in completed), draws=sum(r['score'] == .5 for r in completed),
            losses=sum(r['score'] == 0 for r in completed),
            ply_limit_draws=sum(r['termination'] == 'ply_limit' for r in completed),
            complete_pairs=len(usable), incomplete_pairs=len(pairs)-len(usable),
            paired_score=sum(scores)/len(scores) if scores else None,
            candidate_act_ms=sum(e['elapsed_ms'] for r in rows for e in r['agent_events'].get(r['candidate_color'], [])),
            candidate_tracker_ms=sum(e['elapsed_ms'] for r in rows for e in r['tracker_events'].get(r['candidate_color'], []))))
    return {'interpretation': 'Exploratory fixed one-ply planner. Time budget is diagnostic, not enforced. '
            'Scores use complete pairs only; failures are not draws. No strength claim or confidence interval from a smoke pilot.',
            'candidates': summaries}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def run(config, out):
    validate(config)
    if config['device'] == 'cpu' and any(s['kind'] == 'net1' for s in [*config['candidates'], config['opponent']]):
        import torch
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    engine = shutil.which(config['stockfish_path'])
    source_files = sorted([*ROOT.glob('fow_shared/*.py'), *ROOT.glob('pair_b/src/pairb/**/*.py'), *ROOT.glob('pair_a_prep/*.py')])
    def git(*args):
        return subprocess.run(['git', '-C', str(ROOT), *args], capture_output=True, text=True).stdout.strip()
    packages = {}
    for name in ('chess', 'numpy', 'torch'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    manifest = dict(config=config, git_head=git('rev-parse', 'HEAD'), git_status=git('status', '--porcelain'),
                    source_sha256={str(p.relative_to(ROOT)): digest(p) for p in source_files},
                    checkpoint_sha256={s['checkpoint']: digest(ROOT/s['checkpoint']) for s in [*config['candidates'], config['opponent']] if 'checkpoint' in s},
                    engine_path=engine, engine_sha256=digest(engine) if engine else None,
                    python=sys.version, platform=platform.platform(), packages=packages,
                    planner='OnePlyBot', engine_reset_each_call=True, torch_cpu_threads=1,
                    opening_information='Every initial FEN is public to both trackers; no private midgame starts.',
                    seed_policy='Same seed for each paired game; shared runner uses seed+color index for agent and tracker.')
    write_json(out/'manifest.json', manifest)
    records = []
    with (out/'games.jsonl').open('x') as stream:
        for job in schedule(config):
            record = run_game(config, job)
            stream.write(json.dumps(record, allow_nan=False) + '\n')
            stream.flush()
            records.append(record)
            write_json(out/'summary.json', summarize(records))
            print(job['pair_id'], job['candidate_color'], record['status'], record.get('termination', record.get('error')), flush=True)
    return records


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    records = run(json.loads(args.config.read_text()), args.out)
    return int(any(r['status'] != 'completed' for r in records))


if __name__ == '__main__':
    raise SystemExit(main())
