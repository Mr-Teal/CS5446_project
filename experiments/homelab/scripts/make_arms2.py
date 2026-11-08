"""Generate the second round of arms: the search allowed to use its clock.

Why a second round. The first round varied sample_size and belief exactness and
left the search budget at SearchFactory's defaults for search_mode=subgame, which
are solver_rounds 8, max_nodes 1024, max_evaluator_calls 48 and stop_on_time
FALSE (evaluation_factories.py:152-163 and :30-33). stop_on_time false means the
agent never looks at turn.time_budget_ms, so eight rounds is the whole search.
Every Pair A move in those 232 games reports stop:round_limit, and the measured
cost was 401 ms of a 5,000 ms budget.

The probes (probe_report.py over probe-*.ini) measured what the same agent does
when the ceiling is lifted and the clock is switched on, one game each:

    probe            rounds  nodes  ms/move  fallback
    p0 defaults         8.0    471      401      0.05
    p1 s16 rounds<=64  59.0   1351     1872      0.00
    p4 s16 rounds<=1k 386.4   1456     4121      0.00
    p2 s64 rounds<=64  60.6   1789     2250      0.00
    p5 s64 rounds<=1k 179.8   2488     4262      0.00
    p3 s256 rounds<=64 53.2   2297     2914      0.38
    p6 s128 rounds<=1k    --     --       --   4.5 GiB OOM

So at the same per-move wall clock the default configuration completes 8 CFR
rounds where 386 are available: it is using two percent of the iterations it
could afford. That is the thing worth measuring in games.

The arms. Both carry exact belief and max_candidates = none, and both differ from
the baseline only in the search budget, so a difference is attributable to it.

  clock-s16   sample 16, round ceiling 1024, 16,384 nodes, clock on.
              Same hypotheses as the baseline, a search that spends its budget.
  clock-s64   sample 64, round ceiling 1024, 65,536 nodes, clock on.
              Four times the breadth at the same clock, which the probes show
              costs convergence: 180 rounds against 386. Whether breadth or
              convergence wins is the open question.

The baseline is not re-run. It is the existing exact-s16 arm, whose configs set
none of these keys and so take the defaults, on these same seeds with these same
colours. Reuse is sound there precisely because stop_on_time is false in that arm:
no decision depends on elapsed time, so those games are reproducible. The two new
arms are timing-dependent by construction and are not bit-reproducible; that is a
property of searching against a clock, and is why they are compared by score over
many paired seeds rather than by replay.

Sample 256 gets no arm. At 5 s per move it cannot complete one solving round on
38 percent of turns, and chess_subgame_agent.act() answers a SearchBudgetError
with self._rng.choice(moves) -- a uniform random legal move. An arm there would
measure random play, which is what the first round's exact-s256 arm did measure:
fallback rate 0.71 and a score of 0.042.
"""
import pathlib

HERE = pathlib.Path(__file__).resolve().parent

HEADER = """; {title}
;
; {purpose}
;
; Material evaluator on BOTH sides, standard start, alternating colours, 5 s per
; move, 200-ply cap. Same seeds and colours as the exact-s16 baseline, so the
; paired unit is one seed.

[player_a]
name = {name}
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
stop_on_time = true

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
games = 2
alternating_colors = true
rules = teal
time_budget_ms = 5000
max_plies = 200
initial_fen =
seed = {seed}
seed_mode = per_game

[output]
directory = pair_c/runs/strength-{arm}-c{index}
hash_rules = pair_c/hash_rules.json
"""

ARMS = {
    "clock-s16": dict(
        name="Pair A subgame PCFR+ (exact belief, sample 16, search on the clock)",
        sample_size=16, rounds=1024, nodes=16384, evals=4096,
        purpose="ARM 5. Baseline hypotheses, search spends its 5 s budget instead of\n"
                "; stopping after eight rounds. Probe p4 measured 386 rounds per move here\n"
                "; against the baseline's 8, with no fallbacks."),
    "clock-s64": dict(
        name="Pair A subgame PCFR+ (exact belief, sample 64, search on the clock)",
        sample_size=64, rounds=1024, nodes=65536, evals=8192,
        purpose="ARM 6. Four times the hypotheses at the same clock. Probe p5 measured\n"
                "; 180 rounds per move, so this buys breadth with convergence."),
}

SEEDS = [1001 + 2 * i for i in range(50)]

written = 0
for arm, spec in ARMS.items():
    for index, seed in enumerate(SEEDS, start=1):
        (HERE / f"{arm}-c{index}.ini").write_text(HEADER.format(
            title=f"Strength arm {arm}, chunk {index} of {len(SEEDS)}",
            purpose=spec["purpose"], name=spec["name"], arm=arm, index=index,
            sample_size=spec["sample_size"], rounds=spec["rounds"],
            nodes=spec["nodes"], evals=spec["evals"], seed=seed), encoding="utf-8")
        written += 1

print(f"wrote {written} configs: {len(ARMS)} arms x {len(SEEDS)} chunks x 2 games = "
      f"{len(ARMS) * len(SEEDS) * 2} games")
print(f"seeds per arm: {SEEDS[0]} to {SEEDS[-1] + 1}, matching the exact-s16 baseline")
