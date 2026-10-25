"""Run a configurable, color-balanced series of Fog-of-War chess games."""

from __future__ import annotations

import argparse
import configparser
import json
import statistics
import sys
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pair_b" / "src"))

from fow_shared.evaluation import MatchConfig, play_game
from pairb.rules import GameReferee, pick_rules
from pairb.tracker import ParticleTracker

from pair_c.agent_api import load_player, project_path


def load_config(path: Path) -> dict:
    """Read and validate the INI file; return values in the types the game runner needs."""
    parser = configparser.ConfigParser()
    if not parser.read(path, encoding="utf-8"):
        raise FileNotFoundError(f"Configuration file not found: {path}")

    players = {}
    for side in ("a", "b"):
        section = f"player_{side}"
        settings = {key: value.strip() for key, value in parser.items(section)}
        settings["name"] = parser.get(section, "name", fallback=f"Player {side.upper()}").strip()
        settings["factory"] = parser.get(section, "factory").strip()
        players[side] = settings

    config = {
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

    # Belief-tracker settings belong to each player, like checkpoint_path: every
    # agent may rely on its own belief granularity, so they cannot be global.
    for side in ("a", "b"):
        section = f"player_{side}"
        players[side]["leaf_depth"] = parser.getint(section, "leaf_depth")
        players[side]["tracker_particles"] = parser.getint(section, "tracker_particles")
        players[side]["tracker_hypotheses"] = parser.getint(section, "tracker_hypotheses")
        players[side]["tracker_rebuild_tries"] = parser.getint(section, "tracker_rebuild_tries")

    if config["games"] < 1:
        raise ValueError("games must be at least 1")
    if config["rules"] not in ("standin", "teal"):
        raise ValueError("rules must be explicitly set to 'standin' or 'teal'")
    if config["time_budget_ms"] < 1 or config["max_plies"] < 1:
        raise ValueError("time_budget_ms and max_plies must be positive")
    if config["seed"] < 0 or config["seed_mode"] not in ("fixed", "per_game"):
        raise ValueError("seed must be non-negative and seed_mode must be 'fixed' or 'per_game'")
    for side in ("a", "b"):
        settings = players[side]
        if settings["leaf_depth"] < 0:
            raise ValueError(f"player_{side}: leaf_depth cannot be negative")
        if (settings["tracker_particles"] < 1 or settings["tracker_hypotheses"] < 1
                or settings["tracker_rebuild_tries"] < 0):
            raise ValueError(
                f"player_{side}: tracker_particles and tracker_hypotheses must be "
                "positive; tracker_rebuild_tries cannot be negative"
            )
    return config


def seed_for_game(config: dict, game_index: int) -> int:
    """Return the configured fixed seed or a reproducible unique seed for this game."""
    if config["seed_mode"] == "fixed":
        return config["seed"]
    return config["seed"] + game_index


def summarize(records: list[dict], config: dict) -> dict:
    """Count outcomes from Player A's point of view; failed games are excluded from rates."""
    completed = [record for record in records if record["status"] == "completed"]
    wins = draws = losses = 0
    for record in completed:
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

    denominator = len(completed)
    score_rate = (wins + 0.5 * draws) / denominator if denominator else None
    return {
        "player_a": config["players"]["a"]["name"],
        "player_b": config["players"]["b"]["name"],
        "player_a_factory": config["players"]["a"]["factory"],
        "player_b_factory": config["players"]["b"]["factory"],
        "games_requested": config["games"],
        "games_completed": denominator,
        "games_failed": len(records) - denominator,
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
        "runner_forcibly_interrupts_agents": False,
        "current_one_ply_agent_uses_time_budget": False,
        "failed_games": [
            {"game": row["game"], "error": row["error"]}
            for row in records if row["status"] == "failed"
        ],
    }


def run(config: dict, source_config: Path) -> dict:
    """Run each game, save its record immediately, then save one aggregate summary."""
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
        player_a = load_player(config["players"]["a"]["factory"], config["players"]["a"], stack)
        player_b = load_player(config["players"]["b"]["factory"], config["players"]["b"], stack)
        print(
            f"Players: A={config['players']['a']['name']} | B={config['players']['b']['name']} | "
            f"colors={'alternating' if config['alternating_colors'] else 'A always White'}",
            flush=True,
        )
        config["output_dir"].mkdir(parents=True)
        (config["output_dir"] / "evaluate_config.ini").write_text(
            source_config.read_text(encoding="utf-8"), encoding="utf-8",
        )

        with (config["output_dir"] / "games.jsonl").open("w", encoding="utf-8") as log:
            for index in range(config["games"]):
                # Alternate the player identities' colors every game to balance White and Black.
                a_color = "white" if not config["alternating_colors"] or index % 2 == 0 else "black"
                b_color = "black" if a_color == "white" else "white"
                player_by_color = {a_color: "a", b_color: "b"}
                agents = {
                    a_color: player_a,
                    b_color: player_b,
                }
                # Each tracker is built from the settings of the player who
                # will hold that color in this game, so Player A and Player B
                # truly own independent belief-tracking configurations.
                trackers = {
                    color: ParticleTracker(
                        rules,
                        n_particles=config["players"][player_by_color[color]]["tracker_particles"],
                        n_hypotheses=config["players"][player_by_color[color]]["tracker_hypotheses"],
                        rebuild_tries=config["players"][player_by_color[color]]["tracker_rebuild_tries"],
                        initial_fen=config["initial_fen"],
                    )
                    for color in ("white", "black")
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
                    "player_a_color": a_color,
                    "player_by_color": player_by_color,
                    "status": "failed",
                }
                print(
                    f"Game {index + 1}/{config['games']} starting | "
                    f"A ({a_color}) vs B ({b_color}) | seed={game_seed}",
                    flush=True,
                )

                try:
                    match = MatchConfig(
                        time_budget_ms=config["time_budget_ms"],
                        max_plies=config["max_plies"],
                        seed=game_seed,
                        rules_id=rules.name,
                        engine_id=f"{config['players']['a']['name']}-vs-{config['players']['b']['name']}",
                        leaf_depth=max(
                            config["players"]["a"]["leaf_depth"],
                            config["players"]["b"]["leaf_depth"],
                        ),
                    )
                    result = play_game(referee, agents, trackers, match)
                    ended = referee.result()
                    base_record.update({
                        "status": "completed",
                        "winner": result.winner,
                        "termination": "ply_limit" if result.stopped_at_ply_limit else ended[1],
                        "stopped_at_ply_limit": result.stopped_at_ply_limit,
                        "plies": [asdict(ply) for ply in result.plies],
                    })
                    move_counts = {"a": 0, "b": 0}
                    for ply in result.plies:
                        move_counts[player_by_color[ply.player]] += 1
                    if result.winner == "draw":
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
    print(f"\nResults after {completed} completed games:")
    print(f"  Player A: {summary['player_a']}")
    print(f"    Wins: {summary['player_a_wins']}")
    print(f"    Draws: {summary['draws']}")
    print(f"    Losses: {summary['player_a_losses']}")
    print(f"    Win rate: {summary['player_a_win_rate']:.1%}" if completed else "    Win rate: unavailable")
    print(f"    Score rate: {summary['player_a_score_rate']:.1%}" if completed else "    Score rate: unavailable")
    print(f"  Player B: {summary['player_b']}")
    print(f"    Wins: {summary['player_a_losses']}")
    print(f"    Draws: {summary['draws']}")
    print(f"    Losses: {summary['player_a_wins']}")
    print(f"    Win rate: {summary['player_a_losses'] / completed:.1%}" if completed else "    Win rate: unavailable")
    print(f"    Score rate: {summary['player_b_score_rate']:.1%}" if completed else "    Score rate: unavailable")
    print(f"Results: {config['output_dir']}")


if __name__ == "__main__":
    main()
