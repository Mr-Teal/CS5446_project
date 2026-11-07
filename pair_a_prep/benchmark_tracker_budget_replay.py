"""Validate finite tracker budgets on complete archived games, without engines.

Stops and records a failed update rather than pruning or injecting the true
position. The referee/true-path audit is external to the factory tracker.
"""

import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from pairb.rules import pick_rules
from .benchmark_belief_tracker import contains_path, memory_usage
from .evaluation_factories import HistoryTrackerFactory
from .evaluation_tracking import TrackingBudgetError
from .rules_adapter import RulesAdapter


def run(args):
    with gzip.open(args.input,"rt",encoding="utf-8") as source:
        events=[json.loads(line) for line in source]
    start=next(e for e in events if e['event']=='start')
    positions=[e for e in events if e['event']=='position']
    actions=[e['decision']['move'] for e in events if e['event']=='decision']
    output=args.output
    output.mkdir(parents=True,exist_ok=False)
    rules=RulesAdapter()
    state=rules.initial_state(positions[0]['fen'])
    settings=dict(public_initial_fen=state.fen,sample_size="3",max_candidates="none",
        tracker_backend="native",tracker_policy="budgeted-exact",tracker_slice_ms=str(args.tracker_ms),
        tracker_total_ms=str(args.tracker_ms),tracker_memory_mb=str(args.memory_mb),tracker_max_resumes="0")
    trackers={p:HistoryTrackerFactory(settings).create_tracker(pick_rules("teal"),state.fen) for p in ('white','black')}
    for p,t in trackers.items(): t.reset(p,start['agent_seeds'][p])
    reference={}
    for line in args.reference.read_text().splitlines():
        row=json.loads(line)
        if row.get('game')==start['game']:
            reference[row['ply'],row['player']]=row
    result={'game':start['game'],'seed':start['seed'],'input_sha256':sha256(args.input.read_bytes()).hexdigest(),
        'source_plies':len(actions),'tracker_ms':args.tracker_ms,'logical_mib':args.memory_mb,
        'tracking_only_combined_ms':args.combined_ms,'updates':0,'status':'failed',
        'max_update_ms':0,'max_combined_ms':0,'true_path_audit':True,'reference_counts_match':True}
    last_ply=0
    try:
        with (output/'updates.jsonl').open('x',encoding='utf-8') as log:
            for ply in range(len(actions)+1):
                last_ply=ply
                mover=rules.current_player(state) if ply else None
                if ply:
                    state=rules.apply_move(state,actions[ply-1])
                assert state.fen==positions[ply]['fen']
                combined=0.0
                for player,policy in trackers.items():
                    obs=rules.observe(state,player)
                    own=actions[ply-1] if mover==player else None
                    policy.total_ms=min(args.tracker_ms,max(0,args.combined_ms-combined))
                    began=perf_counter()
                    error=None
                    try:
                        policy.update(obs,own)
                    except TrackingBudgetError as exc:
                        error=str(exc)
                    elapsed=(perf_counter()-began)*1000
                    combined+=elapsed
                    result['max_update_ms']=max(result['max_update_ms'],elapsed)
                    result['max_combined_ms']=max(result['max_combined_ms'],combined)
                    metadata=policy.last_update
                    row={'ply':ply,'player':player,'wall_ms':elapsed,'combined_ms':combined,'error':error,
                        **memory_usage(),'result':None if metadata is None else
                        {k:getattr(metadata,k) for k in metadata.__dataclass_fields__ if k!='belief'}}
                    log.write(json.dumps(row)+'\n');log.flush()
                    if error: raise TrackingBudgetError(error)
                    assert policy.tracker.support_complete
                    expected=reference[ply,player]
                    assert (policy.tracker.population_size,policy.tracker.state_count)==(
                        expected['history_count'],expected['state_count'])
                    assert contains_path(policy.tracker,tuple(actions[:ply]),state.fen)
                    result['updates']+=1
            ended=rules.terminal(state)
            assert ended is not None
            result.update(status='complete',plies=len(actions),winner=ended.winner,reason=ended.reason)
    except TrackingBudgetError as exc:
        result.update(error=str(exc),failed_ply=last_ply)
    except BaseException as exc:
        result.update(status='error',error=f'{type(exc).__name__}: {exc}',failed_ply=last_ply)
        raise
    finally:
        result.update(memory_usage())
        (output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--tracker-ms',type=float,default=15000)
    parser.add_argument('--combined-ms',type=float,default=16000)
    parser.add_argument('--memory-mb',type=float,default=1024)
    args=parser.parse_args()
    if run(args)['status']!='complete': raise SystemExit(1)


if __name__=='__main__':
    main()
