"""scripts/eval_children.py: how close each scorer's per-move values are to careful Stockfish (Fog Lab).

The script draws parents from the training games of a D2-format dataset and scores every fog-legal child of
every parent in the two ways a search can ask: one call on the parent, and one call per board. These tests run
it on a few positions with small untrained networks and shallow Stockfish, or with stand-in evaluators, so they
check the plumbing and the arithmetic. The real numbers are in checkpoints/belief-v1-d1/eval-children-d16.json.
"""
import importlib.util
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

import chess
import pytest

torch = pytest.importorskip("torch")  # Intel Macs have no torch build: skip this file there

from fow_shared.values import fog_legal_moves
from pairb.belief_data import ENCODING as BELIEF_ENCODING
from pairb.belief_net import BeliefNetwork
from pairb.data import ENCODING as NET1_ENCODING, split_of
from pairb.net1 import Network1
from pairb.stockfish import StockfishEvaluator

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "eval_children.py"
needs_engine = pytest.mark.skipif(shutil.which("stockfish") is None, reason="needs Stockfish on PATH")
MAE_KEYS = {"belief_children", "belief_boards", "net1_children", "net1_boards", "sf_children", "sf_boards"}
DIFFERENCES = ("belief_children - net1_children", "belief_children - belief_boards", "net1_boards - net1_children")


def game_ids(split: str, n: int) -> list[str]:
    """The first n ids of the D2 naming (g-000000, g-000001, ...) that fall in `split`."""
    return [g for g in (f"g-{i:06d}" for i in range(100)) if split_of(g) == split][:n]


TRAIN_A, TRAIN_B = game_ids("train", 2)
PARENTS = [  # three parents of two training games
    (TRAIN_A, "r3k2r/8/8/8/8/8/4q3/R3K2R w KQkq - 0 1"),  # White is in check: fog rules allow 26 moves, chess 1
    (TRAIN_B, "r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N1PN2/PP3PPP/R2QKB1R w KQ - 2 9"),
    (TRAIN_B, "r2qkb1r/ppp2ppp/2n1bn2/3pp3/4P3/2NP1N2/PPP1BPPP/R1BQK2R b KQkq - 3 6"),
]


@pytest.fixture(scope="module")
def script():
    """scripts/ is not a package: load the file by its path."""
    spec = importlib.util.spec_from_file_location("eval_children", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_data(folder: Path, parents) -> Path:
    """A D2-style dataset folder: one part file with a record per (parent, move), so each parent repeats."""
    folder.mkdir()
    rows = [{"game_id": g, "parent_fen": fen, "move": move} for g, fen in parents for move in ("a2a3", "b2b3")]
    (folder / "part-0000.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return folder


def write_checkpoints(folder: Path) -> Path:
    """Fresh small networks, saved as the training scripts save them, in the folders the script reads them from."""
    nets = {"belief-v1-d1": (BeliefNetwork(blocks=1, channels=8, embed=16, use_d1=True), BELIEF_ENCODING),
            "net1-v2": (Network1(blocks=1, channels=8), NET1_ENCODING)}
    for run, (net, encoding) in nets.items():
        (folder / run).mkdir(parents=True)
        saved = {"state_dict": net.state_dict(), "config": net.config, "encoding": encoding}
        torch.save(saved, folder / run / "best.pt")
    return folder


def snapshot(folder: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}


class Stub:
    """An evaluator whose every value is a constant: `children` through evaluate_children, `boards` through
    evaluate_boards."""

    def __init__(self, children, boards):
        self.children, self.boards = children, boards

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def evaluate_children(self, fen):
        return {m.uci(): self.children for m in fog_legal_moves(chess.Board(fen))}

    def evaluate_boards(self, fens, player):
        return [self.boards] * len(fens)


# Catches: a fog-only move (such as castling out of check) missing from the children, a parent counted twice, or a
# result without the numbers the Tests tab reads.
@needs_engine
def test_measure_scores_every_fog_legal_child_of_the_chosen_parents(script, tmp_path):
    data = write_data(tmp_path / "d2-mini", PARENTS)
    checkpoints = write_checkpoints(tmp_path / "checkpoints")
    result = script.measure(data, checkpoints, n_parents=2, depth=2, seed=5, device="cpu")
    boards = [chess.Board(fen) for _, fen in script.pick_parents(data, 2, 5)]
    assert any(b.legal_moves.count() < len(fog_legal_moves(b)) for b in boards), \
        "the tiny dataset must give a parent with a fog-only move for this check to mean anything"
    assert result["parents"] == 2
    assert result["children"] == sum(len(fog_legal_moves(b)) for b in boards)
    assert set(result["mae"]) == MAE_KEYS and all(0 <= v <= 2 for v in result["mae"].values())
    for name in DIFFERENCES:
        difference = result[name]
        assert difference["games"] == 2 and difference["beliefs"] == result["children"] and len(difference["ci95"]) == 2
    assert (result["target_depth"], result["seed"], result["split"], result["data"]) == (2, 5, "train", "d2-mini")
    assert result["created"]


# Catches: values paired with the wrong evaluator or the wrong kind of call, a difference taken the wrong way round,
# a network read from the wrong checkpoint folder, the device or the depth not passed on, or the parents counted as
# asked for (here 100) rather than as scored (the 3 the data has).
def test_each_column_comes_from_its_own_evaluator_and_call(script, tmp_path, monkeypatch):
    loaded, depths = {}, []

    def loader(name, children, boards):
        def from_checkpoint(path, **kwargs):
            loaded[name] = (Path(path), kwargs.get("device"))
            return Stub(children, boards)
        return from_checkpoint

    def stockfish(depth):
        depths.append(depth)
        return Stub(0.5, 0.6) if depth == 1 else Stub(0.0, 0.0)  # careful Stockfish is the target: 0 everywhere

    monkeypatch.setattr(script.BeliefNetworkEvaluator, "from_checkpoint", loader("belief", 0.1, 0.2))
    monkeypatch.setattr(script.NetworkEvaluator, "from_checkpoint", loader("net1", 0.3, 0.4))
    monkeypatch.setattr(script, "StockfishEvaluator", stockfish)
    checkpoints = tmp_path / "checkpoints"
    result = script.measure(write_data(tmp_path / "d2-mini", PARENTS), checkpoints, n_parents=100, depth=7, seed=5,
                            device="cpu")
    assert result["parents"] == 3
    assert result["children"] == sum(len(fog_legal_moves(chess.Board(fen))) for _, fen in PARENTS)
    assert result["mae"] == pytest.approx({"belief_children": 0.1, "belief_boards": 0.2, "net1_children": 0.3,
                                           "net1_boards": 0.4, "sf_children": 0.5, "sf_boards": 0.6})
    assert result["belief_children - net1_children"]["mean"] == pytest.approx(-0.2)
    assert result["belief_children - belief_boards"]["mean"] == pytest.approx(-0.1)
    assert result["net1_boards - net1_children"]["mean"] == pytest.approx(0.1)
    assert loaded == {"belief": (checkpoints / "belief-v1-d1" / "best.pt", "cpu"),
                      "net1": (checkpoints / "net1-v2" / "best.pt", "cpu")}
    assert sorted(depths) == [1, 7] and result["target_depth"] == 7


# Catches: validation or test games among the parents (the test games stay untouched until the final report), a
# parent counted once per child move, or fewer parents than the data has when more are asked for.
def test_parents_come_from_training_games_only(script, tmp_path):
    val, test = game_ids("val", 1)[0], game_ids("test", 1)[0]
    others = [(val, chess.STARTING_FEN), (test, "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")]
    data = write_data(tmp_path / "d2-mini", [*PARENTS, *others])
    assert sorted(script.pick_parents(data, 100, seed=5)) == sorted(PARENTS)


# Catches: a different choice of parents from the 18 Oct measurement (sorted, de-duplicated, then shuffled by the
# seed), which would make its result impossible to reproduce.
def test_parents_are_chosen_as_in_the_18_oct_measurement(script, tmp_path):
    data = write_data(tmp_path / "d2-mini", PARENTS)
    pool = sorted(set(PARENTS))
    random.Random(7).shuffle(pool)
    assert pool != sorted(PARENTS), "the seed must reorder the parents for this check to mean anything"
    assert script.pick_parents(data, 2, seed=7) == pool[:2]


# Catches: a mistyped data folder ending in an obscure numpy error instead of saying what is wrong.
def test_a_folder_without_training_parents_is_named(script, tmp_path):
    with pytest.raises(ValueError, match="no-such"):
        script.measure(tmp_path / "no-such", tmp_path, n_parents=1, depth=1, seed=5, device="cpu")


# Catches: Stockfish processes left running when the measurement stops half-way (here a parent that cannot be read,
# after all the engines have started).
@needs_engine
def test_every_engine_is_quit_when_the_run_stops_half_way(script, tmp_path, monkeypatch):
    started = []
    init = StockfishEvaluator.__init__

    def recording_init(self, *args, **kwargs):
        init(self, *args, **kwargs)
        started.append(self)

    monkeypatch.setattr(StockfishEvaluator, "__init__", recording_init)
    data = write_data(tmp_path / "d2-bad", [(TRAIN_A, "this is not a position")])
    with pytest.raises(ValueError):
        script.measure(data, write_checkpoints(tmp_path / "checkpoints"), n_parents=1, depth=2, seed=5, device="cpu")
    assert len(started) == 4  # quick and careful Stockfish, and one inside each network's evaluator
    assert all(ev.engine.protocol.returncode.done() for ev in started)


# Catches: anything but the result file left behind (the 18 Oct scratch version wrote children_rows.json into the
# working folder), an input file changed, or the defaults (seed 5, device cpu) not what the plan says.
@needs_engine
def test_the_command_writes_its_result_file_and_nothing_else(tmp_path):
    data = write_data(tmp_path / "d2-mini", PARENTS)
    checkpoints = write_checkpoints(tmp_path / "checkpoints")
    work, out = tmp_path / "work", tmp_path / "results" / "children.json"
    work.mkdir()
    out.parent.mkdir()
    before = snapshot(tmp_path)
    run = subprocess.run([sys.executable, str(SCRIPT), "--data", str(data), "--checkpoints", str(checkpoints),
                          "--parents", "2", "--depth", "2", "--out", str(out)],
                         cwd=work, capture_output=True, encoding="utf-8", timeout=300)
    assert run.returncode == 0, run.stderr
    after = snapshot(tmp_path)
    written = after.pop(out)
    assert after == before, "the command changed something other than --out"
    report = json.loads(written.decode("utf-8"))
    assert (report["parents"], report["target_depth"], report["seed"]) == (2, 2, 5)
    assert json.loads(run.stdout) == report


# Catches: minutes of measuring thrown away because the output folder was mistyped.
def test_a_missing_output_folder_is_refused_before_any_work(tmp_path):
    run = subprocess.run([sys.executable, str(SCRIPT), "--data", str(tmp_path / "no-data"),
                          "--out", str(tmp_path / "no-folder" / "children.json")],
                         capture_output=True, encoding="utf-8", timeout=300)
    assert run.returncode != 0 and "no-folder" in run.stderr
