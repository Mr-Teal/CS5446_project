"""Finite-gadget reach/offset frames and checked affine warm-continuation evidence."""

import argparse
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import platform

from .affine_solver import transport_affine_solver
from .gadgets import SubgameRoot, build_gadget
from .gadget_frames import certify_gadget_frames
from .pcfr import PCFRPlus
from .provenance import source_manifest, NORMALIZATION, git_revision
from .toy_games import Node, terminal, behavioral_value
from .value_frames import transport_value


def _transform(root, scale, offset):
    root = deepcopy(root)
    def visit(node):
        if node.payoff is not None:
            node.payoff = scale*node.payoff+offset
        else:
            for child in node.children.values():
                visit(child)
    visit(root)
    return root


def _policy_error(a, b):
    return max((abs(value-b.policy(average)[p][key][action]) for average in (False, True)
        for p in (0, 1) for key, row in a.policy(average)[p].items()
        for action, value in row.items()), default=0.)


def run():
    values = (("a1", "A", 1., .75), ("a2", "A", 3., -.5), ("b", "B", 2., .25))
    roots = tuple(SubgameRoot(name, group, Node(player=0, infoset="I", children={
        "L": terminal(value), "R": terminal(-value)}), mass)
        for name, group, mass, value in values)
    alternates = {"A": .125, "B": -.25}
    resolve = build_gadget(roots, alternates, "resolve", {"A": .5, "B": .5})
    margin = build_gadget(roots, alternates, "maxmargin")
    frames = certify_gadget_frames(resolve, margin)
    frame_rows = []
    for group, mass in frames.group_masses.items():
        raw_sum = sum(root.reach_mass*(.3*root.continuation.children["L"].payoff+
            .7*root.continuation.children["R"].payoff) for root in roots if root.opponent_infoset == group)
        local = behavioral_value(margin.tree.children[group], ({"I": {"L": .3, "R": .7}}, {}))
        frame_rows.append(dict(group=group, declared_reach_mass=mass, raw_weighted_sum=raw_sum,
            raw_conditional=raw_sum/mass, actual_maxmargin_local=local,
            transported_local=transport_value(raw_sum/mass, frames.source[group], frames.target[group]),
            reconstructed_sum=frames.target[group].scale*local+frames.target[group].offset))
    rows = []
    for mode, gadget in (("resolve", resolve), ("maxmargin", margin)):
        for schedule in ("simultaneous", "alternating"):
            target = _transform(gadget.tree, 4., .125)
            old, scratch = PCFRPlus(gadget.tree, schedule=schedule), PCFRPlus(target, schedule=schedule)
            old.run(5)
            scratch.run(5)
            before = deepcopy(old.policy())
            warm, mapping = transport_affine_solver(old, target)
            trace = []
            for _ in range(8):
                warm.step()
                scratch.step()
                error = _policy_error(warm, scratch)
                if error > 1e-9:
                    raise AssertionError("affine warm continuation differs from scratch target training")
                trace.append(dict(round=warm.rounds, policy_max_error=error))
            rows.append(dict(mode=mode, schedule=schedule, mapping=asdict(mapping), trace=trace,
                source_unchanged=old.rounds == 5 and old.policy() == before,
                final_warm_value=behavioral_value(warm.root, warm.policy()),
                final_scratch_value=behavioral_value(scratch.root, scratch.policy())))
    return dict(scope="finite identical-root coordinates and unchanged-structure affine solver copies only",
        python=platform.python_version(), base_commit_at_execution=git_revision(),
        source_hash_convention=NORMALIZATION, source_sha256=source_manifest(),
        frames=asdict(frames), frame_checks=frame_rows, warm_continuations=rows,
        live_agent_integration=False, gift_ledger_remains_audit_only=True,
        not_proven=["cross-turn changed sample/reach correspondence", "Resolve-to-Maxmargin exact state transfer",
                    "new infoset warm state", "outside-sample values", "playing strength"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(output=str(args.output), frame_checks=len(report["frame_checks"]),
        continuations=len(report["warm_continuations"]), max_policy_error=max(
            row["policy_max_error"] for item in report["warm_continuations"] for row in item["trace"]))))


if __name__ == "__main__":
    main()
