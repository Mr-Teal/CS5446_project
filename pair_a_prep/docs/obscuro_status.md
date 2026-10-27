# Obscuro implementation status

This is a repository implementation map, not a claim of exact reproduction.
The source anchors below follow the existing [paper specification map](paper_specs.md)
for Zhang and Sandholm, *General search techniques without common knowledge
for imperfect-information games*, arXiv:2506.01242v2. The authors' original
implementation and evaluation setup are unavailable. Engineering choices below
are explicitly separated from the source-mapped mechanisms.

## Mechanism checklist

| Mechanism and source anchor | Current evidence | Remaining work / difference |
|---|---|---|
| FoW rules and private observations, App. A | `rules_adapter.py`, special-position fixtures, referee integration; #28 integrated in Pair A | Main rollout still depends on #15. New configurations identify the no-move terminal draw; historical artifacts retain their old rule revision. |
| Consistent root histories | Partner's `belief_tracker.py`; replay validates observations/actions and retains repetition stacks | Exact internal enumeration is not scalable. Work with tracker owner on bounded, history-preserving candidates; output sampling alone does not bound population. |
| Information-set identity | Private observation/action hash chains in `chess_search.py` | Current tree uses a sampled-root game, not the paper's complete knowledge-limited construction. |
| KLUSS knowledge restriction, App. C.6 | Synchronized-cut toy prototype in `knowledge.py` | Build the relevant chess history/knowledge closure and connect unfreezing to chess subgames. Toy cut logic is not a general asynchronous-history implementation. |
| PCFR+, section 3 and App. C.4 | `pcfr.py`, predictive regret state, alternating/simultaneous schedules, toy LP/reference checks | Fixed-tree and warm-growth tests are not whole-game exploitability or a proof of reproduction. New infosets currently start with uniform strategy. |
| One-sided growing-tree expansion, App. C.4 | `expand_chess_tree`, `ChessGadget.expand`, retained old minimizers | Current growth expands every frontier by a common depth. Implement source-specific frontier selection and alternating exploring-player logic. |
| Frontier evaluation/initialization, App. C.5 | Generic `evaluate_children`, mover-to-actor sign conversion, actual terminal overrides; Material/Stockfish integration available | Experiments here use Material. Original source map specifies Stockfish 14 D1/MultiPV and initialization toward the best child; that initialization is not implemented. |
| Resolve / Maxmargin, App. C.2-C.3 | Generic gadget builder and chess bridge, path/key/offset-preserving growth | Caller supplies reaches, alternates and Resolve priors. Implement paper-derived gift/alternate updates and nonuniform root distribution, then mode transitions. Belief weights must not silently replace these inputs. |
| Root replenishment, Fig. 9 | Sampled candidates can be supplied externally | No source-specific replenishment. Source-map target 256 is a minimum target, not a hard cap on all retained roots. |
| Retain search state and final solving, section 3.4 and App. C.1 | Within-turn growth retains solver state; `anytime_agent.py` reserves final rounds and a clock fraction | Rebuilds each turn. No filtering/rerooting of saved trees across new observations; simplified serial scheduling, no original concurrent schedule. |
| Last iterate and purification, App. C.7-C.8 | Raw last-iterate policy sampled and exported without replacement | Implement source-specific mode/stability/support purification (source-map support limit 3). Keep raw and played policies separate. |
| Whole agent and labels | Fixed-depth prototype, optional gadget API, budgeted uniform-growth agent; continuation labels are belief-weighted and unshifted | Budgeted agent currently uses the original sampled-root tree, not gadgets. Full paper mechanisms above remain necessary before calling it a complete Obscuro reproduction. |

## Ownership and immediate sequence

The [expansion audit](expansion_mechanism_audit.md) now checks the local paper's
exact support/PUCT mixture and initialization. It also clarifies that our
complete-cut requirement is an engineering restriction; the paper can expand
one history leaf without expanding every member of its information set.

1. User: integrate and test the within-turn budgeted agent and document baseline costs.
2. User: derive selective expansion and new-node initialization from the source
   pseudocode before implementing them. Existing uniform growth is a reference.
3. User and tracker owner: agree on bounded-history semantics, then test short
   observation sequences before attempting long games or cross-turn persistence.
4. User: connect chess knowledge restriction and paper-derived gadget inputs.
5. User: add cross-turn retention, mode transitions and purification separately.
6. Evaluation owner, with user support: freeze rules/source versions, integrate
   the available agent and measure strength only after stable end-to-end runs.

#27 supplies raw-tree growth, #29 gadget growth, and #28 the shared-rule update.
All three are now integrated in the Pair A base; #15 remains the route to main.

## Reporting requirements

- Name the implementation `uniform-growth-pcfr-prototype-v1`, not full Obscuro.
- Preserve source hashes, configuration, seeds, tracker limits and rule revision.
- Distinguish final tree size from total preparation/failed-expansion work.
- Compare actual evaluator calls and elapsed time, not only identical upper caps.
- Report interrupted initial builds and fallback counts. Fallback policies have
  no invented continuation values and cannot produce training labels.
- Do not count a diagnostic ply limit as a draw or infer ratings from toy/short
  games. Per-subgame Nash gaps do not establish whole-game exploitability.
- Stockfish version changes, simplified scheduling, missing purification and
  unresolved knowledge/gadget inputs must remain visible in the final report.
