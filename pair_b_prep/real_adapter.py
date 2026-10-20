"""Local PR4 validation bridge; source evaluators are imported unchanged."""
import hashlib
import shutil
from pathlib import Path
from types import SimpleNamespace
from .adapter_example import make_turn



def build(config):
    kind = config['kind']
    source_commit = config['source_commit']  # caller-verified revision, never guessed
    engine_path = None
    if kind in ('stockfish', 'network'):
        engine_path = shutil.which(config.get('stockfish_path', 'stockfish'))
        if engine_path is None:
            raise FileNotFoundError('Stockfish not found; set stockfish_path or PATH')
    engine_hash = hashlib.sha256(Path(engine_path).read_bytes()).hexdigest() if engine_path else None
    metadata = dict(demo_only=False, code_commit=source_commit,
                    source='revision supplied by caller; verify against checkout or ZIP comment',
                    cache_policy='ucinewgame before each engine call')
    if kind == 'material':
        from pairb.material import MaterialEvaluator
        evaluator = MaterialEvaluator()
        metadata['cache_policy'] = 'none'
    elif kind == 'stockfish':
        from pairb.stockfish import StockfishEvaluator
        evaluator = StockfishEvaluator(depth=config['depth'], path=engine_path)
    elif kind == 'network':
        from pairb.network_evaluator import NetworkEvaluator
        from pairb.data import ENCODING
        evaluator = NetworkEvaluator.from_checkpoint(config['checkpoint'],
                    device=config.get('device', 'cpu'), stockfish_path=engine_path)
        metadata.update(checkpoint_sha256=hashlib.sha256(Path(config['checkpoint']).read_bytes()).hexdigest(),
                        encoder_version=ENCODING, device=evaluator.device)
    else:
        raise ValueError(f'Unknown evaluator: {kind}')
    sf = getattr(evaluator, 'stockfish', evaluator)
    if hasattr(sf, 'engine'):
        metadata.update(stockfish_build=sf.engine.id, engine_settings=dict(
            threads=1, hash_mb=16, depth=sf.depth, new_game_each_call=sf.new_game_each_call),
            engine_sha256=engine_hash)
    def synchronize():
        if kind == 'network':
            import torch
            if evaluator.device.startswith('cuda'):
                torch.cuda.synchronize()
            elif evaluator.device == 'mps':
                torch.mps.synchronize()
    return SimpleNamespace(evaluator=evaluator, make_turn=make_turn, metadata=metadata,
                           close=evaluator.close, synchronize=synchronize)
