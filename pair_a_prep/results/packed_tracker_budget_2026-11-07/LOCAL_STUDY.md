# Packed tracker integration and Windows runtime repair — 2026-11-07

Local branch: `pair-a/packed-tracker-budget`. Source combines main
`aac39b4b9226a46c63479b236a805f980412b61c`, PR65 `e6a5701` and PR66 `0968af3`
with the previously unpublished memory ledger. PR67 and its changed search
mechanisms are not imported. PR33 remains deferred. No GitHub push, comment,
review or merge and no formal playing-strength batch occurred.

## Implementation and verification

- The ledger inventories packed payloads directly, charges a shared key once,
  and never decodes a Board merely to measure storage. Retained states, path
  nodes/edges, temporary filter work and output replacement remain separate.
  Inventory is reused across resumes; full history support and exact-or-fail
  behavior are preserved. PR66's 16-bit counter boundary is unchanged by the
  user's explicit review decision.
- A newly built ZS21 DLL and both current manifests agree with the portability
  source. Stockfish 13 and NNUE bytes are unchanged. All 66 current assets match;
  134 historical evidence files remain byte-identical. The real
  Windows doctor verifies the rule ABI and four single-thread SF13 workers.
- Compiler matching accepts appropriate x86/ARM target triples instead of
  treating all 64-bit hosts as x86_64. Windows was actually built and run;
  ARM/macOS architecture checks are mocked, not platform build certification.
- Shared/Pair A: **1001 passed**, zero skips, in the locked Python 3.12 runtime.
  Pair C: **46 passed**, zero skips, in a separate torch-enabled Pixi environment.
  These are separate invocations, not one combined environment or additive
  coverage with the earlier 214 focused tests. Pair C reports one upstream
  python-chess asyncio deprecation warning under Python 3.14.
- New regressions cover no-decode inventory/allocation, shared packed payload,
  current source/DLL identities, actual doctor execution, tamper/missing-file
  rejection and compiler architecture matching. The earlier ledger regressions
  continue to cover resume/output/RNG/history parity and scratch lifetime.
  `before.xml` includes both reproduced integration failures and tests for newly
  introduced helper APIs; its nine failures are not nine distinct product bugs.

The initial full-suite command omitted the documented Pair B PYTHONPATH and
failed collection. The first Pair C environment lacked pytest. These setup
failures are retained separately; the corrected invocations above passed.
`pair-a-validation` inherits the parent default environment, adding pytest and
python-chess; it does not change the locked `zs21_runtime` environment. See
[Pixi's multi-environment documentation](https://pixi.prefix.dev/latest/workspace/multi_environment/).

## Fixed Black ply11: three independent processes per configuration

The exact private prefix is the same reconstructed seed18 input used in the
November 2 study; its prefix through ply9 matches Bryan's saved fixture. Prefix
construction and post-update size diagnostics are outside the timed update.
Cases were frozen before execution; processes ran sequentially. The PR66
baseline uses its original tracker and graph. The integrated code keeps the
same transition semantics. All complete results match **4,270,301 histories,
197,218 states and the exact returned-sample signature**.

| Case | Complete | Median update s | Range s | Max logical MiB | Peak RSS MiB |
| --- | ---: | ---: | --- | ---: | ---: |
| pr66-512 | 0/3 | 1.517 | 1.507–1.577 | 511.93 | 146.12 |
| integrated-512 | 3/3 | 6.316 | 6.275–6.454 | 216.00 | 247.88 |
| integrated-512-sliced | 3/3 | 6.888 | 6.804–6.980 | 216.00 | 249.54 |
| pr66-reference | 3/3 | 5.835 | 5.766–5.839 | 1974.98 | 249.56 |

PR66's old cumulative charges exhaust 512 MiB despite much lower actual RSS.
The corrected ledger improves budget usability, not universal speed: the
unconstrained-enough PR66 single call is slightly faster on this fixture. All
integrated runs inventory once, including sliced runs. Logical charges are not
RSS or an OS memory limit; no pruning or hidden true-state injection occurs.

## Ten complete-game input replays

Frozen games 0–9, each in a new process. Limits: 15 s per tracker update,
1 GiB logical accounting per tracker, 16 s for both serial tracker updates.
This **excludes agent thought time**. Successful updates must match archived
state/history counts and pass an external true-path audit.

| Game | Original plies | Result | Accepted updates | Failed ply | Max update s | Max combined tracking s | Peak RSS MiB |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 0 | 104 | failed | 71 | 35 | 15.047 | 15.049 | 368.48 |
| 1 | 72 | complete | 146 | — | 14.731 | 15.304 | 497.01 |
| 2 | 34 | complete | 70 | — | 0.026 | 0.029 | 89.71 |
| 3 | 85 | complete | 172 | — | 10.944 | 10.954 | 390.62 |
| 4 | 65 | complete | 132 | — | 0.990 | 0.994 | 129.93 |
| 5 | 51 | failed | 32 | 16 | 15.046 | 15.046 | 374.84 |
| 6 | 128 | complete | 258 | — | 6.344 | 6.347 | 257.55 |
| 7 | 16 | complete | 34 | — | 0.090 | 0.143 | 83.25 |
| 8 | 30 | complete | 62 | — | 0.034 | 0.035 | 84.19 |
| 9 | 48 | complete | 98 | — | 4.824 | 5.023 | 230.76 |

Result: **8/10 complete**, 1075 accepted updates
out of 1077 recorded attempts. Every accepted update retains
complete support and passes both audits. Failures stop explicitly; they are
not losses/draws and are not omitted. The November 2 Board-ledger 6/10 result
remains a separate historical run, not a controlled same-session baseline.

## Live whole-turn diagnostic

The existing SF19 pilot uses seeds17/18 from the normal start, 15 s tracking,
1 GiB logical memory, a 16 s whole-turn wrapper and a 400-ply cutoff. The clock
includes both serial trackers, tracing and agent execution from referee handoff.
It is cooperative; late results are rejected, not forcibly interrupted by the
OS. This exercises the generic tracker and existing main search, not ZS21/SF13
playing strength. Private inputs, attempted actions and applied moves survive
resource failures.

| Seed | Result | Applied plies | Failed update | Max update s | Max returned whole-turn s | Peak RSS MiB |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| 17 | complete | 39 | — | 0.005 | 1.385 | 126.60 |
| 18 | failed | 13 | black ply13: time | 15.057 | 8.784 | 615.38 |

No formal competition budget is accepted merely because a fixture or short
game passed. Use the complete attempt records when deciding the final budget.
Keep exact support versus explicit approximation and the whole-turn clock in
that decision; the current work does not silently change those policies.
The live seed18 Black private prefix through ply11 matches the fixed-input
comparison exactly. The tested 15 s/update, 1 GiB and 16 s whole-turn policy
**has not passed complete-game readiness**: two archived replays and one live
attempt still time out despite successful integration tests.

## Reproduction and evidence

Run the scripts through Pixi from the outer project directory:

```powershell
pixi run --locked -e darkchess python -X utf8 scripts/run_packed_budget_2026_11_07.py fixed
pixi run --locked -e darkchess python -X utf8 scripts/run_packed_budget_2026_11_07.py replay
pixi run --locked -e darkchess python -X utf8 scripts/run_packed_budget_2026_11_07.py matches
```

They refuse to overwrite existing stage outputs. Use a new dated output root
for a new run. Each stage's plan pins source hashes and settings; raw JSON,
JSONL, configs, logs and failures are retained in its subdirectory. The repo's
`pair_a_prep.benchmark_tracker_*` modules are the reusable CLI workers.

`before-working-tree.zip` and `.patch` preserve all previously uncommitted
work. `native-build/`, the current build record, regression XML/logs,
`doctor.json`, environment snapshots and `verification.json` support the
implementation handoff. Historical 34-game ZS21 results are unchanged.
