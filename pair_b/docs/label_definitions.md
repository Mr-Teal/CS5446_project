# Label definitions for solver training records

Status: Pair B proposal, for Pair A to check before the label pilot (see the discussion on #2).
It changes no shared code. It fixes what the existing `TrainingRecord` fields mean when Pair A's
agents write them, so every label run means the same thing. Items marked **proposal** need
Pair A's view; the open questions are collected at the end.

## Why one meaning matters

Pair B's belief network learns to predict these numbers from the belief alone. If one run
labels values under the raw policy and another under the purified one, or weights the boards
differently, the network learns a mixture of the two and no comparison is clean.

## One record is one decision

Every decision the labelling agent makes, for either colour, gives one `TrainingRecord`, written
with `fow_shared.recording` and split by whole game through `game_id`.

| Field | Definition |
|---|---|
| `agent_input.belief` | Exactly the root positions the solver used, sampled and retained (Obscuro's 256 is a minimum target, not a cap), in the same order as the values below, with their sampled-root weights (summing to 1). `population_size` is the number of consistent positions before sampling. FENs are written with `standard_fen`. |
| `hypothesis_values[i]` | Expected game result for the acting player (+1 win, 0 draw, -1 loss) if hypothesis `i` is the true position and both players then follow the solver's raw strategy profile in the solved subgame, with frontier nodes taking the leaf evaluator's values. One value per hypothesis, in belief order. |
| `root_value` | The weighted mean of the hypothesis values, using the belief's weights: `sum_i w_i * hypothesis_values[i]`. Not the gadget's opponent-root prior, which stays separate (paper_specs: "Keep sampled-root weights distinct from the gadget's opponent-root prior"). |
| `decision.root_policy` | The solver's raw root strategy: Obscuro's last PCFR+ iterate (O26 App. C.7), or ZS21's LP solution. Never the purified policy. |
| `decision.move` | The move actually played: sampled from the purified policy for Obscuro (O26 App. C.7–C.8), from the raw policy for ZS21. |
| Perspective | Always the acting player's (`observation.player`), in [-1, 1], as everywhere in `fow_shared`. |

These values depend on the belief, not just the board: the same position can be worth different
amounts under different beliefs, because the solver's strategy depends on what each player
knows. That dependence is what the belief network has to learn, as the value networks of
DeepStack and ReBeL learn the values of a subgame's root states under the solved strategy.

## Proposals

1. **proposal: raw last iterate, not the average.** Labels use the strategy the agent actually
   holds before purification. The PCFR+ average strategy stays a diagnostic.
2. **proposal: values of the subgame itself.** A hypothesis value is the value of entering the
   subgame at that root, not a gadget's alternate or opt-out value. The solver's own root
   estimate, if it differs, goes in `decision.diagnostics["solver_root_value"]`.
3. **proposal: record the played policy too.** `Decision` has no field for the purified
   distribution. Either store it in `decision.diagnostics` as `played_policy:<uci>` entries, or
   add an optional field in a small shared change.
4. **proposal: settings named by `config_id`.** A versioned config file names the agent and its
   code commit, an iteration budget (not wall-clock, so a seed reproduces the record), the leaf
   evaluator `stockfish-19-d1` (MultiPV, 1 thread, 16 MB hash, cleared before each call), the
   root-sample target (256 for Obscuro, `L=200` for ZS21), the purification mode and the rules
   profile `paper_fow_v1_proposed`. `config_id` is that file's name plus a short hash of it.
5. **proposal: games.** Self-play of the labelling agent against itself, a fresh `game_id` and
   seed per game, and 2–8 random opening plies for variety, as in Pair B's practice data.

## Checks in the pilot (Pair B)

Before any long run, on a small batch:

- every record passes the `TrainingRecord` and `LeafValues` validation;
- `|root_value - sum_i w_i * hypothesis_values[i]| <= 1e-6` on every record;
- the same seed and config reproduce the same record exactly;
- time and memory per decision, and that a crashed run restarts from its last finished game;
- the belief network's encoder accepts every record (`fow_shared.features.encode_belief`).

## Open questions for Pair A

1. Do the proposals above match what your solvers can expose? In particular, can each solver
   report a value per root position under the final strategy profile?
2. Played policy: diagnostics entries, or a new optional field?
3. If the tracker merges transpositions, how do merged roots map to `Hypothesis` entries and
   their weights?
4. Which iteration budget makes a decision affordable for about 10,000 labelled decisions?
