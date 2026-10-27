"""Executable configuration; reject unsupported semantic changes explicitly."""

import hashlib
from pathlib import Path
import tomllib

from .rule_profile import RULES_ID, NO_MOVE_RULE, TERMINAL_PRECEDENCE


def default_path():
    packaged = Path(__file__).resolve().parents[2] / "zs21_runtime/configs/runtime.toml"
    if packaged.is_file():
        return packaged
    return Path(__file__).resolve().parents[4] / "configs/runtime.toml"


def load(path=None, variant="main"):
    path = Path(path or default_path()).resolve()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    fixed = {
        "rules": dict(profile=RULES_ID, no_move_rule=NO_MOVE_RULE,
                      terminal_precedence=list(TERMINAL_PRECEDENCE)),
        "agent": dict(particle_floor=200, information_denominator=10000000, mode_epsilon=1e-15,
                      submission_reserve_seconds=2., initial_solution_reserve_seconds=.5,
                      tracker_backend="native", main_scale=1., sixfold_scale=6.),
        "engine": dict(threads_per_worker=1, workers=4, depth=1, tau_pawns=6., mate_one_move=.9,
                       mate_decay=.78, hash_mb_per_worker=16),
        "lp": dict(method="highs-ds", threads=1, feasibility_tolerance=1e-8,
                   certificate_retry_tolerances=[1e-9, 1e-10], certificate_tolerance=1e-8),
        "experiment": dict(parallel_games=1, color_schedule="alternating_white_black"),
    }
    for section, entries in fixed.items():
        for key, expected in entries.items():
            if data.get(section, {}).get(key) != expected:
                raise ValueError(f"unsupported configuration: {section}.{key} must be {expected!r}")
    if variant not in ("main", "sixfold") or data["agent"]["support_tolerance"] not in (1e-7, 1e-9, 1e-11):
        raise ValueError("unknown value variant or support sensitivity value")
    project = path.parent.parent
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(), data=data,
                specification_sha256=hashlib.sha256((path.parent/data["specification"]).read_bytes()).hexdigest(),
                engine=str((project/data["engine"]["path"]).resolve()),
                agent_kwargs=dict(scale=data["agent"][variant+"_scale"],
                                  particle_floor=data["agent"]["particle_floor"],
                                  support_tolerance=data["agent"]["support_tolerance"],
                                  tracker_backend=data["agent"]["tracker_backend"]))
