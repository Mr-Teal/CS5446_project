"""Distinct pilot protocols must not collide in record or game identity."""

from dataclasses import replace

import pytest

from pair_a_prep.label_pilot import KINGS, collect, pilot_config_id, pilot_configuration, semantic_records
from pair_a_prep.search_agent import FixedDepthPCFRAgent, SearchConfig


class ZeroLeaf:
    name = "pilot-id-zero"

    def evaluate_children(self, fen):
        import chess
        from fow_shared.values import fog_legal_moves
        return {m.uci(): 0.0 for m in fog_legal_moves(chess.Board(fen))}

    def evaluate_boards(self, fens, player):
        return [0.0 for _ in fens]


SETTINGS = dict(initial_fen=KINGS, config=SearchConfig(rounds=1, stop_on_time=False),
                max_plies=1, sample_size=4, max_candidates=2000)


@pytest.mark.parametrize("change", [dict(sample_size=2), dict(max_candidates=1000),
                                    dict(max_plies=2), dict(d1=ZeroLeaf())],
                         ids=["sample-size", "candidate-cap", "ply-cap", "d1-features"])
def test_changing_pilot_settings_changes_record_and_game_ids(change):
    before, _ = collect(ZeroLeaf(), games=1, **SETTINGS)
    after, _ = collect(ZeroLeaf(), games=1, **{**SETTINGS, **change})
    assert before[0].config_id != after[0].config_id
    assert before[0].game_id != after[0].game_id
    assert {r.config_id for r in after} == {after[0].config_id}
    # Agent identity remains about search; the record identifies the full pilot.
    agent_id = FixedDepthPCFRAgent(ZeroLeaf(), SETTINGS["config"], KINGS).config_id
    assert before[0].config_id != agent_id


def test_fixed_protocol_and_seed_repeat_ids_and_semantic_records():
    first, _ = collect(ZeroLeaf(), games=1, seed=17, **SETTINGS)
    second, _ = collect(ZeroLeaf(), games=1, seed=17, **SETTINGS)
    assert semantic_records(first) == semantic_records(second)
    changed_seed, _ = collect(ZeroLeaf(), games=1, seed=19, **SETTINGS)
    assert changed_seed[0].config_id == first[0].config_id
    assert changed_seed[0].game_id != first[0].game_id


def test_extending_batch_preserves_existing_game_identity():
    short, _ = collect(ZeroLeaf(), games=1, seed=17, **SETTINGS)
    longer, _ = collect(ZeroLeaf(), games=2, seed=17, **SETTINGS)
    assert semantic_records(short) == semantic_records(longer[:1])
    assert longer[0].config_id == longer[1].config_id
    assert longer[0].game_id != longer[1].game_id


def test_protocol_identity_is_canonical_and_covers_search_and_leaf_settings():
    base = pilot_configuration(ZeroLeaf(), **SETTINGS)
    assert pilot_config_id(base) == pilot_config_id(dict(reversed(list(base.items()))))
    changed = pilot_configuration(ZeroLeaf(), **{**SETTINGS, "config": replace(SETTINGS["config"], rounds=2)})
    assert pilot_config_id(changed) != pilot_config_id(base)
    leaf = ZeroLeaf()
    leaf.name = "different-leaf"
    assert pilot_config_id(pilot_configuration(leaf, **SETTINGS)) != pilot_config_id(base)
    leaf.name = ZeroLeaf.name
    leaf.new_game_each_call = False
    assert pilot_config_id(pilot_configuration(leaf, **SETTINGS)) != pilot_config_id(base)
