"""Bridge template: genuine shared contracts, model construction pending Colin's code."""
from fow_shared.contracts import AgentInput, Belief, Hypothesis, Observation


def make_turn(spec):
    """Build an API probe, not a claim about a reachable game history."""
    obs = Observation(player=spec['player'], ply=158, visible_squares=(),
        visible_pieces={}, legal_moves=tuple(spec['legal_moves']), halfmove_clock=None)
    belief = Belief(spec['player'], 158,
        tuple(Hypothesis(f, w) for f, w in zip(spec['fens'], spec['weights'])),
        population_size=len(spec['fens']), weighting='pair_b_contract_probe')
    return AgentInput(obs, belief, 1000)


def build(config):
    # Replace with Colin's actual constructor and checkpoint loading, then return:
    # SimpleNamespace(evaluator=evaluator, make_turn=make_turn,
    #     metadata={'demo_only': False, 'checkpoint_sha256': ..., 'code_commit': ...,
    #               'stockfish_build': ..., 'engine_settings': ..., 'device': ...,
    #               'encoder_version': ..., 'cache_policy': ...},
    #     synchronize=..., before_sample=..., close=...)
    raise NotImplementedError("Connect Colin's evaluator here; see README.md")
