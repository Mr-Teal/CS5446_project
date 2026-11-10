"""Run a bounded, frozen evaluation and always produce a return archive."""
import argparse
import json
import math
import os
from pathlib import Path
import random
import signal
import shutil
import statistics
import subprocess
import sys
import time
import traceback
import zipfile

from settings import SOURCE, CHECKPOINT, config, digest

ENGINE_SHA256 = '45bc8e4969147db9c2eb533810637994619bff0eacc81ccfd9854394901bcbd0'
LOCAL_CONFIGS = {
    'pair_c/configs/network1-bounded-readiness.ini',
    'pair_c/configs/network1-bounded-readiness-seed18.ini',
}

def source_state(repo):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True, stderr=subprocess.STDOUT)
    if git('rev-parse', 'HEAD').strip() != SOURCE:
        raise RuntimeError('Use pinned PR76 source ' + SOURCE)
    changed = set(git('diff', 'HEAD', '--name-only').splitlines())
    untracked = set(git('ls-files', '--others', '--exclude-standard').splitlines())
    if (changed | untracked) - LOCAL_CONFIGS:
        raise RuntimeError('Unexpected checkout changes: ' + str(sorted((changed | untracked) - LOCAL_CONFIGS)))
    return dict(status=git('status', '--porcelain=v1', '--untracked-files=all').splitlines(),
                local_config_hashes={name: digest(repo / name) for name in sorted(changed | untracked)})

def native_identity(repo):
    folder = repo / 'pair_a_prep/_belief_build'
    record = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    binary = folder / record['library']
    if binary.parent.resolve() != folder.resolve() or digest(binary) != record['dll_sha256']:
        raise RuntimeError('Native library identity mismatch')
    return record


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


def _inspect_pair(folder, seed, *, opening=False, expected=None):
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
            # Record actual anytime depth/work; require a complete solve, no fallback.
            if diagnostics.get('solver_rounds') != 16 or diagnostics.get('fallback') != 0:
                problems.append('incomplete solve/fallback or missing round diagnostics')
            if diagnostics.get('over_budget') != 0 or ply.get('over_budget') is True:
                problems.append('agent exceeded its search allowance or timing is missing')
            if diagnostics.get('search_depth') not in (1, 2):
                problems.append('missing/invalid anytime depth')
            calls = diagnostics.get('evaluator_calls')
            if not isinstance(calls,(int,float)) or not math.isfinite(calls) or calls < 0:
                problems.append('missing/invalid evaluator-work diagnostics')
            elif calls == 0 and not (diagnostics.get('frontier_leaves') == 0 and diagnostics.get('terminal_leaves',0) > 0):
                problems.append('zero evaluator work without a rule-decided tree')
    tracking = []
    try:
        tracking = [json.loads(line) for line in (folder / 'tracker_updates.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
        if any(not isinstance(r, dict) for r in tracking):
            problems.append('invalid tracker record type')
            tracking = [r for r in tracking if isinstance(r, dict)]
        if not tracking or any(r.get('outcome') != 'returned' or r.get('error') or
                r.get('policy') != 'bounded-history-replay-v1' or
                r.get('expansion_complete') is not True or r.get('retained_count', 8193) > 8192
                for r in tracking):
            problems.append('failed/missing/invalid bounded tracker updates')
        for game in rows:
            for player in ('white', 'black'):
                if not any(r.get('game') == game.get('game') and r.get('player') == player for r in tracking):
                    problems.append('missing private tracker stream')
    except (OSError, ValueError, TypeError):
        problems.append('missing/corrupt tracker records')
        tracking = []
    if not opening and counts['capped']:
        problems.append('capped attempts are unscored')
    if opening and counts['capped'] != 2:
        problems.append('opening stage expected two capped, unscored attempts')
    if expected is not None:
        try:
            provenance = json.loads((folder / 'provenance.json').read_text(encoding='utf-8'))
            hashes = provenance['sha256']
            checks = [
                provenance['git_commit'] == expected['source'],
                provenance['git_status'] == expected['source_state']['status'],
                hashes['config_raw'] == expected['config_sha256'],
                digest(folder / 'evaluate_config.ini') == expected['config_sha256'],
                hashes['player_a_checkpoint'] == expected['checkpoint_sha256'],
                hashes['player_b_checkpoint'] is None,
                hashes['player_a_stockfish'] == hashes['player_b_stockfish'] == expected['stockfish_sha256'],
                provenance['player_devices']['a']['device'] == expected['device'],
                all(provenance['stockfish'][side]['name'] == 'Stockfish 19' for side in ('a','b')),
            ]
            if not all(checks):
                raise ValueError('Provenance mismatch')
        except (OSError, ValueError, KeyError, TypeError, AssertionError):
            problems.append('missing or mismatched source/config/model/engine/device provenance')
    moves = [m for r in rows for m in r.get('plies', [])]
    diagnostics = [m.get('diagnostics', {}) for m in moves]
    metrics = dict(moves=len(moves), fallback_moves=sum(bool(d.get('fallback')) for d in diagnostics),
        search_overruns=sum(bool(m.get('over_budget')) or bool(m.get('diagnostics', {}).get('over_budget')) for m in moves),
        search_ms=sum(m.get('elapsed_ms', 0) for m in moves),
        depth_counts={str(depth): sum(d.get('search_depth') == depth for d in diagnostics) for depth in (1, 2)},
        evaluator_calls=sum(d.get('evaluator_calls', 0) for d in diagnostics),
        tracker_updates=len(tracking), tracker_ms=sum(r.get('elapsed_ms', 0) for r in tracking),
        max_tracker_ms=max((r.get('elapsed_ms', 0) for r in tracking), default=None),
        max_logical_bytes=max((r.get('accounted_bytes', 0) or 0 for r in tracking), default=None),
        private_stream_counters=[dict(game=game, player=player,
            prunes=max((r.get('prunes', 0) for r in tracking if r.get('game') == game and r.get('player') == player), default=0),
            rebuilds=max((r.get('rebuilds', 0) for r in tracking if r.get('game') == game and r.get('player') == player), default=0))
            for game in (1, 2) for player in ('white', 'black')],
        scope='Search timing is from recorded moves; failed games may omit partial search records. Tracker timing includes failed updates. Logical bytes are not RSS.')
    return dict(counts=counts, metrics=metrics, problems=sorted(set(problems)),
                paired_score=statistics.mean(scores) if len(scores) == 2 and not problems else None)


def inspect_pair(folder, seed, *, opening=False, expected=None):
    # A damaged/interrupted worker record must not prevent diagnostic archiving.
    try:
        return _inspect_pair(folder, seed, opening=opening, expected=expected)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as error:
        return dict(counts=dict(terminal=0, capped=0, failed=0, missing=2),
                    problems=[f'unreadable records; outcome slots unknown: {type(error).__name__}: {error}'],
                    metrics={}, paired_score=None)


def analysis(entries, planned_pairs):
    formal = [r for r in entries if r['stage'] == 'batch']
    scores = [r['inspection']['paired_score'] for r in formal
              if r.get('inspection', {}).get('paired_score') is not None]
    totals = {key: sum(r.get('inspection', {}).get('counts', {'missing': 2}).get(key, 0) for r in formal)
              for key in ('terminal', 'capped', 'failed', 'missing')}
    result = dict(planned_pairs=planned_pairs, launched_pairs=len(formal), complete_clean_pairs=len(scores),
        excluded_launched_pairs=len(formal)-len(scores),
        hard_timeout_pairs=sum(bool(r.get('launch',{}).get('timed_out')) for r in formal),
        unplayed_pairs=planned_pairs-len(formal), planned_games=planned_pairs*2,
        recorded_attempts=sum(totals[k] for k in ('terminal','capped','failed')),
        unknown_attempt_slots=totals['missing'], unplayed_games=(planned_pairs-len(formal))*2, attempt_counts=totals,
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
    for row in manifest['runs']:
        if 'inspection' not in row:
            row['inspection'] = inspect_pair(out / row['folder'], row['seed'], opening=row['stage']=='opening')
            row['inspection']['paired_score'] = None
            row['inspection']['problems'].append('interrupted/uninspected worker; pair excluded')
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
    p.add_argument('--device', choices=['cuda:0'], default='cuda:0')
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
        frozen_state = source_state(repo)
        manifest['source_state'] = frozen_state
        manifest['native_build'] = native_identity(repo)
        (out / 'native-build.json').write_text(json.dumps(manifest['native_build'], indent=2), encoding='utf-8')
        for name in frozen_state['local_config_hashes']:
            destination = out / 'local-configs' / Path(name).name
            destination.parent.mkdir(exist_ok=True)
            shutil.copy2(repo / name, destination)
        controller = out / 'controller'
        controller.mkdir()
        for file in HERE.iterdir():
            if file.is_file() and file.suffix in ('.py', '.txt'):
                shutil.copy2(file, controller / file.name)
        checkpoint = repo / 'pair_b/checkpoints/net1-v2/best.pt'
        if digest(checkpoint) != CHECKPOINT:
            raise RuntimeError('Existing Network 1 checkpoint hash differs')
        manifest['stockfish_sha256'] = digest(engine)
        if manifest['stockfish_sha256'] != ENGINE_SHA256:
            raise RuntimeError('Use the validated Stockfish 19 Windows universal binary')
        preflight_result = out / 'preflight.json'
        launch = command([sys.executable,str(HERE/'preflight.py'),'--repo',str(repo),
            '--stockfish',str(engine),'--device',a.device,'--result',str(preflight_result)],
            repo,out/'preflight.log',min(180, max(1,deadline-time.monotonic())))
        if launch['returncode'] != 0 or launch['timed_out']:
            raise RuntimeError('Model/engine/device preflight failed; see preflight.log')
        device = json.loads(preflight_result.read_text(encoding='utf-8'))['device']
        if device != 'cuda:0':
            raise RuntimeError('Preflight did not select required GPU')
        manifest['device'] = device
        schedule = [('opening',17,4),('readiness',17,200),('readiness',18,200)]
        schedule += [('batch',seed,200) for seed in manifest['planned_batch_seeds']]
        consecutive_bad = 0
        for index,(stage,seed,plies) in enumerate(schedule):
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                manifest.update(status='incomplete',reason='predeclared wall-time cutoff reached')
                break
            if source_state(repo) != frozen_state or native_identity(repo) != manifest['native_build']:
                raise RuntimeError('Source/config/native identity changed during experiment')
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
            if launch['timed_out']:
                inspection['problems'].append('worker hit process/time limit')
            elif launch['returncode'] != 0:
                inspection['problems'].append('worker exited unsuccessfully')
            identity_changed = source_state(repo) != frozen_state or native_identity(repo) != manifest['native_build']
            if identity_changed:
                inspection['problems'].append('source/config/native identity changed during pair')
            if launch['returncode'] != 0 or launch['timed_out'] or inspection['problems']:
                inspection['paired_score'] = None
            row = manifest['runs'][-1]
            row.update(launch=launch,inspection=inspection,status='finished')
            valid = launch['returncode']==0 and not launch['timed_out'] and not inspection['problems']
            row['passed'] = valid
            (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
            if identity_changed:
                raise RuntimeError('Source/config/native identity changed during pair; stopping experiment')
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
