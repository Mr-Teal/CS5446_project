# HiGHS recovery validation

Completed 2026-10-31T16:06:16.061711+00:00. The directory name records the investigation start date.

- Full shared/Pair A regression: **915 passed**, zero failures, errors or skips; JUnit duration 109.76 seconds.
- Both original single-attempt Not Set failures reproduced. Bounded recovery passed unchanged full-game certificates: gaps 1.2208116e-16 and 3.1225023e-17.
- Doctor: all 66 pinned assets verified, four single-thread Stockfish 13 workers.
- Actual paper-agent versus baseline integration: four legal plies, one expansion per move, longest action 1.5903 seconds under the existing 16-second turn deadline. `unfinished_smoke` is intentional and is not a draw or a strength result.

Files: `regression.log/xml`, `recovery.json`, `doctor.json`, `smoke.json` and `verification.json` (hashes and cross-checks).
The fixtures and checker are portable within the pinned Windows runtime; original source and fixture hashes are recorded in the reports.

## Commands from the repository root

```powershell
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess test
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python zs21_runtime/scripts/check_highs_recovery.py --output zs21_runtime/out/highs-recovery-new.json
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess doctor
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python zs21_runtime/examples/python_match.py --plies 4 --max-rounds 1 --output zs21_runtime/out/highs-smoke-new.json
```

The 25 added tests include the two real inputs, both LP sides, bounded retries, deadline expiry, non-retryable statuses/inputs, rejected non-finite outputs, certificate gating, rollback and immediate LP release after a recovered exception. The existing determinism test excludes only the newly introduced wall-clock fields (`seconds` and `time_limit`); moves, policies and all remaining diagnostics must still match exactly.

Development checks exposed and fixed an exception/traceback reference cycle in an early draft; the final regression verifies release with cyclic GC disabled. The first full run only failed the old byte-for-byte trace comparison because it included new wall-clock values. That superseded run is retained in the local project development archive, separate from these final results.

These tests do not prove that all numerical failures are recoverable. Retry exhaustion preserves the previous valid strategy or raises explicitly. Game rules, engine binaries, fixed payoff parameters and the original 34-game evidence were not altered.

See [policy, provenance and limitations](../../../pair_a_prep/docs/zs21_highs_recovery.md).
