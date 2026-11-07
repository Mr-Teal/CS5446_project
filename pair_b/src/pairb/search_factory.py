"""Pair B learned leaves in the same Pair A search used by engine baselines.

Only Network 1 is added here. Search settings, clocks and tracker factories
remain Pair A's. This uses evaluate_children, not whole-belief neural play.
Imports of torch remain lazy so material/Stockfish configurations work without it.
"""

from hashlib import sha256
from pathlib import Path

from pair_a_prep.evaluation_factories import SearchFactory, _load_leaf


ROOT = Path(__file__).resolve().parents[3]


def _checkpoint(settings):
    setting = settings.get("checkpoint_path", "").strip()
    if not setting:
        raise ValueError("network1 requires checkpoint_path")
    path = Path(setting).expanduser()
    path = (path if path.is_absolute() else ROOT / path).resolve()
    digest = sha256(path.read_bytes()).hexdigest()
    expected = settings.get("checkpoint_sha256", "").strip().lower()
    if expected and expected != digest:
        raise ValueError("checkpoint_sha256 does not match the checkpoint")
    return path, digest


class Factory(SearchFactory):
    """Pair C factory entry point for material, Stockfish or Network 1 search."""

    def load_leaf(self):
        kind = self.settings.get("leaf_evaluator", "material").strip().lower()
        if kind != "network1":
            return super().load_leaf()
        if int(self.settings.get("leaf_depth", "1")) != 1:
            raise ValueError("network1 requires leaf_depth=1; search depth is separate")
        path, digest = _checkpoint(self.settings)
        from .network_evaluator import NetworkEvaluator, pick_device

        class OwnedNetwork(NetworkEvaluator):
            def __init__(self, net, label, *, stockfish, device):
                self.device = pick_device(device)
                self.net = net.to(self.device).eval()
                self.stockfish = stockfish
                self.name = f"{label}+{stockfish.name}"

            def new_game(self):
                self.stockfish.new_game()

        # Use the baseline's exact engine validation, options, timeout and owned
        # cleanup. The network reuses this one process; it opens no second one.
        engine_settings = dict(self.settings, leaf_evaluator="stockfish", leaf_depth="1")
        engine_settings.setdefault("stockfish_new_game_each_call", "false")
        engine = _load_leaf(engine_settings)
        try:
            leaf = OwnedNetwork.from_checkpoint(path, stockfish=engine,
                device=self.settings.get("device", "").strip() or None)
            leaf.provenance_checkpoint_path = str(path)
            leaf.handoff_identity = dict(kind="network1", checkpoint_sha256=digest,
                device=str(leaf.device), evaluation="boardwise_evaluate_children",
                stockfish=engine.handoff_identity)
            return leaf
        except Exception:
            engine.close()
            raise
