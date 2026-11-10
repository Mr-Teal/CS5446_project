"""Check the actual model/engine/device before freezing an experiment device."""
import argparse
import json
from pathlib import Path
import sys


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--repo', required=True)
    p.add_argument('--stockfish', required=True)
    p.add_argument('--device', required=True)
    p.add_argument('--result', required=True)
    a = p.parse_args()
    repo = Path(a.repo)
    sys.path[:0] = [str(repo), str(repo / 'pair_b/src')]
    import chess
    import torch
    from pairb.network_evaluator import NetworkEvaluator

    torch.set_num_threads(1)
    devices = ([('cuda:0' if torch.cuda.is_available() else 'cpu'), 'cpu']
               if a.device == 'auto' else [a.device])
    errors = []
    for device in dict.fromkeys(devices):
        try:
            with NetworkEvaluator.from_checkpoint(repo / 'pair_b/checkpoints/net1-v2/best.pt',
                    stockfish_path=a.stockfish, device=device, new_game_each_call=False) as leaf:
                if leaf.stockfish.engine.id.get('name') != 'Stockfish 19':
                    raise RuntimeError('Use Stockfish 19; detected ' + str(leaf.stockfish.engine.id))
                values = leaf.evaluate_children(chess.STARTING_FEN)
                assert len(values) == 20
                result = dict(device=str(next(leaf.net.parameters()).device), torch=str(torch.__version__),
                              engine=leaf.stockfish.engine.id, preflight_errors=errors)
                Path(a.result).write_text(json.dumps(result, indent=2) + '\n',encoding='utf-8')
                print(json.dumps(result))
                return
        except Exception as error:
            errors.append(dict(device=device, error=f'{type(error).__name__}: {error}'))
            if a.device != 'auto' or device == 'cpu':
                raise


if __name__ == '__main__':
    main()
