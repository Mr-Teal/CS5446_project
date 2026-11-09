"""The scorer registry (Fog Lab): which of the five scorers can run on this machine, why the others
cannot, and opening one.

Listing only looks (can torch be found, is the engine there, are the checkpoint files there), so most
tests describe a pretend machine with empty files and a stand-in for the torch check, and need neither
Stockfish nor torch. The tests that open real scorers skip when either is missing, and close every
scorer they open.
"""
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import types
from importlib.machinery import ModuleSpec

import chess
import chess.engine
import pytest

from no_torch import PAIR_B, run_without_torch
from pairb.lab import scorers
from pairb.lab.scorers import (CHECKPOINTS, LABELS, SCORER_IDS, ScorerInfo, ScorerOptions, available_scorers,
                               default_scorer, open_scorer, stockfish_available, torch_available)

NEEDS_STOCKFISH = pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish on PATH")
NEEDS_TORCH = pytest.mark.skipif(not torch_available(), reason="needs torch (Intel Macs have none)")
REAL = ScorerOptions(checkpoints=PAIR_B / "checkpoints", device="cpu")  # the repo's own checkpoints, on the CPU
NETWORKS = ("network1", "belief")
NEED_AN_ENGINE = ("stockfish-d1", "stockfish-d11", "network1", "belief")
NEED_NOTHING_BUT_AN_ENGINE = ("material", "stockfish-d1", "stockfish-d11")  # no checkpoint, no torch
NO_TORCH = "needs torch, which this machine does not have"
NO_ENGINE = "no Stockfish found at 'no-such-engine'"


def machine(tmp_path, monkeypatch, *, has_torch=True, has_stockfish=True, has_checkpoints=True) -> ScorerOptions:
    """Options for a pretend machine. Listing only looks, so empty files stand in for the engine and the
    two checkpoints, and a stand-in answers "is torch here?": nothing real is needed."""
    monkeypatch.setattr(scorers, "torch_available", lambda: has_torch)
    folder = tmp_path / "checkpoints"
    folder.mkdir()
    if has_checkpoints:
        for relative in CHECKPOINTS.values():
            (folder / relative).parent.mkdir(parents=True, exist_ok=True)
            (folder / relative).write_bytes(b"")
    engine = tmp_path / "stockfish"
    if has_stockfish:
        engine.write_bytes(b"")
    return ScorerOptions(checkpoints=folder, stockfish=str(engine) if has_stockfish else "no-such-engine")


def listing(opts) -> dict[str, ScorerInfo]:
    return {info.id: info for info in available_scorers(opts)}


def assert_closed(evaluator):
    """The Stockfish process behind a StockfishEvaluator has quit: it no longer answers."""
    with pytest.raises(chess.engine.EngineTerminatedError):
        evaluator.engine.ping()


# ---- what the page and the API call things ----

# Catches: an id, a label or a checkpoint path changed on one side only. The page, the API and the saved
# games all name scorers by these ids, and the page shows these labels.
def test_ids_labels_and_checkpoints_are_the_agreed_ones():
    assert SCORER_IDS == ("material", "stockfish-d1", "stockfish-d11", "network1", "belief", "belief-v2")
    assert LABELS == {"material": "Piece values", "stockfish-d1": "Quick Stockfish",
                      "stockfish-d11": "Careful Stockfish", "network1": "Network 1", "belief": "Belief network",
                      "belief-v2": "Belief network v2 (solver labels, engine-free)"}
    assert CHECKPOINTS == {"network1": "net1-v2/best.pt", "belief": "belief-v1-d1/best.pt",
                           "belief-v2": "belief-solver-v2-sf8-g237/best.pt"}


def test_options_default_to_the_stockfish_on_the_path_and_the_best_device(tmp_path):
    opts = ScorerOptions(checkpoints=tmp_path)
    assert (opts.stockfish, opts.device) == ("stockfish", None)


def test_lists_all_five_in_order(tmp_path):
    infos = available_scorers(ScorerOptions(checkpoints=tmp_path, stockfish="no-such-engine"))
    assert [i.id for i in infos] == list(SCORER_IDS)
    assert [i.label for i in infos] == [LABELS[i] for i in SCORER_IDS]


def test_everything_is_available_when_everything_is_there(tmp_path, monkeypatch):
    infos = available_scorers(machine(tmp_path, monkeypatch))
    assert [(i.id, i.available, i.reason) for i in infos] == [(s, True, None) for s in SCORER_IDS]


# Catches: CHECKPOINTS naming a file that is not in the repository, which would grey the networks out for good.
def test_the_repos_own_checkpoints_are_where_the_registry_looks(tmp_path, monkeypatch):
    opts = dataclasses.replace(machine(tmp_path, monkeypatch), checkpoints=PAIR_B / "checkpoints")
    got = listing(opts)
    assert got["network1"].available and got["belief"].available, [got[s].reason for s in NETWORKS]
    assert got["belief-v2"].available, got["belief-v2"].reason


# ---- why a scorer is not available ----

# Catches: a scorer that needs the engine listed as available without one, so the page offers it and the
# game fails on the first move.
def test_missing_stockfish_reported(tmp_path, monkeypatch):
    got = listing(machine(tmp_path, monkeypatch, has_stockfish=False))
    assert got["material"].available  # piece values need no engine
    for scorer_id in NEED_AN_ENGINE:
        assert (got[scorer_id].available, got[scorer_id].reason) == (False, NO_ENGINE)


def test_missing_checkpoint_reported(tmp_path, monkeypatch):
    opts = machine(tmp_path, monkeypatch, has_checkpoints=False)
    got = listing(opts)
    for scorer_id in NETWORKS:
        want = f"checkpoint missing: {opts.checkpoints / CHECKPOINTS[scorer_id]}"
        assert (got[scorer_id].available, got[scorer_id].reason) == (False, want)
    assert all(got[s].available for s in NEED_NOTHING_BUT_AN_ENGINE)


# Catches: a folder with the checkpoint's name counting as the checkpoint, which would fail later inside torch.load.
def test_a_folder_is_not_a_checkpoint(tmp_path, monkeypatch):
    opts = machine(tmp_path, monkeypatch, has_checkpoints=False)
    (opts.checkpoints / CHECKPOINTS["belief"]).mkdir(parents=True)
    assert listing(opts)["belief"].reason.startswith("checkpoint missing")


def test_networks_need_torch(tmp_path, monkeypatch):
    got = listing(machine(tmp_path, monkeypatch, has_torch=False))
    for scorer_id in NETWORKS:
        assert (got[scorer_id].available, got[scorer_id].reason) == (False, NO_TORCH)
    assert all(got[s].available for s in NEED_NOTHING_BUT_AN_ENGINE)


# Catches: belief network v2, which reads no engine value, held back by a missing Stockfish, or offered on a
# machine without torch or without its checkpoint.
def test_belief_v2_needs_torch_and_its_checkpoint_but_no_engine(tmp_path, monkeypatch):
    def pretend(name, **missing) -> ScorerInfo:
        (tmp_path / name).mkdir()  # machine() makes one checkpoints folder per pretend machine
        return listing(machine(tmp_path / name, monkeypatch, **missing))["belief-v2"]

    assert pretend("no-engine", has_stockfish=False).available
    assert pretend("no-torch", has_torch=False).reason == NO_TORCH
    assert pretend("no-checkpoint", has_checkpoints=False).reason.startswith("checkpoint missing")


# Catches: the checkpoint blamed on a machine that can never run the network, which sends the user off to
# find a file that would not help. A network is held back by the first of these three, and the page shows one.
@pytest.mark.parametrize("missing, reason", [
    (dict(has_torch=False, has_stockfish=False, has_checkpoints=False), NO_TORCH),
    (dict(has_stockfish=False, has_checkpoints=False), NO_ENGINE),
    (dict(has_checkpoints=False), "checkpoint missing"),
], ids=["torch first", "then Stockfish", "then the checkpoint"])
def test_one_reason_is_given_when_several_apply(tmp_path, monkeypatch, missing, reason):
    got = listing(machine(tmp_path, monkeypatch, **missing))
    for scorer_id in NETWORKS:
        assert got[scorer_id].reason.startswith(reason)


# ---- the scorer a new game starts with ----

def info(scorer_id, available=True) -> ScorerInfo:
    return ScorerInfo(scorer_id, LABELS[scorer_id], available, None if available else "not here")


def test_default_prefers_belief_then_quick_stockfish():
    assert default_scorer([info(s) for s in SCORER_IDS]) == "belief"
    assert default_scorer([info(s, s != "belief") for s in SCORER_IDS]) == "stockfish-d1"
    # a fixed ladder, not "the best one that works": careful Stockfish and Network 1 never stand in
    assert default_scorer([info(s, s in ("material", "stockfish-d11", "network1")) for s in SCORER_IDS]) == "material"
    assert default_scorer([info(s, s == "material") for s in SCORER_IDS]) == "material"


@pytest.mark.parametrize("pretend, want", [
    (dict(), "belief"),
    (dict(has_checkpoints=False), "stockfish-d1"),
    (dict(has_torch=False), "stockfish-d1"),  # an Intel Mac with Stockfish
    (dict(has_torch=False, has_stockfish=False), "material"),
], ids=["everything", "no checkpoint", "no torch", "no torch, no Stockfish"])
def test_default_on_pretend_machines(tmp_path, monkeypatch, pretend, want):
    assert default_scorer(available_scorers(machine(tmp_path, monkeypatch, **pretend))) == want


# ---- the two checks that look instead of importing or starting ----

def stand_in(spec):
    module = types.ModuleType("torch")
    module.__spec__ = spec
    return module


# Catches: torch_available crashing on, or being fooled by, a torch that is not really there. find_spec gives
# None for a blocked torch (as run_without_torch makes it) and raises ValueError for a module with no spec.
@pytest.mark.parametrize("registered, want", [
    (None, False),
    (stand_in(None), False),
    (stand_in(ModuleSpec("torch", None)), True),
], ids=["blocked", "no spec", "found"])
def test_torch_available_looks_without_importing(monkeypatch, registered, want):
    monkeypatch.setitem(sys.modules, "torch", registered)
    assert torch_available() is want


def test_stockfish_available_for_a_file_at_that_path(tmp_path):
    engine = tmp_path / "engine"
    engine.write_bytes(b"")  # not executable: only its being there counts
    assert stockfish_available(str(engine)) is True


def test_stockfish_available_for_a_command_on_the_path(tmp_path, monkeypatch):
    name = "fog-lab-test-engine"
    command = tmp_path / (name + (".exe" if os.name == "nt" else ""))
    command.write_bytes(b"")
    command.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert stockfish_available(name) is True


def test_stockfish_not_available_when_there_is_nothing_there(tmp_path):
    assert stockfish_available("no-such-engine") is False
    assert stockfish_available(str(tmp_path / "no-such-engine")) is False
    assert stockfish_available(str(tmp_path)) is False  # a folder is not an engine


# ---- opening a scorer ----

def test_material_opens_without_engine(tmp_path):
    opts = ScorerOptions(checkpoints=tmp_path, stockfish="no-such-engine")
    with open_scorer("material", opts) as s:
        assert len(s.evaluate_children(chess.STARTING_FEN)) == 20


# Catches: a refused scorer being started anyway (a dead engine path would then raise something other than
# ValueError), and a refusal that does not say why, which is all the page can show.
@pytest.mark.parametrize("pretend, scorer_id", [
    (dict(has_torch=False), "network1"),
    (dict(has_torch=False), "belief"),
    (dict(has_stockfish=False), "stockfish-d1"),
    (dict(has_stockfish=False), "stockfish-d11"),
    (dict(has_stockfish=False), "network1"),
    (dict(has_checkpoints=False), "belief"),
], ids=["no torch, network1", "no torch, belief", "no Stockfish, stockfish-d1", "no Stockfish, stockfish-d11",
        "no Stockfish, network1", "no checkpoint, belief"])
def test_opening_an_unavailable_scorer_is_a_value_error_that_says_why(tmp_path, monkeypatch, pretend, scorer_id):
    opts = machine(tmp_path, monkeypatch, **pretend)
    reason = listing(opts)[scorer_id].reason
    with pytest.raises(ValueError) as refused:
        open_scorer(scorer_id, opts)
    assert reason in str(refused.value) and LABELS[scorer_id] in str(refused.value)


def test_opening_an_unknown_scorer_is_a_value_error(tmp_path):
    with pytest.raises(ValueError, match="unknown scorer 'gpt'"):
        open_scorer("gpt", ScorerOptions(checkpoints=tmp_path))


# Catches: an option that never reaches the evaluator it is meant for: the engine path, the device, or "no
# new game per call", which keeps Stockfish about 3x faster inside a search. The constructors are replaced by
# recorders with the real signatures, so this needs neither the engine nor torch.
def test_options_reach_every_evaluator(tmp_path, monkeypatch):
    opts = dataclasses.replace(machine(tmp_path, monkeypatch), device="cuda")

    class Stockfish:
        def __init__(self, depth, path="stockfish", hash_mb=16, new_game_each_call=True):
            self.settings = dict(depth=depth, path=path, new_game_each_call=new_game_each_call)

    class Network:
        def __init__(self, path, stockfish_path, device, new_game_each_call):
            self.settings = dict(path=path, stockfish_path=stockfish_path, device=device,
                                 new_game_each_call=new_game_each_call)

        @classmethod
        def from_checkpoint(cls, path, stockfish_path="stockfish", device=None, new_game_each_call=True):
            return cls(path, stockfish_path, device, new_game_each_call)

    monkeypatch.setattr(scorers, "StockfishEvaluator", Stockfish)
    for module, name in (("network_evaluator", "NetworkEvaluator"), ("belief_evaluator", "BeliefNetworkEvaluator")):
        replacement = types.ModuleType(f"pairb.{module}")
        setattr(replacement, name, Network)
        monkeypatch.setitem(sys.modules, f"pairb.{module}", replacement)  # what open_scorer imports

    for scorer_id, depth in (("stockfish-d1", 1), ("stockfish-d11", 11)):
        assert open_scorer(scorer_id, opts).settings == dict(depth=depth, path=opts.stockfish, new_game_each_call=False)
    for scorer_id in NETWORKS:
        assert open_scorer(scorer_id, opts).settings == dict(
            path=opts.checkpoints / CHECKPOINTS[scorer_id], stockfish_path=opts.stockfish, device="cuda",
            new_game_each_call=False)


@NEEDS_STOCKFISH
@pytest.mark.parametrize("scorer_id, depth", [("stockfish-d1", 1), ("stockfish-d11", 11)])
def test_stockfish_scorers_open_at_their_depth_and_close(scorer_id, depth):
    with open_scorer(scorer_id, REAL) as s:
        assert (s.depth, s.new_game_each_call) == (depth, False)
        assert len(s.evaluate_children(chess.STARTING_FEN)) == 20
    assert_closed(s)


# Catches: one shared instance behind both calls. A game opens its scorer twice, once for the bot and once
# for the inspector, and closing one must leave the other working.
@NEEDS_STOCKFISH
def test_the_same_scorer_opens_twice_and_each_closes_on_its_own():
    with open_scorer("stockfish-d1", REAL) as inspector:
        bot = open_scorer("stockfish-d1", REAL)
        bot.close()
        assert_closed(bot)
        assert bot is not inspector
        assert len(inspector.evaluate_children(chess.STARTING_FEN)) == 20
    assert_closed(inspector)


@NEEDS_STOCKFISH
@NEEDS_TORCH
@pytest.mark.parametrize("scorer_id, run", [("network1", "net1-v2"), ("belief", "belief-v1-d1")])
def test_networks_open_from_their_checkpoint_and_close(scorer_id, run):
    with open_scorer(scorer_id, REAL) as s:
        assert s.name.startswith(run + "+")  # labelled with its checkpoint's folder
        assert s.device == "cpu"
        assert (s.stockfish.depth, s.stockfish.new_game_each_call) == (1, False)
        values = s.evaluate_children(chess.STARTING_FEN)
        assert len(values) == 20 and all(-1 <= v <= 1 for v in values.values())
    assert_closed(s.stockfish)


# ---- no torch ----

# Catches: a torch import on the way to the list, which would stop the app starting on an Intel Mac.
def test_no_torch_import_on_listing():
    r = run_without_torch("import pairb.lab.scorers as s, pathlib; "
        "print([i.available for i in s.available_scorers(s.ScorerOptions(pathlib.Path('checkpoints')))])", PAIR_B)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().endswith("False, False]")


# Catches: a torch import that only fails quietly where torch is missing (a try/except around it passes the
# test above), but still costs seconds, and memory, on a machine that has torch.
def test_listing_does_not_import_torch_even_where_it_is_installed():
    code = ("import sys, pathlib, pairb.lab.scorers as s; "
            "s.available_scorers(s.ScorerOptions(pathlib.Path('checkpoints'))); "
            "print('torch' in sys.modules)")
    r = subprocess.run([sys.executable, "-c", code], cwd=PAIR_B, capture_output=True, encoding="utf-8",
                       errors="replace", timeout=300)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "False"


def test_without_torch_piece_values_open_and_the_networks_are_refused_not_crashed():
    code = """
import json, pathlib, chess
from pairb.lab.scorers import ScorerOptions, open_scorer
opts = ScorerOptions(pathlib.Path('checkpoints'))
with open_scorer('material', opts) as s:
    moves = len(s.evaluate_children(chess.STARTING_FEN))
refused = {}
for scorer_id in ('network1', 'belief'):
    try:
        open_scorer(scorer_id, opts)
    except ValueError as error:
        refused[scorer_id] = str(error)
print(json.dumps({'moves': moves, 'refused': refused}))
"""
    r = run_without_torch(code, PAIR_B)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["moves"] == 20
    assert sorted(got["refused"]) == ["belief", "network1"]
    assert all(NO_TORCH in message for message in got["refused"].values())
