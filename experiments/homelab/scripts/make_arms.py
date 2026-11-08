"""Generate the strength-comparison arms.

Three arms, all against the same one-ply bot on the SAME Material evaluator, so the
only thing differing between the two sides is Pair A's search and belief.

  exact-s16     exact belief, search sees 16 hypotheses. Our current default.
  exact-s256    exact belief, search sees 256. Obscuro's MinInfosetSize is 256
                (Fig. 9, p. 27) and no document records 16 as a deviation from it.
  pruned-s16    belief capped at 10,000 histories between plies, search sees 16.
                Measures what a drifting belief costs in played games.
  pruned-s256   belief capped the same way, search sees 256. If the sample size
                matters more than exactness, this is the feasible sweet spot:
                bounded memory with the paper's infoset floor. Comparing it with
                exact-s256 isolates exactness at a fixed sample size, and with
                pruned-s16 isolates sample size at a fixed belief.

Pairing. seed_for_game is seed + game_index, so every game has its own seed, and
colour alternates with the index. A given seed therefore means the same position and
the same colour in every arm, and the paired unit is one seed.

Chunk size is two, the smallest that keeps colour balance: index 0 plays Pair A as
white and index 1 as black, so a chunk covers one seed of each colour. Small chunks
matter because some games cost more memory than this host can give: seed 1003
exceeded a 4.5 GiB container twice, before and after the state-packing change. A
chunk that dies costs two games rather than five, every other seed is still
attempted in every arm, and the analysis pairs only on seeds that completed in both.
"""
import pathlib

HERE = pathlib.Path(__file__).resolve().parent

HEADER = """; {title}
;
; {purpose}
;
; Material evaluator on BOTH sides: the VM has no SF19, and equal evaluators isolate
; the search rather than confounding it with leaf strength. Standard start, alternating
; colours, 5 s per move, 200-ply cap.
;
; Paired design: every arm runs these same seeds with the same colours, so a difference
; is measured within a seed rather than between samples.
;
; tracker_policy is exact with max_candidates = none. budgeted-exact charges
; 4096 + 512*(ply+1) bytes per new state against a logical cap, about seven times the
; measured cost at ply 15, and aborts games that have ample real memory.

[player_a]
name = {name}
factory = pair_a_prep.evaluation_factories:SearchFactory
search_mode = subgame
leaf_evaluator = material
leaf_depth = 0
{tracker}
sample_size = {sample_size}
max_candidates = none
tracker_policy = exact
tracker_backend = auto

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
directory = pair_c/runs/{out}
hash_rules = pair_c/hash_rules.json
"""

EXACT_TRACKER = "tracker_factory = pair_a_prep.evaluation_factories:HistoryTrackerFactory"
PRUNED_TRACKER = ("tracker_factory = pruned_tracker:Factory\n"
                  "max_histories = 10000")

ARMS = {
    "exact-s16": dict(
        name="Pair A subgame PCFR+ (exact belief, sample_size 16)",
        tracker=EXACT_TRACKER, sample_size=16,
        purpose="ARM 1. Exact belief, the search sees 16 hypotheses. Our current default."),
    "exact-s256": dict(
        name="Pair A subgame PCFR+ (exact belief, sample_size 256)",
        tracker=EXACT_TRACKER, sample_size=256,
        purpose="ARM 2. Exact belief, the search sees 256 hypotheses, which is Obscuro's\n"
                "; MinInfosetSize (Fig. 9, p. 27). Measures whether our default of 16 costs\n"
                "; anything, since no document records it as a deviation."),
    "pruned-s256": dict(
        name="Pair A subgame PCFR+ (belief pruned to 10k histories, sample_size 256)",
        tracker=PRUNED_TRACKER, sample_size=256,
        purpose="ARM 4. Belief pruned to 10,000 histories, search sees 256. Tests whether\n"
                "; bounded memory and a paper-sized infoset can be had together."),
    "pruned-s16": dict(
        name="Pair A subgame PCFR+ (belief pruned to 10k histories, sample_size 16)",
        tracker=PRUNED_TRACKER, sample_size=16,
        purpose="ARM 3. Belief pruned to 10,000 histories between plies, search sees 16.\n"
                "; Measures what a drifting belief costs. Replay at cap 1,000 loses the true\n"
                "; path on games peaking below 2,100 states and aborts one game outright."),
}

# 50 chunks of 2 games: seeds 1001-1100, one white and one black game per chunk.
SEEDS = [1001 + 2 * i for i in range(50)]

written = 0
for arm, spec in ARMS.items():
    for index, seed in enumerate(SEEDS, start=1):
        (HERE / f"{arm}-c{index}.ini").write_text(HEADER.format(
            title=f"Strength arm {arm}, chunk {index} of {len(SEEDS)}",
            purpose=spec["purpose"], name=spec["name"], tracker=spec["tracker"],
            sample_size=spec["sample_size"], seed=seed,
            out=f"strength-{arm}-c{index}"), encoding="utf-8")
        written += 1

print(f"wrote {written} configs: {len(ARMS)} arms x {len(SEEDS)} chunks x 2 games = "
      f"{len(ARMS) * len(SEEDS) * 2} games")
print(f"seeds per arm: {SEEDS[0]} to {SEEDS[-1] + 1}")
