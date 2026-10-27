# Sampled-tree chess subgame integration

This opt-in prototype connects the finite-cut boundary work to chess. It is not
the authors' implementation, a complete legal-history KLUSS closure, or a claim
of exploitability safety. Existing fixed/uniform/retained modes stay available.

## Entry points

- `ChessSubgameAgent(evaluator, AnytimeConfig(growth="one_sided"), public_fen)`
- Evaluation factory: `search_mode=subgame` (defaults to one-sided growth).
- `purify=False` on the direct constructor is an explicit raw-policy ablation.
- Agent/configuration identifies `sampled-I2-gadget-pcfr-prototype-v1` and
  records the evaluator, clock convention, initialization and fresh-root choices.

## From the previous search to a new chess subgame

The first turn has no blueprint and solves the raw sampled-root game. Later
turns replay the new candidate paths from the public start and require the
private observation stream to extend the saved stream. The projector enumerates
the saved tree at the new ply, replaying hypothetical actions and both players'
private observation/action memories. It does not read a hidden referee action.

At this synchronized cut, find histories with our current private memory I,
then retain every cut history sharing an opponent memory with one of them.
This is I^2 **within the saved sampled tree**. Other own infosets in the retained
set remain unfrozen and are searched. Earlier estimated leaves that cannot reach
the cut are counted as incomplete; they do not supply invented descendants.

For retained roots, derive p(h)x(h), current-profile conditional alternates,
positive counterfactual gifts and the half-uniform / half-y(J) Resolve prior
from the saved raw-continuation profile. Keep complete opponent observation
classes within this explicit cut, not just the new belief's sampled roots.
Zero counterfactual class reach remains an explicit unsupported boundary error.

Retain expanded continuations; an old estimated cut leaf is expanded with the
ordinary evaluator while keeping its previous estimate as boundary evidence.
The search tree includes retained knowledge neighbours outside I. Labels are
computed only for the new input's candidates, in their original order, with
their supplied weights. Those weights never substitute for gadget reaches.

## Newly added roots: explicit approximation choices

A new belief history absent from the projected cut is added with a separate
opponent perfect-information root class. Its opponent memory receives a
synthetic root identity which persists through later hypothetical observations;
this prevents accidentally merging that assumed knowledge with another root.

Its alternate is `min(heuristic_proxy, previous_unshifted_search_value)`, following
the prior-search cap in C.1. Our shared evaluator supplies child values, so the
proxy is a heuristic minimax backup over the newly built shallow continuation,
**not** the paper's direct Stockfish position evaluation. Newly added roots use
unit counterfactual and opponent-sequence masses; this is an exposed engineering
convention because the missing blueprint supplied no such reaches. Resolve's
mixed prior is recomputed after adding those groups. This does not settle the
tracker owner's posterior weighting or replenish its internal population.

## Combined solving, growth and mode transitions

Both gadget modes use the same projected raw continuations through rebuilt
clones. After each completed CFR round, compute the minimum current unshifted
continuation margin: use Maxmargin when it is nonnegative within 1e-10,
otherwise Resolve. Compatible private minimizers/predictors/averages and cached
opponent policies are copied; newly introduced gadget controls start fresh.
The implementation is serial and does not preserve dormant gadget-control
state across every switch, unlike a shared-memory dual-gadget implementation.

One-sided sampling traverses the active gadget, including its selector/exit
controls. A selected chess frontier maps back to its raw history path. Growth
adds all immediate legal children atomically, maintains offsets/key translation,
and initializes new infosets to the heuristic-best child of the first expanded
occurrence. Root and initial shallow-tree infosets now receive the same optional
best-action initialization in selective modes; uniform baselines stay uniform.
The first policy is actually used for feedback, not overwritten by the first
zero-regret PRM+ preparation. Subsequent strategies follow normal PCFR+ updates.

Before saving a blueprint, unwrap opponent gadget keys into the raw tree.
Gadget exits/offsets do not enter continuation labels or the saved previous
search value. The synthetic perfect-information memory keeps this mapping
unambiguous. Cross-turn solver rounds accumulate, but each turn gets a new
round budget and final-solve reserve.

## Purification and output contract

Track raw root support after half of the action's wall-clock budget. For
deterministic fixed-work checks (`stop_on_time=False`), use the second half of
configured solver rounds as an explicitly different convention. Require actions
other than the current top action to remain continuously in the observed
support. Resolve plays the top action; Maxmargin retains at most three eligible
actions. Move excluded mass onto the top action; never renormalize remaining
secondary actions upward. If no second-half sample exists, allow only the top.

`Decision.root_policy` stays raw for training. Actual action sampling uses the
purified distribution, exported in `played_policy:<move>` diagnostics; raw
probabilities are also exported under `raw_policy:<move>`. Values are evaluated
under the raw continuation profile. Do not report purified actions as raw draws.

## Limits and verification

Deadlines remain cooperative; evaluator calls, tree validation/cloning and CFR
rounds are not preemptible. Count actual evaluator calls, fallbacks and overruns.
The optional submission guard now reserves 10% of a clock budget and estimates
the next round using its previous duration; both guard and purification can be
configured through the evaluation factory. See the measured
[clock ablation](clock_purification_ablation.md), including unreserved failures,
fallback work and examples that still exceed an in-flight operation's budget.
Failed preparation leaves the saved blueprint unchanged; label generation
raises rather than inventing values. A raw projected game renormalizes retained
counterfactual masses, so its next CF units are local to that saved sampled game.
Gifts before its saved root and discarded partial branches are not recovered.

Tests cover both CFR schedules, actual initial-policy feedback, C.8 mass moves,
an independently counted 9-history I^2 chess cut (6 neighbours outside current I),
new-root boundary capping, live gadget growth/mode/cross-turn integration, raw
label ordering and saved-state preservation after budget failure. Further
position-corpus checks are separate from playing-strength evaluation.

Remaining before a full reproduction: complete/bounded history inference and
agreed replenishment weighting; knowledge closure beyond the saved tree;
cross-root/pre-saved-root gift bookkeeping and missing-branch correction;
original Stockfish 14 D1/MultiPV calibration; concurrent scheduling and broader
time/strength experiments. The #37 rule-consistency decision remains separate.

## Label contract review gate

Projected subgame solves may contain additional current-infoset roots and blueprint weights not represented by the input belief. Decisions export `label_root_contract_pending=1`; `label()` rejects such records until Pair B agrees the root and weight schema. Cold solves retain the existing input-belief contract. A budget fallback discards the saved blueprint, so the next successful own turn starts cold.
