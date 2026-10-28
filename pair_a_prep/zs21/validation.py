"""Independent small-game evidence for the paper's central constructions."""

import argparse
from collections import defaultdict
from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from ..toy_games import Node, terminal, payoff_matrix, solve_matrix
from .sequence_form import SequenceForm
from .gadget import make_subgame, observed_sequence


def realization(form, player, policy):
    result = np.zeros(len(form.sequences[player]))
    result[0] = 1.
    for key, (parent, actions, indices) in form.infosets[player].items():
        probabilities = policy.get(key, dict.fromkeys(actions, 1 / len(actions)))
        result[indices] = [result[parent] * probabilities[a] for a in actions]
    return result


def simultaneous(own, other, hh, tt, mismatch=0.):
    node = Node(player=0, infoset=own)
    node.observations = (own, other)
    for first in ("H", "T"):
        node.children[first] = Node(player=1, infoset=other + ":move",
            children={second: terminal(hh if first == second == "H" else
                                       tt if first == second == "T" else mismatch)
                      for second in ("H", "T")})
    return node


def appendix_c():
    roots = [simultaneous("R1" if n <= 2 else "R3", f"C{2*(n//2)}", n, 5-n)
             for n in range(1, 5)]
    root = Node(children={str(i): n for i, n in enumerate(roots)} | {"e": terminal(0.)},
                probabilities=dict.fromkeys(["0", "1", "2", "3", "e"], .2))
    form = SequenceForm(root)
    old = replace(form.solve(), x=realization(form, 0, {}))
    common, limited = make_subgame(old, roots), make_subgame(old, roots[:2])
    common_group = next(g for g in common.groups if g.key == "C2")
    limited_group = next(g for g in limited.groups if g.key == "C2")
    assert np.isclose(common_group.audit["alternate"], 1.25)
    assert np.isclose(limited_group.audit["alternate"], 2.5)
    offsets = defaultdict(float)
    for key, value in limited_group.offsets:
        offsets[key] += value
    assert np.isclose(offsets[("C2:move", "H")], 1.5)
    assert np.isclose(offsets[("C2:move", "T")], 1.)
    report = {}
    for name, game in (("common", common), ("one_klss", limited)):
        reduced = game.form()
        x = realization(reduced, 0, {})
        fixed_margin = reduced.counterfactual(x)[0][0]
        assert abs(fixed_margin) < 1e-10
        report[name] = dict(groups=[g.audit for g in game.groups], A=reduced.A.toarray().tolist(),
                            B=reduced.B.toarray().tolist(), sequences=reduced.sequences,
                            uniform_blueprint_margin=float(fixed_margin), solved_value=game.solve().value)
    report["printed_discrepancies"] = dict(C2_common_printed=2.5, C2_common_derived=1.25,
        C2_one_klss_printed=5., C2_one_klss_derived=2.5, C4_prose_printed=2., C4_derived=.5,
        C2_one_klss_prose_printed=3.)
    return report


def proposition3(n):
    roots = [simultaneous(f"R{i}", "C", -1., -1., 1.) for i in range(n)]
    form = SequenceForm(Node(children={str(i): r for i, r in enumerate(roots)},
                             probabilities=dict.fromkeys(map(str, range(n)), 1/n)))
    old_policy = {f"R{i}": {"H": .5+2/n, "T": .5-2/n} for i in range(n)}
    x = realization(form, 0, old_policy)
    old = replace(form.solve(), x=x)
    local_policy = {}
    for i, root in enumerate(roots):
        answer = make_subgame(old, [root]).solve()
        local_policy[f"R{i}"] = answer.policy(0, f"R{i}")
        assert local_policy[f"R{i}"]["T"] > 1-1e-9
    old_security = float(form.counterfactual(x)[0][0])
    new_security = float(form.counterfactual(realization(form, 0, local_policy))[0][0])
    assert np.isclose(old_security, -4/n) and np.isclose(new_security, -1)
    return dict(n=n, blueprint_security=old_security, independent_klss_security=new_security,
                exploitability_increase_factor=n/4, policies=local_policy)


def n_matching_pennies(n=6):
    roots = [simultaneous(f"R{j//2}", f"C{(j+1)//2}", j, n-j) for j in range(1, n+1)]
    root = Node(children={str(i): r for i, r in enumerate(roots)},
                probabilities=dict.fromkeys(map(str, range(n)), 1/n))
    form = SequenceForm(root)
    exact = form.solve()
    oracle = solve_matrix(payoff_matrix(root)[0])
    assert abs(exact.value-oracle["profile_value"]) < 1e-8
    reports = []
    for epsilon in (0., .25):
        policies = {key: {a: (1-epsilon)*p + epsilon*.5 for a, p in exact.policy(0, key).items()}
                    for key in form.infosets[0] if isinstance(key, str)}
        x = realization(form, 0, policies)
        old = replace(exact, x=x)
        updated = {}
        for key in policies:
            answer = make_subgame(old, [r for r in roots if r.infoset == key]).solve()
            updated[key] = answer.policy(0, key)
        lower_old = float(form.counterfactual(x)[0][0])
        lower_new = float(form.counterfactual(realization(form, 0, updated))[0][0])
        reports.append(dict(uniform_mixture_epsilon=epsilon, value=exact.value,
                            old_exploitability=exact.value-lower_old,
                            independent_klss_exploitability=exact.value-lower_new))
    return dict(n=n, normal_form_value=oracle["profile_value"], sequence_form_value=exact.value, cases=reports)


def report():
    return dict(appendix_c=appendix_c(), proposition3=[proposition3(n) for n in (8, 16)],
                n_matching_pennies=n_matching_pennies(),
                scope="small-game correctness; not the paper's Table 1 experiments or chess strength")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = report()
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Appendix C, Proposition 3 and N-matching-pennies checks passed.")
