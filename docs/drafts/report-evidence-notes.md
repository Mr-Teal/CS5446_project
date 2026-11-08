# Report evidence notes

Supporting provenance for the 8 November 2026 report revision. These notes keep implementation history outside the academic argument. They are not additional experimental results or part of the main report.

## Scope and source identities

- The report analyses completed evaluator studies and the archived seven-row one-ply match batch. Its tables retain the established data, populations and numerical results. No new training, formal matches or sealed-test evaluation was performed for this revision.
- The integrated implementation description was checked against main `3335723852ad59ccbe5e999dbe0ce2773f7e56d0`, including merged PR59, PR63 and PR65. PR66 and PR67 remain open at the time of this revision. These status checks do not change historical experiment identities.
- Pair B's original label and check-set studies are documented in the [pinned evaluator README](https://github.com/Mr-Teal/CS5446_project/blob/3335723852ad59ccbe5e999dbe0ce2773f7e56d0/pair_b/README.md), including checkpoint outputs, five-seed context studies and timing populations.
- The [MC/TD results](https://github.com/Mr-Teal/CS5446_project/blob/1db35d68638d52353381d13de20addfea58a4d99/pair_b/experiments/mc_td/RESULTS.md) retain the different distillation/trajectory populations, unfinished-game exclusions, rule mismatches, regularization-edge checks and longer-TD diagnostic. These are prediction studies, not online policy improvement.
- The [formal batch archive](https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27) uses execution source `a5c5fb696bda20f0312abd2a7af020bd6388a6ad`, Stockfish 19 and `pairb-standin` rules. It predates the no-move draw and Fog en-passant repetition changes. Its 1,400 attempts, 1,399 finished games, 699 complete pairs and six capped draws remain distinct from later pilots.
- [Methods and independent archive validation](https://github.com/Mr-Teal/CS5446_project/blob/7c292af5881b8c81e4ffccb7300de21650c9c0ad/pair_b/docs/evaluation-methods-draft.md) describe recomputation of the raw records, intervals, timings and hashes. This was an archive audit, not independent execution of the neural agents.

## Search verification cited in the report

The current implementation map describes sampled synchronous knowledge projection, finite-cut boundaries, heuristic retention and audit-only ancestor gifts. The [pinned mechanism checklist](https://github.com/Mr-Teal/CS5446_project/blob/3335723852ad59ccbe5e999dbe0ce2773f7e56d0/pair_a_prep/docs/obscuro_status.md) distinguishes these from a complete paper reproduction.

Historical checks are kept under their own revisions and are not summed:

- [PR27 supplemental review](https://github.com/Mr-Teal/CS5446_project/pull/27#issuecomment-6406920434), reviewed `7b14bbb`: 404 existing tests and seven additional probes of retained state and failed grafts. This precedes later rule updates.
- [PR30 budget/fallback review](https://github.com/Mr-Teal/CS5446_project/pull/30#issuecomment-6407182994), reviewed `5f334b1`: 425 existing tests and 20 probes; 18 fixed-work cases were repeated. A requested 10 ms cooperative window measured about 10.47 ms. Evaluator-call counts do not equal total computation.
- [Teal's PR59 validation report](https://github.com/Mr-Teal/CS5446_project/pull/59#issuecomment-6593444508), measured `78f687b`: 962 shared/Pair A passes and 46 Pair C passes in separate environments. The combined invocation fails collection; counts are not one whole-project suite. The reported eight-action Stockfish 19 smoke was capped and unscored.
- [Bryan's complementary evidence handoff](https://github.com/Mr-Teal/CS5446_project/pull/59#issuecomment-6595644283): 48 selected ZS21 tests and a two-action Stockfish 13 smoke ending `unfinished_smoke`. Python and native-library choices differ from the locked/shared-tracker run. This was author-assisted validation of integration work, not an independent whole-change approval.
- [Windows pilot record](https://github.com/Mr-Teal/CS5446_project/pull/62): strict seed18 fails at ply 9; relaxed logical-memory settings fail at ply 11. Keep these configurations distinct from the [PR64 pilot](https://github.com/Mr-Teal/CS5446_project/pull/64), runtime `0426f73`, whose no-logical-cap/16-second update policy passes those fixed updates but fails at Black ply 13. None supplies a complete colour pair or strength estimate. Cooperative tracker budgets do not guarantee a combined turn deadline.

## Later evidence that can be added separately

The [8 November Pair A handover in PR73](https://github.com/Mr-Teal/CS5446_project/pull/73), head `8abc854`, reports solver-label generation, network training and full-search network-leaf arms. It is a newer evidence population, not the source of the report's tables. Its log, raw run directories, label data and checkpoint are described on the author's VM/Atlas storage rather than supplied as a complete accessible archive in the handover PR.

Before adding that study, retain frozen code/configuration/checkpoint/engine identities and the full attempted-game schedule, reconcile terminal, capped, failed, killed and unplayed counts, reproduce the aggregates from accessible records, and distinguish comparisons conditional on joint survival. Do not merge the handover's ranges or differing analysis cutoffs into one accepted result. A non-significant network/material contrast does not establish equivalence. Platform results must remain separate. No additional training or stronger-opponent experiment is required to preserve the completed report's existing conclusions.

## Course material used

The report was checked against the local CSxx46 Project Guidelines issued 26 August 2026, especially page 3 (report format, Vancouver references, roles and AI disclosure) and page 5 (problem formulation, technical depth, methodology, analysis, achievement and contributions).

The course connections use the original lecture slides rather than student-generated study guides:

| Course material | Connection developed in the report |
|---|---|
| Sequential Decision Making under Uncertainty, version 1.0 | State, transition, reward and policy; why a private observation is not a fully observed MDP state |
| Reinforcement Learning Model-Free Techniques, version 4.1 | Function approximation; MC returns, TD bootstrapping and semi-gradient prediction; prediction versus control |
| Guided Sequential Decision Making, version 1.0 | Decision-time search and learned frontier values |
| Game Theory, version 4.0 | Sequential zero-sum interaction, strategies and information constraints |

The guidelines' report deadline has an inconsistent printed year. The report does not infer a corrected submission deadline from that typo.

## Contributions and private submission details

Contribution descriptions use [Teal's statement](https://github.com/Mr-Teal/CS5446_project/pull/33#issuecomment-6408509322), [Colin's corrections](https://github.com/Mr-Teal/CS5446_project/pull/33#issuecomment-6437394247), the recorded Pair C workstream and the existing local proposal. Lin's environment/belief wording is explicitly a proposal responsibility, not certification of an unverified implementation. No identity is inferred from the account `xiaomiao-fong`.

The report distinguishes human work from recorded Copilot, Codex and proposal-stage Claude assistance. It makes no unsupported claim that every contributor used or did not use a particular tool.

Public review files contain names but omit student numbers and emails. The local private submission version adds the six members' details from the existing proposal to its cover. Those details must never be copied into this public branch.

## Citation maintenance

References are numbered by first citation and rendered in Vancouver style from a structured source library. Word files embed the matching Word Source Manager records, native CITATION fields and a bibliography field. Their displayed caches are locked to keep the issued DOCX and PDF synchronized; the bibliography's Vancouver display is generated by the report builder, rather than inherited from a workstation's APA default. The shareable XML library and RIS export accompany the report. Editing a source or adding an experiment requires regenerating citation numbers and both document formats together.
