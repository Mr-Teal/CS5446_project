"""Capture private inputs from the known seed-18 failure, outside inference."""
import configparser
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from pair_c import run_evaluation

OUT = Path(__file__).resolve().parent
Original = run_evaluation.GameReferee


def append(row):
    with (OUT / "private-stream.jsonl").open("a") as stream:
        stream.write(json.dumps(row) + "\n")


class CaptureReferee(Original):
    def reset(self, seed):
        super().reset(seed)
        self.capture_seed = seed
        if seed:
            for index, player in enumerate(("white", "black")):
                append({"seed": seed, "tracker_seed": seed + index, "player": player,
                        "observation": asdict(self.observe(player)), "own_move": None})

    def apply(self, move):
        mover = self.current_player()
        super().apply(move)
        for index, player in enumerate(("white", "black")):
            append({"seed": self.capture_seed, "tracker_seed": self.capture_seed + index,
                    "player": player, "observation": asdict(self.observe(player)),
                    "own_move": move if player == mover else None})


if __name__ == "__main__":
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--config", type=Path, default=Path(run_evaluation.__file__).resolve().parents[1] /
                      "pair_c/configs/budgeted_exact_pilot.ini")
    args.add_argument("--stockfish-path")
    args.add_argument("--output", type=Path, default=OUT)
    args = args.parse_args()
    OUT = args.output.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    assert not (OUT / "private-stream.jsonl").exists()
    parser = configparser.ConfigParser()
    parser.read(args.config)
    if args.stockfish_path:
        for side in ("a", "b"):
            parser.set("player_" + side, "stockfish_path", str(Path(args.stockfish_path).resolve()))
    a, b = dict(parser["player_a"]), dict(parser["player_b"])
    # Recreate original game 2: fixed is White, sampled subgame is Black;
    # shared play_game resets White with seed 18 and Black with seed 19.
    parser["player_a"], parser["player_b"] = b, a
    parser.set("match", "games", "1")
    parser.set("match", "seed", "18")
    parser.set("output", "directory", str(OUT / "captured-run"))
    source = OUT / "capture.ini"
    with source.open("w") as stream: parser.write(stream)
    run_evaluation.GameReferee = CaptureReferee
    summary = run_evaluation.run(run_evaluation.load_config(source), source)
    print(json.dumps(summary))
