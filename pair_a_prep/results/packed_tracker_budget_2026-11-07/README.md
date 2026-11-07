# Packed tracker budget repair and Windows evidence

This delivery repairs the memory-budget integration discussed on PR66. It
targets `pair-a/packed-belief-states` and includes the Windows runtime repair
already merged through [PR71](https://github.com/Mr-Teal/CS5446_project/pull/71).
It does not merge the pending PR65/PR66 stack into main, import PR67, or change
PR33. The packed 16-bit counter boundary remains unchanged; this work does not
resolve other reviewers' counter-range or strength-evidence requests on PR66.

The tracker inventories retained packed bytes directly without decoding Board
objects or charging a payload again as a dictionary key. The same-observation
inventory is reused across resumes. Retained states/history paths, temporary
filter work and replacement output are accounted separately. Full feasible
history support, history-count weighting, observation boundaries and explicit
failure on incomplete support are preserved; no pruning is enabled.

## Validation scope

| Source scope | Shared / Pair A | Pair C, separate torch-enabled environment |
| --- | ---: | ---: |
| Original full integration of main `aac39b4` + PR66 + repairs, commit `7c6c862` | 1001 passed, zero skips | 46 passed, zero skips |
| Independent PR66 repair implementation, commit `6b2471d` | 1000 passed, zero skips | 16 passed, zero skips |

The second row was run specifically before delivering to PR66's older branch.
The first row also contains tests already on newer main. These are different
source scopes and overlapping tests, not additive coverage. The independent
PR65 repair separately passed 13 release/doctor/architecture tests.
Pair C emitted one upstream python-chess asyncio deprecation warning.

`delivery-verification.json` checks that merging the tested independent repair
with main recreates the original studied tree, apart from four newly added PR65
evidence files. Later publication changes add documentation/evidence and a
byte-preservation Git attribute, not implementation changes.

The frozen original study is published at
[`7c6c8626b65634bd0ede68ae36376ea3e6af28b3`](https://github.com/Mr-Teal/CS5446_project/tree/7c6c8626b65634bd0ede68ae36376ea3e6af28b3).
See [LOCAL_STUDY.md](LOCAL_STUDY.md) for the measured tables and limitations.
That report and the archive retain their original pre-publication wording
(including `remote_writes: false`), which describes the measurement stage.
This delivery publishes them without rewriting their history.

## Budget findings and remaining work

- Fixed Black ply11: 4,270,301 histories / 197,218 states. At 15 s / 512 MiB,
  the corrected single-call and 250 ms resume configurations each completed
  3/3 trials with exact count/sample parity. The original PR66 accounting
  stopped 3/3 trials on memory at this budget.
- With 3 GiB instead, original PR66's single update was slightly faster.
  The demonstrated improvement is accounting/resume behavior under finite
  budgets; it is not a universal speedup.
- Ten complete archived game inputs: 8 completed, 2 timed out; all 1075
  accepted updates matched reference counts and passed external true-path
  audits. This replay budget excludes agent thinking.
- Live SF19 budget diagnostics: seed17 completed 39 plies; seed18 stopped on
  Black ply13 after a 15.057 s tracker update, below the 1 GiB logical cap.
  Partial beliefs were rejected. These are not ZS21/SF13 strength matches.

**15 s/update, 1 GiB/tracker and 16 s/whole turn have not passed full-game
competition-budget acceptance.** Logical accounting is not a process RSS or
OS-enforced cap. The measured remaining bottleneck is inference time. No
formal strength batch was started, no failed run was counted as a loss/draw,
and the historical 34-game ZS21 record remains unchanged.

## Evidence and reproduction

[evidence.zip](evidence.zip) is the unchanged local handoff archive (2,278,047
bytes, 139 hashed evidence members plus their manifest), SHA256:

```text
ee67e161a55da08846d17f31e772012dced2ee03e386b7757a7538f7b8b0a7f0
```

It includes fixed-input plans and all 12 raw trial records, all ten replay
records, both live-game attempts with private streams/decisions/referee logs,
configs, environment snapshots, source snapshots, patches, build identities,
doctor output, regression logs/XML and setup failures. The pre-edit workspace
backup ZIP, temporary Git indices and pytest temporary directories are not
published. `artifact-sha256.json` here covers the published delivery files.

Extract the archive into a new local directory. Its `HANDOFF.md` gives portable
repository CLI commands with explicit input/output paths. The original outer
orchestration scripts retain their original workspace constants; adapt those
paths or use the repository CLI workers. They refuse existing output paths.

For tests, from the repository root:

```powershell
$env:PYTHONPATH = (Get-Location).Path + ';' + (Join-Path (Get-Location) 'pair_b/src')
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -X utf8 -m pair_a_prep.build_belief_kernel
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -X utf8 -m pytest -q tests pair_a_prep/tests
pixi run --manifest-path PATH_TO_PARENT/pixi.toml --locked -e pair-a-validation python -X utf8 -m pytest -q pair_c/regression_tests
```

The separate parent `pair-a-validation` environment inherits default and adds
pytest/python-chess. Its actual package versions and manifest/lock snapshots
are in the archive. An existing compatible torch-enabled Pixi environment is
also suitable for Pair C. Do not treat that environment as the pinned ZS21
runtime. Use fresh output paths when reproducing the saved test XML/logs.
