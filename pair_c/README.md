# Pair C Match Evaluation

This runner plays a configurable number of complete Fog-of-War chess games between two independently constructed players. Each side has its own Agent factory, Agent, model resources, and tracker factory. Each game receives a new tracker per player. The default configuration is an ablation example: it uses the same Pair B `OnePlyBot` factory class twice, loading a different scorer for each player, and Pair B's `ParticleTracker` for both players.

## Exact tracker budgets and timing

Pair A's history tracker supports an opt-in `tracker_policy=budgeted-exact`.
It resumes interrupted inference and output within an explicit per-update total
time allowance, logical-memory limit and retry count. It returns a complete
uniform sample or fails the attempt; it never silently prunes histories or
submits partial support. See the [settings and semantics](../pair_a_prep/docs/belief_tracker.md#pair-c-evaluation-policy)
and [readiness pilot INI](configs/budgeted_exact_pilot.ini). Existing configurations
retain their original exact policy and 2,000-history capacity limit.

Every tracker update is immediately saved to `tracker_updates.jsonl`, including
updates that fail. The same rows appear under `tracker_updates` in `games.jsonl`.
They record player colour, ply, actual update time including resumes, policy,
retry count, support/work metadata when available, and explicit exhaustion/error
information. Initial and terminal observations are included. Custom trackers
without these metadata fields produce `null` values rather than invented zeros.
`summary.json` reports tracking totals by player identity across colour swaps,
including failed attempts. Existing `timing` and over-budget flags still measure
only `agent.act`; separate tracker budgets are cooperative, not a hard combined
turn deadline. Failed games can still omit partial agent records, so the recorded
agent-plus-tracker aggregate is not full failed-game wall time.

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

Each player section specifies an Agent factory and a tracker factory, both in `python.module:FactoryClass` form. Each factory receives that player's INI settings as strings.

**Agent factory**

1. Set `factory` to your factory class.
2. Implement `load_model()` to return an Agent with `name`, `reset(player, seed)` and `act(turn) -> Decision`. Implement `reset_game()` to clear per-game model state; stateless models may use `pass`. The factory and Agent are reused across games.
3. Follow the Pair B example in `agent_factories.py`: replace the marked method bodies and leave `__init__` unchanged.

**Tracker factory**

1. Set `tracker_factory` to your tracker factory class.
2. Implement `create_tracker()` using the template's signature to return a fresh tracker for each game. It must provide `reset(player, seed)` and `update(observation, own_move=None) -> Belief`. The shared game loop calls these methods; no factory `reset_game()` is needed.
3. Follow the Pair B example in `tracker_factories.py`: replace the marked method body and leave `__init__` unchanged. Parse your tracker's options there; other trackers do not need Pair B's particle settings.

Choose a tracker compatible with your Agent. Pair B's `ParticleTracker` leaves `candidate_moves` empty; Pair A's search requires a tracker that supplies complete candidate paths. See `fow_shared/interfaces.py` for the shared interfaces and `evaluate_config.ini` for a complete configuration example.

## Something about 'Rules'

The current evaluation pipeline supports passing a `rules` object into your tracker through `create_tracker(rules, initial_fen=None)`. The runner creates this object from the match-level `rules` setting (`standin` or `teal`) and passes it to the referee and both tracker factories.

This `rules` object is not a component required by `fow_shared`. The shared interfaces define the methods of an Agent, tracker and referee, but do not require them to accept a rules object or define a shared `Rules` interface.

I included the `rules` argument because Pair B's `GameReferee` and `ParticleTracker` support receiving one. If your Agent and tracker do not use a separate rules object, keep the `rules` parameter in your factory's `create_tracker` signature so the runner can call it, and simply leave it unused in the method body. You do not need to add a rules dependency to your implementation.

## Results

The output directory contains:

- `evaluate_config.ini`: a copy of the exact configuration used.
- `games.jsonl`: one JSON record per attempted game, including player identities, Agent/tracker factory paths and colors, seed, winner, termination reason, every move, and per-move elapsed time. Failed games are recorded with an error.
- `summary.json`: Agent/tracker factory paths, wins, draws, losses, win rate, score rate, completed/failed game counts, move timing, and over-budget counts.

Win rate is `wins / games_scored`; score rate is `(wins + 0.5 * draws) / games_scored`.
`games_scored` includes only observed terminal outcomes. `games_completed` counts
successful runner attempts, including `games_capped`; capped attempts have
`winner: null` and remain separate from terminal draws. Both capped and failed
attempts are excluded from outcome rates. Timing includes successful capped
attempts. A run containing only caps has unavailable outcome rates and can
still exit successfully because a cap is a configured stopping condition.

For the included factory, `leaf_depth` must agree with the scorer: Material=0,
Stockfish D1/Network1/belief=1, and Stockfish D11=11. Mismatches raise before
model/engine loading. This validates metadata without changing Pair B's API;
custom search factories should use separate options for their search depth.

## Relation to the Paper

Obscuro's primary AI comparison was a 1,000-game match against ZS21. The paper reports that its AI-versus-AI time budget was usually 5 seconds per move for the main search loop; this excluded legal-position enumeration. This runner defaults to 5,000 milliseconds and records the budget, but the current baseline agent does not enforce it. The paper does not specify the color schedule for the main match. This runner alternates colors each game as a simple, explicit balancing choice. The current `standin` rules and Pair B one-ply players are development baselines, not a reproduction of the paper's complete systems or result.
