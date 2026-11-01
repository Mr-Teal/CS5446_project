"""Record tracker work independently of the shared loop's agent-only timer."""

from time import perf_counter


class RecordingTracker:
    def __init__(self, tracker, player, record):
        self.tracker, self.player, self.record = tracker, player, record

    def reset(self, player, seed):
        self.tracker.reset(player, seed)

    def update(self, observation, own_move=None):
        began = perf_counter()
        belief = None
        error = None
        previous_result = getattr(self.tracker, "last_update", None)
        try:
            belief = self.tracker.update(observation, own_move=own_move)
            return belief
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            elapsed = (perf_counter() - began) * 1000
            result = getattr(self.tracker, "last_update", None)
            if result is previous_result:
                # Atomic input/capacity errors can leave the prior ply's
                # diagnostics untouched; never label them as this update.
                result = None
            row = {
                "player": self.player, "ply": observation.ply, "elapsed_ms": elapsed,
                "outcome": "failed" if error else "returned", "error": error,
                "policy": getattr(self.tracker, "evaluation_policy", None),
                "policy_stop": getattr(self.tracker, "policy_stop", None),
                "calls": getattr(self.tracker, "update_calls", 1),
                "returned_hypotheses": len(belief.hypotheses) if belief is not None else 0,
                "population_size": belief.population_size if belief is not None else None,
                "weighting": belief.weighting if belief is not None else None,
            }
            for field in ("status", "stopped_by", "support_complete", "expansion_complete",
                          "retained_count", "state_count", "attempted_transitions", "accounted_bytes"):
                row[field] = getattr(result, field, None)
            self.record(row)
