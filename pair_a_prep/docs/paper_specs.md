# Pair A implementation specifications

Prepared 17 October 2026. These are build checklists, not claims that either
agent has been implemented. Agent ownership remains unassigned. Items marked
**proposal** are our engineering choices and require review.

## Fixed primary references

- **Z21:** Zhang and Sandholm, [Subgame solving without common knowledge,
  arXiv:2106.06068v2](https://arxiv.org/pdf/2106.06068v2).
- **O26:** Zhang and Sandholm, [General search techniques without common
  knowledge for imperfect-information games, arXiv:2506.01242v2](https://arxiv.org/pdf/2506.01242v2).

Use the PDF's printed page number; it equals its one-based PDF page number.
The section references below are the authority when the proposal disagrees.

## ZS21: source anchors and required mechanisms

| Component | Mechanism / parameter | Source |
|---|---|---|
| Knowledge restriction | 1-KLSS; freeze our strategy outside the current information set; account for excluded continuation values | §4, pp. 4–5 |
| Solver and tree | LP-based exact trunk solves; selective iterative deepening | App. D.2, p. 16 |
| Frontier | Stockfish 13, depth 1; `tanh(cp / 600)` | App. D.1, p. 16 |
| Candidate tracking | Maintain consistent positions, including transposition approximation | §4; App. D.3 |
| Root replenishment | Uniform sampling without replacement; minimum target `L=200`; new opponent roots assume perfect information | App. D.3, pp. 16–17 |
| New alternate values | `min(leaf_value, previous_search_value)` | App. D.3 |
| Information incentive | Entropy-dependent penalty; `M=10^7` | App. D.3 |
| Gadget choice | Reach-Maxmargin, with Reach-Resolve fallback | App. D.4 |
| Draw approximation | Separate referee draws from search transposition/draw treatment | App. B.1 |

## Obscuro: source anchors and required mechanisms

| Component | Mechanism / parameter | Source |
|---|---|---|
| Knowledge restriction | KLUSS unfreezes the relevant own information sets | App. C.6 |
| Search | PCFR+ with one-sided growing-tree expansion | §3; App. C.4 |
| Frontier | Stockfish 14, depth 1, MultiPV; initialize new strategy toward its best child | App. C.5 |
| Root replenishment | Minimum target 256, not a hard cap on all retained roots | Fig. 9, p. 27 |
| Gadget values | Updated alternate/gift values and nonuniform Resolve root distribution | App. C.2–C.3 |
| Action output | Last iterate; mode-dependent purification, support limit 3 and stability test | App. C.7–C.8 |
| Persistence and schedule | Retain tree/strategy; stop expansion before final solving | §3.4; App. C.1 |
| Interpretation | Reported 10.7 plies is average search-tree depth | App. D |

The tables are the factual source map. The following implementation and
verification plan is proposed work for this repository.

## Proposed ZS21 implementation checklist

This dependency outline is our build order, not a transcription of the
authors' unavailable source code. Use Z21's cited sections to resolve details.

```text
receive the player's next observation and known own action
    update the consistent-position set
    retain compatible previous tree and blueprint information
    replenish sampled roots according to the source-mapped rule
    build the knowledge-limited gadget with frozen outside policies
    repeat while the budget allows:
        solve the current trunk and choose its gadget mode
        identify supported frontier nodes
        expand selected nodes and assign leaf estimates
    retain tree, strategy and expected value for the next turn
    sample a move from the resulting root strategy
```

Keep a separate implementation task for each item: information-set keys,
sequence constraints, alternate payoffs, gifts, solver status/tolerance,
supported-frontier selection, move ordering, entropy incentive, root
replenishment and transposition handling. Omitting any of these should be
named as a simplification in the run configuration.

**Proposed acceptance order:** solve a fixed tiny game; solve its gadget;
grow it incrementally; replay a short observation history; then add chess
rules and engine values. The normal-form oracle gives an independent value
check for the first stages but does not implement the sequence-form gadget.

## Proposed Obscuro implementation checklist

Again, this is an implementation outline; O26's text and Figures 8–12 are the
source for the detailed updates.

```text
receive observation history
    update candidates and reconstruct the relevant saved subgame
    replenish sampled roots and prepare gadget values/priors
    repeat solving and growth until expansion must stop:
        update local predictive regret minimizers with counterfactual values
        alternate the exploring player in tree-growth steps
        expand a frontier and initialize any new information set
    finish the final solver work on the now-fixed tree
    save the raw last-iterate root policy
    apply mode/stability/support purification to a separate played policy
    sample the actual move; retain tree and strategy for the next turn
```

**Proposed acceptance order:** compare fixed-tree values to the oracle; check
predictive updates and zero-reach behavior; add node initialization and growth;
then add persistence, gadget transitions and purification as independently
switchable mechanisms. A sequential debugging schedule is acceptable for
initial verification, but must be recorded if used in reported comparisons
against the original concurrent schedule.

Do not overwrite the raw policy with the purified played policy. Record both
and check that removed probability mass is handled according to the source.
The saved tree needs more than FENs: retain player information sets, reach
information, solver state and expansion status. Keep sampled-root weights
distinct from the gadget's opponent-root prior.

## Build plan for either eventual owner

1. Build a small tree representation with explicit chance nodes, player nodes,
   terminal utilities and information-set IDs. Keep node identity separate
   from both FEN and information-set identity.
2. Require all nodes sharing one information set to share the same available
   actions and the same action distribution. Never select different actions
   solely because the simulator knows which hidden node is real.
3. Verify utilities and chance weighting against `../toy_games.py`. That
   oracle enumerates normal-form pure strategies only for tiny games; it is
   not a scalable sequence-form solver for chess.
4. Add a fixed-tree solver. Before adding pruning or tree growth, compare its
   expected utility and both best-response bounds with the oracle. For PCFR+,
   retain diagnostic average strategies even if the deployed policy uses the
   last iterate. Do not substitute ordinary CFR+ and call it PCFR+.
5. Implement gadget construction and the appropriate knowledge restriction.
   Validate frozen policies and alternate-value sign conventions using
   hand-built game trees. The existing toy games do not yet validate KLSS or
   KLUSS gadget construction.
6. Add tree growth, state replenishment and persistence across observations.
   Verify new nodes enter the correct information sets; preserve a usable
   previous policy when a time budget expires.
7. Connect the separately reviewed FoW rules adapter and leaf evaluator. Use
   a supplied heuristic for ordinary-board estimates and a rules function
   for actual terminal states. Engine mate scores are not FoW referee events.
8. Verify the complete decision path on fixed histories before playing
   matches. Save raw strategy and played action separately.

## Records needed to diagnose one search

**Proposal:** keep current player's observation sequence, candidate count,
sample/history IDs, tree nodes and information sets, frozen flags, leaf values
with an explicit player perspective, gadget mode/margins, solver iterations,
expansion count, root probabilities, raw/played policy and stage timings.
Record solve and tracker time separately. A mixed-policy action sampled with
a fixed seed should be reproducible under an iteration budget; wall-clock
stopping can still change the number of iterations.

For engine estimates returned at a child, check whether they refer to the
child's side to move or the parent's player. A sign error can produce legal
moves and normalized strategies while reversing preferences.

## Questions to settle before production implementation

- **Assignment:** who owns which agent and who reviews the shared rules?
- **Tracker identity:** when do we merge positions, and what private histories
  or opponent-information metadata remain available to search?
- **Evaluator context:** how are several belief groups and their weights
  passed to the network without mixing information sets?
- **Budgets:** which wall-clock components count toward each experimental
  time limit? Any simplified scheduling must be recorded as a deviation.
- **Gadget and solver detail:** pin the predictive-regret update equations,
  zero-reach handling, alternate-value convention and numerical tolerances
  before coding them. These are not resolved by adding a generic LP call.
- **Algorithm prose versus pseudocode:** when a transcription is ambiguous,
  inspect the PDF figure and compare the explanatory subsection before
  choosing behavior; log the choice rather than guessing silently.

## Experiments that isolate a mechanism

**Proposal:** compare one component at a time on fixed roots/leaf values and
then at equal total move budgets. Suggested toggles are KLSS/KLUSS, one-sided/
two-sided growth, purification, root-prior rule and leaf evaluator. The
proposal's R1–R3 ladder changes several mechanisms together; it is a useful
delivery plan but cannot alone attribute a gain to KLUSS.

Do not use subgame Nash gap as whole-game exploitability. Do not infer human
rating from wins against our own reconstruction. Positive, negative and null
results all belong in the report with counts and uncertainty.
