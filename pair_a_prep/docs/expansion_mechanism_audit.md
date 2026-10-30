# Expansion mechanism audit

Checked 26 October 2026 against the supplied `2506.01242v2.pdf` (29 pages),
especially section 3.3, pp. 5-6; section 3.4, p. 6; Appendix C.4, pp. 17-18;
and Appendix C.5, p. 18. The PDF's printed pages match one-based PDF pages.
Online primary reference: [Zhang and Sandholm, v2](https://arxiv.org/pdf/2506.01242v2).
This is a source/implementation audit, not a new expansion implementation.
Implementation update, 27 October: [one_sided_search.md](one_sided_search.md)
records the new optional selective mode, evidence and remaining approximations.
The comparison table below preserves the audited pre-implementation baseline.

## What the paper specifies

1. Alternate the exploring player after **each node expansion** (C.4 footnote
   15). This is distinct from the alternating PCFR+ update schedule.
2. The other player follows its current CFR strategy. Only the exploring
   player uses the exploration policy. It is not simultaneous exploration by
   both players, nor ordinary minimax/UCT applied independently to each board.
3. At an exploring-player information set I, form an exploitation distribution
   uniform over the positive support of the current CFR policy:

   ```text
   support(a | I) = 1 / |{b: x(b | I) > 0}| if x(a | I) > 0, else 0
   ```

   This is not the original probability-weighted policy x.
4. Form a deterministic PUCT choice using the source's score:

   ```text
   Qbar(I, a) = u(x, y | I, a)
                + C * sigma(I, a) * sqrt(N(I)) / (1 + N(I, a))
   explore(a | I) = 1 if a is the selected argmax of Qbar, else 0
   sample(a | I) = 0.5 * support(a | I) + 0.5 * explore(a | I)
   ```

   C is 1 in the paper. C.4 calls sigma the empirical **variance**, with prior
   utility samples -1 and +1; do not silently replace it with a fixed policy
   prior, a standard deviation, or an ordinary UCT logarithmic bonus. N(I)
   counts expansion visits, and N(I,a) selected actions. Keep those statistics
   separate from solver-round counts and from repeated FEN counts.
5. Select a leaf by traversing under that one-sided strategy profile. On the
   selected nonterminal leaf, add **all immediate children** (C.5). Terminal
   outcomes are not evaluator frontiers.
6. Evaluate the selected parent's children with Stockfish 14, depth 1, MultiPV,
   returning child values in one call and converting them to the solver's
   bounded utility convention. Our adapter must still override estimates for
   real FoW terminal outcomes and keep utility perspectives explicit.
7. When an information set is first introduced, initialize its local strategy
   to the heuristic-best action of the first expanded node, rather than a
   uniform strategy. Subsequent nodes in that information set share the same
   minimizer; they must not reinitialize it per hidden board.
8. Solving and growth run concurrently in the original implementation (one
   solving thread and two expansion threads). Stop expansion before stopping
   equilibrium computation. Serial stages can be a documented approximation.

The C.4 asymptotic statement concerns **average strategies** in finite games.
The implementation's choice to act using the last iterate is discussed
separately. This theorem does not establish last-iterate convergence or a
guarantee for our budget-limited chess agent.

## Correction to the earlier development shorthand

Our complete-cut expansion is an engineering baseline, **not a paper
requirement**. The paper selects an individual history leaf; it does not say
to expand every history in the same information set or every frontier in one
batch. It also need not expand the whole game tree (C.4, p. 18).

The invariant is that **expanded decision nodes sharing an information set use
one action distribution and compatible action order**. Do not confuse that
strategy constraint with a requirement to expand all indistinguishable
histories at once. Our all-frontier API currently enforces a stronger common-cut
restriction for simplicity. A selective API needs an explicit partial-tree
contract for expanded and still-estimated occurrences, while preserving shared
strategy, perfect recall and atomic failure behavior.

## Current implementation comparison

| Concern | Current code | Difference / next action |
|---|---|---|
| Expansion unit | `expand_chess_tree` grows every frontier by the same extra depth | Add selected-history-leaf preparation; preserve complete-cut mode as a baseline. |
| Exploring side | `AnytimePCFRAgent` has no expansion-player alternation | Track expansion event number independently of PCFR+ rounds. |
| Sampling | No support/PUCT expansion sampler | Add seeded traversal with shared-I utility/visit statistics. |
| New local policies | `PCFRPlus.expand` initializes new minimizers uniformly | Add explicit optional first-policy initialization, including alternating pending feedback and cached-opponent state. Preserve existing minimizers. |
| Frontier heuristic | Generic `evaluate_children`, tested with Material and Stockfish | Pin evaluator/engine settings; keep actual terminal overrides and signs. |
| Information identity | Private observation/action streams | Reuse the keys; never use the real board or history index to choose a player's behavioral policy. |
| Budget schedule | Serial solve stages, uniform growth, final-round/time reserve | Useful prototype approximation; not the original multithreaded schedule. |
| Gadget growth | Path/key/offset translation is available | Selective growth must apply the same translation, including unshifted continuation labels. The current budgeted agent does not use gadgets. |
| Saved state | Old solver state retained inside one turn | Cross-turn rerooting and blueprint/gift updates remain separate work. |

## Decisions to settle before implementation

The paper provides the central formula but not every closed-source engineering
choice. Record these as implementation choices rather than silently guessing:

- How the conditional utility u(x,y | I,a) is obtained and weighted across
  histories, including zero-reach information sets. A single omniscient board
  score is not automatically the required information-set action value.
- Sample versus population variance; whether variance priors count as visits;
  when a visit updates all action utilities; deterministic tie-breaking.
- Root chance traversal must respect the chosen game/gadget root distribution.
  Belief weights, Resolve prior and Maxmargin selector are different objects.
- Handling partially expanded occurrences of an information set, including
  shared action order, initialization once, and utility accounting.
- Whether a failed budget-limited attempt advances the exploring-player counter
  or visit statistics. Distinguish successful expansion events from attempts.

## Proposed acceptance sequence

1. Pure sampler tests: support is uniform over nonzero actions; mixture is
   exactly half/half; nonexploring policies remain unchanged; tie/variance
   conventions and zero visits are explicit and seeded replay is deterministic.
2. Tiny history-tree test: alternate exploring side after each successful
   expansion; permit unrelated leaves to stay estimated; shared-I policies
   remain shared; compare completed small trees with the LP reference.
3. Optional nonuniform minimizer initialization test: initialize each new I
   once, preserve existing regrets/averages/predictions, and test alternating
   mode's pending state before connecting it to chess.
4. Connect retained `HistoryRoot` contexts to selected chess paths and gadget
   translations. Test hidden histories, same-FEN paths, repetition, both colours
   and partial preparation failures.
5. Compare with the present uniform baseline using actual evaluator work and
   time, not final depth alone. This is not a promise of stronger play.
