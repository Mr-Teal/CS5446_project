# Pair C Match Evaluation

This runner plays a configurable number of complete Fog-of-War chess games between two independently constructed players. Each side has its own factory-class instance, Agent instance, and model resources. The default configuration is an ablation example: it uses the same Pair B `OnePlyBot` factory class twice, loading a different scorer for each player.

## Run

From the repository root, activate the Python environment that has the project dependencies installed, then run:

```powershell
python pair_c/run_evaluation.py
```

The default configuration is `pair_c/evaluate_config.ini`. An alternative INI file can be passed as the first argument:

```powershell
python pair_c/run_evaluation.py path/to/another_config.ini
```

## Configuration

See `evaluate_config.ini` for configuration details.

## Evaluate Other Agents

You should provide a factory class whose only user implementation is `load_model`. Pair C reuses `fow_shared.evaluation.play_game` for each single game, so `load_model` must return an Agent providing `name`, `reset(player, seed)`, and `act(turn) -> Decision`. See the `Factory` class and the `--- Your Code Start Here ---` markers in `pair_c/agent_factories.py`;  Keep the framework `__init__` unchanged. The factory itself does not define `reset`, `act`, or `close`; those belong to the Agent returned by `load_model`. Set the player's `factory` entry to `your_module:YourFactory`. If your model needs additional configuration options, contact Zhijian Wang so he can add them.

## Results

The output directory contains:

- `evaluate_config.ini`: a copy of the exact configuration used.
- `games.jsonl`: one JSON record per attempted game, including player identities and colors, seed, winner, termination reason, every move, and per-move elapsed time. Failed games are recorded with an error.
- `summary.json`: wins, draws, losses, win rate, score rate, completed/failed game counts, move timing, and over-budget counts.

Win rate is `wins / completed games`. Score rate follows the paper's convention: `(wins + 0.5 * draws) / completed games`. Failed games are excluded from both rates and shown separately.

## Relation to the Paper

Obscuro's primary AI comparison was a 1,000-game match against ZS21. The paper reports that its AI-versus-AI time budget was usually 5 seconds per move for the main search loop; this excluded legal-position enumeration. This runner defaults to 5,000 milliseconds and records the budget, but the current baseline agent does not enforce it. The paper does not specify the color schedule for the main match. This runner alternates colors each game as a simple, explicit balancing choice. The current `standin` rules and Pair B one-ply players are development baselines, not a reproduction of the paper's complete systems or result.
