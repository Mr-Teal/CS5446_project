"""Data for the tracking figure, ply 0 -> 1 from Black's side (15 Nov 2026): Black's guard tracker (seed 1, as in the
Figure 2/3 example), White plays 1.Nh3. Prints JSON: stored boards and move sequences before and after, White's legal
first moves, which of them leave Black's view exactly as Black then sees it, Black's visible squares and pieces after
ply 1, and the first moves of the boards the tracker sampled into the belief."""
import json
import sys

sys.path.insert(0, "/repo/pair_a_prep/experiments/network_leaf_2026-11/strength")
from guard_tracker import Factory as GuardFactory  # noqa: E402
from pairb.rules import pick_rules  # noqa: E402

rules = pick_rules("teal")
t = GuardFactory({"max_states": "96000", "sample_size": "16", "max_candidates": "none", "tracker_policy": "exact",
                  "tracker_backend": "auto"}).create_tracker(rules, initial_fen=None)
t.reset("black", 1)
inner = getattr(t, "_inner", t)
start = rules.initial_state(None)
t.update(rules.observe(start, "black"))
before = (inner.state_count, inner.population_size)
after_state = rules.apply_move(start, "g1h3")
obs = rules.observe(after_state, "black")
belief = t.update(obs)
legal = sorted(rules.legal_moves(start))
fits = [m for m in legal if rules.observe(rules.apply_move(start, m), "black") == obs]
out = {"before": before, "after": (inner.state_count, inner.population_size), "legal": legal, "fits": fits,
       "visible": sorted(obs.visible_squares), "visible_pieces": {k: v for k, v in obs.visible_pieces.items() if v},
       "sampled": [{"first": h.candidate_moves[-1], "weight": h.weight} for h in belief.hypotheses]}
print(json.dumps(out))
