"""Start Fog Lab: python -m pairb.lab [--port 8765] [--stockfish stockfish] [--device DEVICE]
[--rules auto|teal|standin]

It puts the repository's root on the import path before it chooses the rules, since Teal's adapter (pair_a_prep) lives
there, then serves on 127.0.0.1 until Ctrl+C. The Tests tab's runs merge the stages of pair_b/fog_lab_stages.json in
this checkout and are saved in pair_b/.fog_lab/runs; they use the same Stockfish and device as the games, and leave out
the networks where torch is not installed. On the way out it closes the live game and stops a test run that is going.
The line it prints says the port it listens on, which is not the one asked for when that was 0.
"""
import argparse
import re
import sys

from ..rules import pick_rules
from .paths import ensure_repo_on_path, lab_home
from .runs import RunManager
from .scorers import ScorerOptions, torch_available
from .server import LabApp, make_server


def _port(text: str) -> int:
    if not re.fullmatch(r"[0-9]{1,5}", text) or int(text) > 65535:
        raise argparse.ArgumentTypeError("the port must be a number from 0 to 65535")
    return int(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pairb.lab", description="Fog Lab: a local app for trying and "
                                     "testing the belief bot, in your browser. It listens on 127.0.0.1 only.")
    parser.add_argument("--port", type=_port, default=8765, help="the port to listen on; 0 takes any free one "
                        "(default: 8765)")
    parser.add_argument("--stockfish", default="stockfish", help="the Stockfish command on the PATH, or the path of "
                        "the engine, such as C:/tools/stockfish.exe (default: stockfish)")
    parser.add_argument("--device", default=None, help="the device for the networks, such as cpu, mps or cuda "
                        "(default: the best one torch finds)")
    parser.add_argument("--rules", choices=("auto", "teal", "standin"), default="auto", help="the rules to play by: "
                        "auto is Teal's adapter when this checkout has it, else Pair B's stand-in (default: auto)")
    args = parser.parse_args(argv)
    repo = ensure_repo_on_path()  # before the rules are chosen: Teal's adapter is imported from the repo root
    try:
        rules = pick_rules(args.rules)
    except ValueError as error:
        parser.error(str(error))
    runs = RunManager(repo, lab_home(repo), repo / "pair_b" / "fog_lab_stages.json", torch=torch_available(),
                      stockfish=args.stockfish, device=args.device)
    app = LabApp(repo, ScorerOptions(repo / "pair_b" / "checkpoints", stockfish=args.stockfish, device=args.device),
                 rules, runs=runs)
    try:
        server = make_server(app, args.port)
    except OSError as error:
        print(f"Fog Lab: cannot listen on 127.0.0.1:{args.port}: {error}. Another Fog Lab may be running; "
              "choose another port with --port.", file=sys.stderr)
        return 1
    print(f"Fog Lab: http://127.0.0.1:{server.server_address[1]}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if runs.status()["running"]:
            print("Fog Lab: stopping the test run that is going, then leaving", file=sys.stderr, flush=True)
        app.close()  # the live game, and the test run (it waits a little for the run to be saved)
    return 0


if __name__ == "__main__":
    sys.exit(main())
