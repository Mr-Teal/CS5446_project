"""The five scorers Fog Lab offers, which of them can run on this machine and why not, and opening one.

All five are existing LeafEvaluators (fow_shared.interfaces): piece values, Stockfish at depth 1 and at
depth 11, Network 1 and the belief network.

available_scorers only looks. It asks whether torch can be found (importlib.util.find_spec, no import),
whether the engine is there and whether the checkpoint files are there, and starts and loads nothing,
so the page can ask whenever it likes. The two network modules import torch at their top, and only
open_scorer imports them, so the app starts on a machine with no torch (an Intel Mac) and shows the
networks greyed out with the reason, instead of failing to start.

A scorer that is held back by several things gives one reason, the first of: no torch, no Stockfish, no
checkpoint. The networks need all three; torch comes first because nothing the user does about the
others helps on a machine that cannot run it.

Stockfish-based scorers are opened with new_game_each_call=False, as inside a search: no ucinewgame
before each call, so the engine keeps its hash and answers faster (about 3.4x for quick Stockfish,
checkpoints/timing-new-game-each-call.json).
Only labelling needs every answer to ignore the earlier ones.
"""
import importlib.util
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..material import MaterialEvaluator
from ..stockfish import StockfishEvaluator

SCORER_IDS = ("material", "stockfish-d1", "stockfish-d11", "network1", "belief")
LABELS = {"material": "Piece values", "stockfish-d1": "Quick Stockfish",
          "stockfish-d11": "Careful Stockfish", "network1": "Network 1", "belief": "Belief network"}
CHECKPOINTS = {"network1": "net1-v2/best.pt", "belief": "belief-v1-d1/best.pt"}  # inside the checkpoints folder

_STOCKFISH_DEPTH = {"stockfish-d1": 1, "stockfish-d11": 11}
_NO_TORCH = "needs torch, which this machine does not have"


@dataclass(frozen=True)
class ScorerOptions:
    """Where the things the scorers need are on this machine."""

    checkpoints: Path  # the folder holding net1-v2/ and belief-v1-d1/ (pair_b/checkpoints)
    stockfish: str = "stockfish"  # a command on the PATH, or the path of the engine
    device: str | None = None  # for the networks; None lets pairb.network_evaluator.pick_device choose


@dataclass(frozen=True)
class ScorerInfo:
    """One row of the scorer list. `reason` says why a scorer is unavailable, and is None when it is available."""

    id: str
    label: str
    available: bool
    reason: str | None


def torch_available() -> bool:
    """Whether torch can be imported here, found without importing it (an import takes seconds, and fails
    on an Intel Mac). find_spec gives None when torch is absent or blocked, and raises ValueError when a
    module is registered under the name without a spec."""
    try:
        return importlib.util.find_spec("torch") is not None
    except ValueError:
        return False


def stockfish_available(path: str) -> bool:
    """Whether `path` names an engine: a command on the PATH, or a file at that path."""
    return shutil.which(path) is not None or Path(path).is_file()


def _why_unavailable(scorer_id: str, opts: ScorerOptions) -> str | None:
    """The reason this scorer cannot be opened here, or None when it can. Only looks."""
    is_network = scorer_id in CHECKPOINTS
    if is_network and not torch_available():
        return _NO_TORCH
    if scorer_id != "material" and not stockfish_available(opts.stockfish):
        return f"no Stockfish found at '{opts.stockfish}'"
    if is_network:
        checkpoint = opts.checkpoints / CHECKPOINTS[scorer_id]
        if not checkpoint.is_file():
            return f"checkpoint missing: {checkpoint}"
    return None


def available_scorers(opts: ScorerOptions) -> list[ScorerInfo]:
    """All five scorers in SCORER_IDS order, each with whether it can be opened here and, if not, why."""
    infos = []
    for scorer_id in SCORER_IDS:
        reason = _why_unavailable(scorer_id, opts)
        infos.append(ScorerInfo(scorer_id, LABELS[scorer_id], reason is None, reason))
    return infos


def default_scorer(infos: list[ScorerInfo]) -> str:
    """The scorer a new game starts with: the belief network if it can run, else quick Stockfish, else
    piece values, which always can."""
    usable = {info.id for info in infos if info.available}
    for scorer_id in ("belief", "stockfish-d1"):
        if scorer_id in usable:
            return scorer_id
    return "material"


def open_scorer(scorer_id: str, opts: ScorerOptions):
    """A new LeafEvaluator for this scorer, which is also a context manager. The caller closes it: it may
    own a Stockfish process. Each call opens its own, so one game can hold two (the bot's and the
    inspector's).

    ValueError, with the reason, when the id is unknown or the scorer is unavailable here. Whatever goes
    wrong after that (an engine that will not start, a checkpoint that will not load, a torch that will
    not import) is raised as it is.
    """
    if scorer_id not in SCORER_IDS:
        raise ValueError(f"unknown scorer {scorer_id!r}; the scorers are {', '.join(SCORER_IDS)}")
    reason = _why_unavailable(scorer_id, opts)
    if reason is not None:
        raise ValueError(f"{LABELS[scorer_id]} is not available: {reason}")
    if scorer_id == "material":
        return MaterialEvaluator()
    if scorer_id in _STOCKFISH_DEPTH:
        return StockfishEvaluator(_STOCKFISH_DEPTH[scorer_id], path=opts.stockfish, new_game_each_call=False)
    checkpoint = opts.checkpoints / CHECKPOINTS[scorer_id]
    settings = dict(stockfish_path=opts.stockfish, device=opts.device, new_game_each_call=False)
    # Imported here, not at the top of the file: these modules import torch, and listing must work without it.
    if scorer_id == "network1":
        from ..network_evaluator import NetworkEvaluator
        return NetworkEvaluator.from_checkpoint(checkpoint, **settings)
    from ..belief_evaluator import BeliefNetworkEvaluator
    return BeliefNetworkEvaluator.from_checkpoint(checkpoint, **settings)
