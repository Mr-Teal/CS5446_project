"""Export actual toy solver checkpoints to a standalone interactive HTML page."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gadgets import build_gadget, SubgameRoot
from .knowledge import knowledge_demo, restrict_cut
from .pcfr import PCFRPlus
from .toy_games import (Node, terminal, matching_pennies, hidden_coin, kuhn_poker,
                        payoff_matrix, solve_matrix)


def _tree(node, path="root"):
    return {"id": path, "player": node.player, "infoset": node.infoset,
            "payoff": node.payoff, "probabilities": node.probabilities,
            "children": {a: _tree(c, path + "/" + a) for a, c in node.children.items()}}


def make_report(rounds=200):
    if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 1:
        raise ValueError("rounds must be positive")
    scenarios = [("Matching pennies", matching_pennies(), None),
                 ("Hidden coin (75% heads)", hidden_coin(), None),
                 ("Kuhn poker", kuhn_poker(), None)]
    roots, blueprint = knowledge_demo()
    for mode in ("klss", "kluss"):
        cut = restrict_cut(roots, "current", blueprint, mode)
        gadget = cut.gadget({"J0": 2.0})
        meta = {"distances": cut.distances, "retained": cut.retained, "removed": cut.removed,
                "frozen": cut.frozen, "active_own": cut.active_own, "mode": mode,
                "observations": {r.root_id: [r.own_observation, r.opponent_observation] for r in roots}}
        scenarios.append((mode.upper() + " + Resolve", gadget.tree, meta))
    margin = build_gadget([
        SubgameRoot("A", "J0", Node(player=0, infoset="decision", children={
            "L": terminal(1), "R": terminal(-1)}), 1),
        SubgameRoot("B", "J1", Node(player=0, infoset="decision", children={
            "L": terminal(-1), "R": terminal(1)}), 1)], {"J0": 0, "J1": .4}, mode="maxmargin")
    scenarios.append(("Maxmargin gadget", margin.tree, None))
    report = {"scope": "Full-tree debugging view, never agent input", "scenarios": []}
    checkpoints = sorted(set(range(min(30, rounds) + 1)) |
                         set(range(40, rounds + 1, max(10, rounds // 30))) | {rounds})
    for name, root, knowledge in scenarios:
        oracle = solve_matrix(payoff_matrix(root)[0])
        solver = PCFRPlus(root, schedule="alternating")
        frames = []
        for checkpoint in checkpoints:
            solver.run(checkpoint - solver.rounds)
            frames.append({"round": checkpoint, "metrics": solver.metrics(),
                           "last": solver.policy(), "average": solver.policy(True),
                           "regrets": [{k: m.regrets.tolist() for k, m in player.items()}
                                       for player in solver.minimizers]})
        report["scenarios"].append({"name": name, "tree": _tree(root), "knowledge": knowledge,
                                    "oracle": oracle["profile_value"], "frames": frames})
    return report


def export(output: Path, rounds=200):
    report = make_report(rounds)
    template = Path(__file__).with_name("toy_visualizer.html").read_text(encoding="utf-8")
    payload = json.dumps(report, allow_nan=False).replace("<", "\\u003c")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        page = template.replace('<script id="report" type="application/json">__REPORT_DATA__</script>',
                                '<script id="report" type="application/json">' + payload + '</script>')
        # The exporter supports arbitrary output folders, so do not retain the
        # source template's relative link to results/ inside a generated page.
        page = page.replace('href="results/toy_explorer.html"', 'href="#"')
        page = page.replace('This source template has no run data.',
                            'If this message remains visible, JavaScript did not finish loading.')
        stream.write(page)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=200)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("rounds must be positive")
    report = export(args.output, args.rounds)
    print("Wrote", args.output.resolve())
    for scenario in report["scenarios"]:
        print(scenario["name"], scenario["frames"][-1]["metrics"]["average"])


if __name__ == "__main__":
    main()
