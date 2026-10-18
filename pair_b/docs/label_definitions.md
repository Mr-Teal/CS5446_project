# Label definitions for solver training records

Status: agreed in outline with Pair A on #5 (18 October 2026). It changes no shared code. It fixes
what the existing `TrainingRecord` fields mean when Pair A's agents write them, so every label run
means the same thing. Items marked **proposal** still need Pair A's view; the points still open
are collected at the end.

## Why one meaning matters

Pair B's belief network learns to predict these numbers from the belief alone. If one run
labels values under the raw policy and another under the purified one, or weights the boards
differently, the network learns a mixture of the two and no comparison is clean.

## One record is one decision

Every decision the labelling agent makes, for either colour, gives one `TrainingRecord`, written
with `fow_shared.recording` and split by whole game through `game_id`.

| Field | Definition |
|---|---|
| `agent_input.belief` | Exactly the root positions the solver used, sampled and retained (Obscuro's 256 is a minimum target, not a cap), in the same order as the values below, with their sampled-root weights (summing to 1). `population_size` is the number of consistent positions before sampling, or `None` when that number is unknown, as the shared contract allows. FENs are written with `standard_fen`. |
| `hypothesis_values[i]` | Expected game result for the acting player (+1 win, 0 draw, -1 loss) if hypothesis `i` is the true position and both players then follow the solver's raw strategy profile in the solved subgame, with frontier nodes taking the leaf evaluator's values. One value per hypothesis, in belief order. |
| `root_value` | **The training target:** the weighted mean of the hypothesis values, using the belief's weights, `sum_i w_i * hypothesis_values[i]`. Not the gadget's opponent-root prior, which stays separate (paper_specs: "Keep sampled-root weights distinct from the gadget's opponent-root prior"). A different internal estimate of the solver goes in `decision.diagnostics["solver_root_value"]`. |
| `decision.root_policy` | The solver's raw root strategy: Obscuro's last PCFR+ iterate (O26 App. C.7), or ZS21's LP solution. Never the purified policy. |
| `decision.move` | The move actually played: sampled from the purified policy for Obscuro (O26 App. C.7–C.8), from the raw policy for ZS21. |
| `decision.diagnostics["played_policy:<uci>"]` | The distribution the played move was sampled from, one entry per legal move: the purified policy for Obscuro, the raw one for ZS21. |
| Perspective | Always the acting player's (`observation.player`), in [-1, 1], as everywhere in `fow_shared`. |

These values depend on the belief, not just the board: the same position can be worth different
amounts under different beliefs, because the solver's strategy depends on what each player
knows. That dependence is what the belief network has to learn, as the value networks of
DeepStack and ReBeL learn the values of a subgame's root states under the solved strategy.

## How label games are played

- Self-play of the labelling agent against itself, with a fresh `game_id` and seed per game.
- For variety, each game opens with 2–8 random plies, as in Pair B's practice data. They are
  played through the runner from the initial position, so both trackers receive every
  observation, and their own moves, from ply 0. No tracker is ever initialised from the true
  position after the opening: that would reveal hidden information.
- Every decision of both players after the opening is recorded.

## Settings

A versioned config file, named by `config_id` (the file's name plus a short hash of it), records:

- the agent and its code commit, and the rules profile `paper_fow_v1_proposed`;
- the leaf evaluator `stockfish-19-d1` (MultiPV, 1 thread, 16 MB hash, cleared before each call);
- the root-sample target (256 for Obscuro, `L=200` for ZS21);
- each solver's own search and expansion limits and stopping conditions, since they differ:
  for ZS21 the LP solver, its tolerances and the trunk-deepening limits; for Obscuro the PCFR+
  iterations, the tree-growth schedule and when expansion stops before final solving;
- the purification mode;
- the per-move budget, chosen from the pilot's measurements.

## Proposals

1. **proposal: raw last iterate, not the average.** Labels use the strategy the agent actually
   holds before purification. The PCFR+ average strategy stays a diagnostic.
2. **proposal: values of the subgame itself.** A hypothesis value is the value of entering the
   subgame at that root, not a gadget's alternate or opt-out value. Before the label run, both
   solvers must be shown to expose these per-root values under the final raw strategy profile.

## Checks in the pilot

Before any long run, on a small batch:

- every record passes the `TrainingRecord` and `LeafValues` validation;
- `|root_value - sum_i w_i * hypothesis_values[i]| <= 1e-6` on every record;
- each solver reports a value per root position under the final raw strategy, gadget opt-out
  values excluded (Pair A);
- **reproducibility:** under a fixed environment and config, a rerun reproduces the sampled
  hypotheses exactly, and the policies and values within an explicit tolerance (proposal: 1e-6),
  comparing everything except runtime diagnostics such as timings. A fixed iteration budget alone
  may not make records identical, so this is measured, not assumed;
- time and memory per decision, and that a crashed run restarts from its last finished game;
- the belief network's encoder accepts every record (`fow_shared.features.encode_belief`).

## Still open

1. **Per-root values:** confirm that both solvers can expose them as defined above (Pair A,
   before committing to the label run).
2. **Transpositions:** how merged roots map to `Hypothesis` entries and their weights. Pair A will
   confirm this while building the tracker; equal FENs alone are not enough to merge, because
   repetition history and information histories can differ.
3. **Budget:** chosen from the pilot's measurements, about 10,000 labelled decisions in all.
