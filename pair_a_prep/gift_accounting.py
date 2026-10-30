"""Immutable, pruned audit DAG for local CF gifts across saved chess roots.

Ancestor gifts are recorded, never added numerically across different raw-tree
counterfactual normalizations. Exact old-gadget payment lifting is separate.
"""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import fsum, isclose, isfinite


@dataclass(frozen=True)
class GiftContribution:
    infoset: str
    action: str
    retained_delta: float
    discarded_delta: float
    full_delta: float
    gift: float


@dataclass(frozen=True)
class GiftEvent:
    event_id: str
    source_unit: str
    group: str
    local_gift: float
    terms: tuple
    parents: tuple


@dataclass(frozen=True)
class GiftLedger:
    events: tuple
    roots: tuple

    def metrics(self):
        current = set(self.roots)
        return dict(gift_ledger_events=float(len(self.events)),
            gift_ledger_ancestor_events=float(sum(e.event_id not in current for e in self.events)),
            gift_ledger_prior_positive_events=float(sum(e.event_id not in current and e.local_gift > 0
                                                       for e in self.events)),
            gift_ledger_audit_only=1.)


def extend_ledger(previous, specifications):
    """Append auditable root events and keep only their reachable ancestors."""
    entries = {} if previous is None else {event.event_id: event for event in previous.events}
    roots = []
    for spec in specifications:
        source_unit, group, gift, terms, parents = spec
        parents = tuple(dict.fromkeys(parents))
        if any(parent not in entries for parent in parents):
            raise ValueError("unknown gift ancestor")
        terms = tuple(GiftContribution(**term) for term in terms)
        if not source_unit or not group or not isfinite(gift) or gift < 0:
            raise ValueError("gift events need units, groups and finite nonnegative gifts")
        for term in terms:
            if not all(isfinite(value) for value in (term.retained_delta, term.discarded_delta,
                                                     term.full_delta, term.gift)):
                raise ValueError("nonfinite gift contribution")
            if not isclose(term.retained_delta+term.discarded_delta, term.full_delta, abs_tol=1e-10, rel_tol=1e-10):
                raise ValueError("retained and discarded CF contributions do not sum")
            if not isclose(max(term.full_delta, 0.), term.gift, abs_tol=1e-10, rel_tol=1e-10):
                raise ValueError("take positive part after summing CF contributions")
        if not isclose(fsum(term.gift for term in terms), gift, abs_tol=1e-10, rel_tol=1e-10):
            raise ValueError("gift does not match its recorded contributions")
        payload = dict(source_unit=source_unit, group=group, local_gift=gift,
                       terms=[asdict(term) for term in terms], parents=parents)
        identity = sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
        entries[identity] = GiftEvent(identity, source_unit, group, gift, terms, parents)
        roots.append(identity)
    reachable, stack = set(), list(roots)
    while stack:
        identity = stack.pop()
        if identity not in reachable:
            reachable.add(identity)
            stack.extend(entries[identity].parents)
    return GiftLedger(tuple(entries[key] for key in sorted(reachable)), tuple(roots))


def ledger_for_projection(previous, projection):
    specs = []
    boundary = projection.boundaries
    saved_cut = None if boundary is None else boundary.audit.get("saved_cut")
    for index, (identity, group) in enumerate(zip(projection.root_ids, projection.groups)):
        record = None if saved_cut is None else saved_cut["groups"].get(group)
        gift = 0. if boundary is None else boundary.gifts[group]
        terms = [] if record is None else record["ancestor_gifts"]
        unit = saved_cut["source_unit_id"] if record is not None else "no-prior-cf:"+identity
        parent = projection.parent_events[index] if projection.parent_events else None
        specs.append((unit, group, gift, terms, () if parent is None else (parent,)))
    return extend_ledger(previous, specs)
