"""Write the ini files of the two strength arms for the v2 (engine-free, solver-label) belief network leaf.

  netv2-fe-s16-cN      Pair A subgame PCFR+ with the v2 network leaf  vs  Material OnePlyBot (particle tracker)
                       = the existing net-fe-s16 arm with the new checkpoint; same seeds, colours, 5 s clock,
                       2 games per chunk, so it is directly comparable with fe-s16 (material leaf, 0.919),
                       sf14-fe-s16 (Stockfish d1 leaf, 1.000) and net-fe-s16 (v1 network leaf, 0.967).
  netv2-vs-fe-s16-cN   the same agent  vs  Pair A subgame PCFR+ with the MATERIAL leaf (the fe-s16 agent)
                       = same search on both sides, only the leaf differs; both sides get 5 s per move.

usage: python3 make_netv2_inis.py <experiment dir> <checkpoint path inside the container> [chunks=50]
Runs on the VM host (python3 only). Existing target files are overwritten (they are generated).
"""
import re
import sys
from pathlib import Path

exp = Path(sys.argv[1])
ckpt = sys.argv[2]
chunks = int(sys.argv[3]) if len(sys.argv) > 3 else 50
tag = Path(ckpt).parent.name  # e.g. belief-solver-v2-sf8

material_b = """[player_b]
name = Pair A subgame PCFR+ (exact belief, sample 16, full effort, material leaf)
factory = pair_a_prep.evaluation_factories:SearchFactory
search_mode = subgame
leaf_evaluator = material
leaf_depth = 0
tracker_factory = pair_a_prep.evaluation_factories:HistoryTrackerFactory
sample_size = 16
max_candidates = none
tracker_policy = exact
tracker_backend = auto
solver_rounds = 1024
max_nodes = 16384
max_evaluator_calls = 4096
stop_on_time = true

"""

for n in range(1, chunks + 1):
    src = (exp / f"net-fe-s16-c{n}.ini").read_text()
    a = src.replace("/repo/pair_b/checkpoints/belief-solver-v1/best.pt", ckpt)
    a = a.replace("belief-solver-v1 network leaf", f"{tag} network leaf, engine-free, trained on Stockfish-d8 solver labels")
    a = re.sub(r"^; Strength arm net-fe-s16, chunk (\d+) of 50",
               rf"; Strength arm netv2-fe-s16, chunk \1 of {chunks}: v2 network leaf vs Material OnePlyBot", a, flags=re.M)
    a = a.replace(f"pair_c/runs/strength-net-fe-s16-c{n}", f"pair_c/runs/strength-netv2-fe-s16-c{n}")
    assert ckpt in a and f"strength-netv2-fe-s16-c{n}" in a
    (exp / f"netv2-fe-s16-c{n}.ini").write_text(a)

    b = re.sub(r"\[player_b\].*?(?=\[match\])", material_b, a, flags=re.S)
    b = b.replace("; Strength arm netv2-fe-s16,", "; Strength arm netv2-vs-fe-s16,")
    b = b.replace("vs Material OnePlyBot", "vs the material-leaf subgame agent (same search, only the leaf differs)")
    b = b.replace(f"pair_c/runs/strength-netv2-fe-s16-c{n}", f"pair_c/runs/strength-netv2-vs-fe-s16-c{n}")
    assert "material leaf)" in b and "OnePlyBot" not in b and f"strength-netv2-vs-fe-s16-c{n}" in b
    (exp / f"netv2-vs-fe-s16-c{n}.ini").write_text(b)

    # Head-to-head with the tail-guarded tracker (96,000 states) on BOTH sides: two exact trackers in one 8000m
    # container were memory-killed in 2 of the first 3 chunks (exit 137, 2026-11-10). The guard is the label
    # agent's own setting (label_sf8.pbs MAX_STATES=96000) and the guard-fe-s16 arm had 2 kills in 49 chunks.
    g = b.replace("tracker_factory = pair_a_prep.evaluation_factories:HistoryTrackerFactory",
                  "tracker_factory = guard_tracker:Factory\nmax_states = 96000")
    g = g.replace("(exact belief, sample 16,", "(tail-guarded belief 96000 states, sample 16,")
    g = g.replace("; Strength arm netv2-vs-fe-s16,", "; Strength arm netv2-vs-fe-guard-s16,")
    g = g.replace("(same search, only the leaf differs)", "(same search and guard tracker both sides, only the leaf differs)")
    g = g.replace(f"pair_c/runs/strength-netv2-vs-fe-s16-c{n}", f"pair_c/runs/strength-netv2-vs-fe-guard-s16-c{n}")
    assert g.count("guard_tracker:Factory") == 2 and f"strength-netv2-vs-fe-guard-s16-c{n}" in g
    (exp / f"netv2-vs-fe-guard-s16-c{n}.ini").write_text(g)
print(f"wrote {chunks} netv2-fe-s16, {chunks} netv2-vs-fe-s16 and {chunks} netv2-vs-fe-guard-s16 ini files in {exp} "
      f"with checkpoint {ckpt}")
