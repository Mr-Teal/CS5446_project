import json
import os
from pathlib import Path
import subprocess
import shutil
import sys

import chess
import numpy as np
import pytest

from pairb.data import split_of
from pairb.linear import LinearCorrection
from pairb.linear_workflow import evaluate, load_dataset, mask_split, train

ROOT=Path(__file__).resolve().parents[2]


def dataset(path):
    path.mkdir()
    records=[]
    parent=chess.Board()
    for i in range(60):
        for move in ['e2e4','d2d4']:
            b=parent.copy();b.push_uci(move)
            records.append(dict(game_id=f'fixture-{i}',fen=b.fen(),parent_fen=parent.fen(),
                                rule=None,d1={'v':0.1},d11={'v':0.15 if move=='e2e4' else -0.1}))
    (path/'part-00.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    return records


def test_train_isolates_whole_games_and_test_targets(tmp_path):
    folder=tmp_path/'data';records=dataset(folder)
    out=tmp_path/'run';train(folder,out,[0.01,0.1])
    first=LinearCorrection.load(out/'best.npz')
    splits=json.loads((out/'splits.json').read_text())
    assert not set(splits['train']) & set(splits['val'])
    assert all(split_of(g)=='train' for g in splits['train'])
    assert all(split_of(g)=='val' for g in splits['val'])
    assert splits['test_held_out_games']>0
    for row in records:
        if split_of(row['game_id'])=='test': row['d11']['v']=-0.95
    (folder/'part-00.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    train(folder,tmp_path/'second',[0.01,0.1])
    second=LinearCorrection.load(tmp_path/'second'/'best.npz')
    assert first.alpha==second.alpha
    assert np.array_equal(first.coef,second.coef)
    assert first.intercept==second.intercept
    assert first.metadata['source']['sha256']!=second.metadata['source']['sha256']
    with pytest.raises(FileExistsError): train(folder,out,[0.01])


def test_seen_game_guards_empty_split_and_regret(tmp_path):
    folder=tmp_path/'data';dataset(folder)
    train(folder,tmp_path/'run',[0.01])
    model=LinearCorrection.load(tmp_path/'run'/'best.npz')
    arrays,source=load_dataset(folder)
    report=evaluate(model,arrays,source,'val',n_boot=10)
    assert report['selection_game_overlap']>0
    assert not report['independent_games']
    assert report['linear']['choice']['regret']==pytest.approx(0)
    with pytest.raises(ValueError,match='overlap'): evaluate(model,arrays,source,'train')
    diagnostic=evaluate(model,arrays,source,'train',allow_seen_games=True,n_boot=10)
    assert diagnostic['fitting_game_overlap']>0
    with pytest.raises(ValueError,match='positive'): evaluate(model,arrays,source,'val',n_boot=0)
    with pytest.raises(ValueError,match='no non-rule rows'):
        mask_split({k:v[:0] for k,v in arrays.items()},'val')
    changed={**source,'sha256':'different'}
    with pytest.raises(ValueError,match='overlap'): evaluate(model,arrays,changed,'val')


def test_blank_game_id_rejected(tmp_path):
    folder=tmp_path/'data';records=dataset(folder);records[0]['game_id']=' '
    (folder/'part-00.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    with pytest.raises(ValueError,match='nonblank'): load_dataset(folder)


def test_cli_without_torch_and_final_gate(tmp_path):
    folder=tmp_path/'data';dataset(folder)
    # A fresh process fails if the baseline attempts any direct or transitive torch import.
    blocker=tmp_path/'blocker';blocker.mkdir()
    (blocker/'sitecustomize.py').write_text('''
import sys
class BlockTorch:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'torch' or fullname.startswith('torch.'):
            raise RuntimeError('baseline imported torch')
sys.meta_path.insert(0,BlockTorch())
''')
    env={**os.environ,'PYTHONPATH':os.pathsep.join([str(blocker),str(ROOT),str(ROOT/'pair_b'/'src')])}
    def run(script,*args):
        return subprocess.run([sys.executable,str(ROOT/'pair_b'/'scripts'/script),*map(str,args)],
                              env=env,text=True,capture_output=True)
    trained=run('train_linear.py','--data',folder,'--out',tmp_path/'run','--alphas',0.01)
    assert trained.returncode==0,trained.stderr
    if shutil.which('stockfish'):
        timing=tmp_path/'timing.json'
        benchmark=run('benchmark_linear.py','--run',tmp_path/'run','--data',folder,
                      '--limit',1,'--repeats',1,'--out',timing)
        assert benchmark.returncode==0,benchmark.stderr
        timed=json.loads(timing.read_text())
        assert set(timed['evaluators'])=={'material','d1','linear'}
        assert timed['engine_binary_sha256']
        assert all(v['calls']==1 and v['median_ms']>=0 for v in timed['evaluators'].values())
    result=tmp_path/'eval.json'
    denied=run('eval_linear.py','--run',tmp_path/'run','--data',folder,'--split','test','--out',result)
    assert denied.returncode!=0 and '--final' in denied.stderr
    assert not result.exists()
    evaluated=run('eval_linear.py','--run',tmp_path/'run','--data',folder,'--split','test','--final',
                  '--out',result,'--n-boot',10)
    assert evaluated.returncode==0,evaluated.stderr
    assert json.loads(result.read_text())['independent_games']


def test_missing_split_evidence_does_not_claim_independence(tmp_path):
    folder=tmp_path/'data';dataset(folder)
    arrays,source=load_dataset(folder)
    from pairb.linear import FEATURES
    model=LinearCorrection(np.zeros(FEATURES),0,1)
    report=evaluate(model,arrays,source,'val',n_boot=10)
    assert report['independent_games'] is None
    assert not report['split_evidence_available']
