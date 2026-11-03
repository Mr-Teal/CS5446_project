# Bounded recovery of ZS21 HiGHS Not Set failures

Two historical LP solves stopped further tree expansion even though the agent
still had time. The agent kept its previous valid strategy, but did not try the
existing tighter-tolerance ladder: that ladder handled `CertificateError`
only, while unsuccessful `linprog` calls raised an ordinary `SolveError`.

The sequence-form solver now uses the same bounded ladder for a specifically
identified Not Set result. Game rules, payoff matrices, information penalties,
Stockfish, the shared tracker and the separate PCFR+ solver are unaffected.

## Recovery policy

1. Start with the existing `highs-ds`, single-thread, presolve-enabled solve at
   primal/dual feasibility tolerance `1e-8`.
2. Retry at `1e-9`, then `1e-10` only after a full-game certificate failure or
   an unsuccessful result with **both SciPy status 4 and the exact HiGHS
   marker `(HiGHS Status 0: Not Set)`**. An unrelated status-4 error is not
   classified as this failure.
3. Each attempt solves both primal and dual LPs cold, against the same already
   constructed matrices. Failure of the dual LP also restarts both sides.
4. All calls share the original absolute `perf_counter` deadline. Each receives
   only the time left; the solver checks the deadline before and after each LP
   and after certification. The existing agent submission reserve is unchanged.
5. At most three attempts are made. `refine=False` remains a single-attempt
   diagnostic mode. Time/iteration-limit statuses, infeasible/unbounded models,
   other solver errors, invalid inputs and missing/non-finite solutions do not
   trigger this retry policy.
6. Every accepted strategy must still pass the full original-game `1e-8`
   flow, inequality, nonnegativity and best-response-gap certificate. The
   acceptance threshold, `M=10^7`, support threshold and mode epsilon are not
   relaxed. Exhaustion or deadline expiry raises `SolveError`; the existing
   agent transaction retains its previous valid strategy, or fails explicitly
   if no valid strategy exists yet.

The runtime configuration retains the existing
`certificate_retry_tolerances = [1e-9, 1e-10]` key for compatibility; these
fixed tolerances now also cover the narrowly identified Not Set result. No
extra solver dependency, hidden restart budget or automatic model rescaling
has been introduced.

`LinearProgramError` is a `SolveError` subclass with `side`, `scipy_status`,
`highs_model_status` and `retryable_not_set`. The HiGHS status is extracted only
for the known Not Set marker; other native statuses are left unspecified.
`precision_attempts` keeps its existing fields and adds `stage`, `failure_kind`
and `lp_results`. Each actual call records its side, success, finite-solution
flag, SciPy status, message, elapsed time and effective options. Existing
gadget/agent traces carry this information, including failed expansions.
The SciPy API does not expose the native run status here, so it is not invented.

## Evidence and remaining uncertainty

The fixtures come from the original frozen evaluation, game-001 ply61 and
game-006 ply68 (human-readable games 2 and 7). The fixed-work replay matched
the preceding decisions and reproduced the failed calls. The full forms and
exact raw inputs are included under [tests/fixtures](../tests/fixtures/README.md).

Both models passed input-structure and exact rational feasibility/boundedness
audits. In HiGHS 1.12.0, their original numerical paths lost dual feasibility
after pivot485 / pivot670, then failed Phase1 recovery after605 /690 pivots.
The scaled-solve error path left the outer status as Not Set. These are
numerical solver failures, not proofs that the game is infeasible or unbounded.
The investigation does not attribute the first rounding error to one unique
coefficient or prove that every possible Not Set cause has been eliminated.

Original sources: [dual simplex](https://github.com/ERGO-Code/HiGHS/blob/v1.12.0/highs/simplex/HEkkDual.cpp)
and [scaled solve/status propagation](https://github.com/ERGO-Code/HiGHS/blob/v1.12.0/highs/lp_data/HApp.h).

With the recovery enabled, game001 succeeds at `1e-9` and game006 at `1e-10`.
Full-game certificate gaps are approximately `1.22e-16` and `3.12e-17`.
These are solver regressions, not new match results or evidence of stronger play.
The historical 34-game score remains an unchanged result of its frozen version.

## Reproduce and test

From the repository root, using the pinned Windows environment:

```powershell
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python zs21_runtime/scripts/check_highs_recovery.py
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess python -m pytest -q pair_a_prep/tests/test_zs21_not_set.py pair_a_prep/tests/test_zs21_precision.py
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess test
```

The checker writes `zs21_runtime/out/highs-recovery.json` and refuses to
overwrite an existing report; pass `--output` with a fresh path to repeat it.
It first reproduces each single-attempt failure and then records the recovered
full-game certificate, call options, attempts, versions and fixture/source hashes.

The new tests cover both actual historical inputs, primal/dual failure paths,
bounded retry counts, shared deadlines and late results, rejected input/status
classes, non-finite output, certificate rejection after recovery, and retention
of the agent's valid snapshot after all retries fail. Existing certificate-gap,
small-game oracle and gadget tests remain in place.

Saved release validation is under
[`zs21_runtime/validation/highs-recovery-2026-10-31`](../../zs21_runtime/validation/highs-recovery-2026-10-31).
