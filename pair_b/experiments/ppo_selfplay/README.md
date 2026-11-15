# PPO self-play agent (15 Nov 2026)

A PPO agent for fog-of-war chess that plays from its own view, with no belief and no search; its
network; a player for `pair_c.run_evaluation`; and the records of its matches against the Material
OnePlyBot, misty and the policy network.

Read `pair_b/docs/handover_ppo_agent_2026-11-15.md` first: results, how to run, limits.

| Folder | What |
|---|---|
| `player/` | `ppo_player.py` (factories for the runner) and the `fowppo` package (agent, network, training code) |
| `checkpoints/ppo-selfplay-12h/` | The network and its facts |
| `configs/` | Example configurations |
| `scripts/` | Write configurations, play an arm in parallel, recount |
| `results/` | Game records (one archive per arm), one row per game in `all_games.csv` |
| `tests/` | 31 tests |
| `training/` | Hourly matches during training, earlier matches, training logs, the scripts as run |
