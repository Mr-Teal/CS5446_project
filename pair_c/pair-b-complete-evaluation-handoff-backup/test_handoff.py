"""Synthetic orchestration checks; these are not game experiments."""
import contextlib
import configparser
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import run


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def pair(self, *, capped=False):
        rows = []
        for i,color in enumerate(('white','black')):
            rows.append(dict(game=i+1,seed=17,player_a_color=color,status='completed',
                stopped_at_ply_limit=capped,termination='ply_limit' if capped else 'king_capture',
                winner=None if capped else color,
                plies=[dict(move='test-only',diagnostics=dict(solver_rounds=16,over_budget=0,
                    evaluator_calls=1,search_nodes=4)) for _ in range(4)]))
        (self.root/'games.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        return rows

    def write(self,rows):
        (self.root/'games.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))

    def test_opening_caps_are_expected_but_readiness_caps_do_not_pass(self):
        self.pair(capped=True)
        opening = run.inspect_pair(self.root,17,opening=True)
        self.assertEqual(opening['problems'],[])
        self.assertIsNone(opening['paired_score'])
        ready = run.inspect_pair(self.root,17)
        self.assertIn('capped attempts are unscored',ready['problems'])
        self.assertIsNone(ready['paired_score'])

    def test_terminal_pair_uses_player_identity_across_colour_swap(self):
        self.pair()
        answer = run.inspect_pair(self.root,17)
        self.assertEqual(answer['paired_score'],1)
        self.assertEqual(answer['counts']['terminal'],2)

    def test_missing_diagnostics_and_failed_game_cannot_be_scored_as_success(self):
        rows = self.pair()
        rows[0]['plies'][0]['diagnostics'] = {}
        rows[1].update(status='failed',error='TrackerLost')
        self.write(rows)
        result = run.inspect_pair(self.root,17)
        self.assertIsNone(result['paired_score'])
        self.assertEqual(result['counts']['failed'],1)
        self.assertTrue(result['problems'])

    def test_corrupt_partial_record_is_retained_and_counted_missing(self):
        rows = self.pair()
        self.write(rows[:1])
        with (self.root/'games.jsonl').open('a') as stream:
            stream.write('{"partial":')
        result = run.inspect_pair(self.root,17)
        self.assertEqual(result['counts']['missing'],1)
        self.assertIsNone(result['paired_score'])

    def test_wrong_source_or_engine_provenance_cannot_pass(self):
        self.pair()
        ini = self.root/'evaluate_config.ini'
        ini.write_text('test config')
        expected = dict(source=run.SOURCE,config_sha256=run.digest(ini),
                        checkpoint_sha256='test checkpoint',stockfish_sha256='test engine',device='cpu')
        provenance = dict(git_commit=run.SOURCE,git_status=[],
            sha256=dict(config_raw=run.digest(ini),player_a_checkpoint='test checkpoint',
                player_b_checkpoint=None,player_a_stockfish='test engine',player_b_stockfish='test engine'),
            player_devices={'a':{'device':'cpu'}},
            stockfish={s:{'name':'Stockfish 19'} for s in ('a','b')})
        path = self.root/'provenance.json'
        path.write_text(json.dumps(provenance))
        self.assertEqual(run.inspect_pair(self.root,17,expected=expected)['problems'],[])
        provenance['sha256']['player_b_stockfish'] = 'other engine'
        path.write_text(json.dumps(provenance))
        self.assertIsNone(run.inspect_pair(self.root,17,expected=expected)['paired_score'])

    def test_pilots_are_not_pooled_and_uninspected_attempts_stay_unknown(self):
        entries = [dict(stage='opening',seed=17,inspection={'paired_score':1,'counts':{'terminal':2}}),
                   dict(stage='batch',seed=1001,inspection={'paired_score':0.5,'counts':{'terminal':2},'problems':[]}),
                   dict(stage='batch',seed=1002,status='started')]
        answer = run.analysis(entries,50)
        self.assertEqual(answer['complete_clean_pairs'],1)
        self.assertEqual(answer['score_on_complete_clean_pairs'],0.5)
        self.assertEqual(answer['attempt_counts']['missing'],2)
        self.assertEqual(answer['unplayed_pairs'],48)
        self.assertEqual(answer['excluded_launched_pairs'],1)
        self.assertIsNone(answer['paired_bootstrap_ci95'])

    def test_final_archive_contains_partial_logs_and_manifest(self):
        (self.root/'partial.log').write_text('retained failure')
        with contextlib.redirect_stdout(io.StringIO()):
            run.finalize(self.root,dict(status='diagnostic_complete',reason='test failure',runs=[],planned_pairs=50))
        archive = self.root.with_name(self.root.name+'-return.zip')
        self.addCleanup(archive.unlink)
        with zipfile.ZipFile(archive) as z:
            self.assertIn('partial.log',z.namelist())
            self.assertEqual(json.loads(z.read('manifest.json'))['status'],'diagnostic_complete')

    def test_hard_timeout_stops_the_child_process(self):
        result = run.command([sys.executable,'-c','import time; time.sleep(30)'],
                             self.root,self.root/'process.log',0.2)
        self.assertTrue(result['timed_out'])

    def test_rule_decided_tree_can_legitimately_have_zero_evaluator_calls(self):
        rows = self.pair()
        rows[0]['plies'][0]['diagnostics'].update(evaluator_calls=0,frontier_leaves=0,terminal_leaves=3)
        self.write(rows)
        self.assertEqual(run.inspect_pair(self.root,17)['paired_score'],1)

    def simulate(self, fail_readiness=False):
        repo = self.root/'repo'; repo.mkdir()
        engine = self.root/'engine'; engine.write_bytes(b'fake engine for orchestration test')
        out = self.root/'out'
        real_digest = run.digest
        stages = []

        def fake_digest(path):
            return run.CHECKPOINT if Path(path).name=='best.pt' else real_digest(path)

        def fake_git(args,**kwargs):
            return run.SOURCE+'\n' if 'rev-parse' in args else ''

        def fake_command(args,unused_repo,log,timeout):
            log.write_text('synthetic worker, no actual games')
            if '--result' in args:
                Path(args[args.index('--result')+1]).write_text('{"device":"cpu"}')
                return dict(returncode=0,timed_out=False)
            ini = Path(args[-1]); c = configparser.ConfigParser(); c.read(ini)
            folder=Path(c['output']['directory']);folder.mkdir()
            opening=c['match']['max_plies']=='4'
            stage='opening' if opening else ('readiness' if 'readiness' in folder.name else 'batch')
            stages.append(stage)
            rows=[]
            failed=fail_readiness and stage=='readiness'
            for i,color in enumerate(('white','black')):
                rows.append(dict(game=i+1,seed=int(c['match']['seed']),player_a_color=color,
                    status='failed' if failed else 'completed',winner=None if opening else 'draw',
                    stopped_at_ply_limit=opening,termination='ply_limit' if opening else 'threefold_repetition',
                    plies=[dict(move='synthetic',diagnostics=dict(solver_rounds=16,over_budget=0,evaluator_calls=1)) for _ in range(4)]))
            (folder/'games.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            (folder/'evaluate_config.ini').write_bytes(ini.read_bytes())
            prov=dict(git_commit=run.SOURCE,git_status=[],sha256=dict(config_raw=real_digest(ini),
                player_a_checkpoint=run.CHECKPOINT,player_b_checkpoint=None,
                player_a_stockfish=real_digest(engine),player_b_stockfish=real_digest(engine)),
                player_devices={'a':{'device':'cpu'}},stockfish={s:{'name':'Stockfish 19'} for s in ('a','b')})
            (folder/'provenance.json').write_text(json.dumps(prov))
            return dict(returncode=1 if failed else 0,timed_out=False)

        args=['run.py','--repo',str(repo),'--stockfish',str(engine),'--out',str(out),'--pairs','20']
        with patch.object(sys,'argv',args),patch.object(run.subprocess,'check_output',fake_git),\
             patch.object(run,'digest',fake_digest),patch.object(run,'command',fake_command),\
             contextlib.redirect_stdout(io.StringIO()):
            run.main()
        return stages,json.loads((out/'manifest.json').read_text())

    def test_controller_runs_whole_frozen_batch_only_after_gates_pass(self):
        stages,manifest=self.simulate()
        self.assertEqual(stages,['opening','readiness','readiness']+['batch']*20)
        self.assertEqual(manifest['status'],'batch_attempts_complete')
        self.assertTrue(manifest['analysis']['clean_full_batch'])
        self.assertEqual(manifest['analysis']['complete_clean_pairs'],20)
        self.assertEqual(manifest['analysis']['paired_bootstrap_ci95'],[0.5,0.5])

    def test_controller_stops_at_failed_readiness_and_archives_unplayed_batch(self):
        stages,manifest=self.simulate(fail_readiness=True)
        self.assertEqual(stages,['opening','readiness'])
        self.assertEqual(manifest['status'],'diagnostic_complete')
        self.assertEqual(manifest['analysis']['unplayed_pairs'],20)
        self.assertFalse(manifest['analysis']['clean_full_batch'])


if __name__ == '__main__':
    unittest.main()
