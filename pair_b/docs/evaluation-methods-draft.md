# Evaluation Methods and Batch Validation

Draft prepared 26 October 2026 for team review; not yet incorporated into the team report. The formal batch has not been run by Bryan; its results remain blank. The historical cross-check below is completed work, not a result from the proposed batch.

## Report Draft: Evaluation Methods

### Objective and Comparisons

The proposed evaluation asks whether changing the leaf evaluator changes playing performance under a common fog-of-war decision procedure. The evaluator-based agents use a one-ply belief planner, with a separate particle tracker for each player, 256 particles and eight sampled hypotheses. The planner selects a move using its weighted average evaluated value across hypotheses. The candidate evaluators are material, Stockfish depth 1, Stockfish depth 11, Network 1, the belief-conditioned network and the linear correction. A random-action agent provides an additional comparator; it is not an evaluator using the same move-selection calculation.

Each candidate, including the random comparator, will play Stockfish depth 1. Stockfish depth 1 against itself provides a symmetry check, not a requirement that a finite sample score exactly 0.5. The planned batch contains 200 games per pairing, seven pairings and 1,400 scheduled games in total. Completed and eligible counts will be reported separately from scheduled counts.

The comparison holds the outer planning and belief-sampling configuration constant for evaluator-based agents. It does not equalise total computation: evaluators differ in internal work, particularly Stockfish depths 1 and 11. Nor is this an equal-time experiment; the one-ply planner does not enforce its supplied action-time budget. Playing score will therefore be accompanied by per-side decision latency, game wall-clock time and tracker diagnostics. The bot's measured decision time excludes its tracker update cost.

### Openings and Information Access

For each pairing, the proposed seed is 0. Each opening consists of two to eight random legal plies, excluding moves that end the game. Opening index i uses seed 1000 * seed + i. Each opening is played twice with player colours exchanged, giving 100 scheduled colour pairs per pairing. Opening moves are passed through the game machinery so both trackers receive their respective observations. The protocol seeds game n with 1000 * seed + n and the Black player with that seed plus one.

During play, each agent receives only its own observations and tracker belief. Access to the true board is reserved for the referee and post-game diagnostics, not the player's move selection. In the match runner, the belief-conditioned evaluator scores the children of individual hypotheses; its whole-belief evaluation path is offline only. Consequently, these matches do not directly validate whole-belief gameplay.

### Rules, Engine State and Provenance

All rows are proposed to use explicitly selected stand-in rules. One results table must use one documented rules version; automatic adapter selection is unsuitable because it can change with checkout contents. Before the batch is accepted, its exact source revision, rules identifier and source hashes must be recorded.

The team has supported treating a position with no fog-legal move and no other terminal result as a draw. Implementation rollout is still pending for the batch revision: PR #28 targets the Pair A branch, not main. The intended rule must reach and be checked on the selected batch revision. Historical pre-change results must not be mixed with post-change results in a single formal table. Under the interim policy, unresolved no-move errors are excluded and counted explicitly; they must not be silently relabelled as draws after the run.

The proposed engine is Stockfish 19 with one thread and a 16 MB hash. The runner clears engine state at the start of every game and retains it between calls within that game, including the diagnostic engine's corresponding per-game reset. The per-call watchdog defaults to 60 seconds and preserves depth-limited search. It is failure protection, not a whole-move or whole-game time budget.

For every run, retain the exact command, source and rules identity, seeds, opening configuration, tracker settings, engine identity and settings, checkpoint identities, environment details and output location. Record any differences between machines. Checkpoints remain fixed; no new training is part of this evaluation plan.

### Scores and Uncertainty

Game scores are 1 for a win, 0.5 for a draw and 0 for a loss, from the candidate's perspective. For an opening with both colour-swapped games completed, its pair score is the mean of the two game scores. The primary estimate is the mean across complete colour pairs. A pair can score 0, 0.25, 0.5, 0.75 or 1. Incomplete pairs are counted and excluded from this estimate.

Raw wins, draws and losses count all finished games, including a finished game whose partner failed. They therefore need not reproduce the paired estimate when incomplete pairs exist. Both populations and their counts must be shown explicitly.

The existing protocol reports a Wilson 95% interval using the number of complete pairs as its sample size. This is an approximate interval for fractional pair scores, not an exact binomial interval for independent games. It is retained for consistency with the protocol and remains non-degenerate at all-win or all-loss outcomes. If there are no complete pairs, the paired estimate and interval are unavailable.

A percentile bootstrap resamples complete pairs with replacement, using 2,000 resamples and seed 0. It is reported only with at least 20 complete pairs and nonconstant pair scores. Where available, this is the headline interval; otherwise the table uses the Wilson interval and states why the bootstrap was withheld. These are per-row intervals, not a multiple-comparison-adjusted claim of superiority across all evaluators.

### Failures and Diagnostic Interpretation

Failed games retain their error records and are excluded from the playing score and their colour pair. A failed post-game value-loss measurement does not invalidate an already completed game; it is recorded as a diagnostic error. The runner returns a nonzero exit status if either type of failure occurs and stops after five consecutive failed games. Engine recovery events must remain visible in the artifacts.

Report game failures, incomplete pairs, diagnostic failures and termination causes separately. Do not present a run with unexplained errors as a clean evaluation. Explain exclusions because failure rates can bias comparisons. A ply-cap draw, a rule-terminal draw and a technical failure are distinct outcomes and must not be conflated.

The post-game true-board value-loss measure is an evaluator-based diagnostic of the effect of hidden information. It is not an exact strategic value of information or an exploitability measurement. Likewise, a lower error against full-board Stockfish labels does not establish that the learned evaluator captures the strategic value of information. Playing strength claims must remain conditional on the tested opponents, openings, rules and planner.

## Report Draft: Historical Independent Cross-Check

A separate, previously completed cross-check used independently implemented runners on Stockfish 19 depth 1 against material from the standard public start. Bryan's run comprised ten seeds, each played with both colours, using stand-in rules, 256 particles, eight hypotheses, 2,000 rebuild tries and a 200-ply cap. Its historical source revision was 3afc5945dfa5a98e5a90275782b8658b69bb9bcf, audited on 22 October 2026; it was not rerun on the publication PR head.

| Runner | D1 wins/draws/losses | Complete pairs | Paired score | Approximate Wilson 95% interval | Engine reset policy | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Colin: play_matches | 20 / 0 / 0 | 10 | 1.00 | 0.72-1.00 | Before each game | Committed result reported in the pinned protocol |
| Bryan: match_experiment | 20 / 0 / 0 | 10 | 1.00 | 0.72-1.00 | Before every call; fresh engines per game | Independently audited historical artifacts, PR #31 |

The bootstrap is withheld for these rows because there are only ten pairs and every pair has the same score. Bryan's 20 games contained 734 plies and ended by king capture, with no game failures, ply-cap draws or recorded action-budget overruns. Across both trackers there were 1,508 updates, including 42 rebuilt and 163 capped updates. The diagnostic action budget was not an enforced equal-time constraint.

The results are shown side by side, not pooled. The runners share game machinery and deliberately differ in engine reset policy; identical aggregate outcomes on this lopsided pairing do not establish statistical equivalence or independent verification of all shared components. This check does not establish general chess strength, neural-evaluator performance or whole-belief gameplay. The historical audit's 131 passed and 13 skipped tests were not rerun for publication. The artifacts predate the Stockfish watchdog fix.

## Formal Results Table: Unfilled

All measured-result cells below are intentionally blank; scheduled game counts describe the proposed plan. Fill results only from validated artifacts; blank does not mean zero. Record the actual source/rules revision, machines, checkpoints and run dates with the completed table.

| Candidate versus Stockfish D1 | Scheduled games | Finished W/D/L | Complete pairs | Paired score | Wilson 95% | Bootstrap 95% or reason | Game/diagnostic errors | Candidate latency median/p95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Material | 200 | | | | | | | |
| Stockfish D1 | 200 | | | | | | | |
| Stockfish D11 | 200 | | | | | | | |
| Network 1 | 200 | | | | | | | |
| Belief-conditioned network | 200 | | | | | | | |
| Linear correction | 200 | | | | | | | |
| Random | 200 | | | | | | | |

Also retain per-row opponent latency, game wall time, termination counts, incomplete pairs and tracker health in a companion table or appendix. Do not infer significance from overlapping or non-overlapping intervals alone.

## Operational Checklist: Not Report Prose

### Before Launch

- [ ] Confirm the final protocol in issue #17. The proposed objection cutoff is 27 October 2026, 23:59 SGT; it is not a course deadline or proof that the batch has started.
- [ ] Confirm the operator and machine, including working Torch and Stockfish 19 on that machine. ZW was asked to confirm; no confirmation was visible at drafting time. Bryan has not volunteered to run all 1,400 games.
- [ ] Select and record the exact batch source revision. Today's main SHA is a documentation reference, not automatically the approved batch revision.
- [ ] Coordinate PR #28's no-move rule into that revision and verify the actual stand-in execution path. A merge into the Pair A branch alone is insufficient. If the team elects to run under the interim policy, record that explicit decision and the unchanged exclusion/count footnote before starting.
- [ ] Verify the watchdog and engine recovery on the selected revision. PR #22 is merged, but its presence must be checked in the actual checkout.
- [ ] Pin all seven candidate identities, checkpoint hashes, seeds, tracker configuration, opening range, ply cap and engine settings. Record the runner's effective settings, not only CLI defaults assumed from older docs.
- [ ] Reconcile any use of PR #26's workflow with play_matches as runner of record. A wrapper must preserve per-game reset, both player trackers, nonzero exit status and provenance.
- [ ] Use distinct, non-overwriting output directories per pairing. Run a small colour-paired smoke test on the selected machine; keep smoke artifacts separate from the formal batch.
- [ ] Check that the smoke test loads the intended modules/checkpoints and writes complete game, pairing, diagnostic and provenance records. Do not treat a stale downloaded snapshot as the selected revision.

### After Each Pairing

- [ ] Preserve raw records before analysis. Record command exit status and whether the full scheduled run completed or stopped early.
- [ ] Check unique game IDs, opening IDs, seeds and exactly one game per colour in each retained pair. Confirm the two games use the same opening.
- [ ] Recompute raw W/D/L, finished games, failed games, incomplete pairs and the complete-pair denominator. Inspect every error and termination cause; do not convert technical failures into losses or draws.
- [ ] Recompute pair scores and the mean from raw records, checking the candidate's orientation in both colours.
- [ ] Reproduce Wilson and eligible paired-bootstrap intervals using the recorded protocol. Record why a bootstrap or estimate is unavailable.
- [ ] Check per-game engine reset, recorded recovery events and failure exit status. Keep post-game diagnostic errors distinct from playing outcomes.
- [ ] Summarise median/p95 decision latency for both sides, game wall time, ply-cap/rule-terminal outcomes and tracker capped/rebuilt counts. Include measurement units and sample counts.
- [ ] Compare source, rules, configuration and checkpoint hashes across all seven rows. Quarantine incompatible rows instead of pooling them.
- [ ] Investigate unexpected self-play or random-comparator behaviour without requiring an exact score or deleting inconvenient valid results.

### Before Using the Table

- [ ] Confirm all seven planned rows are accounted for, including stopped or failed rows. Do not silently substitute a smaller run or a different seed.
- [ ] Resolve or explain all exclusions and diagnostic failures, including the potential for failure-related selection bias.
- [ ] Keep historical cross-checks in their own table with their own provenance and engine policy. Do not add their games to the formal batch denominator.
- [ ] State the limits: fixed outer planning configuration, unequal internal compute and time, approximate labels/diagnostics, no full-chess exploitability claim and no direct whole-belief gameplay validation.
- [ ] Have another teammate check the table against raw artifacts before report inclusion. Record reviewer and artifact locations.

### Current Status

- Colin's review was requested on PR #31 and verified after a browser reload on 26 October 2026. The PR remains open; no merge was performed.
- The issue #19 report/presentation guidance is published. No additional toy experiment is required by this draft.
- Machine/operator confirmation and a selected batch rules revision remain outstanding. No formal games, smoke tests or new training were launched by this task.
- Actual batch validation must wait for the selected revision, environment and run artifacts. This checklist is preparation, not a validation pass.

## Sources and Editorial Notes

- [Pinned match protocol at main 2af8f1f](https://github.com/Mr-Teal/CS5446_project/blob/2af8f1f731a978cd5a5bb1f5d5131b40ae01c72d/pair_b/docs/match_protocol.md): planner, opening generation, engine policy, scores, interval caveats, failures and Colin's cross-check.
- [Issue #17](https://github.com/Mr-Teal/CS5446_project/issues/17): proposed batch and cutoff, support from Bryan/Teal, whole-belief gameplay limitation and outstanding machine/operator confirmation. This discussion supersedes older wording in the protocol about the runner decision and no-move proposal.
- [Bryan's protocol response](https://github.com/Mr-Teal/CS5446_project/issues/17#issuecomment-6406041253): rule rollout, historical separation and batch prerequisites.
- [Historical cross-check PR #31](https://github.com/Mr-Teal/CS5446_project/pull/31), publication head 8735be4cc7e06928db6d12ee2487a08bb86e5ba7: provenance, artifact audit and Bryan's results. Its publication source is distinct from the historical run source.
- [No-move rule PR #28](https://github.com/Mr-Teal/CS5446_project/pull/28): approved by Bryan at 21da153c8efdc1ae78dd1fac053c2402e1c7b3c7, with 451 integration tests; not a test of the eventual batch revision.
- [Watchdog PR #22](https://github.com/Mr-Teal/CS5446_project/pull/22) and [claim-boundary PR #24](https://github.com/Mr-Teal/CS5446_project/pull/24): merged safeguards and limits; no fresh test run is claimed here.
- [Published information-example guidance](https://github.com/Mr-Teal/CS5446_project/issues/19#issuecomment-6406533365): motivation and presentation, separate from playing-strength evidence.

Only convert future-tense methods into completed-methods prose after checking the actual batch artifacts. Keep editorial status and the operational checklist outside the submitted report narrative.