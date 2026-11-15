# PPO self-play agent with the belief input (15 Nov 2026)

The first PPO agent (`../ppo_selfplay/`) with one change: its input is the team's 32-plane belief
picture instead of its own view with a memory of last-seen pieces. This folder holds the agent, its
network, a player for `pair_c.run_evaluation`, and the records of its matches against the Material
OnePlyBot, misty, the policy network and the first PPO agent.

Read `pair_b/docs/handover_ppo_belief_agent_2026-11-15.md` first: results, how to run, limits.

The agent keeps its belief in a small C++ library. Build it once before anything else:
`python player/kernel/build.py`.

| Folder | What |
|---|---|
| `player/` | `ppo_belief_player.py` (factories for the runner), the `fowppo_belief` package (agent, belief sampler bridge, network, training code) and `kernel/` (the belief sampler's source and build) |
| `checkpoints/ppo-belief-5h/` | The network and its facts |
| `configs/` | Example configurations |
| `scripts/` | Write configurations, play an arm in parallel, count different games |
| `results/` | Game records (one archive per arm), one row per game in `all_games.csv` |
| `tests/` | 39 tests |
| `training/` | Half-hourly matches during training, matches against the first PPO agent, training logs, the scripts as run |
