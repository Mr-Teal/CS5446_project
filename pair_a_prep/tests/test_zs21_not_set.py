import json
import gc
from pathlib import Path
from time import perf_counter
import weakref

import numpy as np
import pytest
from scipy.optimize import OptimizeResult
from scipy.sparse import csr_matrix

from pair_a_prep.toy_games import matching_pennies
from pair_a_prep.zs21 import sequence_form as solver
from pair_a_prep.zs21.agent import PaperAgent
from pair_a_prep.zs21.gadget import Gadget
from pair_a_prep.zs21.lp_diagnostics import load_form
from pair_a_prep.zs21.model import Referee
from pair_a_prep.tests.test_zs21_agent import FixedEvaluator


FIXTURES = Path(__file__).parent / "fixtures"
NOT_SET = "(HiGHS Status 0: Not Set)"


def failed(status=4, message=NOT_SET):
    return OptimizeResult(success=False, status=status, message=message, x=None)


def stored_arrays(form):
    return [a.copy() for m in (form.A, form.B, form.C, *form.flows)
            for a in (m.data, m.indices, m.indptr)] + [a.copy() for a in form.rhs]


@pytest.mark.parametrize("stem,tolerances,value", [
    ("zs21_lp_not_set_game001_ply61", [1e-8, 1e-9], -0.0013766009475807452),
    ("zs21_lp_not_set_game006_ply68", [1e-8, 1e-9, 1e-10], -0.01732808261498714),
])
def test_historical_not_set_recovers_on_unchanged_full_model(stem, tolerances, value, monkeypatch):
    form = load_form(FIXTURES / (stem + ".npz"))
    original_arrays = stored_arrays(form)
    original = solver.linprog
    with np.load(FIXTURES / (stem + "_raw.npz"), allow_pickle=False) as arrays:
        raw = {key: arrays[key].copy() for key in arrays}
    metadata = json.loads(str(raw["metadata"]))
    for name in ("A_ub", "A_eq"):
        raw[name] = csr_matrix((raw[name + "_data"], raw[name + "_indices"],
                               raw[name + "_indptr"]), shape=raw[name + "_shape"])
    calls = []

    def record(*args, **kwargs):
        # This captured failure occurs in the first (primal) LP.
        if not calls:
            for name in ("A_ub", "A_eq"):
                assert kwargs[name].shape == raw[name].shape
                assert (kwargs[name] != raw[name]).nnz == 0
            for name in ("c", "b_ub", "b_eq"):
                assert np.array_equal(kwargs[name], raw[name])
            assert [list(bound) for bound in kwargs["bounds"]] == metadata["bounds"]
        calls.append(dict(kwargs["options"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(solver, "linprog", record)
    with pytest.raises(solver.LinearProgramError, match="Not Set") as error:
        form.solve(refine=False)
    assert error.value.scipy_status == 4 and error.value.side == "primal"
    assert len(calls) == 1
    calls.clear()
    result = form.solve(deadline=perf_counter() + 30)
    assert result.value == pytest.approx(value, abs=1e-12)
    assert abs(result.upper - result.lower) <= 1e-8
    assert result.flow_error <= 1e-8 and result.inequality_error <= 1e-8
    assert min(result.x.min(), result.y.min()) >= 0
    attempts = result.precision_attempts
    assert [a["feasibility_tolerance"] for a in attempts] == tolerances
    assert all(a["failure_kind"] == "highs_not_set" and not a["accepted"] for a in attempts[:-1])
    assert attempts[-1]["accepted"]
    for attempt in attempts[:-1]:
        record = attempt["lp_results"][0]
        assert record["scipy_status"] == 4 and record["highs_model_status"] == 0
        assert record["side"] == "primal" and not record["success"]
    assert [r["side"] for r in attempts[-1]["lp_results"]] == ["primal", "dual"]
    assert all(np.array_equal(before, after) for before, after in zip(original_arrays, stored_arrays(form)))
    json.dumps(attempts, allow_nan=False)


@pytest.mark.parametrize("failure_call", [1, 2])
def test_either_lp_failure_restarts_both_sides_cold(failure_call, monkeypatch):
    original = solver.linprog
    calls = []

    def inject(*args, **kwargs):
        calls.append(dict(kwargs["options"]))
        if len(calls) == failure_call:
            return failed()
        return original(*args, **kwargs)

    monkeypatch.setattr(solver, "linprog", inject)
    result = solver.SequenceForm(matching_pennies()).solve()
    assert result.value == pytest.approx(0.)
    assert len(calls) == failure_call + 2
    assert [o["primal_feasibility_tolerance"] for o in calls] == [1e-8] * failure_call + [1e-9] * 2
    assert result.precision_attempts[0]["stage"] == ("primal" if failure_call == 1 else "dual")
    assert [r["side"] for r in result.precision_attempts[-1]["lp_results"]] == ["primal", "dual"]


@pytest.mark.parametrize("refine,expected", [(True, 3), (False, 1)])
def test_not_set_retries_are_bounded(refine, expected, monkeypatch):
    calls = []
    monkeypatch.setattr(solver, "linprog", lambda **kw: calls.append(kw) or failed())
    form = solver.SequenceForm(matching_pennies())
    with pytest.raises(solver.LinearProgramError):
        form.solve(refine=refine)
    assert len(calls) == expected
    assert not any(a["accepted"] for a in form.solve_attempts)


@pytest.mark.parametrize("status,message", [
    (1, "Time limit reached. (HiGHS Status 13: Time limit reached)"),
    (2, "The problem is infeasible. (HiGHS Status 8: Infeasible)"),
    (3, "The problem is unbounded. (HiGHS Status 10: Unbounded)"),
    (4, "(HiGHS Status 2: Model error)"),
    (4, "An unrelated numerical error"),
    (2, NOT_SET),
])
def test_unrelated_statuses_are_not_retried(status, message, monkeypatch):
    calls = []
    monkeypatch.setattr(solver, "linprog", lambda **kw: calls.append(kw) or failed(status, message))
    form = solver.SequenceForm(matching_pennies())
    with pytest.raises(solver.LinearProgramError) as error:
        form.solve()
    assert error.value.scipy_status == status
    assert len(calls) == 1 and len(form.solve_attempts) == 1


@pytest.mark.parametrize("value", [None, np.nan, np.inf])
def test_success_with_invalid_solution_is_rejected_without_retry(value, monkeypatch):
    calls = []

    def invalid(**kw):
        calls.append(kw)
        x = None if value is None else np.full(len(kw["c"]), value)
        return OptimizeResult(success=True, status=0, message="Optimal", x=x)

    monkeypatch.setattr(solver, "linprog", invalid)
    with pytest.raises(solver.SolveError, match="non-finite"):
        solver.SequenceForm(matching_pennies()).solve()
    assert len(calls) == 1


def test_input_error_is_not_retried(monkeypatch):
    form = solver.SequenceForm(matching_pennies())
    form.C.data[0] = np.nan
    original, calls = solver.linprog, []

    def record(**kw):
        calls.append(kw)
        return original(**kw)

    monkeypatch.setattr(solver, "linprog", record)
    with pytest.raises(ValueError):
        form.solve()
    assert len(calls) == 1


def test_all_retries_share_one_deadline(monkeypatch):
    now, limits = [0.], []
    original = solver.linprog

    def record(**kw):
        limits.append(kw["options"]["time_limit"])
        if len(limits) == 1:
            now[0] += 3.
            return failed()
        answer = original(**kw)
        now[0] += 2.
        return answer

    monkeypatch.setattr(solver, "perf_counter", lambda: now[0])
    monkeypatch.setattr(solver, "linprog", record)
    result = solver.SequenceForm(matching_pennies()).solve(deadline=10.)
    assert limits == [10., 7., 5.]
    assert result.precision_attempts[-1]["accepted"]


def test_no_retry_starts_after_deadline(monkeypatch):
    clock, calls = iter([0., 9., 10.]), []
    monkeypatch.setattr(solver, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(solver, "linprog", lambda **kw: calls.append(kw) or failed())
    with pytest.raises(solver.SolveError, match="deadline before LP"):
        solver.SequenceForm(matching_pennies()).solve(deadline=10.)
    assert len(calls) == 1


@pytest.mark.parametrize("success", [False, True])
def test_solver_return_after_deadline_is_not_accepted_or_retried(success, monkeypatch):
    clock, calls = iter([0., 10.]), []
    original = solver.linprog

    def finish(**kw):
        calls.append(kw)
        return original(**kw) if success else failed()

    monkeypatch.setattr(solver, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(solver, "linprog", finish)
    form = solver.SequenceForm(matching_pennies())
    with pytest.raises(solver.SolveError, match="deadline after LP"):
        form.solve(deadline=10.)
    assert len(calls) == 1 and not form.solve_attempts[0]["accepted"]


def test_completed_certificate_after_deadline_is_rejected(monkeypatch):
    form, now = solver.SequenceForm(matching_pennies()), [0.]
    original = form._certify

    def certify(*args):
        result = original(*args)
        now[0] = 10.
        return result

    monkeypatch.setattr(form, "_certify", certify)
    monkeypatch.setattr(solver, "perf_counter", lambda: now[0])
    with pytest.raises(solver.SolveError, match="deadline after LP certificate"):
        form.solve(deadline=10.)
    assert not form.solve_attempts[0]["accepted"]


@pytest.mark.parametrize("certificate_recovers", [False, True])
def test_recovery_still_requires_full_certificate(certificate_recovers, monkeypatch):
    form = solver.SequenceForm(matching_pennies())
    linprog, certify = solver.linprog, form._certify
    calls, checks = [], []

    def solve(**kw):
        calls.append(kw)
        return failed() if len(calls) == 1 else linprog(**kw)

    def check(*args):
        checks.append(args)
        if not certificate_recovers or len(checks) == 1:
            raise solver.CertificateError("injected full-game gap failure")
        return certify(*args)

    monkeypatch.setattr(solver, "linprog", solve)
    monkeypatch.setattr(form, "_certify", check)
    if certificate_recovers:
        result = form.solve()
        assert abs(result.upper - result.lower) <= 1e-8
        assert result.precision_attempts[-1]["accepted"]
    else:
        with pytest.raises(solver.CertificateError):
            form.solve()
        assert not any(a["accepted"] for a in form.solve_attempts)
    assert len(calls) == 5 and len(checks) == 2
    assert form.solve_attempts[0]["failure_kind"] == "highs_not_set"
    assert form.solve_attempts[1]["failure_kind"] == "certificate"


def test_exhausted_not_set_preserves_agent_valid_snapshot(monkeypatch):
    referee = Referee()
    agent = PaperAgent("white", 42, FixedEvaluator(), max_rounds=1)
    original_gadget, original_lp = Gadget.solve, solver.linprog
    first, failures = [], []

    def gadget(game, deadline, **kwargs):
        if not first:
            result = original_gadget(game, deadline, **kwargs)
            first.append(result)
            return result
        return original_gadget(game, deadline, **kwargs)

    def fail_expansion(**kw):
        if first:
            failures.append(kw)
            return failed()
        return original_lp(**kw)

    monkeypatch.setattr(Gadget, "solve", gadget)
    monkeypatch.setattr(solver, "linprog", fail_expansion)
    try:
        agent.observe(referee.observe("white"))
        decision = agent.act(perf_counter() + 30)
        assert len(failures) == 3
        assert agent.snapshot is first[0]
        assert decision.diagnostics["rounds"] == 0
        assert "Not Set" in agent.trace["stop_reason"]
        assert len(agent.trace["incomplete_lp_precision_attempts"]) == 3
        assert all(a["failure_kind"] == "highs_not_set" for a in agent.trace["incomplete_lp_precision_attempts"])
        assert agent.snapshot.form.C.shape == agent.gadget.form().C.shape
        decision.validate_for(referee.observe("white"))
    finally:
        agent.close()


def test_recovered_failure_does_not_retain_lp_until_cyclic_gc(monkeypatch):
    original, calls = solver.linprog, [0]

    def inject(**kw):
        calls[0] += 1
        return failed() if calls[0] == 1 else original(**kw)

    monkeypatch.setattr(solver, "linprog", inject)
    enabled = gc.isenabled()
    gc.disable()
    try:
        form = solver.SequenceForm(matching_pennies())
        reference = weakref.ref(form)
        result = form.solve()
        del result, form
        assert reference() is None
    finally:
        if enabled:
            gc.enable()
