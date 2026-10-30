"""Record a finite Resolve oracle and a Maxmargin rescaling counterexample."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform

import numpy as np

from .gadgets import SubgameRoot, build_gadget
from .provenance import source_manifest, NORMALIZATION, git_revision
from .toy_games import Node, terminal, payoff_matrix, solve_matrix
from .value_frames import ValueFrame, transport_value, transport_resolve_prior, transport_delta


def run():
    source = {g: ValueFrame("declared_common_player0_unit") for g in ("A", "B")}
    target = {"A": ValueFrame("declared_common_player0_unit", 2., .3),
              "B": ValueFrame("declared_common_player0_unit", .25, -.1)}
    values = {"A": {"a": 1., "b": -.5}, "B": {"a": -.25, "b": .75}}
    alternates, prior = {"A": .2, "B": .1}, {"A": .7, "B": .3}
    def roots(table):
        return [SubgameRoot(g, g, Node(player=0, infoset="shared-own", children={
            a: terminal(v) for a, v in row.items()}), 1.) for g, row in table.items()]
    old = build_gadget(roots(values), alternates, "resolve", prior)
    conversion = transport_resolve_prior(prior, source, target)
    new_values = {g: {a: transport_value(v, source[g], target[g]) for a, v in row.items()}
                  for g, row in values.items()}
    new_alt = {g: transport_value(v, source[g], target[g]) for g, v in alternates.items()}
    new = build_gadget(roots(new_values), new_alt, "resolve", conversion.prior)
    old_matrix, new_matrix = payoff_matrix(old.tree)[0], payoff_matrix(new.tree)[0]
    old_value = solve_matrix(old_matrix)["profile_value"]
    new_value = solve_matrix(new_matrix)["profile_value"]
    residual = float(np.max(np.abs(old_matrix-(conversion.scale*new_matrix+conversion.offset))))
    if residual > 1e-12:
        raise AssertionError("Resolve payoff transport failed")
    return dict(scope="explicit-frame toy arithmetic only; no chess/gift-ledger/solver-state integration",
        python=platform.python_version(), base_commit_at_execution=git_revision(),
        source_hash_convention=NORMALIZATION, source_sha256=source_manifest(),
        resolve=dict(source_frames={g: asdict(f) for g, f in source.items()},
            target_frames={g: asdict(f) for g, f in target.items()}, source_prior=prior,
            target_prior=conversion.prior, expectation_scale=conversion.scale,
            expectation_offset=conversion.offset, source_matrix=old_matrix.tolist(),
            target_matrix=new_matrix.tolist(), max_matrix_residual=residual,
            source_lp_value=old_value, target_lp_value=new_value,
            reconstructed_source_lp_value=conversion.source_expected_value(new_value)),
        gift_delta_example=dict(source=.25, target_A=transport_delta(.25, source["A"], target["A"])),
        maxmargin=dict(source_margins={"A": .2, "B": .3}, target_scales={"A": .1, "B": 1.},
            unweighted_target_margins={"A": 2., "B": .3}, source_minimizer="A",
            unweighted_target_minimizer="B", source_unit_corrected_minimizer="A"),
        missing=["derive proven frames from actual CF reach/gadget offsets", "transport solver warm state",
                 "handle outside-sample branches", "validate across live turns"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(output=str(args.output), residual=report["resolve"]["max_matrix_residual"],
                         source_lp_value=report["resolve"]["source_lp_value"])))


if __name__ == "__main__":
    main()
