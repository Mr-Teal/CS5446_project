# Windows native tracker and Obscuro integration pilot

This completes the three requested checks: fixed difficult-update measurement,
PR59/PR60 integration, and a small colour-swapped real-engine pilot. The checks
were executed; formal long-game readiness **did not pass**.

## Source and environment

The isolated integration branch merges PR60 `cae3fef` onto PR59 `06023e2`.
The overlapping tracker implementation retains PR59's latest resume fixes;
both authors' regression files remain. ZS21's LP recovery is preserved.
Runtime commit `f94714a` includes the local compiler-selection fix and a
`--backend` option for the existing fixed-update profiler. No changes were
made to either author's branch or to main. PR51 is not included.

The optional kernel was actually built and loaded on Windows x64 with the
locked Pixi Python and conda-forge x86_64 GCC 16.2.0. DLL SHA256:
`ab512c381088143f37e8fe1a9e2f32e7c9121f1da7586e94e8ae0b83dd0de4ac`.
The build manifest and complete runtime Python hashes are in `summary.json`.
DLLs and environment files are not committed.

An initial build selected `C:\MinGW\bin\g++` before Pixi's cross compiler
and produced an incompatible DLL (`WinError 193`). The builder now prefers
`x86_64-w64-mingw32-g++` and rejects a non-x86_64 target for 64-bit Python.
An initial test invocation outside Pixi failed on that DLL; a subsequent
Pixi collection needed the repository's Pair B source path. After rebuilding
and supplying that path, **337 selected tests passed, zero skipped**, including
Python/native output continuation, LP recovery, shared contracts, evaluation
policy, factories and Pair C tests. These are focused integration regressions,
not the author's full 947-test suite or a new full ZS21 release validation.

## Fixed Black-view update at ply 9

Each trial is a fresh process replaying the same committed private stream.
Native loading is required before the controls start. Profiling instrumentation
is disabled: phase fields are zero placeholders, not measured phase costs.

| Backend / cooperative limits | Trials | Result | Median update wall time |
|---|---:|---|---:|
| Native, 250 ms slices, 5 s total, 64 MiB, 17 calls | 3 | One call-limit stop; two memory stops | 250.44 ms |
| Native, 1000 ms slices, 5 s total, 64 MiB, up to 6 calls | 3 | Three memory stops | 254.01 ms |
| Native, one 15 s slice, 512 MiB | 3 | Three complete updates | 1105.99 ms |
| Python, no time/memory limit | 1 | Complete | 8708.43 ms |

Failed-control times do not measure completed inference and must not be
described as fast solutions. The native and Python completed results have
identical serialized-belief signatures. The completed graph contains 197,428
histories and 33,191 states; retained logical owned bytes are 46,909,646.
The cap also charges transient allocation/output reserves conservatively,
so that retained count does not imply the 64 MiB update must succeed.
512 MiB is a logical budget, not measured process RSS. No hard deadline or
memory guarantee is established. One Python trial is not a controlled
whole-game speedup estimate.

## Real SF19 integration and pilots

Both configurations use standard start, seeds 17/18, alternating colours,
native exact tracking, sample size 3, no population cap, no pruning and no
partial-belief substitution. A is the sampled subgame prototype; B is the
fixed-depth-1 PCFR reference, **not ZS21**. Both use the pinned Windows
Stockfish 19 binary. Search clocks are diagnostic (`stop_on_time=false`).
Each configuration requests two attempts with a 40-ply cap.

| Tracker policy | First attempt | Second attempt | Tracker records |
|---|---|---|---:|
| 250 ms slices / 5 s total / 64 MiB / 16 resumes | White A wins by king capture at ply 39 | Black tracker fails at ply 9 after 17 calls, ~4.372 s, resume limit | 100 |
| One 15 s slice / 512 MiB / zero resumes | White A wins by king capture at ply 39 | Black tracker fails at ply 11, ~2.462 s, logical memory limit | 104 |

Increasing resources passes the earlier update but exposes a later limit;
it does not validate the relaxed setting as a formal protocol. The first
attempt is the same seed in both controls and is not independent strength
evidence. Neither configuration completes a colour pair. Do not pool them
or report the runner's conditional 100% win rate as agent strength.

The runner exits nonzero and records the tracking failure explicitly.
`tracker_updates.jsonl` retains initial, off-turn, terminal and failed updates.
Failed attempts still omit partial agent action records, so their console
zero-move totals do not mean no earlier actions occurred. Agent timing and
per-update tracking timing are separate; no whole-turn latency claim is made.
No engine failure was recorded; resources are owned by the runner's ExitStack.
This pilot did not independently inspect process liveness after cleanup.

## Reproduce and inspect

Run from the isolated integration checkout, with Pixi installed:

```powershell
$env:PYTHONPATH = (Get-Location).Path + ';' + (Join-Path (Get-Location) 'pair_b/src')
pixi run --locked --manifest-path zs21_runtime/pixi.toml -e darkchess python -m pair_a_prep.build_belief_kernel
pixi run --locked --manifest-path zs21_runtime/pixi.toml -e darkchess python pair_a_prep/results/windows_tracker_pilot_2026-11-01/run_controls.py
pixi run --locked --manifest-path zs21_runtime/pixi.toml -e darkchess python -m pair_c.run_evaluation pair_a_prep/results/windows_tracker_pilot_2026-11-01/strict.ini
pixi run --locked --manifest-path zs21_runtime/pixi.toml -e darkchess python -m pair_c.run_evaluation pair_a_prep/results/windows_tracker_pilot_2026-11-01/relaxed.ini
```

Expose the matching SF19 executable as `stockfish` or edit the local config
path. Its SHA256 is pinned; a different binary requires an explicit hash and
identity update. Choose fresh output directories. The controls script refuses
existing output files and uses `pair_a_prep/local_runs/windows-20261101`.
Its directory must exist before invocation. The two expected failed pilots
return nonzero after saving their summaries.

`summary.json` contains measurements, source manifests and failure details.
`evidence.zip` contains per-game/per-update records, fixed-update trials and
the successful regression XML. Absolute checkout/engine paths are sanitized;
the contents are not raw-byte replicas of the local artifacts. The original
local outputs remain ignored. `artifact-sha256.json` identifies the published
files; source hashes use the separately stated CRLF-to-LF convention.

## Recommendation before November 4

Review/integrate the resumed-output implementation and factory telemetry,
then agree a bounded evaluation scope with the tracker and evaluation owners.
These data do not support an unrestricted standard-start exact-tracker batch
under either tested budget. A reviewed approximation or a declared restricted
position/length protocol is a team decision. Do not silently prune, substitute
the referee state, discard failures or repeatedly raise budgets until one run
succeeds. Obscuro search itself needs no new mechanism for these checks.

## PR62 reproducibility correction

The original artifact manifest accidentally hashed CRLF working copies for
several files while Git contained LF blobs. The replacement manifest hashes
the actual published bytes, with `-text` attributes preserving them. This is
a metadata correction, not a rerun. `summary.json`, `evidence.zip` and the two
pilot configurations remain byte-identical to the previous published blobs.

The original PR60 `profile_update.py` is restored byte for byte so its
unchanged historical manifest verifies. The measured Windows variant is
preserved separately as `profile_update_windows_v1.py`, byte-identical to
the script in the measured revision. The controls now invoke that version
with an explicit original input path. `provenance-correction.json` records
both script hashes and the historical execution-manifest interpretation.
The 134-entry manifest in `summary.json` remains execution provenance; its
old profiler entry maps to the preserved Windows variant, not the restored
current file. No old source identity has been relabelled.

Verify the published artifact hashes, preserved evidence and historical
profiler manifest with:

```powershell
python pair_a_prep/results/windows_tracker_pilot_2026-11-01/verify_evidence.py
```
