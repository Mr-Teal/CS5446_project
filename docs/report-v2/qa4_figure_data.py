"""Data for the report's state-representation figure (15 Nov 2026): the qa4 position (1.Nh3 d5 2.c4 Qd6 3.Qa4+),
Black to move. Black's belief comes from the match tracker (guard tracker, sample 16) fed Black's observations ply by
ply. Writes JSON: the true board, what Black sees, each sampled board with White's third move, and per square the
probability of each White piece over the belief (what the probability board's planes 14-19 hold)."""
import json
import sys

sys.path.insert(0, "/repo/pair_a_prep/experiments/network_leaf_2026-11/strength")
import chess  # noqa: E402

from guard_tracker import Factory as GuardFactory  # noqa: E402
from pairb.rules import pick_rules  # noqa: E402

MOVES = ["g1h3", "d7d5", "c2c4", "d8d6", "d1a4"]
rules = pick_rules("teal")
tracker = GuardFactory({"max_states": "96000", "sample_size": "16", "max_candidates": "none", "tracker_policy": "exact",
                        "tracker_backend": "auto"}).create_tracker(rules, initial_fen=None)
tracker.reset("black", 1)
state = rules.initial_state(None)
belief = tracker.update(rules.observe(state, "black"))
for ply, move in enumerate(MOVES):
    state = rules.apply_move(state, move)
    belief = tracker.update(rules.observe(state, "black"), own_move=move if ply % 2 == 1 else None)
obs = rules.observe(state, "black")
total = sum(h.weight for h in belief.hypotheses)
prob = {}
for h in belief.hypotheses:
    board = chess.Board(h.fen)
    for sq, piece in board.piece_map().items():
        if piece.color == chess.WHITE:
            name = chess.square_name(sq)
            prob.setdefault(name, {})
            prob[name][piece.symbol()] = prob[name].get(piece.symbol(), 0.0) + h.weight / total
out = {
    "moves": MOVES,
    "true_fen": rules.board(state).fen(),
    "visible_squares": sorted(obs.visible_squares),
    "visible_pieces": {k: v for k, v in obs.visible_pieces.items() if v},
    "hypotheses": [{"fen": h.fen, "white_third_move": h.candidate_moves[-1], "weight": h.weight / total}
                   for h in belief.hypotheses],
    "white_piece_probability": prob,
    "population": belief.population_size,
}
print(json.dumps(out))
