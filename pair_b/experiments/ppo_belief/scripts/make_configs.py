"""Write the configurations of one arm for the team's match runner (pair_c.run_evaluation).

    python scripts/make_configs.py belief-vs-policy-fuzzy --games 100 --chunk 2 --device cuda

The files go to configs/<name>/ in this package. The belief-input PPO network is player A, so every
score is from its side. The protocol is the one of the first PPO agent's matches, of Pair A's strength
arms and of the policy-network handover of 15 November: standard start, colours alternate (A is White
in odd games), rules = teal, 5 s per move (no player here uses the clock), 200-ply cap, and game g of
the arm has seed 1000 + g.

Paths in the files: each PPO checkpoint is relative to its own package (its player resolves it). The
policy-network checkpoints and the output folder are relative to the team repository, so start the
runner from the repository root, as the policy-network handover says.
"""
import argparse
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]

BELIEF = """[player_a]
name = PPO self-play network with belief input (final network of the 5-hour run; own belief sampler, no search; move choice: {choice})
factory = ppo_belief_player:PpoBeliefFactory
checkpoint_path = checkpoints/ppo-belief-5h/final.pt
move_choice = {choice}
device = cpu
leaf_depth = 0
tracker_factory = ppo_belief_player:NoBeliefFactory
"""

OPPONENTS = {
    # Player B of Pair A's strength arms (for example strength-netv2-fe-s16), unchanged.
    "belief-vs-oneply-material": """[player_b]
name = Material OnePlyBot (particle tracker)
factory = pair_c.agent_factories:Factory
scorer_id = material
leaf_depth = 0
device = cpu
tracker_factory = pair_c.tracker_factories:Factory
tracker_particles = 256
tracker_hypotheses = 8
tracker_rebuild_tries = 2000
""",
    # Player A of the handover's proposed match (pair_b/docs/handover_policy_network_2026-11-15.md, section 5).
    "belief-vs-policy-fuzzy": """[player_b]
name = Policy network, no search (fuzzy board, 56,437 positions, seed 2)
factory = pairb.policy_agent:PolicyFactory
checkpoint_path = pair_b/checkpoints/policy-conv-fuzzy-r2-s2/best.pt
device = {device}
leaf_depth = 0
tracker_factory = guard_tracker:Factory
max_states = 96000
sample_size = 16
max_candidates = none
tracker_policy = exact
tracker_backend = auto
""",
    # The handover's other checkpoint ("CHOICE A"): every-board input.
    "belief-vs-policy-every-board": """[player_b]
name = Policy network, no search (every board, 56,437 positions, seed 2)
factory = pairb.policy_agent:PolicyFactory
checkpoint_path = pair_b/checkpoints/policy-conv-gen0r2-s2/best.pt
device = {device}
leaf_depth = 0
tracker_factory = guard_tracker:Factory
max_states = 96000
sample_size = 16
max_candidates = none
tracker_policy = exact
tracker_backend = auto
""",
    # The first PPO agent (pair_b/experiments/ppo_selfplay), with its player section of its own matches.
    "belief-vs-ppo": """[player_b]
name = PPO self-play network (final network of the 12.2-hour run; no belief, no search; move choice: sample)
factory = ppo_player:PpoFactory
checkpoint_path = checkpoints/ppo-selfplay-12h/final.pt
move_choice = sample
device = cpu
leaf_depth = 0
tracker_factory = ppo_player:NoBeliefFactory
""",
}

MATCH = """[match]
games = {games}
alternating_colors = true
rules = teal
time_budget_ms = 5000
max_plies = 200
initial_fen =
seed = {seed}
seed_mode = per_game

[output]
directory = {output}
hash_rules = pair_c/hash_rules.json
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("arm", choices=sorted(OPPONENTS))
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--chunk", type=int, default=2, help="games per process; even, so that odd seeds stay White for A")
    parser.add_argument("--first-game", type=int, default=1, help="odd; game g has seed 1000 + g")
    parser.add_argument("--move-choice", choices=("sample", "best"), default="sample")
    parser.add_argument("--device", default="cpu", help="device of the policy network: cpu, cuda, mps")
    parser.add_argument("--out", default="pair_c/runs/ppo-belief", help="output root, relative to the team repository or absolute")
    parser.add_argument("--name", help="folder name under configs/ and under --out (default: the arm, plus -best)")
    args = parser.parse_args()
    if args.chunk % 2 or args.games % 2 or args.first_game % 2 == 0:
        parser.error("--games and --chunk must be even and --first-game odd")
    name = args.name or args.arm + ("" if args.move_choice == "sample" else "-best")
    folder = PACKAGE / "configs" / name
    folder.mkdir(parents=True, exist_ok=True)
    player_a = BELIEF.format(choice=args.move_choice)
    player_b = OPPONENTS[args.arm].format(device=args.device)
    last = args.first_game + args.games - 1
    for first in range(args.first_game, last + 1, args.chunk):
        end = min(first + args.chunk - 1, last)
        label = f"games-{first:03d}-{end:03d}"
        text = (f"; {name}, games {first} to {end} (seeds {1000 + first} to {1000 + end}). Written by make_configs.py.\n\n"
                + player_a + "\n" + player_b + "\n"
                + MATCH.format(games=end - first + 1, seed=1000 + first, output=f"{args.out.rstrip('/')}/{name}/{label}"))
        (folder / f"{label}.ini").write_text(text, encoding="utf-8")
    print(f"wrote {len(list(folder.glob('games-*.ini')))} configuration(s) in {folder}")


if __name__ == "__main__":
    main()
