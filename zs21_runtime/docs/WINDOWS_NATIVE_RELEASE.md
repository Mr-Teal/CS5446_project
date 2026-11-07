# Windows native release identity after PR65

PR65 changes the export spelling in `pair_a_prep/zs21/native/inference.cpp`.
Although the Windows preprocessor preserves its meaning, changing the source
bytes invalidates the previous release's recorded SHA256. The runtime doctor
must continue to reject that mismatch; bypassing its check is not a repair.

The current Windows DLL was rebuilt on 7 November 2026 using the locked
`zs21_runtime` Pixi compiler. Its source, compiler, environment and artifact
identities are recorded in
[`builds/windows-native-2026-11-07.json`](../builds/windows-native-2026-11-07.json).
`assets.manifest.json` and `pair_a_prep/zs21/native/inference.manifest.json` now
identify that current source/DLL pair. The Stockfish 13 executable and NNUE
were not rebuilt. Archived validation and experiment manifests retain their
original identities and results.

## Validate a current delivery

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = (Get-Location).Path + ';' + (Join-Path (Get-Location) 'pair_b/src')
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -X utf8 zs21_runtime/scripts/doctor.py
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -X utf8 -m pytest -q pair_a_prep/tests/test_zs21_release.py
```

The real Windows regression checks all current assets, the native rule ABI,
four single-thread Stockfish 13 workers and an actual initial-board evaluation.
Separate regressions require the two manifests to agree with current bytes and
verify that missing/tampered assets are rejected before native loading.

## Future source or binary changes

Build to a fresh directory first:

```powershell
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -X utf8 zs21_runtime/scripts/build.py --native-only --output zs21_runtime/out/new-native-build
```

Review the build manifest, install the resulting DLL, and deliberately record
the new source/DLL hashes in both current manifests with a new dated build
record. `build.py` alone does not update the current release manifests. Keep old
build records and measurements unchanged. Repeat doctor, native/rule tests and
a real-engine integration check before treating the new artifact as validated.

The optional generic-tracker kernel has its own ignored build manifest and can
be rebuilt with `pixi run ... python -m pair_a_prep.build_belief_kernel`. Its
compiler check now matches the architecture and pointer size of Python instead
of assuming every 64-bit process is x86_64. ARM/macOS matching has deterministic
mock coverage; it is not a claim that those builds were executed on this host.
The locked shipped ZS21 runtime remains Windows-only; host portability has its
own documented validation scope.
