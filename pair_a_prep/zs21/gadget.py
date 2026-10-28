"""Algorithm 12: explicit additive B, reach gifts and both gadget modes."""

from dataclasses import dataclass, field
from collections import defaultdict
from math import isfinite

from ..toy_games import Node, terminal
from .sequence_form import SequenceForm, SolveError


class BoundaryError(RuntimeError):
    pass


def observed_sequence(memory):
    return (("observe", memory), "seen")


@dataclass
class Group:
    key: str
    roots: list
    probabilities: list
    offsets: list = field(default_factory=list)
    auxiliary: list = field(default_factory=list)
    audit: dict = field(default_factory=dict)


@dataclass
class Gadget:
    groups: list
    information: list = field(default_factory=list)
    mode: str = "MAXMARGIN"
    last_solve_warning: str = ""
    last_precision_attempts: list = field(default_factory=list)

    @property
    def roots(self):
        return [node for group in self.groups for node in group.roots]

    def form(self, deadline=None):
        if not self.groups:
            raise ValueError("empty gadget")
        root = Node(player=1, infoset=("gadget", "choose"))
        terms, auxiliary = [], []
        scale = 1. / len(self.groups) if self.mode == "RESOLVE" else 1.
        if self.mode == "RESOLVE":
            root.player = None
        for group in self.groups:
            chance = Node(children={str(i): n for i, n in enumerate(group.roots)},
                          probabilities={str(i): p for i, p in enumerate(group.probabilities)})
            child = chance
            if self.mode == "RESOLVE":
                child = Node(player=1, infoset=("gadget", "enter", group.key),
                             children={"EXIT": terminal(0.), "PLAY": chance})
                root.probabilities[group.key] = scale
            root.children[group.key] = child
            terms.extend((None, sequence, value * scale) for sequence, value in group.offsets)
            auxiliary.extend(group.auxiliary)
        terms.extend((ours, theirs, value * scale) for ours, theirs, value in self.information)
        return SequenceForm(root, terms, auxiliary, deadline)

    def solve(self, deadline=None, *, keep_first_on_conversion_failure=False):
        self.last_solve_warning = ""
        self.last_precision_attempts = []
        solution = self._solve_current(deadline)
        value = solution.value
        target = "RESOLVE" if value < -1e-15 else "MAXMARGIN"
        if target != self.mode:
            previous = self.mode
            self.mode = target
            try:
                solution = self._solve_current(deadline)
            except SolveError as exc:
                self.mode = previous
                if not keep_first_on_conversion_failure:
                    raise
                self.last_solve_warning = str(exc)
                exc.__traceback__ = exc.__context__ = exc.__cause__ = None
        return solution

    def _solve_current(self, deadline):
        form = self.form(deadline)
        try:
            return form.solve(deadline)
        finally:
            self.last_precision_attempts.extend(dict(mode=self.mode, **attempt)
                                                for attempt in getattr(form, "solve_attempts", ()))


def make_subgame(old, retained):
    """One knowledge step at the selected own information set.

    Auxiliary opponent flow rows retain decisions on discarded own branches.
    They carry Algorithm 12 lines 24-27 without adding these branches to A.
    """
    form = old.form
    values, best = form.counterfactual(old.x)
    groups = defaultdict(list)
    for node in retained:
        groups[node.observations[1]].append(node)
    cuts = {form.index[1][observed_sequence(memory)]: memory for memory in groups}
    owners = [None] * len(form.sequences[1])
    for index in range(1, len(owners)):
        owners[index] = cuts.get(index, owners[form.parents[1][index]])
    copied_nodes = set()
    stack = list(retained)
    while stack:
        node = stack.pop()
        copied_nodes.add(id(node))
        stack.extend(node.children.values())
    reaches, discarded, copied, auxiliaries = defaultdict(float), defaultdict(list), defaultdict(list), defaultdict(list)
    for identity, (sequences, probability, node) in form.nodes.items():
        if node.player == 1 and node.payoff is None:
            reaches[node.infoset] += probability * old.x[sequences[0]]
        owner = owners[sequences[1]]
        if owner is not None and node.payoff is not None and identity not in copied_nodes:
            discarded[owner].append((sequences, probability, node.payoff))
    old_b = form.B.getrow(0)
    for col, value in zip(old_b.indices, old_b.data):
        if owners[col] is not None:
            copied[owners[col]].append((form.sequences[1][col], value))
    for key, (parent, actions, _) in form.infosets[1].items():
        if owners[parent] is not None:
            auxiliaries[owners[parent]].append((1, key, form.sequences[1][parent], actions))
    result = []
    for memory, roots in sorted(groups.items()):
        cut_semantic = observed_sequence(memory)
        cut = form.index[1][cut_semantic]
        normalizer = sum(form.nodes[id(n)][1] * old.x[form.nodes[id(n)][0][0]] for n in roots)
        full_reach = form.reach(0, memory, old.x)
        if normalizer <= 0 or full_reach <= 0:
            raise BoundaryError("zero counterfactual reach in retained root")
        original_alternate = float(values[cut] / full_reach)
        # Put the entire margin on the retained-mass scale (Appendix C.2).
        # Scaling only A and discarded branches would change a zero old margin.
        retained_scale = full_reach / normalizer
        alternate = float(values[cut] / normalizer)
        gifts = []
        sequence = form.parent_sequence(1, cut)
        while sequence:
            key, action = form.sequences[1][sequence]
            parent, actions, _ = form.infosets[1][key]
            if len(actions) > 1:
                q = reaches[key]
                if q <= 0:
                    raise BoundaryError("zero reach at gift ancestor")
                gift = float((values[sequence] - best[key]) / q)
                if gift < 0 or not isfinite(gift):
                    raise BoundaryError("invalid nonnegative gift")
                gifts.append((str(key), action, gift))
            sequence = parent
        gift = sum(g[2] for g in gifts) * retained_scale
        offsets = [(cut_semantic, -alternate + gift)]
        copied_b, pruned = len(copied[memory]), len(discarded[memory])
        offsets.extend((semantic, float(value / normalizer)) for semantic, value in copied[memory])
        offsets.extend((form.sequences[1][sequences[1]],
                        float(old.x[sequences[0]] * probability * payoff / normalizer))
                       for sequences, probability, payoff in discarded[memory])
        auxiliary = auxiliaries[memory]
        result.append(Group(memory, list(roots),
                            [float(form.nodes[id(n)][1] * old.x[form.nodes[id(n)][0][0]] / normalizer)
                             for n in roots], offsets, auxiliary,
                            dict(alternate=alternate, gift=gift, ancestor_gifts=gifts,
                                 original_alternate=original_alternate, retained_scale=retained_scale,
                                 normalization=normalizer, full_reach=full_reach,
                                 copied_b=copied_b, pruned_terminals=pruned)))
    return Gadget(result)
