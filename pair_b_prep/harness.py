"""Local integration checks; no network access, engine dependency, or training."""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib
import json
import math
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent

def suite():
    return json.loads((ROOT / 'fixtures.json').read_text())['positions']

def score(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        # Accept scalar numeric types such as numpy.float32 via float conversion.
        if isinstance(value, (str, bool)):
            raise AssertionError(f'non-numeric score: {value!r}')
    value = float(value)
    if not math.isfinite(value) or not -1 <= value <= 1:
        raise AssertionError(f'score outside finite [-1,1]: {value}')
    return value

def close(a, b, tol):
    if abs(score(a) - score(b)) > tol:
        raise AssertionError(f'{a} != {b} (tolerance {tol})')

def vector(values, n):
    values = list(values)
    if len(values) != n:
        raise AssertionError(f'expected {n} values, got {len(values)}')
    return [score(v) for v in values]

def children(result, case, tol):
    if not hasattr(result, 'keys'):
        raise AssertionError('children must be a move-to-value mapping')
    if 'moves' in case and set(result) != set(case['moves']):
        raise AssertionError(f"wrong move set: expected {case['moves']}, got {list(result)}")
    if not set(case.get('required_moves', ())).issubset(result):
        raise AssertionError('required fog move missing')
    for value in result.values():
        score(value)
    for move, value in case.get('child_values', {}).items():
        close(result[move], value, tol)

def belief_specs():
    # Constructed contract probes, not sampled game histories or training records.
    a = '7k/8/8/8/8/8/8/K7 w - - 10 80'
    b = '7k/8/8/8/8/8/8/K7 w - - 30 80'
    c = '7k/8/8/8/8/8/8/K7 b - - 20 80'
    return [
        dict(player='white', fens=[a, b], weights=[0.25, 0.75],
             legal_moves=['a1a2','a1b1','a1b2']),
        dict(player='black', fens=[c], weights=[1.0],
             legal_moves=['h8g7','h8g8','h8h7'])]

def make_turn(spec):
    # Local structural stand-in. Real adapters must construct fow_shared objects.
    obs = NS(player=spec['player'], ply=158, visible_squares=(), visible_pieces={},
             legal_moves=tuple(spec['legal_moves']), halfmove_clock=None)
    hypotheses = tuple(NS(fen=f, weight=w) for f,w in zip(spec['fens'],spec['weights']))
    return NS(observation=obs, belief=NS(hypotheses=hypotheses), time_budget_ms=1000)

def answer(result, spec):
    vals = vector(result.hypothesis_values, len(spec['fens']))
    policy = result.policy
    if policy is not None:
        if set(policy) != set(spec['legal_moves']):
            raise AssertionError('policy must cover exactly legal moves')
        probs = [score(v) for v in policy.values()]
        if any(p < 0 for p in probs) or abs(sum(probs)-1) > 1e-6:
            raise AssertionError('policy probabilities must be nonnegative and sum to 1')
    return vals

class DummyEvaluator:
    """Fixture-only plumbing demonstration. It cannot play chess or prove correctness."""
    name = 'fixture-dummy-NOT-A-CHESS-EVALUATOR'
    def evaluate_children(self, fen):
        c = next(c for c in suite() if c['fen'] == fen)
        return {m: c.get('child_values', {}).get(m, 0.0)
                for m in c.get('moves', c.get('required_moves', []))}
    def evaluate_boards(self, fens, player):
        out = []
        for fen in fens:
            case = next((c for c in suite() if c['fen'] == fen), {})
            white = case.get('white_value', int(fen.split()[4])/1000)
            out.append(white if player == 'white' else -white)
        return out
    def evaluate_beliefs(self, turns):
        return [NS(hypothesis_values=tuple(self.evaluate_boards(
            [h.fen for h in t.belief.hypotheses], t.observation.player)), policy=None) for t in turns]

def build_dummy(config):
    return NS(evaluator=DummyEvaluator(), make_turn=make_turn,
              metadata={'demo_only': True, 'config':config})

def run_checks(bundle, tol=1e-6):
    ev = bundle.evaluator
    results = []
    def check(name, fn):
        try:
            fn()
            results.append(dict(name=name,status='pass'))
        except Exception as exc:
            results.append(dict(name=name,status='fail',detail=f'{type(exc).__name__}: {exc}'))
    for c in suite():
        check('children/'+c['id'], lambda c=c: children(ev.evaluate_children(c['fen']),c,tol))
        def board_case(c=c):
            w = vector(ev.evaluate_boards([c['fen']], 'white'),1)[0]
            b = vector(ev.evaluate_boards([c['fen']], 'black'),1)[0]
            close(w,-b,tol)
            if 'white_value' in c:
                close(w,c['white_value'],tol)
        check('board_perspective_and_rules/'+c['id'],board_case)
    def boards_batch():
        # Append a known win so rule scores cannot accidentally form a palindrome
        # that would conceal an implementation reversing a batch.
        fens = [c['fen'] for c in suite()] + [suite()[2]['fen']]
        for player in ('white','black'):
            single = [vector(ev.evaluate_boards([f],player),1)[0] for f in fens]
            batched = vector(ev.evaluate_boards(fens,player),len(fens))
            reverse = vector(ev.evaluate_boards(fens[::-1],player),len(fens))[::-1]
            for a,b,c in zip(single,batched,reverse):
                close(a,b,tol); close(a,c,tol)
    check('boards/batch_and_order',boards_batch)
    def beliefs_batch():
        specs = belief_specs()
        turns = [bundle.make_turn(s) for s in specs]
        before = repr(turns)
        out = list(ev.evaluate_beliefs(turns))
        if len(out) != len(specs):
            raise AssertionError('one answer required per belief')
        for spec,turn,result in zip(specs,turns,out):
            vals = answer(result,spec)
            single = list(ev.evaluate_beliefs([turn]))
            if len(single) != 1:
                raise AssertionError('single belief produced wrong output length')
            other = answer(single[0],spec)
            for a,b in zip(vals,other): close(a,b,tol)
            if result.policy is not None and single[0].policy is not None:
                for m in spec['legal_moves']: close(result.policy[m],single[0].policy[m],tol)
        if repr(turns) != before:
            raise AssertionError('evaluator mutated inputs')
        # Reverse hypotheses and corresponding weights: output must follow that order.
        spec = specs[0]
        rev = dict(spec, fens=spec['fens'][::-1], weights=spec['weights'][::-1])
        reverse = list(ev.evaluate_beliefs([bundle.make_turn(rev)]))
        if len(reverse) != 1: raise AssertionError('wrong reversed belief result count')
        revvals = answer(reverse[0],rev)
        for a,b in zip(out[0].hypothesis_values,revvals[::-1]): close(a,b,tol)
    check('beliefs/grouping_order_unknown_clock_and_policy',beliefs_batch)
    results.append(dict(name='encoder/per_hypothesis_clock_and_no_hidden_state',status='manual',
        detail='Inspect real encoder and data flow; passing black-box probes does not prove absence of leakage.'))
    results.append(dict(name='history/repetition',status='manual',
        detail='FEN-only methods cannot represent repetition history. Use shared rule fixtures with full history during integration.'))
    return results

def benchmark(bundle, repeats, warmups, tol):
    ev = bundle.evaluator
    sync = getattr(bundle,'synchronize',lambda:None)
    reset = getattr(bundle,'before_sample',lambda:None)
    rows=[]
    for case in suite():
        for i in range(warmups+repeats):
            reset(); sync()
            start=time.perf_counter_ns()
            values=ev.evaluate_children(case['fen'])
            sync()
            elapsed=(time.perf_counter_ns()-start)/1e6
            children(values,case,tol)
            if i >= warmups:
                rows.append(dict(position_id=case['id'], sample=i-warmups,
                    elapsed_ms=elapsed, child_count=len(values),
                    values={m:float(v) for m,v in values.items()},
                    ranking=sorted(values,key=lambda m:(-values[m],m))))
    return rows

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adapter',default='pair_b_prep.harness:build_dummy',help='module:factory; factory(config) returns a bundle')
    parser.add_argument('--config',type=Path)
    parser.add_argument('--out',type=Path,default=ROOT/'results'/'demo')
    parser.add_argument('--repeats',type=int,default=10)
    parser.add_argument('--warmups',type=int,default=2)
    parser.add_argument('--tolerance',type=float,default=1e-6)
    args=parser.parse_args(argv)
    if args.repeats<1 or args.warmups<0 or not math.isfinite(args.tolerance) or args.tolerance<0:
        parser.error('require repeats >= 1, warmups >= 0, and finite tolerance >= 0')
    config=json.loads(args.config.read_text()) if args.config else {}
    module,factory=args.adapter.split(':',1)
    bundle=getattr(importlib.import_module(module),factory)(config)
    try:
        checks=run_checks(bundle,args.tolerance)
        failed=any(c['status']=='fail' for c in checks)
        samples=[] if failed else benchmark(bundle,args.repeats,args.warmups,args.tolerance)
        metadata=dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),
            evaluator=bundle.evaluator.name,adapter=args.adapter,config=config,
            platform=platform.platform(),python=sys.version,
            fixture_sha256=hashlib.sha256((ROOT/'fixtures.json').read_bytes()).hexdigest(),
            harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            warmups=args.warmups,repeats=args.repeats,tolerance=args.tolerance,
            adapter_metadata=bundle.metadata,
            timing='evaluate_children end-to-end, synchronized; excludes setup and before_sample; repeated positions may be cached')
        args.out.mkdir(parents=True,exist_ok=True)
        (args.out/'report.json').write_text(json.dumps(dict(metadata=metadata,checks=checks),indent=2)+'\n')
        (args.out/'samples.jsonl').write_text(''.join(json.dumps(s)+'\n' for s in samples))
        with (args.out/'summary.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['position_id','samples','child_count','median_ms','min_ms','max_ms'])
            writer.writeheader()
            for c in suite():
                group=[r for r in samples if r['position_id']==c['id']]
                if group:
                    times=[r['elapsed_ms'] for r in group]
                    writer.writerow(dict(position_id=c['id'],samples=len(group),child_count=group[0]['child_count'],
                        median_ms=statistics.median(times),min_ms=min(times),max_ms=max(times)))
        for c in checks: print(c['status'].upper(),c['name'],c.get('detail',''))
        print('Results:',args.out.resolve())
        if bundle.metadata.get('demo_only'): print('DEMO ONLY: no real evaluator or model has been validated.')
        return 1 if failed else 0
    finally:
        getattr(bundle,'close',lambda:None)()

if __name__=='__main__':
    raise SystemExit(main())
