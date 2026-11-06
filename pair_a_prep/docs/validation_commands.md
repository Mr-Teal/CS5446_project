# Separate validation commands for the integrated runtime

Pair A owns this command handoff. The measured reference is PR59 runtime
`78f687b860a3fb95160b80be472d7fc8621a144b`; this documentation does not
refresh its results or approve a different head.

## Why two invocations

Do not advertise `pixi ... test pair_c/regression_tests` as an all-green
combined command. Pair A and Pair C both contain `test_provenance.py`; default
pytest module imports collide during combined collection. Run the suites in
separate Python processes. This documents the supported invocation without
hiding the issue through a different import mode.

The locked ZS21 Pixi environment intentionally has no PyTorch dependency.
Two Pair C loader-provenance tests import Pair B network classes, so the Pair C
suite needs an existing torch-enabled environment. Do not change the locked
runtime or install packages merely to combine these two validation scopes.

## Windows: shared and Pair A, including native checks

From the repository root, with Pixi on PATH:

```powershell
$env:PYTHONPATH = (Get-Location).Path + ';' + (Join-Path (Get-Location) 'pair_b/src')
pixi run --locked --manifest-path zs21_runtime/pixi.toml -e darkchess python -m pair_a_prep.build_belief_kernel
pixi run --locked --manifest-path zs21_runtime/pixi.toml -e darkchess test --junitxml=zs21_runtime/out/shared-paira.xml -o cache_dir=zs21_runtime/out/pytest-cache
```

The builder must select an x86_64 compiler for 64-bit Python. Its ignored
`pair_a_prep/_belief_build/manifest.json` records the actual compiler, source
hashes and DLL identity. Confirm optional native cases ran rather than counting
skips as native validation. Pixi must remain visible to subprocess tests.
The task includes `tests` and `pair_a_prep/tests`; do not append Pair C here.

## Pair C in the existing torch-enabled environment

Use that environment's Python explicitly; the example assumes the project's
existing Pair B virtual environment. Substitute its actual location if needed.
Keep the repository root and Pair B source on PYTHONPATH as above.

```powershell
$pairBPython = Join-Path (Get-Location) 'pair_b/.venv/Scripts/python.exe'
& $pairBPython -c "import torch; print(torch.__version__)"
& $pairBPython -m pytest pair_c/regression_tests -q --junitxml=zs21_runtime/out/pairc.xml -o cache_dir=zs21_runtime/out/pytest-cache
```

The second invocation checks provenance/tracking regressions, including mocked
network resource declarations. Passing does not certify GPU inference,
checkpoint quality or formal match readiness. Record both Python environments
and commands; do not call the two results one locked whole-project run.

## Evidence scope and merge handoff

At the reference head, the Windows check reported 962 shared/Pair A passes in
the locked environment and 46 Pair C passes in the separate torch-enabled
environment, both with zero skips. The initial combined collection error and
locked Pair C's two missing-torch failures were retained in the review report.
A separate actual SF19 pawn smoke completed two four-ply capped attempts,
with provenance, action diagnostics and 20 tracker update records together.
These are short integration checks, not a whole-game strength result.
The source for these November 3 results is [the exact-head validation report](https://github.com/Mr-Teal/CS5446_project/pull/59#issuecomment-6593444508); its detailed XML and machine-readable outputs remain local to the validation checkout. The November 1 archive linked below describes earlier pilot/provenance evidence, not these fresh 962/46 results.

Nine published Windows artifacts and eight historical profile files can be
checked against their manifests. The 134 historical execution sources must be
verified against their recorded source revision and profiler mapping, not
against the current integrated runner. Do not relabel old execution hashes.
See [the preserved Windows evidence](../results/windows_tracker_pilot_2026-11-01/README.md).

Before main integration, obtain review of the exact head after conflict
resolution. Keep the native evidence, independent review, known strict ply9 /
relaxed ply11 failures and whole-turn budget agreement separate. Successful
regressions do not settle the latter resource/protocol decisions. Rerun the
relevant checks when runtime sources change; documentation-only edits do not
refresh measured results.
