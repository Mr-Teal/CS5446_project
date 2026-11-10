"""Frozen comparison settings shared by the automatic handoff runner."""
import configparser
import hashlib
from pathlib import Path

SOURCE = 'aaa000a034ae5275afe981402891596e660312a4'
CHECKPOINT = 'ab470346acb5eb37947e3ab0eb43c005894ae72569ca016d7635fc2be6f9171f'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def config(repo, engine, engine_hash, device, output, max_plies):
    common = dict(factory='pairb.search_factory:Factory', leaf_depth='1',
        stockfish_path=engine.as_posix(), stockfish_sha256=engine_hash,
        stockfish_hash_mb='16', stockfish_new_game_each_call='false',
        stockfish_call_timeout_s='2', stockfish_expected_name='Stockfish 19',
        search_mode='anytime', growth='uniform', initial_depth='1', max_depth='2',
        rounds_per_stage='2', final_rounds='2', max_evaluator_calls='128',
        solver_rounds='16', max_nodes='4096', stop_on_time='true',
        tracker_factory='pair_a_prep.evaluation_factories:HistoryTrackerFactory',
        public_initial_fen='', tracker_policy='bounded-history', max_candidates='none',
        sample_size='4', tracker_backend='native', tracker_total_ms='60000',
        tracker_max_histories='8192', tracker_rebuild_attempts='8')
    c = configparser.ConfigParser()
    c['player_a'] = dict(common, name='Network1 anytime search bounded histories', leaf_evaluator='network1',
        checkpoint_path=(repo / 'pair_b/checkpoints/net1-v2/best.pt').as_posix(),
        checkpoint_sha256=CHECKPOINT, device=device)
    c['player_b'] = dict(common, name='Stockfish D1 anytime search bounded histories', leaf_evaluator='stockfish')
    c['match'] = dict(games='2', alternating_colors='true', rules='teal',
        time_budget_ms='5000', max_plies=str(max_plies), initial_fen='',
        seed='17', seed_mode='fixed')
    c['output'] = dict(directory=output.as_posix(), hash_rules=(repo / 'pair_c/hash_rules.json').as_posix())
    return c


