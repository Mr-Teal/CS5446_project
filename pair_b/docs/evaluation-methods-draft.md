# Evaluation Methods and Batch Validation

Expanded methods and operational checklist, revised 28 October 2026 after independent review of PR #38 at 5e9393a. Colin completed all seven rows on his M5 Pro Mac on 26–27 October at a5c5fb6 (main 2af8f1f plus #34). Bryan independently checked the archived records and approved #38; he did not rerun the matches. The shorter report draft in PR #33 uses selected methods. The earlier independent cross-check remains separate. The #17 objection window closed on 27 October 2026 at 23:59 SGT. PR #38 merged into main at 0a7a148 on 28 October at 01:18 SGT, after that cutoff.

## Report Draft: Evaluation Methods

### Objective and Comparisons

The evaluation asks whether changing the leaf evaluator changes playing performance under a common fog-of-war decision procedure. The evaluator-based agents use a one-ply belief planner, with a separate particle tracker for each player, 256 particles and eight sampled hypotheses. The planner selects a move using its weighted average evaluated value across hypotheses. The candidate evaluators are material, Stockfish depth 1, Stockfish depth 11, Network 1, the belief-conditioned network and the linear correction. A random-action agent provides an additional comparator; it is not an evaluator using the same move-selection calculation.

Each candidate, including the random comparator, played Stockfish depth 1. Stockfish depth 1 against itself provides a symmetry check, not a requirement that a finite sample score exactly 0.5. The batch scheduled 200 games per pairing, seven pairings and 1,400 games in total. There are 1,399 finished games and one technical failure. Paired scores use 100 complete pairs per row except random, which has 99 complete pairs (198 games); its W/D/L counts all 199 finished games.

The comparison holds the outer planning and belief-sampling configuration constant for evaluator-based agents. It does not equalise total computation: evaluators differ in internal work, particularly Stockfish depths 1 and 11. Nor is this an equal-time experiment; the one-ply planner does not enforce its supplied action-time budget. Playing score is therefore accompanied by per-side decision latency, game wall-clock time and tracker diagnostics. The bot's measured decision time excludes its tracker update cost.

### Openings and Information Access

For each pairing, the seed was 0. Each opening consists of two to eight random legal plies, excluding moves that end the game. Opening index i uses seed 1000 * seed + i. Each opening is played twice with player colours exchanged, giving 100 scheduled colour pairs per pairing. Opening moves are passed through the game machinery so both trackers receive their respective observations. The protocol seeds game n with 1000 * seed + n and the Black player with that seed plus one.

During play, each agent receives only its own observations and tracker belief. Access to the true board is reserved for the referee and post-game diagnostics, not the player's move selection. In the match runner, the belief-conditioned evaluator scores the children of individual hypotheses; its whole-belief evaluation path is offline only. Consequently, these matches do not directly validate whole-belief gameplay.

### Rules, Engine State and Provenance

All seven rows used explicitly selected stand-in rules (`pairb-standin`) at a5c5fb696bda20f0312abd2a7af020bd6388a6ad. One results table must use one documented rules version; automatic adapter selection is unsuitable because it can change with checkout contents. The archived summaries record the exact source revision, rules identifier and source hashes.

The batch is pre-rule: its recorded `no_move_rule` is `unresolved`. PR #28's no-move draw rule subsequently reached main with #15 on 27 October. PR #37 also changed threefold-repetition adjudication to use a fog-of-war en passant position key; it merged at 04f992d on 28 October at 00:19 SGT. The batch predates both changes. A rules flag alone does not pin this behavior. No archived game has a no-move error or a `no_legal_moves` ending. The pre-rule table is retained under its original revision and exclusion policy; zero observed no-move failures does not make it equivalent to post-rule play, because the rule also changes evaluated child values. Do not pool pre/post-rule games or relabel historical outcomes. A post-rule rerun requires a separate team decision and a new complete table.

The batch used Stockfish 19 with one thread and a 16 MB hash. The runner clears engine state at the start of every game and retains it between calls within that game, including the diagnostic engine's corresponding per-game reset. The per-call watchdog defaults to 60 seconds and preserves depth-limited search. It is failure protection, not a whole-move or whole-game time budget.

For every run, retain the exact command, source and rules identity, seeds, opening configuration, tracker settings, engine identity and settings, checkpoint identities, environment details and output location. Record any differences between machines. Checkpoints remain fixed; no new training is part of this evaluation plan.

### Scores and Uncertainty

Game scores are 1 for a win, 0.5 for a draw and 0 for a loss, from the candidate's perspective. Pair B's runner scores a game still ongoing at the 200-ply cap as a draw (`ply_limit`); this differs from Pair C's capped/null convention. The archived batch contains two such draws for linear and four for depth-11 Stockfish. Every other recorded draw is threefold repetition. For an opening with both colour-swapped games completed, its pair score is the mean of the two game scores. The primary estimate is the mean across complete colour pairs. A pair can score 0, 0.25, 0.5, 0.75 or 1. Incomplete pairs are counted and excluded from this estimate.

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

The results are shown side by side, not pooled. The runners share game machinery and differ in engine reset policy, Stockfish build, platform, Python version, seed mapping and source revision (Colin: 00639cb; Bryan: 3afc594). Both historical runs predate the Stockfish watchdog fix. Identical aggregate outcomes on this lopsided pairing do not establish statistical equivalence or independent verification of all shared components. This check does not establish general chess strength or neural-evaluator performance and does not directly validate whole-belief gameplay. The historical audit's 131 focused tests passed and 13 were skipped; they were not rerun for publication. Preserve each run's own manifest and environment details.

## Formal Results Table: Archived Pre Rule Batch

Colin ran the batch from 26 October 22:47 to 27 October 08:09 SGT on one M5 Pro Mac, macOS 26.5.1, Python 3.14.6, NumPy 2.5.4, torch 2.14.1 (networks on MPS) and Stockfish 19. Source a5c5fb6, stand-in rules, seed 0, 256 particles, eight hypotheses, 200-ply cap, one engine thread and 16 MB hash were common across rows. The executable SHA-256 is `dc2f18c34ae962dff591b66147d220ec06e61d756b93d8a4f5e04fd8e55c251f`. Checkpoint identities remain in each summary. Results are archived in [PR #38](https://github.com/Mr-Teal/CS5446_project/pull/38), reviewed at 5e9393a and merged into main at 0a7a148 on 28 October at 01:18 SGT, after the #17 objection window closed.

| Candidate versus Stockfish D1 | Scheduled | Finished W/D/L | Complete pairs | Paired score | Wilson 95% | Bootstrap 95% or reason | Game/diagnostic errors | Candidate ms mean/p95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| material | 200 | 9/1/190 | 100 | 0.048 | 0.020–0.108 | 0.023–0.078 | 0/0 | 4.0/7.3 |
| stockfish-d1 | 200 | 103/2/95 | 100 | 0.520 | 0.423–0.615 | 0.455–0.588 | 0/0 | 12.2/23.9 |
| stockfish-d11 | 200 | 114/6/80 | 100 | 0.585 | 0.487–0.677 | 0.513–0.660 | 0/0 | 3281.2/9054.7 |
| network1 | 200 | 100/6/94 | 100 | 0.515 | 0.418–0.611 | 0.448–0.585 | 0/0 | 33.4/52.7 |
| belief | 200 | 111/3/86 | 100 | 0.563 | 0.465–0.656 | 0.495–0.630 | 0/0 | 139.1/257.4 |
| linear | 200 | 98/9/93 | 100 | 0.513 | 0.416–0.608 | 0.455–0.573 | 0/0 | 15.5/30.0 |
| random | 200 | 0/0/199 | 99 | 0.000 | 0.000–0.037 | Withheld: all pairs score 0 | 1/0 | 0.0/0.0 |

Score and both intervals use complete colour pairs; W/D/L uses every finished game. Three-decimal scores and intervals follow the published table's half-up rounding of the exact figures; some run-log cells round down instead (linear 0.513 versus 0.512, belief 0.563 versus 0.562, material bootstrap 0.023–0.078 versus 0.022–0.077, and D11 bootstrap lower bound 0.513 versus 0.512). These are display differences, not different results. Random game 36 (opening 18) failed with `TrackerLost: no position fits black's view at ply 18`; its surviving partner remains in W/D/L but is excluded from the paired score. This leaves 1,398 games in 699 complete pairs across the seven separate comparisons. The failure and random row's nonzero process exit remain visible. There are no diagnostic errors, recovery events or recorded budget overruns. Timings exclude opening moves and tracker maintenance; candidate mean/p95 here is distinct from median/p95 in #38's main table. Full opponent timings, wall times, endings and tracker aggregates remain in the summaries.

**No-move footnote for every row:** source a5c5fb6, rules `pairb-standin`, `no_move_rule=unresolved`; unresolved no-move games excluded = 0; terminal `no_legal_moves` draws included = 0. The one random failure is a tracker failure, not a no-move case.

The controls are consistent with expectations: random and material score poorly, and D1 self-play has both intervals spanning 0.5. Linear and Network 1 do not establish improvement over D1. Belief has a higher point estimate but both intervals include 0.5. D11's bootstrap narrowly excludes 0.5 while its Wilson interval includes it; do not infer a multiple-comparison-adjusted superiority claim. Rows are separate matches against D1, not a head-to-head ranking. The belief row scores single-board children and does not establish strategic belief-context value or whole-belief gameplay.

Independent archive review by Bryan with Codex assistance: all 22 manifest file sizes/hashes and seven decompressed game-stream hashes match. All 52 recorded source SHA-256 values match the pinned source snapshot; those source bytes also match GitHub's blob identities for a5c5fb6. Scores, both intervals, W/D/L, pairing/seed/opening consistency, timings, value-loss/tracker aggregates, termination and failure totals were independently recomputed from 1,400 records. Both generated tables rebuild byte for byte. This was an archive audit, not a match rerun or independent neural execution; original pre-normalization summary hashes and execution-machine history remain author-provided evidence.

The batch was executed before the objection cutoff. #34 was also merged ahead of its stated time gate, as Colin disclosed on #38. Review and publication do not retroactively change that sequence. The #17 objection window closed on 27 October at 23:59 SGT, and #38 merged after it on 28 October at 01:18 SGT. The batch keeps its pre-rule source; any subsequent objections require follow-up.

## Operational Checklist: Not Report Prose

### Batch Launch Record and Future Runs

- Completed operator/machine confirmation: Colin ran all seven rows on his M5 Pro with torch and Stockfish 19; no split-machine batch was needed.
- Completed source/configuration record: all rows use a5c5fb6 and explicit stand-in rules. The archived source includes the watchdog. Each row has its own output folder, command, settings, engine and checkpoint identities.
- This batch retained the pre-rule interim policy; the draw-rule implementation reached main later. Do not rewrite its source or outcomes to match main.
- The #17 objection window closed on 27 October 2026 at 23:59 SGT; #38 merged after the cutoff on 28 October at 01:18 SGT. Preserve the historical execution and publication chronology.
- For any future batch, agree the protocol, operator, machine and exact rule/source revision first; verify effective modules, engines and checkpoints with a separate colour-paired smoke run. Use non-overwriting row folders. Keep Pair C experiments separate unless their scoring, tracker, engine and provenance contracts are explicitly reconciled.

### After Each Pairing

- [ ] Preserve raw records before analysis. Save the exact command, exit code and interruption/termination status beside each run, including partial runs.
- [ ] Require `games + errors == settings.games`, using the summary's finished-game and game-error counts, then reconcile these counts and all scheduled game IDs against raw records. Diagnostic errors do not count as attempted games. A stopped 200-game run with only two finished games is incomplete even if `errors == 0`, `stopped_early` is null and `incomplete_pairs == 0`; those flags alone are insufficient. Record missing games and quarantine incomplete rows until resolved or explicitly reported as partial, never as a completed scheduled batch.
- [ ] Check unique game IDs, opening IDs, seeds and exactly one game per colour in each retained pair. Confirm the two games use the same opening.
- [ ] Recompute raw W/D/L, finished games, failed games, incomplete pairs and the complete-pair denominator. Inspect every error and termination cause; do not convert technical failures into losses or draws.
- [ ] Recompute pair scores and the mean from raw records, checking the candidate's orientation in both colours.
- [ ] Reproduce Wilson and eligible paired-bootstrap intervals using the recorded protocol. Record why a bootstrap or estimate is unavailable.
- [ ] Check per-game engine reset, recorded recovery events and failure exit status. Keep post-game diagnostic errors distinct from playing outcomes.
- [ ] Summarise the runner's mean/p95 decision latency for both sides, game wall time, ply-cap/rule-terminal outcomes and tracker capped/rebuilt counts. Include measurement units and sample counts; do not label a recorded mean as a median.
- [ ] Fill each row's no-move footnote using both pre-integration error paths or the post-integration terminal reason, as appropriate for its pinned rules.
- [ ] Compare source, rules, configuration, checkpoint and engine identities across all seven rows, including each `record.stockfish.sha256` and the recorded executable/build/settings. Account for intentional candidate/checkpoint differences and document machine/build differences. Quarantine unapproved or unexplained incompatibilities instead of pooling them.
- [ ] Investigate unexpected self-play or random-comparator behaviour without requiring an exact score or deleting inconvenient valid results.

### Before Using the Table

- [ ] Confirm all seven planned rows are accounted for, including stopped or failed rows. Do not silently substitute a smaller run or a different seed.
- [ ] Resolve or explain all exclusions and diagnostic failures, including the potential for failure-related selection bias.
- [ ] Keep historical cross-checks in their own table with their own provenance and engine policy. Do not add their games to the formal batch denominator.
- [ ] State the limits: fixed outer planning configuration, unequal internal compute and time, approximate labels/diagnostics, no full-chess exploitability claim and no direct whole-belief gameplay validation.
- [ ] Have another teammate check the table against raw artifacts before report inclusion. Record reviewer and artifact locations.

### Current Status

- PR #31 and #32 merged on 26 October. Their historical checks remain historical; publication did not rerun them.
- The seven-row batch is complete and independently audited as described above. #38 was approved at 5e9393a and merged at 0a7a148 on 28 October at 01:18 SGT, after the #17 window closed. #49's three documentation changes merged at 4fe521b on 27 October at 22:48 SGT.
- #15, #26, #36, #34 and #45 are on main. ZS21/shared-EP integration #37 is also on main at 04f992d (28 October at 00:19 SGT). The later Pair A search stack (#39, #40, #41, #42, #43, #44, #46, #48, #52, #53, #54, #55, #56, #57 and #58) is also on main as of 1db35d6. These merged mechanisms are separate from the historical batch evaluated here; their integration does not establish formal full-agent match readiness.
- Issue #19's worked example and narrative are available. No additional toy experiment or post-rule batch is required by this revision.
- No new training or matches were run for this document update. Future post-rule experiments require a separately pinned and validated run.

## Sources and Editorial Notes

- **Report allocation:** this is an expanded reference, not 2.5-3 pages to paste into the ten-page main report. Keep the comparison/planner and information boundary; color-pair sampling and score denominator; uncertainty/exclusions; source/rules/engine policy; and unequal-compute limitation. Condense provenance and historical comparisons into Section 6.2, separate from formal results. Keep commands, field-level acceptance checks, detailed seed mapping and the full operational checklist in this linked document. PR #33 Section 5 uses a compact methods/table layout; recheck pagination when actual results and figures are added.
- [Colin's methods review](https://github.com/Mr-Teal/CS5446_project/pull/32#pullrequestreview-5647085913): interrupted-run observation, no-move paths, recorded latency/provenance and editorial follow-ups. These are reviewer-reported checks, not new tests run for this revision.
- [Pinned match protocol at main 2af8f1f](https://github.com/Mr-Teal/CS5446_project/blob/2af8f1f731a978cd5a5bb1f5d5131b40ae01c72d/pair_b/docs/match_protocol.md): planner, opening generation, engine policy, scores, interval caveats, failures and Colin's cross-check.
- [Issue #17](https://github.com/Mr-Teal/CS5446_project/issues/17): batch and cutoff, support from Bryan/Teal, Colin's machine/operator confirmation, completion report and whole-belief gameplay limitation. This discussion supersedes older wording in the protocol about the runner decision and no-move proposal.
- [Bryan's protocol response](https://github.com/Mr-Teal/CS5446_project/issues/17#issuecomment-6406041253): rule rollout, historical separation and batch prerequisites.
- [Historical cross-check PR #31](https://github.com/Mr-Teal/CS5446_project/pull/31), publication head 8735be4cc7e06928db6d12ee2487a08bb86e5ba7: provenance, artifact audit and Bryan's results. Its publication source is distinct from the historical run source.
- [No-move rule PR #28](https://github.com/Mr-Teal/CS5446_project/pull/28): approved by Bryan at 21da153c8efdc1ae78dd1fac053c2402e1c7b3c7, with 451 integration tests; not a test of the eventual batch revision.
- [Watchdog PR #22](https://github.com/Mr-Teal/CS5446_project/pull/22) and [claim-boundary PR #24](https://github.com/Mr-Teal/CS5446_project/pull/24): merged safeguards and limits; no fresh test run is claimed here.
- [Published information-example guidance](https://github.com/Mr-Teal/CS5446_project/issues/19#issuecomment-6406533365): motivation and presentation, separate from playing-strength evidence.

Completed-methods wording above follows the independently checked #38 artifacts. Keep editorial status and the operational checklist outside the submitted report narrative. The detailed after-pairing and acceptance checklists remain reusable requirements, not a claim that every author-side launch action was witnessed by the reviewer.

- [Reviewed batch artifacts at 5e9393a](https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27): raw games, summaries, checksums and table builder.
- [PR #49](https://github.com/Mr-Teal/CS5446_project/pull/49): companion protocol/README status corrections.
