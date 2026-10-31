# Pair A delivery candidate: f821781

Runtime candidate: `f821781baae62af2629a2c41964cacc74f0f264e` on
`pair-a/per-action-diagnostics`. Validation ran from a clean working tree.
Subsequent documentation commits do not change the tested runtime. This is
a candidate freeze, not a release tag, merge approval or formal batch result.

## Frozen scope

The deliverable is an **Obscuro-inspired sampled subgame prototype** with:

- Shared FoW rules and the rules adapter, private observation/history inputs,
  and observation-consistent candidate histories from the exact tracker.
- PCFR+, one-sided selective growth and best-child initialization.
- Sampled synchronous knowledge projection, finite-cut gadget boundaries,
  heuristic cross-turn reuse and policy purification.
- Explicit Material or pinned Stockfish evaluation, lifecycle cleanup and
  Pair C configuration/factory integration.
- Per-action numeric diagnostics preserved in successful production records.

No additional algorithm mechanism is required for this declared approximate
scope. Full asynchronous knowledge closure, numerical ancestor-gift transfer
and further policy/regret ablations are outside this freeze. Projected
training labels remain disabled pending the root/weight agreement. The
partner's ZS21 integration is a separate implementation, not the fixed-depth
PCFR reference opponent used in the smoke configuration.

## Candidate acceptance record

| Check | Result |
|---|---|
| Shared + Pair A + Pair C regression selection | First run: 753 passed, 3 failed because `pixi` was absent from PATH |
| Three existing ZS21 process tests, environment-corrected rerun | 3 passed; temporary Pixi PATH and normal user-directory access |
| Distinct regression cases passing across those two runs | 756; not a single uninterrupted all-green suite |
| Real SF19 standard-start traced smoke | 2 colour-swapped four-ply attempts, 8 actions, no failures/fallbacks/over-budget actions |
| Normal production runner using generated pinned config | 2 capped attempts, 8 actions, no failures; moves match traced run |
| Diagnostics | Saved mappings equal traced decisions; production output preserves mappings |
| Engine lifecycle | Four factory-reset callbacks and both traced engines closed |
| Outcomes | Zero terminal games scored; win/score rates unavailable |

The Pixi rerun produced a pytest cache-write warning but passed all three
tests. No source fix, lockfile update or permanent environment modification
was required. The initial failures and successful rerun must both remain
visible; do not describe the initial invocation as fully passing.

Commands from the repository root:

```powershell
.\pair_b\.venv\Scripts\python.exe -m pytest tests pair_a_prep/tests pair_c/regression_tests -q
# If Pixi is installed through conda, expose its bin directory for this shell.
# Use your actual environment location; the path is machine-specific.
$env:PATH = 'C:\path\to\conda-env\bin;' + $env:PATH
.\pair_b\.venv\Scripts\python.exe -m pytest pair_a_prep/tests/test_zs21_integration.py::test_actual_paper_agent_process_can_play_and_exit_cleanly pair_a_prep/tests/test_zs21_protocol.py -q
```

Real-engine reproduction uses the [handoff commands](stockfish_evaluation_handoff.md)
with the standard-start config and fresh output directories. Compact evidence
is in [`delivery_candidate_reference.json`](../results/delivery_candidate_reference.json).
The trace adds overhead; these are not latency benchmarks. Stockfish 19
differs from the paper's Stockfish 14.

## Exit criteria and remaining gates

The short integration checks pass at the frozen runtime. Final delivery still
requires reviewed dependency merges, a successful check on the resulting
integrated checkout, and resolution of the exact tracker's long-game capacity
limit with its owner. Pair C's provenance fixes and an agreed match protocol
are required before formal evaluation claims. See the
[formal acceptance gates](formal_evaluation_readiness.md).

Do not add more optional mechanisms to resolve those process or capacity
gates. Reopen runtime development for a reproduced defect or an agreed
integration requirement. Changes to rules, search, tracker, evaluator or
runner invalidate the corresponding frozen evidence and require targeted
revalidation. Documentation-only edits do not refresh measured results.

Immediate work allocation:

- Pair A user: maintain this candidate and respond to concrete review findings;
  report/slides material is already prepared.
- Tracker owner with Pair A: agree and validate bounded, history-preserving
  inference for the intended game length.
- Pair C and evaluator owners: integrate provenance, agree the frozen protocol
  and run formal matches after the runtime gates are cleared.
- Team reviewers: resolve the upstream review stack; this document does not
  bypass an outstanding change request or assign approval to anyone.
