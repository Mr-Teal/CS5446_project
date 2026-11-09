# Pair B review of the research handover, 9 November 2026

This completes the requested Pair B review of PR73 section 4.3 using the available
source. It is a review under Bryan's authenticated account, assisted by Codex;
it is not a review attributed to Colin. The accompanying handover was corrected
during the review, so this is author-assisted document validation rather than an
independent approval of those edits.

## Verified scope

- Inspected the label collector at [87b3089](https://github.com/Mr-Teal/CS5446_project/blob/87b3089/pair_a_prep/label_run.py),
  including partial failed-game records and resume behavior.
- Inspected the new leaf factory at [d63de87](https://github.com/Mr-Teal/CS5446_project/blob/d63de87/pair_a_prep/evaluation_factories.py).
  It loads a belief-network checkpoint, but the search queries individual FENs
  through `evaluate_children`; the existing evaluator constructs singleton
  beliefs for those calls. Training with context does not establish deployment
  with the live whole-belief input.
- Inspected Pair B's model, loader, validator and training script at main
  [3335723](https://github.com/Mr-Teal/CS5446_project/tree/3335723852ad59ccbe5e999dbe0ce2773f7e56d0).
  Local review source files were checked against the repository blob hashes.
- Instantiating the documented pure belief-network architecture (six residual
  blocks, 64 channels, embedding 128, 32 input planes, context enabled, no D1)
  gives **561,681 parameters**. This verifies the architecture count, not the
  identity/configuration of the unavailable trained checkpoint.
- Arithmetic agrees: 14,073 + 5,676 = 19,749 records; 268 + 34 + 34 = 336 reported
  game IDs/parts; 87/90 rounds to 0.967; the Atlas survivor score is 15/34, or 0.441.
  With five positive and one negative discordant pair, the two-sided exact sign
  test is **0.21875**, rounded 0.22. This is not evidence of equivalence.
- **69 existing Pair B tests passed, zero skips**, covering label validation,
  belief data, network interfaces and tiny synthetic training/evaluation
  fixtures. Python 3.12.15, torch 2.2.2, NumPy 1.26.4, Intel macOS, one CPU
  thread. The fixture models/data are temporary test inputs, not a new project
  training run, held-out evaluation of `belief-solver-v1`, or GPU benchmark.

Reproduce the interface checks in the project's torch-enabled environment:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m pytest -q pair_b/tests/test_label_validation.py pair_b/tests/test_belief_data.py pair_b/tests/test_belief_net.py pair_b/tests/test_train_belief_net.py
```

These tests cover capabilities of the existing pipeline. They cannot validate
the new dataset, reported MAEs, latency, best epoch, test isolation or game scores
without the actual artifacts. No new release weights or performance experiments
were produced by this review.

## Corrections made to the handover

1. Label all new experimental numbers as author-reported; host-local paths are
   not accessible evidence links.
2. Replace equality/equivalence claims based on non-significant comparisons.
3. Distinguish attempted/partial game parts from completed games. The collector
   retains pre-failure records; a passing format validator does not certify
   history-sensitive solver targets or sample completeness.
4. Explain the singleton deployment path and separate `belief-solver-v1` from
   archived Network 1 and PR70's already merged integration.
5. Treat the material-derived-label explanation as a hypothesis. The differing
   board/position metrics and context ablations do not isolate its cause.
6. Preserve the reported measurements while requiring explicit accounting for
   opponent `TrackerLost`, caps, errors, kills and unplayed games before accepting
   an outcome comparison. Joint-survivor results remain conditional on survival.
7. Keep additional training iterations, residual models and stronger opponents
   as optional research. Issue20 Option B and the completed Pair B experiments
   do not acquire a new training requirement.

## Evidence needed from the experiment owner before adopting these new results

| Artifact | Required content |
|---|---|
| Attempt manifest | Every planned seed/colour/arm and its terminal, capped, failed, killed or unplayed status; reconcile first games retained from interrupted chunks and both opponent tracking failures. |
| Game evidence | Immutable configs, raw game/tracker records, source/engine/checkpoint identity, hardware and clock scope; analysis script/command that reproduces the tables and paired intersections. |
| Label archive | Part-file hashes, collection/progress manifests, failed/partial retention policy, unique game IDs across both hosts and validator invocation/output. |
| Training evidence | Dataset hashes, explicit split IDs, training arguments/logs, selection metric, epoch, summary and full checkpoint SHA256. The published hash prefix alone is insufficient. |
| Evaluation evidence | Validation and no-context baseline commands/results on identified populations; latency method/device; evidence that the held-out test has not selected the model. |

These are evidence-delivery requirements if the new study is adopted, not a
request for Colin/Bryan to repeat the author's training. The currently available
handover is useful research documentation; it does not release or verify the
new model.

## Runtime and final-delivery boundaries

PR66 remains under a counter-range change request at 3e06bc0. PR67 remains under
history-sensitive aliasing and evaluator-budget/fallback change requests at
53d0adb. Their 8 November rechecks confirm those defects remain reproducible:
[PR66](https://github.com/Mr-Teal/CS5446_project/pull/66#issuecomment-6715040064),
[PR67](https://github.com/Mr-Teal/CS5446_project/pull/67#issuecomment-6715040817).

Merging this documentation does not merge or approve PR66, PR67, `solver-labels`,
or `network-leaf`, and does not establish an accepted full-game competition
budget. PR33, its branch, presentation, report and private submission copies
were not edited in this session. Final artifact decisions remain with the
separate final-delivery work.
