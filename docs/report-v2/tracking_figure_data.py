"""Numbers for the report's tracking figure (15 Nov 2026).
Part 1, the Qa4+ example (1.Nh3 d5 2.c4 Qd6 3.Qa4+), Black's guard tracker: stored boards (state_count) and
move sequences (population_size) after every update; then White's third move by hand with the rules adapter: how many
White moves the position allows, and how many of them leave Black's view exactly as Black then sees it.
Part 2, a recorded game (argv[1], a games.jsonl row from the match runner): the same two numbers for one player's
tracker at each of its turns, to show boards stored once with a count above 1."""
import json
import sys

sys.path.insert(0, "/repo/pair_a_prep/experiments/network_leaf_2026-11/strength")
from guard_tracker import Factory as GuardFactory  # noqa: E402
from pairb.rules import pick_rules  # noqa: E402

SETTINGS = {"max_states": "96000", "sample_size": "16", "max_candidates": "none", "tracker_policy": "exact",
            "tracker_backend": "auto"}
rules = pick_rules("teal")


def tracker_for(player):
    t = GuardFactory(SETTINGS).create_tracker(rules, initial_fen=None)
    t.reset(player, 1)
    return t


def inner(t):
    return getattr(t, "_inner", t)


# part 1
MOVES = ["g1h3", "d7d5", "c2c4", "d8d6", "d1a4"]
t = tracker_for("black")
state = rules.initial_state(None)
b = t.update(rules.observe(state, "black"))
print("qa4: start | boards", inner(t).state_count, "sequences", inner(t).population_size)
for ply, move in enumerate(MOVES):
    before = state
    state = rules.apply_move(state, move)
    b = t.update(rules.observe(state, "black"), own_move=move if ply % 2 == 1 else None)
    print(f"qa4: after {move} | boards {inner(t).state_count} sequences {inner(t).population_size} belief {len(b.hypotheses)}")
    if move == "d1a4":
        target = rules.observe(state, "black")
        legal = list(rules.legal_moves(before))
        keep = [m for m in legal if rules.observe(rules.apply_move(before, m), "black") == target]
        print(f"qa4: White's third move: {len(legal)} legal moves; {len(keep)} leave Black's view as seen: {sorted(keep)}")

# part 2
row = json.loads(open(sys.argv[1]).readline())
moves = [p["move"] for p in row["plies"]]
for player in ("white", "black"):
    t = tracker_for(player)
    state = rules.initial_state(None)
    t.update(rules.observe(state, player))
    for ply, move in enumerate(moves[:24]):
        mover = rules.current_player(state)
        state = rules.apply_move(state, move)
        t.update(rules.observe(state, player), own_move=move if mover == player else None)
        if rules.current_player(state) == player:
            i = inner(t)
            print(f"game seed {row['seed']} {player} to move at ply {ply + 1} (after {move}): boards {i.state_count} "
                  f"sequences {i.population_size}")
