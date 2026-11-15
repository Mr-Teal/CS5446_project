"""The policy network at the report figure's position (15 Nov 2026): 1.Nh3 d5 2.c4 Qd6 3.Qa4+, Black to move, Black's
belief from the match tracker. For each checkpoint given: its top legal moves, and whether the chosen move lets the
queen take the king on the Qa4+ board. For the first checkpoint also prints the nonzero enemy-piece probability
planes (14-19) of the exact network input, mapped back to square names, to check the figure against."""
import sys

sys.path.insert(0, "/repo/pair_a_prep/experiments/network_leaf_2026-11/strength")
import chess  # noqa: E402

from fow_shared.contracts import AgentInput, HistoryEvent  # noqa: E402
from guard_tracker import Factory as GuardFactory  # noqa: E402
from pairb.policy_agent import PolicyFactory  # noqa: E402
from pairb.rules import pick_rules  # noqa: E402

MOVES = ["g1h3", "d7d5", "c2c4", "d8d6", "d1a4"]
PIECES = "PNBRQK"
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
obs = rules.observe(state, "black")
turn = AgentInput(obs, belief, 5000, tuple(history))
check_board = next(chess.Board(h.fen) for h in belief.hypotheses if h.candidate_moves[-1] == "d1a4")


def loses_king(move):
    b = check_board.copy()
    b.push(chess.Move.from_uci(move))
    k = b.king(chess.BLACK)
    return any(m.to_square == k for m in b.pseudo_legal_moves)


for i, ckpt in enumerate(sys.argv[1:]):
    agent = PolicyFactory({"checkpoint_path": ckpt, "device": "cpu"}).load_model()
    agent.reset("black", 0)
    probs = agent.move_probabilities(turn)
    top = sorted(probs.items(), key=lambda kv: -kv[1])[:6]
    print(f"{ckpt} input={agent.input_mode}: plays {top[0][0]} (loses king on Qa4+ board: {loses_king(top[0][0])}) "
          f"| top 6 {[(m, round(p, 3)) for m, p in top]}")
    if i == 0:
        planes, weights = agent.network_input(turn)
        print("network input", planes.shape, "weights", weights.tolist())
        for t in range(6):
            cells = []
            for row in range(8):
                for col in range(8):
                    v = float(planes[0, 14 + t, row, col])
                    if v > 1e-6:
                        cells.append(f"{chess.FILE_NAMES[col]}{row + 1}:{v:.2f}")  # Black's frame: row = rank index
            print(f"  plane {14 + t} enemy {PIECES[t]} probability: {' '.join(cells)}")
        print("  plane 20 (log2 population / 15):", round(float(planes[0, 20, 0, 0]), 4))
