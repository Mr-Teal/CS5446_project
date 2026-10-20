"""Start Fog Lab: python -m pairb.lab [--port 8765] [--stockfish stockfish] [--device DEVICE]
[--rules auto|teal|standin] [--open]

It puts the repository's root on the import path before it chooses the rules, since Teal's adapter (pair_a_prep) lives
there, then serves on 127.0.0.1 until Ctrl+C. The Tests tab's runs merge the stages of pair_b/fog_lab_stages.json in
this checkout and are saved in pair_b/.fog_lab/runs; they use the same Stockfish and device as the games, and leave out
the networks where torch is not installed. A --stockfish path is made absolute at start-up (engine_path), since those
runs' checks work in another folder. On the way out it closes the live game and stops a test run that is going.
The line it prints says the port it listens on, which is not the one asked for when that was 0. With --open it then
opens that address in the default browser: the server already listens, so the page's first request waits for it.
"""
import argparse
import os
import re
import sys
import webbrowser
from pathlib import Path

from ..rules import pick_rules
from .paths import ensure_repo_on_path, lab_home
from .runs import RunManager
from .scorers import ScorerOptions, torch_available
from .server import LabApp, make_server


def _port(text: str) -> int:
    if not re.fullmatch(r"[0-9]{1,5}", text) or int(text) > 65535:
        raise argparse.ArgumentTypeError("the port must be a number from 0 to 65535")
    return int(text)


def engine_path(value: str) -> str:
    """The --stockfish value as the app hands it on. A path, one with a folder separator in it or naming a file that is
    there (Windows finds stockfish.exe in the folder it starts from), is made absolute against the folder the app
    starts in: the Tests tab's harness and history checks run in a stage's worktree, where a relative path points
    nowhere. A bare command name such as stockfish is kept as it is, for the PATH lookup."""
    try:
        names_a_file = Path(value).is_file()
    except (OSError, ValueError):  # a name the file system cannot hold
        names_a_file = False
    if names_a_file or any(separator in value for separator in (os.sep, os.altsep) if separator):
        return str(Path(value).absolute())
    return value


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
    parser.add_argument("--open", action="store_true", help="open the page in the default browser once Fog Lab "
                        "listens")
    args = parser.parse_args(argv)
    repo = ensure_repo_on_path()  # before the rules are chosen: Teal's adapter is imported from the repo root
    try:
        rules = pick_rules(args.rules)
    except ValueError as error:
        parser.error(str(error))
    stockfish = engine_path(args.stockfish)
    runs = RunManager(repo, lab_home(repo), repo / "pair_b" / "fog_lab_stages.json", torch=torch_available(),
                      stockfish=stockfish, device=args.device)
    app = LabApp(repo, ScorerOptions(repo / "pair_b" / "checkpoints", stockfish=stockfish, device=args.device),
                 rules, runs=runs)
    try:
        server = make_server(app, args.port)
    except OSError as error:
        print(f"Fog Lab: cannot listen on 127.0.0.1:{args.port}: {error}. Another Fog Lab may be running; "
              "choose another port with --port.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Fog Lab: {url}  (Ctrl+C to stop)", flush=True)
    if args.open:
        try:
            opened = webbrowser.open(url)
        except webbrowser.Error:
            opened = False
        if not opened:
            print("Fog Lab: no browser opened; open the address above yourself", file=sys.stderr, flush=True)
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
