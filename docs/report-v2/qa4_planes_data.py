"""Plane values for the state figure's plane row (15 Nov 2026): the exact network input of the probability-board
policy (policy-conv-fuzzy-r2-s2) at 1.Nh3 d5 2.c4 Qd6 3.Qa4+, Black to move, Black's tracker as in Figure 3.
Prints JSON {plane index: {square: value}} for every plane, nonzero entries only, squares named on the real board
(Black's frame: row = rank index, so row 0 is rank 1)."""
import json
import sys

sys.path.insert(0, "/repo/pair_a_prep/experiments/network_leaf_2026-11/strength")
from fow_shared.contracts import AgentInput, HistoryEvent  # noqa: E402
from fow_shared.features import PLANE_NAMES  # noqa: E402
from guard_tracker import Factory as GuardFactory  # noqa: E402
from pairb.policy_agent import PolicyFactory  # noqa: E402
from pairb.rules import pick_rules  # noqa: E402

MOVES = ["g1h3", "d7d5", "c2c4", "d8d6", "d1a4"]
rules = pick_rules("teal")
tracker = GuardFactory({"max_states": "96000", "sample_size": "16", "max_candidates": "none", "tracker_policy": "exact",
                        "tracker_backend": "auto"}).create_tracker(rules, initial_fen=None)
tracker.reset("black", 1)
state = rules.initial_state(None)
history = []
belief = tracker.update(rules.observe(state, "black"))
for ply, move in enumerate(MOVES):
    obs = rules.observe(state, "black")
    history.append(HistoryEvent(obs, move if rules.current_player(state) == "black" else None))
    state = rules.apply_move(state, move)
    belief = tracker.update(rules.observe(state, "black"), own_move=move if ply % 2 == 1 else None)
turn = AgentInput(rules.observe(state, "black"), belief, 5000, tuple(history))
agent = PolicyFactory({"checkpoint_path": "/repo/pair_b/checkpoints/policy-conv-fuzzy-r2-s2/best.pt",
                       "device": "cpu"}).load_model()
planes, weights = agent.network_input(turn)
out = {"names": list(PLANE_NAMES), "input": agent.input_mode, "planes": {}}
for k in range(planes.shape[1]):
    cells = {}
    for row in range(8):
        for col in range(8):
            v = float(planes[0, k, row, col])
            if abs(v) > 1e-6:
                cells["abcdefgh"[col] + str(row + 1)] = round(v, 4)
    out["planes"][k] = cells
print(json.dumps(out))
