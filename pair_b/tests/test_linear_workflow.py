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
from pairb.linear_workflow import evaluate, load_dataset, mask_split, network_split_evidence, train

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


def distinct_games(path, first):
    """Games fixture-0 ... fixture-59 (dataset()'s IDs), but each a different game: game i decides
    at the position after opening `first + i` (one of 400 first-move pairs). Two folders with
    different `first` reuse the IDs for other games, as two runs of make_d2.py do."""
    path.mkdir()
    records = []
    for i in range(60):
        parent = chess.Board()
        parent.push(list(parent.legal_moves)[(first + i) % 20])
        parent.push(list(parent.legal_moves)[(first + i) // 20 % 20])
        for j, move in enumerate(list(parent.legal_moves)[:2]):
            child = parent.copy()
            child.push(move)
            records.append(dict(game_id=f"fixture-{i}", fen=child.fen(), parent_fen=parent.fen(), rule=None,
                                d1={"v": 0.1}, d11={"v": 0.15 if j == 0 else -0.1}))
    (path / "part-00.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    return records


def fitted_model(tmp_path):
    distinct_games(tmp_path / "fit", first=0)
    train(tmp_path / "fit", tmp_path / "run", [0.01])
    return LinearCorrection.load(tmp_path / "run" / "best.npz")


# Catches: fresh games refused, or reported as not independent, because another dataset reuses
# the game IDs (d2-check's g-000000 is not d2-v2's g-000000).
def test_another_dataset_reusing_the_ids_for_other_games_is_independent(tmp_path):
    model = fitted_model(tmp_path)
    splits = model.metadata["splits"]
    assert [len(splits["content_keys"][s]) for s in ("train", "val")] == [len(splits["train"]), len(splits["val"])]
    distinct_games(tmp_path / "fresh", first=200)
    arrays, source = load_dataset(tmp_path / "fresh")
    report = evaluate(model, arrays, source, "train", n_boot=10)
    assert report["overlap_basis"] == "content"
    assert report["game_id_overlap"] == {"train": report["games"], "val": 0} and report["games"] > 0
    assert report["fitting_game_overlap"] == report["selection_game_overlap"] == 0
    assert report["independent_games"] is True


# Catches: the content check letting a real overlap through: the fitting games themselves, from
# the same folder (compared by ID) or from a copy with other bytes (compared by content).
def test_the_fitting_games_are_still_refused_without_the_flag(tmp_path):
    model = fitted_model(tmp_path)
    arrays, source = load_dataset(tmp_path / "fit")
    with pytest.raises(ValueError, match="overlap.*game_id"):
        evaluate(model, arrays, source, "train")
    copy = tmp_path / "copy"
    shutil.copytree(tmp_path / "fit", copy)
    (copy / "manifest.json").write_text('{"note": "the same games"}\n')
    arrays, source = load_dataset(copy)
    with pytest.raises(ValueError, match="overlap.*content"):
        evaluate(model, arrays, source, "train")
    with pytest.raises(ValueError, match="overlap.*content"):
        evaluate(model, arrays, source, "val")
    diagnostic = evaluate(model, arrays, source, "train", allow_seen_games=True, n_boot=10)
    assert diagnostic["overlap_basis"] == "content"
    assert diagnostic["fitting_game_overlap"] == diagnostic["games"] and diagnostic["independent_games"] is False


# Catches: Network 1, whose split file lists game IDs only, called not independent on fresh games
# when its games are the linear model's, or its guard not firing when its games are not.
def test_network_1_follows_the_linear_evidence_when_the_splits_match(tmp_path):
    model = fitted_model(tmp_path)
    distinct_games(tmp_path / "fresh", first=200)
    arrays, source = load_dataset(tmp_path / "fresh")
    report = evaluate(model, arrays, source, "train", n_boot=10)
    data = mask_split(arrays, "train")
    same = json.loads((tmp_path / "run" / "splits.json").read_text())
    evidence = network_split_evidence({"train": same["train"], "val": same["val"]}, model, data, report)
    assert evidence["same_games_as_linear"] and evidence["overlap_basis"] == "content"
    assert evidence["overlaps"] == {"train": 0, "val": 0} and evidence["independent_games"]
    assert evidence["game_id_overlap"]["train"] == report["games"]
    other = {"train": same["train"][1:], "val": same["val"]}  # not the linear model's games: IDs only
    with pytest.raises(ValueError, match="Network 1 .*overlap.*game_id"):
        network_split_evidence(other, model, data, report)
    seen = network_split_evidence(other, model, data, report, allow_seen_games=True)
    assert not seen["same_games_as_linear"] and seen["overlap_basis"] == "game_id"
    assert seen["overlaps"]["train"] == report["games"] - 1 and not seen["independent_games"]


# Catches: a value-error interval that is not linear minus quick Stockfish on the evaluated rows,
# or that resamples positions one by one instead of whole games.
def test_the_report_has_the_value_error_difference_against_quick_stockfish(tmp_path):
    model = fitted_model(tmp_path)
    distinct_games(tmp_path / "fresh", first=200)
    arrays, source = load_dataset(tmp_path / "fresh")
    report = evaluate(model, arrays, source, "train", n_boot=200)
    difference = report["mae_difference"]
    assert difference["mean"] == pytest.approx(report["linear"]["mae"] - report["baseline"]["mae"], abs=1e-6)
    assert difference["positions"] == report["n"] and difference["games"] == report["games"]
    assert difference["resampled"] == "games" and difference["ci95"][0] <= difference["mean"] <= difference["ci95"][1]


# Catches: the Apple-GPU timing of Network 1 run on another device than asked, or the committed CPU
# run's evaluator name changing under it.
@pytest.mark.skipif(shutil.which('stockfish') is None, reason='needs Stockfish on PATH')
def test_benchmark_times_network1_on_the_device_asked_for(tmp_path):
    pytest.importorskip('torch')
    folder=tmp_path/'data';dataset(folder)
    def run(script,*args):
        return subprocess.run([sys.executable,str(ROOT/'pair_b'/'scripts'/script),*map(str,args)],
                              text=True,capture_output=True)
    assert run('train_linear.py','--data',folder,'--out',tmp_path/'run','--alphas',0.01).returncode==0
    net1=ROOT/'pair_b'/'checkpoints'/'net1-v2'
    for extra,key in (((),'network_cpu'),(('--net1-device','cpu'),'network_cpu')):
        timing=tmp_path/f'timing-{len(extra)}.json'
        benchmark=run('benchmark_linear.py','--run',tmp_path/'run','--data',folder,'--limit',1,'--repeats',1,
                      '--net1-run',net1,*extra,'--out',timing)
        assert benchmark.returncode==0,benchmark.stderr
        timed=json.loads(timing.read_text())
        assert set(timed['evaluators'])=={'material','d1','linear',key}
        assert timed['network_device']=='cpu'
