"""Generate the Obscuro-mechanism arms from the full-effort (clock-s16) templates.

Each chunk file is read from clock-s16-c{n}.ini and copied verbatim except for
the keys named below, so every arm keeps the same seeds, colours, opponent,
5 s clock, 200-ply cap and full-effort search budgets. Diffing an output
against its template must show only the intended keys.

  fe-s16        no key changes except name/directory. Runs on the mechanisms
                branch, so it is the same-code control for the arms below AND
                the test of whether the blended gadget, the anytime fallback and
                position-distinct fresh roots moved the full-effort result.
  fe-s256       sample_size 256. Fig. 9 l.9-10: top the infoset up to
                min{|P|, 256}. The tracker returns min(|P|, 256) histories, so
                |I| = retained_I1 + min(|P|, 256); max_nodes is raised because
                256 depth-1 roots alone need about 8k nodes.
  guard-fe-s16  tail-guarded tracker. max_states 175000 is sized for the 8000m
                container the way 300000 was for 15 GiB: reserve about 5.5 GiB
                for the belief at 1,444 B/state and a measured one-update growth
                factor of up to 23.1x (verification log item 20).
  sf14-fe-s16   Stockfish 14.1, depth 1, MultiPV (Obscuro C.5), pinned by the
                executable's sha256. The paper's engine generation; apt 14.1-1.
                The Pair C opponent keeps its Material scorer, so this arm is the
                paper's configuration, not an equal-evaluator comparison.
"""
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
SF_SHA = "79aa1e0c17294d94d07df98ebd0c0af04036a905837cfd2f98689d37e0c75013"
# The guard threshold is sized to the container, by the arithmetic in verification
# log item 20 (reserve ~2/3 of the cap for the belief, 1,444 B/state, growth up to
# 23.1x): 96000 for 4500m, 175000 for 8000m, 300000 for the 15 GiB Atlas cgroup.
GUARD_MAX_STATES = os.environ.get("GUARD_MAX_STATES", "175000")

ARMS = {
    "fe-s16": dict(
        name="Pair A subgame PCFR+ (exact belief, sample 16, full effort, mechanisms branch)",
        player_a={}, tracker=None),
    "fe-s64": dict(
        name="Pair A subgame PCFR+ (exact belief, sample 64 top-up, full effort)",
        player_a={"sample_size": "64"}, tracker=None),
    "fe-s256": dict(
        name="Pair A subgame PCFR+ (exact belief, sample 256 top-up, full effort)",
        player_a={"sample_size": "256", "max_nodes": "32768"}, tracker=None),
    "guard-fe-s16": dict(
        name=f"Pair A subgame PCFR+ (tail-guarded belief {GUARD_MAX_STATES} states, sample 16, full effort)",
        player_a={}, tracker=("guard_tracker:Factory", {"max_states": GUARD_MAX_STATES})),
    "sf14-fe-s16": dict(
        name="Pair A subgame PCFR+ (exact belief, sample 16, full effort, Stockfish 14.1 d1)",
        player_a={"leaf_evaluator": "stockfish", "leaf_depth": "1",
                  "stockfish_path": "/usr/games/stockfish", "stockfish_sha256": SF_SHA,
                  "stockfish_expected_name": "Stockfish 14.1", "stockfish_hash_mb": "16"},
        tracker=None),
}

KEY = re.compile(r"^(\w+)\s*=\s*(.*)$")


def rewrite(text, arm, spec, chunk):
    out, section, pending = [], None, dict(spec["player_a"])
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            # Keys the template lacked are appended at the end of [player_a].
            if section == "player_a":
                out.extend(f"{k} = {v}" for k, v in pending.items())
                pending = {}
            section = stripped[1:-1]
            out.append(line)
            continue
        match = KEY.match(stripped)
        if match and section == "player_a":
            key = match.group(1)
            if key == "name":
                line = f"name = {spec['name']}"
            elif key in pending:
                line = f"{key} = {pending.pop(key)}"
            elif key == "tracker_factory" and spec["tracker"]:
                factory, extra = spec["tracker"]
                out.append(f"tracker_factory = {factory}")
                out.extend(f"{k} = {v}" for k, v in extra.items())
                continue
        elif match and section == "output" and match.group(1) == "directory":
            line = f"directory = pair_c/runs/strength-{arm}-c{chunk}"
        elif stripped.startswith(";") and "Strength arm clock-s16" in stripped:
            line = line.replace("clock-s16", arm)
        out.append(line)
    if section == "player_a":
        out.extend(f"{k} = {v}" for k, v in pending.items())
    return "\n".join(out) + "\n"


def main():
    written = 0
    for chunk in range(1, 51):
        template = HERE / f"clock-s16-c{chunk}.ini"
        if not template.exists():
            sys.exit(f"missing template {template}")
        text = template.read_text(encoding="utf-8")
        for arm, spec in ARMS.items():
            (HERE / f"{arm}-c{chunk}.ini").write_text(rewrite(text, arm, spec, chunk), encoding="utf-8")
            written += 1
    print(f"wrote {written} configs: {len(ARMS)} arms x 50 chunks x 2 games")


if __name__ == "__main__":
    main()
