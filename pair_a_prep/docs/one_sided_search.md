# Serial one-sided search prototype

This advances the source audit in `expansion_mechanism_audit.md`. It is not a
complete Obscuro reproduction or evidence of stronger play.

## Implemented path

Use `AnytimeConfig(growth="one_sided")` with `AnytimePCFRAgent`. The default
`growth="uniform"` remains the complete-frontier reference. The selective agent
identifies itself as `one-sided-pcfr-prototype-v1`; its configuration digest
includes the growth choice. Public observations, sampled candidate histories
and the existing exact history tracker feed the same shared agent interface.

1. Solve a serial stage of PCFR+.
2. Alternate the exploring player after each successful node expansion,
   independently of the solver's update schedule.
3. At explorer infosets, sample half uniformly over positive raw-policy support
   and half at the variance-PUCT argmax. The other player keeps the raw policy;
   chance retains the tree's actual probabilities.
4. Expand one selected nonterminal history leaf by all legal immediate children.
   Unselected histories remain estimates, including indistinguishable histories.
   Expanded occurrences share an infoset minimizer and compatible action order.
5. Initialize newly introduced growth infosets toward the heuristic-best child
   of their first prepared occurrence. Existing state is never reinitialized.
   Alternating mode publishes this policy as pending feedback and extends its
   cached opponent profile. The initial shallow tree is also seeded toward heuristic-best children. Simultaneous growth preserves a new seed until its first feedback, including after completed rounds.
6. Commit only after budget checks and solver validation. A failed preparation
   retains solver state, sampler counts, exploring side and proposal RNG state.
   Terminal/depth-limited samples consume RNG but do not alternate the explorer.
7. Reserve final solving work and return the raw last iterate. No purification.

`ChessGadget.expand(selected_paths=...)` supports the same partial-history path
translation, including Resolve enter paths and Maxmargin payoff offsets. The
automatic sampler is connected to the raw-tree agent only. The integrated subgame prototype also seeds gadget growth; the generic gadget API still requires externally supplied boundaries.

## Explicit engineering conventions

- Conditional action utilities use current-profile joint-reach weighting over
  expanded occurrences of the information set. At zero joint reach, occurrences
  receive equal weight. This fallback is an approximation, not hidden truth.
- Variance is population variance over utility samples with prior samples -1
  and +1. Priors do not count as expansion visits. Each successful traversal
  updates every action's conditional-utility sample at visited explorer infosets;
  visit counts increase only for selected actions. C=1. Ties use action order.
- Utilities are recomputed over the current partial tree for each proposal.
  Counts and samples persist within the turn only. Terminal or depth-limited
  samples wait until the next scheduled growth opportunity, without rejection
  sampling or conditioning the strategy on frontier availability.
- Deadlines are cooperative, including utility traversal. An evaluator call or
  CFR round cannot be interrupted. Tree copying and samples are extra memory;
  max_nodes bounds the committed chess tree, not total process memory.
- The locked evaluation protocol must identify the evaluator separately. The
  included smoke uses Material, not the paper's Stockfish 14 D1/MultiPV.

## Reproduce the evidence

From the repository root, using the existing Pair B environment:

```powershell
& .\pair_b\.venv\Scripts\python.exe -m pair_a_prep.one_sided_experiment --output pair_a_prep/local_runs/one-sided.json
& .\pair_b\.venv\Scripts\python.exe -m pair_a_prep.presentation_materials
& .\pair_b\.venv\Scripts\python.exe -m pytest -q tests pair_a_prep/tests
```

`results/one_sided_reference.json` includes seeds, source hashes, configurations,
per-turn work/timing and two colour-swapped six-ply integration runs. Both runs
were capped and have null outcomes, with no over-budget moves at a 10-second
diagnostic budget. Tracker time lies outside the per-action budget in the shared
runner. These are synthetic kings-only fixtures, not a strength evaluation.

For three root seeds, uniform growth used 68 nodes / 13 evaluator calls; selective
growth used 22-24 nodes / 5 calls. This compares actual work under equal upper
limits and 12 solver rounds, not equal evaluator work or equal achieved depth.
Recorded wall times are machine-specific single measurements, not a benchmark.

## Remaining full-agent work

The optional subgame stack now implements sampled-tree knowledge projection,
boundary/gift updates, cross-turn rerooting, initial-tree best-child seeding and
purification. These are prototypes, not a full Obscuro reproduction. Remaining
work includes exact knowledge closure beyond the saved sample, numerical
ancestor gadget-payment lifting, agreed root replenishment/weights, bounded
history-preserving inference, Stockfish 14 calibration and long-game validation.
ZS21's position-merging tracker is not a drop-in history-preserving root supply.
The shared FoW-effective EP repetition correction is now on main via #37.
