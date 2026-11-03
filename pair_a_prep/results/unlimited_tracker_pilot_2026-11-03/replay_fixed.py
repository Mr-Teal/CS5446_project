from pathlib import Path
from dataclasses import asdict
from time import perf_counter
import json,hashlib,sys,ctypes as C
from ctypes import wintypes as W
from pair_c.run_evaluation import load_config
from pair_a_prep.evaluation_factories import HistoryTrackerFactory
from pairb.rules import pick_rules
from fow_shared.contracts import Observation
root=Path.cwd();out=root/'pair_a_prep/local_runs/unlimited-20261103';target,trial=map(int,sys.argv[1:])
config=load_config(out/'prefix.ini');tracker=HistoryTrackerFactory(config['players']['a']).create_tracker(pick_rules('teal'),config['initial_fen']);tracker.reset('black',19)
stream=[json.loads(x) for x in (out/'prefix-private-stream.jsonl').read_text().splitlines()]
stream=[x for x in stream if x['game']==2 and x['player']=='black' and x['observation']['ply']<=target]
for row in stream:
 d=row['observation'];obs=Observation(**{**d,'visible_squares':tuple(d['visible_squares']),'legal_moves':tuple(d['legal_moves'])})
 began=perf_counter();belief=tracker.update(obs,row['own_move']);elapsed=(perf_counter()-began)*1000
result=dict(target_ply=target,trial=trial,scope='fresh process; exact prefix preparation outside target timer',elapsed_ms=elapsed,population_size=belief.population_size,support_complete=tracker.support_complete,status=tracker.last_update.status,returned=len(belief.hypotheses),signature=hashlib.sha256(json.dumps(asdict(belief),sort_keys=True).encode()).hexdigest(),memory_mb=tracker.memory_mb)
assert result['status']=='complete' and result['support_complete']
(out/f'fixed-{target}-{trial}.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
