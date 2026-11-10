"""Run a bounded, frozen evaluation and always produce a return archive."""
import argparse
import json
import math
import os
from pathlib import Path
import random
import signal
import statistics
import subprocess
import sys
import time
import traceback
import zipfile

from settings import SOURCE, CHECKPOINT, config, digest

HERE = Path(__file__).resolve().parent


def stop_tree(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=30)


def command(args, repo, log, timeout):
    env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    env['PYTHONPATH'] = os.pathsep.join([str(repo), str(repo / 'pair_b/src'), env.get('PYTHONPATH', '')])
    with log.open('w', encoding='utf-8') as stream:
        process = subprocess.Popen(args, cwd=repo, env=env, stdout=stream, stderr=subprocess.STDOUT,
            **({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt'
               else {'start_new_session': True}))
        try:
            return dict(returncode=process.wait(timeout=timeout), timed_out=False)
        except subprocess.TimeoutExpired:
            stop_tree(process)
            return dict(returncode=None, timed_out=True)
        except BaseException:
            stop_tree(process)
            raise


def inspect_pair(folder, seed, *, opening=False, expected=None):
    problems = []
    path = folder / 'games.jsonl'
    rows = []
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError('record is not an object')
                rows.append(row)
            except ValueError:
                problems.append('corrupt/partial game record retained in archive')
    if len(rows) != 2:
        problems.append('expected two attempted game records')
    if len(rows) == 2 and [r.get('player_a_color') for r in rows] != ['white', 'black']:
        problems.append('colour schedule differs')
    if any(r.get('seed') != seed for r in rows):
        problems.append('seed differs')
    counts = dict(terminal=0, capped=0, failed=0, missing=max(0, 2-len(rows)))
    scores = []
    for row in rows:
        if row.get('status') != 'completed':
            counts['failed'] += 1
            problems.append('runner recorded a failed attempt')
            continue
        capped = row.get('stopped_at_ply_limit') or row.get('termination') == 'ply_limit'
        if capped:
            counts['capped'] += 1
        else:
            counts['terminal'] += 1
            winner = row.get('winner')
            if winner not in ('white', 'black', 'draw'):
                problems.append('terminal record lacks a valid outcome')
            else:
                scores.append(0.5 if winner == 'draw' else float(winner == row['player_a_color']))
        if opening and len(row.get('plies', [])) != 4:
            problems.append('opening attempt did not contain four legal actions')
        for ply in row.get('plies', []):
            diagnostics = ply.get('diagnostics', {})
            # This fixed-search implementation records normal solver rounds and
            # evaluator work. Missing diagnostics are unknown, not successful zeros.
            if diagnostics.get('solver_rounds') != 16 or diagnostics.get('fallback', 0) != 0:
                problems.append('incomplete solve/fallback or missing round diagnostics')
            if diagnostics.get('over_budget') != 0 or ply.get('over_budget') is True:
                problems.append('agent exceeded its search allowance or timing is missing')
            calls = diagnostics.get('evaluator_calls')
            if not isinstance(calls,(int,float)) or not math.isfinite(calls) or calls < 0:
                problems.append('missing/invalid evaluator-work diagnostics')
            elif calls == 0 and not (diagnostics.get('frontier_leaves') == 0 and diagnostics.get('terminal_leaves',0) > 0):
                problems.append('zero evaluator work without a rule-decided tree')
    if not opening and counts['capped']:
        problems.append('capped attempts are unscored')
    if opening and counts['capped'] != 2:
        problems.append('opening stage expected two capped, unscored attempts')
    if expected is not None:
        try:
            provenance = json.loads((folder / 'provenance.json').read_text(encoding='utf-8'))
            hashes = provenance['sha256']
            assert provenance['git_commit'] == expected['source']
            assert provenance['git_status'] == []
            assert hashes['config_raw'] == expected['config_sha256']
            assert digest(folder / 'evaluate_config.ini') == expected['config_sha256']
            assert hashes['player_a_checkpoint'] == expected['checkpoint_sha256']
            assert hashes['player_b_checkpoint'] is None
            assert hashes['player_a_stockfish'] == hashes['player_b_stockfish'] == expected['stockfish_sha256']
            assert provenance['player_devices']['a']['device'] == expected['device']
            assert all(provenance['stockfish'][side]['name'] == 'Stockfish 19' for side in ('a','b'))
        except (OSError, ValueError, KeyError, TypeError, AssertionError):
            problems.append('missing or mismatched source/config/model/engine/device provenance')
    return dict(counts=counts, problems=sorted(set(problems)),
                paired_score=statistics.mean(scores) if len(scores) == 2 and not problems else None)


def analysis(entries, planned_pairs):
    formal = [r for r in entries if r['stage'] == 'batch']
    scores = [r['inspection']['paired_score'] for r in formal
              if r.get('inspection', {}).get('paired_score') is not None]
    totals = {key: sum(r.get('inspection', {}).get('counts', {'missing': 2}).get(key, 0) for r in formal)
              for key in ('terminal', 'capped', 'failed', 'missing')}
    result = dict(planned_pairs=planned_pairs, launched_pairs=len(formal), complete_clean_pairs=len(scores),
        excluded_launched_pairs=len(formal)-len(scores),
        hard_timeout_pairs=sum(bool(r.get('launch',{}).get('timed_out')) for r in formal),
        unplayed_pairs=planned_pairs-len(formal), attempt_counts=totals,
        score_on_complete_clean_pairs=statistics.mean(scores) if scores else None,
        paired_bootstrap_ci95=None, bootstrap_unit='whole seed/colour pair',
        clean_pair_scores_by_seed=[dict(seed=r['seed'],score=r['inspection']['paired_score'])
            for r in formal if r.get('inspection',{}).get('paired_score') is not None],
        interpretation=('All planned pairs completed cleanly; this describes the frozen seed set, not optimal play or equivalence.'
            if len(scores)==planned_pairs else 'Conditional on clean completion. Excluded/unplayed pairs prevent a claim over all planned seeds. No equivalence claim.'))
    reasons = {}
    for row in formal:
        for reason in row.get('inspection',{}).get('problems',['no complete inspection']):
            reasons[reason] = reasons.get(reason,0)+1
    result['excluded_pair_reasons'] = reasons
    if len(scores) >= 20:
        rng = random.Random(20261109)
        draws = sorted(statistics.mean(rng.choices(scores, k=len(scores))) for _ in range(20000))
        result['paired_bootstrap_ci95'] = [draws[499], draws[19499]]
    result['clean_full_batch'] = len(scores) == planned_pairs
    return result


def finalize(out, manifest):
    manifest['analysis'] = analysis(manifest['runs'], manifest['planned_pairs'])
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n',encoding='utf-8')
    (out / 'analysis.json').write_text(json.dumps(manifest['analysis'], indent=2) + '\n',encoding='utf-8')
    text = ('Status: ' + manifest['status'] + '\nReason: ' + manifest.get('reason', '') + '\n\n'
            + json.dumps(manifest['analysis'], indent=2) + '\n\n'
            'Return this entire archive, including failed/capped attempts and logs.\n'
            'A diagnostic stop completes this handoff; it does not establish playing strength.\n'
            'Do not change code, tracker policy, budgets or checkpoint to force a passing result.\n')
    (out / 'RESULTS.txt').write_text(text,encoding='utf-8')
    archive = out.with_name(out.name + '-return.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in sorted(out.rglob('*')):
            if path.is_file():
                z.write(path, path.relative_to(out))
    print(text, flush=True)
    print('RETURN THIS FILE:', archive, flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--stockfish', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--device', default='auto')
    p.add_argument('--hours', type=float, default=4)
    p.add_argument('--pairs', type=int, default=50)
    p.add_argument('--pair-timeout-minutes', type=float, default=20)
    a = p.parse_args()
    if not math.isfinite(a.hours) or not math.isfinite(a.pair_timeout_minutes) or a.hours <= 0 or a.pair_timeout_minutes <= 0 or not 20 <= a.pairs <= 100:
        p.error('positive finite time limits and 20..100 pairs are required')
    repo, engine, out = a.repo.resolve(), a.stockfish.resolve(), a.out.resolve()
    if out == repo or repo in out.parents or out.exists() or out.with_name(out.name+'-return.zip').exists():
        p.error('Use a fresh output folder outside the repository; existing results are never overwritten')
    out.mkdir(parents=True)
    deadline = time.monotonic() + a.hours * 3600
    manifest = dict(source=SOURCE, checkpoint_sha256=CHECKPOINT, runs=[], planned_pairs=a.pairs,
        planned_batch_seeds=list(range(1001, 1001+a.pairs)), status='setup',
        hours_limit=a.hours, pair_timeout_minutes=a.pair_timeout_minutes,
        stop_rules='opening gate, then two terminal readiness pairs, then fixed batch; stop at wall-time limit, hard timeout, or three consecutive invalid batch pairs; never stop on win rate')
    try:
        head = subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True,stderr=subprocess.STDOUT).strip()
        status = subprocess.check_output(['git','-C',str(repo),'status','--porcelain=v1','--untracked-files=all'],text=True,stderr=subprocess.STDOUT)
        if head != SOURCE or status.strip():
            raise RuntimeError('Use a clean checkout at '+SOURCE+'; do not discard existing work')
        checkpoint = repo / 'pair_b/checkpoints/net1-v2/best.pt'
        if digest(checkpoint) != CHECKPOINT:
            raise RuntimeError('Existing Network 1 checkpoint hash differs')
        manifest['stockfish_sha256'] = digest(engine)
        preflight_result = out / 'preflight.json'
        launch = command([sys.executable,str(HERE/'preflight.py'),'--repo',str(repo),
            '--stockfish',str(engine),'--device',a.device,'--result',str(preflight_result)],
            repo,out/'preflight.log',min(180, max(1,deadline-time.monotonic())))
        if launch['returncode'] != 0 or launch['timed_out']:
            raise RuntimeError('Model/engine/device preflight failed; see preflight.log')
        device = json.loads(preflight_result.read_text(encoding='utf-8'))['device']
        manifest['device'] = device
        schedule = [('opening',17,4),('readiness',17,200),('readiness',18,200)]
        schedule += [('batch',seed,200) for seed in manifest['planned_batch_seeds']]
        consecutive_bad = 0
        for index,(stage,seed,plies) in enumerate(schedule):
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                manifest.update(status='incomplete',reason='predeclared wall-time cutoff reached')
                break
            label = f'{index:03d}-{stage}-seed{seed}'
            folder = out / label
            ini = out / (label+'.ini')
            c = config(repo,engine,manifest['stockfish_sha256'],device,folder,plies)
            c['match']['seed'] = str(seed)
            with ini.open('w',encoding='utf-8',newline='\n') as f:
                c.write(f)
            manifest['runs'].append(dict(stage=stage,seed=seed,folder=label,status='started'))
            (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
            print('Running',label,flush=True)
            launch = command([sys.executable,str(repo/'pair_c/run_evaluation.py'),str(ini)],
                repo,out/(label+'.log'),min(remaining,a.pair_timeout_minutes*60))
            inspection = inspect_pair(folder,seed,opening=stage=='opening',
                expected=dict(manifest,config_sha256=digest(ini)))
            row = manifest['runs'][-1]
            row.update(launch=launch,inspection=inspection,status='finished')
            valid = launch['returncode']==0 and not launch['timed_out'] and not inspection['problems']
            row['passed'] = valid
            (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
            if launch['timed_out']:
                manifest.update(status='incomplete',reason=label+' hit the process/time limit; remaining attempts unplayed')
                break
            if stage != 'batch' and not valid:
                manifest.update(status='diagnostic_complete',reason=label+' did not pass; full batch deliberately not launched')
                break
            consecutive_bad = 0 if valid else consecutive_bad+1
            if consecutive_bad >= 3:
                manifest.update(status='incomplete',reason='three consecutive invalid batch pairs; remaining attempts unplayed')
                break
        else:
            manifest.update(status='batch_attempts_complete',reason='all planned batch pairs attempted; inspect exclusions before interpreting')
    except KeyboardInterrupt:
        manifest.update(status='interrupted',reason='operator interrupted; completed outputs preserved')
    except Exception as error:
        manifest.update(status='diagnostic_complete',reason=f'{type(error).__name__}: {error}')
        details = traceback.format_exc()
        captured = getattr(error,'output',None)
        if captured:
            details += '\nCaptured command output:\n' + (captured.decode(errors='replace') if isinstance(captured,bytes) else str(captured))
        (out/'setup-or-run-error.log').write_text(details,encoding='utf-8')
    finally:
        finalize(out,manifest)


if __name__ == '__main__':
    main()
