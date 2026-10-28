"""Review issue 3: independent tracker factories through the real match loop."""

import configparser
import json
from pathlib import Path

from pair_c import run_evaluation
from pair_c.tracker_factories import Factory as PairBTrackerFactory
from fow_shared.contracts import Belief, Decision, Hypothesis
from fow_shared.values import standard_fen
from pairb.rules import StandinRules
from pairb.tracker import ParticleTracker


CUSTOM_START = "7k/8/8/8/8/8/8/K7 b - - 0 1"


class PathTracker:
    """Bounded test tracker: enumerate observation-consistent paths without a referee."""

    def __init__(self, rules, initial_fen=None):
        self.rules = rules
        self.initial_fen = initial_fen

    def reset(self, player, seed):
        self.player = player
        self.paths = [(self.rules.initial_state(self.initial_fen), ())]
        self.last_ply = None

    def update(self, observation, own_move=None):
        assert observation.player == self.player
        if self.last_ply is None:
            assert observation.ply == 0 and own_move is None
        else:
            assert observation.ply == self.last_ply + 1
            candidates = []
            for state, path in self.paths:
                moves = self.rules.legal_moves(state)
                if own_move is not None:
                    moves = (own_move,) if own_move in moves else ()
                candidates.extend(
                    (self.rules.apply_move(state, move), path + (move,))
                    for move in moves
                )
            self.paths = candidates
        self.paths = [
            (state, path) for state, path in self.paths
            if self.rules.observe(state, self.player) == observation
        ]
        assert self.paths, "no candidate path fits this player's observation"
        self.last_ply = observation.ply
        hypotheses = tuple(
            Hypothesis(
                standard_fen(self.rules.board(state)), 1 / len(self.paths),
                history_id=" ".join(path), candidate_moves=path,
            )
            for state, path in self.paths
        )
        return Belief(self.player, observation.ply, hypotheses,
                      population_size=len(hypotheses), weighting="uniform")


class CheckingAgent:
    """Check the belief delivered to act, then choose a deterministic legal move."""

    def __init__(self, settings):
        self.name = settings["name"]
        self.expect_paths = settings["tracker_kind"] == "paths"
        self.start_fen = settings["test_start_fen"] or None

    def reset(self, player, seed):
        self.player = player

    def act(self, turn):
        assert turn.observation.player == self.player
        for hypothesis in turn.belief.hypotheses:
            if self.expect_paths:
                assert len(hypothesis.candidate_moves) == turn.observation.ply
                rules = StandinRules()
                state = rules.initial_state(self.start_fen)
                for ply, move in enumerate(hypothesis.candidate_moves):
                    # Each hypothesized history must match all earlier private
                    # observations and the player's known moves, not just its FEN.
                    event = turn.history[ply]
                    assert rules.observe(state, self.player) == event.observation
                    if event.own_move is not None:
                        assert move == event.own_move
                    state = rules.apply_move(state, move)
                assert standard_fen(rules.board(state)) == hypothesis.fen
                assert rules.observe(state, self.player) == turn.observation
            else:
                assert hypothesis.candidate_moves == ()
        moves = turn.observation.legal_moves
        return Decision(moves[0], {move: float(move == moves[0]) for move in moves})


class AgentFactory:
    def __init__(self, settings):
        self.settings = settings

    def load_model(self):
        return CheckingAgent(self.settings)

    def reset_game(self):
        pass


class TrackerFactory:
    instances = []

    def __init__(self, settings):
        self.settings = settings
        self.created = []
        self.starts = []
        TrackerFactory.instances.append(self)

    def make(self, rules, initial_fen, kind):
        if kind == "paths":
            return PathTracker(rules, initial_fen)
        return PairBTrackerFactory(self.settings).create_tracker(rules, initial_fen)

    def create_tracker(self, rules, initial_fen=None):
        self.starts.append(initial_fen)
        tracker = self.make(rules, initial_fen, self.settings["tracker_kind"])
        self.created.append(tracker)
        return tracker


def write_config(tmp_path):
    factory_names = ("TrackerFactory", "TrackerFactory")
    kinds = ("particle", "paths")
    initial_fen = CUSTOM_START
    parser = configparser.ConfigParser()
    parser.read(Path(run_evaluation.__file__).with_name("evaluate_config.ini"), encoding="utf-8")
    for side, factory_name, kind in zip(("a", "b"), factory_names, kinds):
        section = f"player_{side}"
        parser.set(section, "name", side.upper())
        parser.set(section, "factory", f"{__name__}:AgentFactory")
        parser.set(section, "tracker_factory", f"{__name__}:{factory_name}")
        parser.set(section, "tracker_kind", kind)
        parser.set(section, "test_start_fen", initial_fen or "")
        if kind == "paths":
            for option in ("tracker_particles", "tracker_hypotheses", "tracker_rebuild_tries"):
                parser.remove_option(section, option)
        else:
            # Keep the four-ply probe below the cap so sampling cannot discard
            # a history needed later; still use independent per-player values.
            parser.set(section, "tracker_particles", "1024" if side == "a" else "512")
            parser.set(section, "tracker_hypotheses", "3" if side == "a" else "2")
            parser.set(section, "tracker_rebuild_tries", "0")
    parser.set("match", "games", "2")
    parser.set("match", "max_plies", "4")
    parser.set("match", "alternating_colors", "true")
    parser.set("match", "rules", "standin")
    parser.set("match", "initial_fen", initial_fen or "")
    parser.set("output", "directory", str(tmp_path / "results"))
    source = tmp_path / "evaluate_config.ini"
    with source.open("w", encoding="utf-8") as stream:
        parser.write(stream)
    return source


def test_independent_tracker_outputs(tmp_path, monkeypatch):
    kinds = ("particle", "paths")
    initial_fen = CUSTOM_START
    monkeypatch.setattr(TrackerFactory, "instances", [])
    games = []
    real_play_game = run_evaluation.play_game

    def record_game(referee, agents, trackers, config):
        games.append(dict(trackers))
        return real_play_game(referee, agents, trackers, config)

    monkeypatch.setattr(run_evaluation, "play_game", record_game)
    source = write_config(tmp_path)
    config = run_evaluation.load_config(source)
    summary = run_evaluation.run(config, source)
    records = [json.loads(line) for line in
               (config["output_dir"] / "games.jsonl").read_text(encoding="utf-8").splitlines()]

    assert summary["games_completed"] == 2, summary["failed_games"]
    assert summary["games_failed"] == 0
    assert len(games) == len(records) == 2
    assert [record["player_a_color"] for record in records] == ["white", "black"]
    factories = TrackerFactory.instances
    assert len(factories) == 2 and factories[0] is not factories[1]
    assert len({id(tracker) for factory in factories for tracker in factory.created}) == 4
    for side, kind, factory in zip(("a", "b"), kinds, factories):
        assert factory.starts == [initial_fen, initial_fen]
        expected_type = PathTracker if kind == "paths" else ParticleTracker
        assert all(isinstance(tracker, expected_type) for tracker in factory.created)
        if kind == "particle":
            assert all(tracker.n_particles == (1024 if side == "a" else 512)
                       for tracker in factory.created)
        for index, record in enumerate(records):
            color = next(color for color, player in record["player_by_color"].items() if player == side)
            assert games[index][color] is factory.created[index]
            assert len(record["plies"]) == 4
            assert record[f"player_{side}_tracker_factory"] == config["players"][side]["tracker_factory"]
        assert summary[f"player_{side}_tracker_factory"] == config["players"][side]["tracker_factory"]
