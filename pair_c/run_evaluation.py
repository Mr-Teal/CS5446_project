"""Run a configurable, color-balanced series of Fog-of-War chess games."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import platform
import statistics
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pair_b" / "src"))

from fow_shared.evaluation import MatchConfig, play_game
from pairb.rules import GameReferee, pick_rules

from pair_c.agent_api import load_player, project_path
from pair_c.tracker_api import load_tracker_factory
from pair_c.tracking import RecordingTracker
from pair_c.provenance import (
    checkpoint_provenance, cpu_model, discover_sources, git_provenance, load_hash_rules, player_device,
    sha256_text_bytes, source_file_hashes, stockfish_provenance,
)


def load_config(path: Path) -> dict:
    """Read and validate the INI file; return values in the types the game runner needs."""
    parser = configparser.ConfigParser()
    source_bytes = path.read_bytes()
    parser.read_string(source_bytes.decode("utf-8"), source=str(path))

    players = {}
    for side in ("a", "b"):
        section = f"player_{side}"
        settings = {key: value.strip() for key, value in parser.items(section)}
        settings["name"] = parser.get(section, "name", fallback=f"Player {side.upper()}").strip()
        settings["factory"] = parser.get(section, "factory").strip()
        settings["tracker_factory"] = parser.get(section, "tracker_factory").strip()
        players[side] = settings

    rules_path = project_path(parser.get("output", "hash_rules", fallback="pair_c/hash_rules.json").strip())
    hash_rules, hash_rules_bytes = load_hash_rules(rules_path)
    config = {
        "source_config_bytes": source_bytes,
        "hash_rules": hash_rules,
        "hash_rules_bytes": hash_rules_bytes,
        "hash_rules_path": rules_path,
        "players": players,
        "games": parser.getint("match", "games"),
        "alternating_colors": parser.getboolean("match", "alternating_colors"),
        "rules": parser.get("match", "rules").strip(),
        "time_budget_ms": parser.getint("match", "time_budget_ms"),
        "max_plies": parser.getint("match", "max_plies"),
        "initial_fen": parser.get("match", "initial_fen").strip() or None,
        "seed": parser.getint("match", "seed"),
        "seed_mode": parser.get("match", "seed_mode").strip().lower(),
        "output_dir": project_path(parser.get("output", "directory")),
    }

    if config["games"] < 1:
        raise ValueError("games must be at least 1")
    if config["rules"] not in ("standin", "teal"):
        raise ValueError("rules must be explicitly set to 'standin' or 'teal'")
    if config["time_budget_ms"] < 1 or config["max_plies"] < 1:
        raise ValueError("time_budget_ms and max_plies must be positive")
    if config["seed"] < 0 or config["seed_mode"] not in ("fixed", "per_game"):
        raise ValueError("seed must be non-negative and seed_mode must be 'fixed' or 'per_game'")
    for side in ("a", "b"):
        if parser.getint(f"player_{side}", "leaf_depth") < 0:
            raise ValueError(f"player_{side}: leaf_depth cannot be negative")
    # Preserve player options as strings for both factories. Each tracker factory
    # parses its own settings; other trackers need not define particle options.
    return config


def collect_provenance(config: dict, source_config: Path, started_at: str, players: dict) -> dict:
    """Describe this run; CUDA means the CUDA version used to build PyTorch."""
    try:
        import torch
    except ImportError:
        torch = None
        torch_version = cuda_version = None
    else:
        torch_version = str(torch.__version__)
        cuda_version = torch.version.cuda
    source_bytes = config.get("source_config_bytes")
    if source_bytes is None:
        source_bytes = source_config.read_bytes()
    checkpoint_paths = {}
    checkpoint_hashes = {}
    checkpoint_notes = {}
    for side, agent in players.items():
        checkpoint_paths[side], checkpoint_hashes[side], checkpoint_notes[side] = checkpoint_provenance(agent)
    stockfish = {}
    stockfish_hashes = {}
    for side, agent in players.items():
        stockfish[side], stockfish_hashes[side] = stockfish_provenance(agent)
    source_discovery, source_paths, reason = discover_sources(ROOT)
    if source_discovery == "filesystem":
        git_info = {"git_commit": None, "git_status": None,
                    "git_detection_notes": {"git_commit": reason, "git_status": reason}}
    else:
        git_info = git_provenance(ROOT)
        if git_info["git_status"] is None:
            raise RuntimeError(f"Cannot query Git status: {git_info['git_detection_notes']['git_status']}")
        if git_info["git_commit"] is None:
            try:
                subprocess.run(["git", "rev-parse", "--verify", "--quiet", "HEAD"],
                               cwd=ROOT, capture_output=True, check=True, timeout=30)
            except subprocess.CalledProcessError as error:
                if error.returncode != 1:
                    raise RuntimeError(f"Cannot query Git HEAD: {git_info['git_detection_notes']['git_commit']}") from error
            except (OSError, subprocess.SubprocessError) as error:
                raise RuntimeError(f"Cannot query Git HEAD: {error}") from error
            else:
                raise RuntimeError(f"Cannot query Git HEAD: {git_info['git_detection_notes']['git_commit']}")
    return {
        "started_at": started_at,
        **git_info,
        "source_discovery": source_discovery,
        "python_version": platform.python_version(),
        "torch_version": torch_version,
        "cuda_version": cuda_version,
        "cpu_model": cpu_model(),
        "player_devices": {side: player_device(agent, torch) for side, agent in players.items()},
        "config_path": str(source_config.resolve()),
        "hash_rules_path": str(config["hash_rules_path"].resolve()),
        "checkpoint_paths": checkpoint_paths,
        "checkpoint_detection_notes": checkpoint_notes,
        "stockfish": stockfish,
        "sha256": {
            "config": sha256_text_bytes(source_bytes),
            "config_raw": hashlib.sha256(source_bytes).hexdigest(),
            "player_a_checkpoint": checkpoint_hashes["a"],
            "player_b_checkpoint": checkpoint_hashes["b"],
            "player_a_stockfish": stockfish_hashes["a"],
            "player_b_stockfish": stockfish_hashes["b"],
            "source_files": source_file_hashes(ROOT, config["hash_rules"], source_paths),
        },
    }


def seed_for_game(config: dict, game_index: int) -> int:
    """Return the configured fixed seed or a reproducible unique seed for this game."""
    if config["seed_mode"] == "fixed":
        return config["seed"]
    return config["seed"] + game_index


def summarize(records: list[dict], config: dict) -> dict:
    """Count observed outcomes; failed and ply-capped attempts are not scored."""
    completed = [record for record in records if record["status"] == "completed"]
    scored = [record for record in completed if not record["stopped_at_ply_limit"]]
    wins = draws = losses = 0
    for record in scored:
        if record["winner"] == "draw":
            draws += 1
        elif record["winner"] == record["player_a_color"]:
            wins += 1
        else:
            losses += 1

    scores_by_model = {"a": [], "b": []}
    over_budget_by_model = {"a": 0, "b": 0}
    for record in completed:
        for ply in record["plies"]:
            side = record["player_by_color"][ply["player"]]
            scores_by_model[side].append(ply["elapsed_ms"])
            over_budget_by_model[side] += int(ply["over_budget"])

    def timing(values: list[float]) -> dict:
        return {
            "moves": len(values),
            "mean_ms_per_move": statistics.mean(values) if values else None,
            "max_ms_per_move": max(values) if values else None,
        }

    tracking = {"a": [], "b": []}
    tracking_failures = 0
    for record in records:
        for update in record.get("tracker_updates", []):
            tracking[record["player_by_color"][update["player"]]].append(update["elapsed_ms"])
            tracking_failures += int(update["outcome"] == "failed")

    denominator = len(scored)
    score_rate = (wins + 0.5 * draws) / denominator if denominator else None
    return {
        "player_a": config["players"]["a"]["name"],
        "player_b": config["players"]["b"]["name"],
        "player_a_factory": config["players"]["a"]["factory"],
        "player_b_factory": config["players"]["b"]["factory"],
        "player_a_tracker_factory": config["players"]["a"]["tracker_factory"],
        "player_b_tracker_factory": config["players"]["b"]["tracker_factory"],
        "games_requested": config["games"],
        "games_completed": len(completed),
        "games_scored": denominator,
        "games_capped": len(completed) - denominator,
        "games_failed": len(records) - len(completed),
        "ply_limit_policy": "exclude_from_outcome_rates",
        "player_a_wins": wins,
        "draws": draws,
        "player_a_losses": losses,
        "player_a_win_rate": wins / denominator if denominator else None,
        "player_a_score_rate": score_rate,
        "player_b_score_rate": 1.0 - score_rate if score_rate is not None else None,
        "color_assignment": "Player A is White in odd-numbered games and Black in even-numbered games"
        if config["alternating_colors"] else "Player A is White in every game",
        "timing": {
            "player_a": {**timing(scores_by_model["a"]), "over_budget_moves": over_budget_by_model["a"]},
            "player_b": {**timing(scores_by_model["b"]), "over_budget_moves": over_budget_by_model["b"]},
        },
        "tracking": {
            "scope": "tracker.update including all resumes; includes initial, terminal and failed attempts",
            "player_a": {"updates": len(tracking["a"]), "total_ms": sum(tracking["a"])},
            "player_b": {"updates": len(tracking["b"]), "total_ms": sum(tracking["b"])},
            "failed_updates": tracking_failures,
            "all_recorded_agent_and_tracker_ms": sum(sum(values) for values in scores_by_model.values())
                + sum(sum(values) for values in tracking.values()),
            "agent_timing_scope": "successful attempts only; failed attempts can omit partial agent records",
            "budget_scope": "agent over_budget flags exclude tracking; tracker budgets are independent and cooperative",
        },
        "runner_forcibly_interrupts_agents": False,
        "current_one_ply_agent_uses_time_budget": False,
        "failed_games": [
            {"game": row["game"], "error": row["error"]}
            for row in records if row["status"] == "failed"
        ],
    }


def run(config: dict, source_config: Path) -> dict:
    """Run each game, save its record immediately, then save one aggregate summary."""
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if config["output_dir"].exists():
        raise FileExistsError(f"Output directory already exists: {config['output_dir']}")

    rules = pick_rules(config["rules"])
    records = []
    print(
        f"Starting evaluation: {config['games']} games | rules={rules.name} | "
        f"time budget={config['time_budget_ms']} ms per move | max plies={config['max_plies']}",
        flush=True,
    )
    with ExitStack() as stack:
        # Each side invokes its factory separately and owns its own Agent and model resources.
        player_a, reset_a = load_player(config["players"]["a"]["factory"], config["players"]["a"], stack)
        player_b, reset_b = load_player(config["players"]["b"]["factory"], config["players"]["b"], stack)
        provenance = collect_provenance(
            config, source_config, started_at, {"a": player_a, "b": player_b},
        )
        tracker_factories = {
            side: load_tracker_factory(settings["tracker_factory"], settings)
            for side, settings in config["players"].items()
        }
        print(
            f"Players: A={config['players']['a']['name']} | B={config['players']['b']['name']} | "
            f"colors={'alternating' if config['alternating_colors'] else 'A always White'}",
            flush=True,
        )
        config["output_dir"].mkdir(parents=True)
        source_bytes = config.get("source_config_bytes")
        (config["output_dir"] / "evaluate_config.ini").write_bytes(
            source_bytes if source_bytes is not None else source_config.read_bytes(),
        )
        (config["output_dir"] / "hash_rules.json").write_bytes(config["hash_rules_bytes"])
        (config["output_dir"] / "provenance.json").write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )

        with (config["output_dir"] / "games.jsonl").open("w", encoding="utf-8") as log, \
                (config["output_dir"] / "tracker_updates.jsonl").open("w", encoding="utf-8") as tracking_log:
            for index in range(config["games"]):
                # Alternate the player identities' colors every game to balance White and Black.
                a_color = "white" if not config["alternating_colors"] or index % 2 == 0 else "black"
                b_color = "black" if a_color == "white" else "white"
                player_by_color = {a_color: "a", b_color: "b"}
                agents = {
                    a_color: player_a,
                    b_color: player_b,
                }
                referee = GameReferee(rules, initial_fen=config["initial_fen"])
                game_seed = seed_for_game(config, index)
                base_record = {
                    "game": index + 1,
                    "seed": game_seed,
                    "player_a": config["players"]["a"]["name"],
                    "player_b": config["players"]["b"]["name"],
                    "player_a_factory": config["players"]["a"]["factory"],
                    "player_b_factory": config["players"]["b"]["factory"],
                    "player_a_tracker_factory": config["players"]["a"]["tracker_factory"],
                    "player_b_tracker_factory": config["players"]["b"]["tracker_factory"],
                    "player_a_color": a_color,
                    "player_by_color": player_by_color,
                    "status": "failed",
                    "tracker_updates": [],
                }

                def record_tracking(row):
                    base_record["tracker_updates"].append(row)
                    tracking_log.write(json.dumps({"game": index + 1, **row}, ensure_ascii=False) + "\n")
                    tracking_log.flush()
                print(
                    f"Game {index + 1}/{config['games']} starting | "
                    f"A ({a_color}) vs B ({b_color}) | seed={game_seed}",
                    flush=True,
                )

                try:
                    # Factories follow player identities when colors alternate.
                    # Every game receives fresh trackers with the referee's rules
                    # and public start; play_game calls their reset methods.
                    trackers = {
                        color: RecordingTracker(
                            tracker_factories[player_by_color[color]].create_tracker(
                                rules, initial_fen=config["initial_fen"]), color, record_tracking)
                        for color in ("white", "black")
                    }
                    # Each factory owns its scorer's per-game state lifecycle.
                    reset_a()
                    reset_b()
                    match = MatchConfig(
                        time_budget_ms=config["time_budget_ms"],
                        max_plies=config["max_plies"],
                        seed=game_seed,
                        rules_id=rules.name,
                        engine_id=f"{config['players']['a']['name']}-vs-{config['players']['b']['name']}",
                        leaf_depth=max(
                            int(config["players"]["a"]["leaf_depth"]),
                            int(config["players"]["b"]["leaf_depth"]),
                        ),
                    )
                    result = play_game(referee, agents, trackers, match)
                    ended = referee.result()
                    base_record.update({
                        "status": "completed",
                        "winner": None if result.stopped_at_ply_limit else result.winner,
                        "termination": "ply_limit" if result.stopped_at_ply_limit else ended[1],
                        "stopped_at_ply_limit": result.stopped_at_ply_limit,
                        "plies": [asdict(ply) for ply in result.plies],
                    })
                    move_counts = {"a": 0, "b": 0}
                    for ply in result.plies:
                        move_counts[player_by_color[ply.player]] += 1
                    if result.stopped_at_ply_limit:
                        outcome = "ply limit reached (unscored)"
                    elif result.winner == "draw":
                        outcome = "draw"
                    else:
                        winner_side = player_by_color[result.winner]
                        outcome = f"{config['players'][winner_side]['name']} ({result.winner}) won"
                    end_reason = base_record["termination"]
                except Exception as error:
                    move_counts = {"a": 0, "b": 0}
                    base_record["error"] = f"{type(error).__name__}: {error}"
                    outcome = f"ERROR: {base_record['error']}"
                    end_reason = "aborted by error"

                records.append(base_record)
                log.write(json.dumps(base_record, ensure_ascii=False) + "\n")
                log.flush()
                print(
                    f"Game {index + 1}/{config['games']} finished | {outcome} | "
                    f"A ({a_color}): {move_counts['a']} moves | "
                    f"B ({b_color}): {move_counts['b']} moves | "
                    f"reason={end_reason} | seed={game_seed}",
                    flush=True,
                )

    summary = summarize(records, config)
    (config["output_dir"] / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return summary


def main() -> None:
    """Run the INI configuration named on the command line, or the default file in pair_c."""
    default_config = Path(__file__).with_name("evaluate_config.ini")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", type=Path, default=default_config,
                        help="INI file to use (defaults to evaluate_config.ini beside this script)")
    args = parser.parse_args()
    config_path = args.config.resolve()
    try:
        config = load_config(config_path)
        summary = run(config, config_path)
    except Exception as error:
        parser.exit(1, f"Evaluation failed: {type(error).__name__}: {error}\n")

    completed = summary["games_completed"]
    scored = summary["games_scored"]
    failed = summary["games_failed"]
    print(f"\nResults after {completed} successful game attempts:")
    print(f"  Terminal games scored: {scored}")
    print(f"  Ply-capped attempts (unscored): {summary['games_capped']}")
    print(f"  Failed games: {failed}")
    print(f"  Player A: {summary['player_a']}")
    print(f"    Wins: {summary['player_a_wins']}")
    print(f"    Draws: {summary['draws']}")
    print(f"    Losses: {summary['player_a_losses']}")
    print(f"    Win rate: {summary['player_a_win_rate']:.1%}" if scored else "    Win rate: unavailable")
    print(f"    Score rate: {summary['player_a_score_rate']:.1%}" if scored else "    Score rate: unavailable")
    print(f"  Player B: {summary['player_b']}")
    print(f"    Wins: {summary['player_a_losses']}")
    print(f"    Draws: {summary['draws']}")
    print(f"    Losses: {summary['player_a_wins']}")
    print(f"    Win rate: {summary['player_a_losses'] / scored:.1%}" if scored else "    Win rate: unavailable")
    print(f"    Score rate: {summary['player_b_score_rate']:.1%}" if scored else "    Score rate: unavailable")
    print(f"Results: {config['output_dir']}", flush=True)
    if failed:
        parser.exit(
            1,
            f"Evaluation finished with {failed} failed game(s). "
            f"Logs and summary saved to {config['output_dir']}.\n",
        )


if __name__ == "__main__":
    main()
