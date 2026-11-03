# Shared BeliefTracker: full-game validation and measurements

Evidence for the follow-up to [PR #37](https://github.com/Mr-Teal/CS5446_project/pull/37).
The measured tracker was based on main `1db35d68638d52353381d13de20addfea58a4d99`.
The shared tracker retains complete feasible histories in a DAG; the separate
ZS21 agent's tracker is unchanged. See the [tracker guide](../../docs/belief_tracker.md).

## Results

- **890 tests passed** in the original full Pair A/shared regression run.
- **10 complete existing games replayed**, 633 plies, 1,286 private updates across both players.
- No time, memory or internal population cap; no pruning. Output sample size 16 affects returned hypotheses only.
- The true hypothetical history remained represented after every update, verified outside the tracker.
- Median update 5.78 ms; P95 1,658.30 ms; maximum 117.59 s. Six updates exceeded 16 s.
- Peak represented histories: 170,063,309,408,190,345,000; peak current board/counter nodes: 990,143.
- Peak tracker-owned objects: 1,645.53 MiB; whole-process peak RSS: 4,479.79 MiB.
- Paired opening-prefix measurements: 28.08x aggregate speedup over the frozen reference, with matching history counts.

This establishes completion on the selected corpus, not a hard real-time guarantee
or a new playing-strength result. Both agents' existing actions were replayed.
The tracker sees only its own private observations and own actions; the referee
board is used exclusively by the external replay and membership audit.

## Evidence

- [Per-game and size-frequency tables](full-games/report.md)
- [Merged per-update records](full-games/updates.jsonl)
- [Statistics, seeds and source hashes](full-games/summary.json)
- [Paired reference comparison](comparison/comparison.md)
- [Full regression log](validation/regression-final.log) and [JUnit](validation/regression-final.xml)
- [Original validation and environment record](validation/verification.json)
- [Publication checks](validation/publication.json), [portable regression log](validation/portable-regression.log)
  and [JUnit](validation/portable-regression.xml)
- [Portable Stockfish/runtime check](validation/portable-doctor.json) and
  [packaged-input full-game smoke replay](validation/portable-replay-002.jsonl)
- [Machine configuration](validation/hardware.json)
- [Measured source snapshot](measured-source/) and [replay inputs](inputs/)

Archived records preserve their original absolute host paths and hashes. Those paths
are provenance, not prerequisites: use the repository-local `inputs/` below.
The published report generators use English to follow the repository convention;
no inference behavior or measured numbers were changed for publication.
Before upload, the repository's own locked Pixi environment passed all 890 tests,
the four single-thread Stockfish 13 workers passed the runtime check, and packaged
game 2 completed all 34 plies and 70 private updates. This smoke replay is separate
from the original ten-game timing statistics. Git attributes preserve the archived
bytes; [archive-manifest.json](archive-manifest.json) records their SHA-256 hashes.
Memory counts reachable tracker-owned Python objects once; process RSS additionally
includes both trackers, audit temporaries, the interpreter and allocator retention.
Frequencies are per-update observations from this selected corpus, not universal
probabilities of FoW states. The tables also separate decision-turn observations.

## Reproduce on Windows with the existing portable Pixi runtime

From the repository root in PowerShell:

```powershell
$trackerRepo = (Get-Location).Path
$env:PYTHONPATH = "$trackerRepo;$trackerRepo\pair_b\src"
Set-Location zs21_runtime
pixi run --locked -e darkchess python -m pair_a_prep.build_belief_kernel
pixi run --locked -e darkchess python reproduce.py test
pixi run --locked -e darkchess python -m pair_a_prep.benchmark_belief_tracker --input ../pair_a_prep/results/belief_tracker_2026-10-31/inputs --output out/belief-replay --games 0 1 2 3 4 5 6 7 8 9 --backend native --isolated
pixi run --locked -e darkchess python -m pair_a_prep.summarize_belief_benchmark out/belief-replay --expected-games 10
pixi run --locked -e darkchess python -m pair_a_prep.compare_belief_benchmarks --input ../pair_a_prep/results/belief_tracker_2026-10-31/inputs --output out/belief-comparison
```

Use a new output directory for each run; the benchmark refuses to overwrite traces.
Wall-clock measurements vary by machine. Native acceleration is optional; the pure
Python tracker remains available with `backend="python"`. Native binaries are built
locally and ignored by Git. Time and memory controls are cooperative; see the guide
for partial results, resume behavior, empty support and explicit pruning.

To regenerate only the committed statistical tables without replaying games:

```powershell
pixi run --locked -e darkchess python -m pair_a_prep.summarize_belief_benchmark ../pair_a_prep/results/belief_tracker_2026-10-31/full-games --expected-games 10
```
