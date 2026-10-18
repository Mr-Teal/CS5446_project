"""Bridge template: genuine shared contracts, model construction pending Colin's code."""
from dataclasses import fields
from fow_shared.contracts import AgentInput, Belief, Hypothesis, Observation


def make_turn(spec):
    """Build an API probe, not a claim about a reachable game history."""
    # PR #2 requires side_to_move; main before that PR has no such field.
    # Both use schema v1, so inspect the actual contract instead of its version.
    turn_fields = {}
    if 'side_to_move' in {field.name for field in fields(Observation)}:
        # These are acting-player probes, including Black at an even ply.
        # Do not infer turn from ply parity (custom starts may begin with Black).
        turn_fields['side_to_move'] = spec['player']
    obs = Observation(player=spec['player'], ply=158, visible_squares=(),
        visible_pieces={}, legal_moves=tuple(spec['legal_moves']), halfmove_clock=None,
        **turn_fields)
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
