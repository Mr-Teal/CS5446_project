# Tracker output-resume validation

Completed 2026-10-31T16:28:56.916140+00:00; source parent `21ab48284352cd1e027b98ea93f930622137be6c`.

When expansion has completed but output hits its budget, the tracker now retains
the continuation. `resume()` reuses the graph and re-materializes the requested
sample with its saved RNG state. Advancing after a returned partial output from
an exact completed graph preserves exact support. A graph that lost branches or
was pruned remains incomplete. No returned current-ply Belief means resume is
required before accepting another observation.

- **947 tests passed**, zero failures, errors or skips, in 135.26 seconds.
- **32 new output regressions**, 16 per Python/native backend, cover time and
  memory stops, repeated resume, full and sampled outputs, history/weight/RNG
  parity including subsequent updates, unchanged completed graph/transitions,
  advancement, zero output, zero/small memory, invalid budget, earlier pruning
  and reset. The reviewer's first-history clock interruption fails on the old
  source; `before-fix.xml` preserves that check.
- Complete committed `game-002` replay passed separately on both backends:
  34 plies and 70 private updates each, ending in king capture. All per-update
  history/returned counts match, support remains exact, and the external oracle
  checks actual full-path membership on every update. These are two backends of
  the same existing game, not two new matches or a strength result.
- The previous HiGHS recovery source and fixture hashes remain unchanged; its
  regressions are included in the full suite above.

The tests inject a clock or output-stage cap to exercise the budget boundary
deterministically; they also test real zero/small memory limits on resume.
Windows native acceleration was available here. Other platforms can run the
Python cases and skip the optional native cases.

Output is re-materialized, not incrementally cached. Repeated small slices may
repeat a prefix; one call needs enough budget for the requested output. A partial
prefix retains its conservative weighting label. This preserves the existing
cooperative budget model and does not introduce a hard RSS or wall-time bound.

From the repository root:

```powershell
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess test
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -m pytest -q pair_a_prep/tests/test_belief_output_resume.py
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -m pair_a_prep.benchmark_belief_tracker --input pair_a_prep/results/belief_tracker_2026-10-31/inputs --output zs21_runtime/out/resume-replay-python --games 2 --backend python
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -m pair_a_prep.benchmark_belief_tracker --input pair_a_prep/results/belief_tracker_2026-10-31/inputs --output zs21_runtime/out/resume-replay-native --games 2 --backend native
```

Use new output directories for replays; the runner refuses to overwrite evidence.
Files: `regression.log/xml`, `before-fix.xml`, both `replay-*` directories and
`verification.json` with source/evidence hashes. No formal evaluation was run;
the existing ten-game benchmark and 34-game score remain historical evidence.

See the [public budget and continuation contract](../../../pair_a_prep/docs/belief_tracker.md#time-and-memory-budgets).
