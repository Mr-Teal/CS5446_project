"""How long the belief evaluator takes per belief, scored in one call and one at a time.

    .venv/bin/python experiments/readme_checks/time_belief_evaluator.py <d6-check> checkpoints/belief-v1-d1/timing-beliefs.json

The first --beliefs beliefs of the check set's train split (record order), scored by
BeliefNetworkEvaluator.from_checkpoint(checkpoints/belief-v1-d1/best.pt) on --device with
new_game_each_call=False, as inside a search: all of them in one evaluate_beliefs call (--repeats
times, the median kept), then each on its own. Also times building the planes alone
(encode_belief, the step the network reads), for the share of the one-call time it takes. One
warm-up call first, not timed. Refuses to overwrite.
"""
import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path

from fow_shared.features import encode_belief
from fow_shared.recording import read_records
from pairb.belief_data import opponent_visible
from pairb.belief_evaluator import BeliefNetworkEvaluator
from pairb.data import split_of
from pairb.provenance import data_files, git_commit, runtime

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("--beliefs", type=int, default=200)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--stockfish", default="stockfish")
    args = ap.parse_args()
    if Path(args.out).exists():
        raise SystemExit(f"{args.out} exists")
    turns = []
    for part in sorted(Path(args.data).glob("part-*.jsonl")):
        turns += [r.agent_input for r in read_records(part) if split_of(r.game_id) == "train"]
        if len(turns) >= args.beliefs:
            break
    turns = turns[:args.beliefs]
    checkpoint = ROOT / "checkpoints" / "belief-v1-d1" / "best.pt"
    with BeliefNetworkEvaluator.from_checkpoint(checkpoint, stockfish_path=args.stockfish, device=args.device,
                                                new_game_each_call=False) as ev:
        ev.evaluate_beliefs(turns[:2])  # warm-up, not timed
        batch = []
        for _ in range(args.repeats):
            started = time.perf_counter()
            ev.evaluate_beliefs(turns)
            batch.append((time.perf_counter() - started) * 1000)
        single = []
        for turn in turns:
            started = time.perf_counter()
            ev.evaluate_beliefs([turn])
            single.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        for turn in turns:
            encode_belief(turn, opponent_visible)
        encode = (time.perf_counter() - started) * 1000
        name, device = ev.name, str(ev.device)
    per_belief_batch = statistics.median(batch) / len(turns)
    report = {
        "source": data_files(args.data), "split": "train", "beliefs": len(turns),
        "boards_per_belief_mean": statistics.mean(len(t.belief.hypotheses) for t in turns),
        "belief_selection": "the first beliefs of the train split, in record order",
        "beliefs_sha256": hashlib.sha256("\n".join(f"{t.observation.ply}|{h.fen}" for t in turns
                                                  for h in t.belief.hypotheses).encode()).hexdigest(),
        "evaluator": name, "device": device, "new_game_each_call": False,
        "ms_per_belief_one_call": per_belief_batch, "one_call_total_ms": batch,
        "ms_per_belief_one_at_a_time_median": statistics.median(single),
        "encode_ms_per_belief": encode / len(turns), "encode_share_of_one_call": encode / len(turns) / per_belief_batch,
        "git_commit": git_commit(), "runtime": runtime(),
    }
    with open(args.out, "x") as f:
        f.write(json.dumps(report, indent=2) + "\n")
    print(f"{len(turns)} beliefs of {report['boards_per_belief_mean']:.1f} boards on {device}: "
          f"{per_belief_batch:.1f} ms each in one call, {report['ms_per_belief_one_at_a_time_median']:.1f} ms one at "
          f"a time; building planes {report['encode_ms_per_belief']:.1f} ms ({100 * report['encode_share_of_one_call']:.0f}%)")


if __name__ == "__main__":
    main()
