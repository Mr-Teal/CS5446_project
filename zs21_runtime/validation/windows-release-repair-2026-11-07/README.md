# PR65 Windows release repair verification

The independent repair is based directly on PR65 `e6a5701f481dc4ab4710f49b7727056ec58f9b50`.
Tested implementation commit: `fc4d31ada17d4709f4fa9f60ac4f6ddf4cdd1dcb`.
Subsequent delivery changes add evidence only. This branch does not import
PR66, PR67 or unrelated main-branch changes.

On Windows, the locked ZS21 Pixi runtime passed **13 tests, zero skips**:

```powershell
$env:PYTHONPATH = (Get-Location).Path + ';' + (Join-Path (Get-Location) 'pair_b/src')
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -X utf8 -m pytest -q pair_a_prep/tests/test_zs21_release.py --junitxml=NEW_OUTPUT/pr65-exact.xml
```

The tests run the actual doctor, check current asset/source/DLL identities,
verify the native ABI and four single-thread SF13 workers, reject tampered or
missing assets before loading, and exercise compiler target matching.
ARM/macOS target checks use mocks; no ARM/macOS build was run.

See `pr65-exact.xml`, `pr65-exact.log` and `artifact-sha256.json` here, plus the
[new build identity](../../builds/windows-native-2026-11-07.json) and
[maintenance guide](../../docs/WINDOWS_NATIVE_RELEASE.md).
The DLL was built during the integrated local study; the dated record keeps
that provenance. It is the same source/DLL pair tested on this independent
branch. Stockfish/NNUE and historical measurement bytes are unchanged.
