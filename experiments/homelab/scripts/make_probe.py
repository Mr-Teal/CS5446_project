"""Probe the search budget, because the strength arms were bound by the wrong limit.

What the 400-game run actually measured. Every A move in those arms reports
`stop:round_limit` with solver_rounds_this_turn = 8, and a mean elapsed of 464 ms
against a 5,000 ms budget. SearchFactory defaults for search_mode=subgame are
solver_rounds 8, max_nodes 1024, max_evaluator_calls 48 and stop_on_time FALSE
(evaluation_factories.py:152-163, :30-33), so the clock was never consulted: the
search stopped after eight rounds having used nine percent of its time.

Raising sample_size alone was therefore not a stronger search but a broken one.
chess_projection.py:67 raises TreeCapacityError when "sampled root nodes alone
exceed max_nodes", and chess_subgame_agent.act() catches that and plays
self._rng.choice(moves) -- a uniform random legal move. Measured fallback rate
was 0.02 for sample_size 16 and 0.71 for 256, which is why the 256 arm scored
0.042: it was playing at random on three turns in four.

So the real question is the one the project cares about: at a fixed per-move wall
clock, which (sample_size, max_nodes, evaluator calls, rounds) point plays best,
and does it still fit in memory? This probe runs one short game per candidate and
reports, per A move, the fallback rate, the rounds actually completed, the nodes
built, the evaluator calls and the elapsed time, plus peak RSS for the process.

A candidate is only worth putting in a paired arm if its fallback rate is ~0 and
it spends a real share of the budget. Anything that still trips a cap is measuring
random play again.
"""
import pathlib

HERE = pathlib.Path(__file__).resolve().parent

HEADER = """; probe {tag}: {purpose}
;
; One game, capped at {plies} plies, exact belief, Material both sides. This is a
; cost measurement, not a strength measurement; the arms come after.

[player_a]
name = probe {tag}
factory = pair_a_prep.evaluation_factories:SearchFactory
search_mode = subgame
leaf_evaluator = material
leaf_depth = 0
tracker_factory = pair_a_prep.evaluation_factories:HistoryTrackerFactory
sample_size = {sample_size}
max_candidates = none
tracker_policy = exact
tracker_backend = auto
solver_rounds = {rounds}
max_nodes = {nodes}
max_evaluator_calls = {evals}
stop_on_time = {clock}

[player_b]
name = Material OnePlyBot (particle tracker)
factory = pair_c.agent_factories:Factory
scorer_id = material
leaf_depth = 0
device = cpu
tracker_factory = pair_c.tracker_factories:Factory
tracker_particles = 256
tracker_hypotheses = 8
tracker_rebuild_tries = 2000

[match]
games = 1
alternating_colors = true
rules = teal
time_budget_ms = 5000
max_plies = {plies}
initial_fen =
seed = 1001
seed_mode = per_game

[output]
directory = pair_c/runs/probe-{tag}
hash_rules = pair_c/hash_rules.json
"""

# Node and evaluator allowances scale with the number of sampled roots: the arms
# show about 26 nodes and one evaluator call per root at sample_size 16, so these
# give every candidate the same per-root room the default gives 16.
PROBES = {
    "p0-default": dict(sample_size=16, rounds=8, nodes=1024, evals=48, clock="false",
                       purpose="the arms' own settings, for reference"),
    "p1-s16-clock": dict(sample_size=16, rounds=64, nodes=8192, evals=512, clock="true",
                         purpose="same sample, search allowed to use the 5 s clock"),
    "p2-s64-clock": dict(sample_size=64, rounds=64, nodes=32768, evals=2048, clock="true",
                         purpose="four times the sample, room to build it"),
    "p3-s256-clock": dict(sample_size=256, rounds=64, nodes=131072, evals=8192, clock="true",
                          purpose="the paper's MinInfosetSize, room to build it"),
    "p4-s16-wide": dict(sample_size=16, rounds=1024, nodes=16384, evals=4096, clock="true",
                        purpose="sample 16, round ceiling lifted so the clock is the only limit"),
    "p5-s64-wide": dict(sample_size=64, rounds=1024, nodes=65536, evals=8192, clock="true",
                        purpose="sample 64, round ceiling lifted"),
    "p6-s128-wide": dict(sample_size=128, rounds=1024, nodes=131072, evals=16384, clock="true",
                         purpose="sample 128, to find where one solving round stops fitting in 5 s"),
    # p6 exceeded 4.5 GiB. It raised two allowances at once, the sample and the node
    # cap, so it does not say which grew. p7 repeats it with the node cap p4 used,
    # separating the search tree from the sample.
    "p7-s128-narrow": dict(sample_size=128, rounds=1024, nodes=16384, evals=4096, clock="true",
                           purpose="sample 128 with p4's node allowance, to attribute p6's OOM"),
}

PLIES = 40

for tag, spec in PROBES.items():
    (HERE / f"probe-{tag}.ini").write_text(
        HEADER.format(tag=tag, plies=PLIES, **spec), encoding="utf-8")
print(f"wrote {len(PROBES)} probe configs, {PLIES} plies each")
