"""Run a real Pair C bounded engine smoke with separate Pair A diagnostics.

The production INI uses SearchFactory. This validation command adds a transparent
trace wrapper only, without changing solver settings or runner accounting.
"""

import argparse
import configparser
import json
from hashlib import sha256
from math import isfinite
from pathlib import Path
import platform

import chess
import numpy

from .evaluation_factories import SearchFactory
from .provenance import source_manifest, NORMALIZATION, git_revision, REPOSITORY
from .rule_readiness import effective_rule_metadata
from .rules_adapter import RulesAdapter


def _emit(path, event):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, allow_nan=False)+"\n")


class TraceAgent:
    def __init__(self, agent, path, identity):
        self.agent, self.path, self.identity = agent, path, identity
        self.game_index = 0

    def __getattr__(self, name):
        return getattr(self.agent, name)

    def reset(self, player, seed):
        self.game_index += 1
        self.agent.reset(player, seed)
        _emit(self.path, dict(event="reset", identity=self.identity, game=self.game_index, player=player, seed=seed))

    def act(self, turn):
        decision = self.agent.act(turn)
        _emit(self.path, dict(event="decision", identity=self.identity, game=self.game_index,
            player=turn.observation.player, ply=turn.observation.ply, move=decision.move,
            config_id=self.agent.config_id, diagnostics=decision.diagnostics))
        return decision

    def close(self):
        self.agent.close()
        try:
            alive = self.agent.evaluator.alive()
            error = None
        except Exception as exc:
            alive, error = None, type(exc).__name__+": "+str(exc)
        _emit(self.path, dict(event="closed", identity=self.identity, engine_alive_after_close=alive,
                              verification_error=error))


class TraceFactory(SearchFactory):
    """Smoke-only factory delegating all resource/solver ownership to SearchFactory."""
    def load_model(self):
        agent = super().load_model()
        path, identity = self.settings["handoff_trace_file"], self.settings["handoff_player_identity"]
        try:
            rules = RulesAdapter()
            state = rules.initial_state(self.settings.get("public_initial_fen", "").strip() or None)
            values = agent.evaluator.evaluate_children(state.fen)
            if set(values) != set(rules.legal_moves(state)) or any(not isfinite(v) or not -1 <= v <= 1 for v in values.values()):
                raise ValueError("engine leaf did not return every legal finite mover-view value")
            _emit(path, dict(event="loaded", identity=identity, config_id=agent.config_id,
                leaf=agent.evaluator.handoff_identity, executable_path=agent.evaluator.provenance_executable_path,
                public_start_probe_moves=len(values)))
        except Exception:
            agent.close()
            raise
        return TraceAgent(agent, path, identity)

    def reset_game(self):
        super().reset_game()
        _emit(self.settings["handoff_trace_file"], dict(event="factory_reset", identity=self.settings["handoff_player_identity"]))


def run(config_path, output, stockfish_path=None):
    from pair_c.run_evaluation import load_config, run as run_evaluation
    config_path, output = Path(config_path).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("choose a fresh handoff output directory")
    parser = configparser.ConfigParser()
    config_bytes = config_path.read_bytes()
    parser.read_string(config_bytes.decode("utf-8"), source=str(config_path))
    trace = output/"agent-events.jsonl"
    for side in ("a", "b"):
        section = "player_"+side
        if parser.get(section, "factory") != "pair_a_prep.evaluation_factories:SearchFactory":
            raise ValueError("handoff smoke expects the Pair A SearchFactory on both sides")
        if parser.get(section, "leaf_evaluator") != "stockfish":
            raise ValueError("handoff smoke requires explicit stockfish leaves")
        parser.set(section, "factory", "pair_a_prep.stockfish_handoff:TraceFactory")
        parser.set(section, "handoff_trace_file", str(trace))
        parser.set(section, "handoff_player_identity", side)
        if stockfish_path:
            parser.set(section, "stockfish_path", str(Path(stockfish_path).expanduser().resolve()))
    parser.set("output", "directory", str(output/"evaluation"))
    output.mkdir(parents=True)
    effective = output/"effective-config.ini"
    with effective.open("w", encoding="utf-8") as stream:
        parser.write(stream)
    config = load_config(effective)
    summary = run_evaluation(config, effective)
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    decisions = [row for row in events if row["event"] == "decision"]
    loaded = [row for row in events if row["event"] == "loaded"]
    closed = [row for row in events if row["event"] == "closed"]
    resets = [row for row in events if row["event"] == "factory_reset"]
    failures = summary["games_failed"]
    complete = (summary["games_completed"]+failures == config["games"] and
                summary["games_requested"] == config["games"])
    traced_moves = sum(summary["timing"][key]["moves"] for key in ("player_a", "player_b"))
    trace_complete = len(decisions) == traced_moves and len(resets) == 2*config["games"]
    pinned = configparser.ConfigParser()
    with effective.open(encoding="utf-8") as stream:
        pinned.read_file(stream)
    for row in loaded:
        section = "player_"+row["identity"]
        pinned.set(section, "factory", "pair_a_prep.evaluation_factories:SearchFactory")
        pinned.remove_option(section, "handoff_trace_file")
        pinned.remove_option(section, "handoff_player_identity")
        pinned.set(section, "stockfish_path", row["executable_path"])
        pinned.set(section, "stockfish_sha256", row["leaf"]["executable_sha256"])
        pinned.set(section, "stockfish_expected_name", row["leaf"]["engine_name"])
    pinned.set("output", "directory", str(output/"pinned-evaluation"))
    with (output/"pinned-config.ini").open("w", encoding="utf-8") as stream:
        pinned.write(stream)
    report = dict(scope="real engine/Pair C bounded handoff, not a formal strength batch",
        status="passed" if not failures and complete and trace_complete and len(loaded) == len(closed) == 2 and
            all(row["engine_alive_after_close"] is False for row in closed) else "failed",
        python=platform.python_version(), numpy=numpy.__version__, chess=chess.__version__,
        base_commit_at_execution=git_revision(), source_hash_convention=NORMALIZATION,
        source_sha256=source_manifest(tuple(path.relative_to(REPOSITORY).as_posix()
            for path in (REPOSITORY/"pair_c").glob("*.py"))+(
                "pair_a_prep/data/pair_c_stockfish_smoke.ini",
                "pair_a_prep/data/pair_c_stockfish_standard_smoke.ini")),
        rules_id="paper_fow_v1_proposed", **effective_rule_metadata(),
        completeness=dict(game_attempts=complete, decision_trace=trace_complete),
        pinned_config=str(output/"pinned-config.ini"), formal_long_game_ready=False,
        source_config=str(config_path), source_config_sha256=sha256(config_bytes).hexdigest(),
        effective_config=str(effective), effective_config_sha256=sha256(effective.read_bytes()).hexdigest(),
        loaded=loaded,
        engine_close_checks=closed, factory_reset_events=len(resets), summary=summary,
        diagnostics=dict(actions=len(decisions), fallbacks=sum(row["diagnostics"].get("fallback", 0) for row in decisions),
            over_budget=sum(row["diagnostics"].get("over_budget", 0) for row in decisions)),
        paper_difference="paper Stockfish 14; this run uses the declared actual binary/version",
        limits=["sampled prototype and heuristic cross-turn reuse", "audit-only ancestor gifts",
                "exact tracker can exceed its capacity in long games", "projected labels remain disabled",
                "trace wrapper adds overhead; this is not a latency benchmark"])
    (output/"handoff.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("data")/"pair_c_stockfish_smoke.ini")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stockfish-path", help="override both engine paths for this local smoke only")
    args = parser.parse_args()
    report = run(args.config, args.output, args.stockfish_path)
    print(json.dumps(dict(status=report["status"], games=report["summary"]["games_completed"],
        failures=report["summary"]["games_failed"], **report["diagnostics"])))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
