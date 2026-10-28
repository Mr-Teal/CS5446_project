from pathlib import Path

import numpy as np
import pytest

from pair_a_prep.toy_games import matching_pennies
from pair_a_prep.zs21 import sequence_form as solver
from pair_a_prep.zs21.lp_diagnostics import load_form, save_form


FIXTURE = Path(__file__).parent / "fixtures/zs21_lp_v5_ply80.npz"


def test_real_game_certificate_is_refined_without_relaxing_acceptance():
    form = load_form(FIXTURE)
    with pytest.raises(solver.CertificateError, match="LP certificate failed"):
        form.solve(refine=False)
    rejected = form.solve_attempts[0]
    assert rejected["gap"] == pytest.approx(1.242005452852398e-8, abs=1e-13)
    result = form.solve()
    assert result.upper - result.lower <= 1e-8
    assert result.flow_error <= 1e-8 and result.inequality_error <= 1e-8
    assert len(result.precision_attempts) > 1
    assert not result.precision_attempts[0]["accepted"]
    assert result.precision_attempts[-1]["accepted"]
    assert result.precision_attempts[-1]["feasibility_tolerance"] < 1e-8
    assert result.x.min() >= 0 and result.y.min() >= 0


def test_refinement_does_not_start_an_lp_after_its_deadline(monkeypatch):
    form = load_form(FIXTURE)
    now = [0.]
    calls = []
    certify, linprog = form._certify, solver.linprog

    def checked(*args):
        try:
            return certify(*args)
        finally:
            now[0] = 10.

    def counted(*args, **kwargs):
        calls.append(kwargs["options"]["primal_feasibility_tolerance"])
        return linprog(*args, **kwargs)

    monkeypatch.setattr(form, "_certify", checked)
    monkeypatch.setattr(solver, "perf_counter", lambda: now[0])
    monkeypatch.setattr(solver, "linprog", counted)
    with pytest.raises(solver.SolveError, match="deadline before LP"):
        form.solve(deadline=10.)
    assert calls == [1e-8, 1e-8]
    assert not any(attempt["accepted"] for attempt in form.solve_attempts)


def test_numeric_fixture_preserves_payoffs_and_full_flow_constraints(tmp_path):
    original = solver.SequenceForm(matching_pennies(), [(('p0', 'H'), None, -.5)])
    path = tmp_path / "game.npz"
    save_form(original, path)
    restored = load_form(path)
    for name in ("A", "B", "C"):
        assert np.array_equal(getattr(original, name).toarray(), getattr(restored, name).toarray())
    for before, after in zip(original.flows, restored.flows):
        assert np.array_equal(before.toarray(), after.toarray())
    a, b = original.solve(), restored.solve()
    assert np.array_equal(a.x, b.x) and np.array_equal(a.y, b.y)
    assert a.value == b.value
    with pytest.raises(FileExistsError):
        save_form(restored, path)
