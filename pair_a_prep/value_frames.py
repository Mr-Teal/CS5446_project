"""Explicit affine payoff frames for toy payment transport, not chess inference.

Callers must establish a common player-0 coordinate system. No source hash,
posterior, reach mass or gift ledger implies such a correspondence automatically.
"""

from dataclasses import dataclass
from math import fsum, isfinite
from numbers import Real


def _scalar(value):
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError("finite real payoff coordinate required")
    return float(value)


@dataclass(frozen=True)
class ValueFrame:
    """common payoff = scale * local payoff + offset, with positive scale."""
    unit: str
    scale: float = 1.
    offset: float = 0.

    def __post_init__(self):
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError("a declared common payoff unit is required")
        if _scalar(self.scale) <= 0:
            raise ValueError("payoff scale must be positive")
        _scalar(self.offset)


def _compatible(source, target):
    if source.unit != target.unit:
        raise ValueError("cannot infer a correspondence between different common units")


def transport_value(value, source, target):
    """Re-express a scalar without changing its declared common payoff."""
    _compatible(source, target)
    common = _scalar(source.scale * _scalar(value) + source.offset)
    return _scalar((common-target.offset)/target.scale)


def transport_delta(delta, source, target):
    """Offsets cancel for differences; positive scaling preserves their sign."""
    _compatible(source, target)
    return _scalar(_scalar(delta)*source.scale/target.scale)


def margin_in_source_units(target_value, target_alternate, source, target):
    """Compare target-frame margins in the original local units, not raw rows."""
    return transport_delta(_scalar(target_value)-_scalar(target_alternate), target, source)


@dataclass(frozen=True)
class ResolveTransport:
    entries: tuple
    scale: float
    offset: float

    @property
    def prior(self):
        return dict(self.entries)

    def source_expected_value(self, target_expected_value):
        return _scalar(self.scale*_scalar(target_expected_value)+self.offset)


def transport_resolve_prior(prior, source_frames, target_frames):
    """Keep a fixed-prior Resolve game strategically equivalent after conversion.

    For each group old_v = a_J * new_v + b_J. Set q_J = p_J*a_J/Z.
    Then old expectation = Z * new expectation + sum(p_J*b_J).
    Group shifts must be action independent, including on the exit branch.
    This does not transport a free Maxmargin opponent selector.
    """
    if not prior or set(prior) != set(source_frames) or set(prior) != set(target_frames):
        raise ValueError("prior and frames must cover exactly the same nonempty groups")
    weights = {key: _scalar(value) for key, value in prior.items()}
    if any(value < 0 for value in weights.values()) or abs(fsum(weights.values())-1) > 1e-12:
        raise ValueError("prior must be nonnegative and sum to one")
    masses, shifts = {}, []
    for group, probability in weights.items():
        old, new = source_frames[group], target_frames[group]
        _compatible(old, new)
        masses[group] = _scalar(probability*new.scale/old.scale)
        shifts.append(_scalar(probability*(new.offset-old.offset)/old.scale))
    scale = _scalar(fsum(masses.values()))
    if scale <= 0:
        raise ValueError("transported prior has no positive finite mass")
    return ResolveTransport(tuple((key, value/scale) for key, value in masses.items()),
                            scale, _scalar(fsum(shifts)))
