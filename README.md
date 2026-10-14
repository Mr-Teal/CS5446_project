# Fog-of-war chess: shared code

This directory currently contains only the common interface. Neither ZS21 nor
Obscuro is assigned or implemented here. The PDF proposal describes earlier
R1–R3 work, but no such source files were present in this directory.

## Integration contract (schema v1)

- `fow_shared/contracts.py`: `Observation` contains what the acting player can
  actually see, including visibly empty squares and the legal UCI moves. It
  never contains a referee board. `HistoryEvent` records each player's own
  observation after every ply and their own move when applicable. `Belief`
  contains sampled complete FENs and optional `history_id`/hypothetical move
  paths, so two candidate histories can reach the same FEN without being
  merged. These are inferred possibilities, never the referee's private game
  record. Belief also contains
  weights conditional on that sample. `AgentInput` joins them with a time
  budget. `Decision.root_policy` is the **unpurified** strategy and covers all
  legal moves; `Decision.move` is the move actually played.
- `fow_shared/interfaces.py`: both agents implement `Agent.reset/act`. A belief
  tracker implements `BeliefTracker.reset/update`. The match runner alone owns
  `Referee` and passes only `AgentInput` to the agent.
- `fow_shared/recording.py`: `TrainingRecord` JSONL is the handoff to Pair B.
  Values are from the acting player's perspective in `[-1, 1]`; metadata includes
  seed, agent name, and a configuration ID.
- `fow_shared/features.py`: candidate network input `(N, 26, 8, 8)` plus
  `(N,)` normalized hypothesis weights. Plane names and orientation are in
  `PLANE_NAMES`. It requires a rules-specific opponent-visibility callback.
- `fow_shared/evaluation.py`: one common `MatchConfig` and `play_game` loop,
  with per-ply move, runtime, budget-overrun flag and search-node records. A
  ply cap is recorded as a separate draw condition. Both players' trackers
  receive observations after every ply. The loop measures an
  overrun but does not interrupt an agent mid-call; process-level time limits
  belong in the eventual match runner.

## Decisions to review together

1. **Rule authority:** choose the exact chess.com/OpenSpiel-compatible rule
   adapter, including visibility, castling, en passant, king capture, draw
   detection and legal-move feedback. The referee adapter is intentionally a
   protocol until that comparison is complete. `python-chess` is used here to
   parse hypothesis FENs; its ordinary legal-move generator is **not** a FoW
   referee.
2. **Belief meaning:** `population_size` is the count before sampling; weights
   sum to one **within the sample**. The default identifier is `uniform`.
   Record any different sampling/weighting scheme under a new identifier.
   The proposal's 256-board cap belongs to a sampler or training loader, not
   the belief schema.
3. **Feature count:** the pitch numbers planes `0..25`, which is 26 planes.
   Its “17 per-board + 8 shared” phrase totals 25. The numbered list actually
   contains 17 per-board and 9 shared planes. This encoder follows the
   numbered list, uses `log2(population_size)/15`, and rotates Black positions
   180 degrees. Pair B should approve or change it before label collection.
4. **Hidden information:** visibility passed to `encode_belief` must be computed
   from each hypothesis, not the true board. Observations and hypotheses are
   checked against each other on visible squares. The belief tracker must
   update solely from the observation stream. `AgentInput.history` stores
   player-visible observations and own actions, never a true-board sequence.
   Each agent may also cache its prior search tree and solver strategy after
   `act`; `reset` clears that cache for the next game.
   A FEN alone does not encode the observation history, the opponent's
   information set, or threefold-repetition history. Do not deduplicate
   hypotheses solely by FEN when those distinctions matter.
5. **Evaluation settings:** agree on per-move budget, Stockfish version/depth,
   seeds, colours and opening set. Store these in versioned config files before
   comparing agent win rates.

## Run the checks

Install dependencies from `pyproject.toml`, then run `python -m pytest -q`.
The checks cover legal-action rejection, weight normalization, feature layout,
visible-state consistency, and JSONL round trips.
