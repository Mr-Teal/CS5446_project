"""Play the configurations of one arm, several at a time, each in its own process.

    python scripts/run_arm.py ppo-vs-policy-fuzzy --repo /path/to/CS5446_project --jobs 6

Each configuration (configs/<name>/games-*.ini, written by make_configs.py) is one call of the team's
runner, `python -m pair_c.run_evaluation <ini>`, started in the team repository. This script sets
PYTHONPATH for it: the repository, pair_b/src, the guard tracker's folder and this package's player/.
A configuration whose output folder already has a summary is skipped. The runner refuses to write into
an existing folder, so a folder without a summary (a run that was cut off) stops this script: look at
it, then move it away by hand.
"""
import argparse
import configparser
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
THREADS = ("OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS")


def output_folder(config: Path, repo: Path) -> Path:
    parser = configparser.ConfigParser()
    parser.read(config, encoding="utf-8")
    folder = Path(parser.get("output", "directory").strip()).expanduser()
    return folder if folder.is_absolute() else repo / folder


def play(config: Path, out: Path, repo: Path, environment: dict) -> tuple[str, int, float]:
    started = time.time()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out.parent / f"{out.name}.log", "w", encoding="utf-8") as log:
        code = subprocess.run([sys.executable, "-m", "pair_c.run_evaluation", str(config)], cwd=repo,
                              env=environment, stdout=log, stderr=subprocess.STDOUT).returncode
    return config.stem, code, time.time() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("name", help="folder name under configs/")
    parser.add_argument("--repo", required=True, help="the team repository checkout (its root)")
    parser.add_argument("--jobs", type=int, default=6, help="processes at a time; a guard tracker can need several GB")
    args = parser.parse_args()
    repo = Path(args.repo).expanduser().resolve()
    if not (repo / "pair_c" / "run_evaluation.py").is_file():
        raise SystemExit(f"{repo} is not the team repository root (no pair_c/run_evaluation.py)")
    paths = [repo, repo / "pair_b" / "src", repo / "pair_a_prep" / "experiments" / "network_leaf_2026-11" / "strength",
             PACKAGE / "player"]
    python_path = os.pathsep.join([*map(str, paths), *filter(None, [os.environ.get("PYTHONPATH")])])
    environment = dict(os.environ, PYTHONPATH=python_path, PYTHONUNBUFFERED="1", **{name: "1" for name in THREADS})
    todo = []
    for config in sorted((PACKAGE / "configs" / args.name).glob("games-*.ini")):
        out = output_folder(config, repo)
        if (out / "summary.json").exists():
            print(f"{config.stem}: already played, skipped")
        elif out.exists():
            raise SystemExit(f"{out} exists without a summary: a run was cut off there")
        else:
            todo.append((config, out))
    print(f"{args.name}: {len(todo)} configuration(s) to play, {args.jobs} at a time", flush=True)
    with ThreadPoolExecutor(args.jobs) as pool:
        for stem, code, seconds in pool.map(lambda pair: play(*pair, repo, environment), todo):
            # Exit code 1 is the runner's signal for "some game failed"; the records are still written.
            print(f"{stem}: exit code {code}, {seconds:.0f} s", flush=True)


if __name__ == "__main__":
    main()
