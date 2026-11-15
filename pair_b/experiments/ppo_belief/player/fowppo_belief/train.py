"""Train a fog-of-war chess player by PPO self-play, for a fixed number of minutes.

    python -m fowppo.train --name pilot --minutes 30

One network plays both colours in most games, and both colours' decisions are training data.
With --rivals some games are played against other opponents, and then only the learner's moves
are training data: "past" is an earlier copy of the network, kept in a pool that grows as training
goes on, and "random" and "greedy" are the hand-made players in env.scripted_action.

Every --eval-minutes the current network plays --eval-games against the two hand-made players,
half as White and half as Black, once sampling its moves as in training and once always playing
its most likely move. Everything is appended to runs/<name>/log.jsonl. The weights go to
runs/<name>/latest.pt at every evaluation, with a numbered copy every --snapshot-minutes;
--resume continues from such a file under a new --name.
"""
import argparse
import copy
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from torch.distributions import Categorical

from .env import LEARNER, N_PLANES, PAST, RIVALS, VecFow, scripted_action
from .model import PolicyValueNet
from .moves import N_ACTIONS
from .ppo import compute_targets, guarded_update
from .procvec import ProcVec


@torch.no_grad()
def evaluate(model, device, opponent: str, games: int, sample: bool, seed: int, opening=(0, 0)) -> dict:
    """The network against a scripted opponent: `games` games, the network White in the odd ones,
    each after a random opening of `opening` = (fewest, most) plies."""
    vec = VecFow(games, auto_reset=False, opening=opening, seed=seed)
    rng = random.Random(seed)
    network_seat = np.arange(games) % 2
    generator = torch.Generator(device="cpu").manual_seed(seed)
    while vec.alive.any():
        actions = np.zeros(games, dtype=np.int64)
        ours = [i for i in range(games) if vec.alive[i] and vec.seat[i] == network_seat[i]]
        theirs = [i for i in range(games) if vec.alive[i] and vec.seat[i] != network_seat[i]]
        if ours:
            logits, _ = model(torch.from_numpy(vec.obs[ours]).to(device), torch.from_numpy(vec.mask[ours]).to(device))
            if sample:
                picked = torch.multinomial(torch.softmax(logits, dim=1).cpu(), 1, generator=generator).squeeze(1)
            else:
                picked = logits.argmax(dim=1).cpu()
            actions[ours] = picked.numpy()
        for i in theirs:
            actions[i] = scripted_action(vec, i, opponent, rng)
        vec.step(actions, only=ours + theirs)
    wins = sum(winner == network_seat[i] for i, (_, winner, _) in enumerate(vec.results))
    draws = sum(winner == -1 for _, winner, _ in vec.results)
    return {"opponent": opponent, "sample": sample, "games": games, "wins": int(wins), "draws": int(draws),
            "losses": int(games - wins - draws), "score": float((wins + 0.5 * draws) / games),
            "mean_plies": float(np.mean([plies for plies, _, _ in vec.results]))}


def parse_rivals(text: str) -> dict:
    """"self=0.8,past=0.15,greedy=0.05" as {name: chance}."""
    rivals = {}
    for part in text.split(","):
        name, _, chance = part.partition("=")
        if name.strip() not in RIVALS:
            raise argparse.ArgumentTypeError(f"unknown rival {name!r}; choose from {RIVALS}")
        rivals[name.strip()] = float(chance)
    return rivals


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--name", required=True)
    parser.add_argument("--minutes", type=float, required=True, help="training time, evaluation included")
    parser.add_argument("--envs", type=int, default=512)
    parser.add_argument("--steps", type=int, default=64, help="plies per game between updates")
    parser.add_argument("--workers", type=int, default=0, help="processes that generate games; 0 = this process")
    parser.add_argument("--worker-timeout", type=float, default=300.0, help="seconds to wait for a game worker")
    parser.add_argument("--rivals", type=parse_rivals, default=None, help='e.g. "self=0.8,past=0.15,greedy=0.05"')
    parser.add_argument("--opening", type=int, nargs=2, default=(0, 0), metavar=("LOW", "HIGH"),
                        help="random plies at the start of every training game")
    parser.add_argument("--eval-opening", type=int, nargs=2, default=(0, 0), metavar=("LOW", "HIGH"),
                        help="random plies at the start of every evaluation game (the team's matches use 2 8)")
    parser.add_argument("--pool-updates", type=int, default=50, help="updates between copies added to the past pool")
    parser.add_argument("--pool-size", type=int, default=24)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--minibatch", type=int, default=2048)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--lr-end", type=float, default=None, help="learning rate at the last minute (linear in time)")
    parser.add_argument("--gamma", type=float, default=0.995)
    parser.add_argument("--lam", type=float, default=0.95)
    parser.add_argument("--clip", type=float, default=0.2)
    parser.add_argument("--entropy", type=float, default=0.01)
    parser.add_argument("--value-coef", type=float, default=0.5)
    parser.add_argument("--shaping", type=float, default=0.02, help="reward per pawn of piece balance; 0 turns it off")
    parser.add_argument("--blocks", type=int, default=4)
    parser.add_argument("--channels", type=int, default=64)
    parser.add_argument("--eval-minutes", type=float, default=4.0)
    parser.add_argument("--eval-games", type=int, default=200)
    parser.add_argument("--snapshot-minutes", type=float, default=30.0)
    parser.add_argument("--save-minutes", type=float, default=5.0, help="minutes between copies of latest.pt")
    parser.add_argument("--resume", default=None, help="a latest.pt or snapshot to continue from")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="mps" if torch.backends.mps.is_available() else "cpu")
    args = parser.parse_args(argv)

    out = Path(__file__).resolve().parent.parent / "runs" / args.name
    out.mkdir(parents=True, exist_ok=False)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device(args.device)
    trained_plies, updates = 0, 0
    resumed = torch.load(args.resume, map_location="cpu") if args.resume else None
    if resumed:
        args.blocks, args.channels = resumed["config"]["blocks"], resumed["config"]["channels"]
    model = PolicyValueNet(args.blocks, args.channels).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, eps=1e-5)
    if resumed:
        model.load_state_dict(resumed["model"])
        if "optimizer" in resumed:
            optimizer.load_state_dict(resumed["optimizer"])
        trained_plies, updates = resumed["plies"], resumed["updates"]
    (out / "config.json").write_text(json.dumps({**vars(args), "parameters": sum(p.numel() for p in model.parameters()),
                                                 "torch": torch.__version__, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                 "resumed_plies": trained_plies}, indent=2))
    log_file = (out / "log.jsonl").open("a")

    def log(record: dict) -> None:
        log_file.write(json.dumps(record) + "\n")
        log_file.flush()

    def weights() -> dict:
        return {name: tensor.detach().cpu().clone() for name, tensor in model.state_dict().items()}

    T, n = args.steps, args.envs
    if args.workers > 0:
        env = ProcVec(n, args.workers, shaping=args.shaping, rivals=args.rivals, seed=args.seed, opening=args.opening,
                      timeout=args.worker_timeout)
    else:
        env = VecFow(n, shaping=args.shaping, rivals=args.rivals, seed=args.seed, opening=args.opening)
    uses_past = bool(args.rivals and args.rivals.get("past", 0) > 0)
    past_model = copy.deepcopy(model) if uses_past else None
    pool = [weights()] if uses_past else []

    obs = np.zeros((T + 2, n, N_PLANES, 64), dtype=np.uint8)
    mask = np.zeros((T + 2, n, N_ACTIONS), dtype=np.bool_)
    action = np.zeros((T + 2, n), dtype=np.int64)
    logp = np.zeros((T + 2, n), dtype=np.float32)
    value = np.zeros((T + 2, n), dtype=np.float32)
    phi = np.zeros((T + 2, n), dtype=np.float32)
    term_r = np.zeros((T + 2, n), dtype=np.float32)
    done = np.zeros((T + 2, n), dtype=np.bool_)
    learner = np.zeros((T + 2, n), dtype=np.bool_)
    records = (obs, mask, action, logp, value, phi, term_r, done, learner)

    started = time.time()
    eval_seconds = 0.0
    next_eval, next_snapshot = 0.0, args.snapshot_minutes * 60
    next_save = args.save_minutes * 60
    first_row = 0
    start_plies = trained_plies
    env_rows = np.arange(n)
    evaluated_at = -1

    def checkpoint(path: Path) -> None:
        # Written under another name and then renamed, so a reader never finds half a file.
        unfinished = path.with_name(path.name + ".tmp")
        torch.save({"model": model.state_dict(), "config": model.config, "optimizer": optimizer.state_dict(),
                    "updates": updates, "plies": trained_plies, "args": {**vars(args), "rivals": args.rivals}},
                   unfinished)
        os.replace(unfinished, path)

    def run_evaluation() -> None:
        nonlocal eval_seconds, evaluated_at
        if evaluated_at == updates:
            return  # these weights were just evaluated
        evaluated_at = updates
        began = time.time()
        results = [evaluate(model, device, opponent, args.eval_games, sample, args.seed + updates, args.eval_opening)
                   for opponent in ("random", "greedy") for sample in (True, False)]
        eval_seconds += time.time() - began
        minutes = (time.time() - started) / 60
        log({"type": "eval", "minutes": minutes, "updates": updates, "plies": trained_plies,
             "eval_seconds": time.time() - began, "results": results})
        checkpoint(out / "latest.pt")
        text = "  ".join(f"{r['opponent']}/{'sample' if r['sample'] else 'best'} {r['score']:.3f}" for r in results)
        print(f"[eval] {minutes:6.1f} min  {trained_plies / 1e6:7.2f}M plies  {text}", flush=True)

    try:
        while True:
            elapsed = time.time() - started
            if elapsed >= next_eval:
                run_evaluation()
                next_eval += args.eval_minutes * 60
            if elapsed >= next_snapshot:
                checkpoint(out / f"snapshot-{round(elapsed / 60):04d}min.pt")
                next_snapshot += args.snapshot_minutes * 60
            if elapsed >= next_save:
                checkpoint(out / "latest.pt")
                next_save = elapsed + args.save_minutes * 60
            if elapsed >= args.minutes * 60:
                break
            if args.lr_end is not None:
                rate = args.lr + (args.lr_end - args.lr) * min(elapsed / (args.minutes * 60), 1.0)
                for group in optimizer.param_groups:
                    group["lr"] = rate
            if uses_past:
                past_model.load_state_dict(random.choice(pool))

            began = time.time()
            with torch.no_grad():
                for t in range(first_row, T + 2):
                    obs[t], mask[t], phi[t] = env.obs, env.mask, env.phi
                    control = env.control.copy()
                    learner[t] = control == LEARNER
                    obs_t, mask_t = torch.from_numpy(obs[t]).to(device), torch.from_numpy(mask[t]).to(device)
                    logits, estimate = model(obs_t, mask_t)
                    dist = Categorical(logits=logits, validate_args=False)
                    picked = dist.sample()
                    action[t] = picked.cpu().numpy()
                    logp[t] = dist.log_prob(picked).cpu().numpy()
                    value[t] = estimate.cpu().numpy()
                    past_rows = np.flatnonzero(control == PAST)
                    if past_rows.size:
                        rows = torch.from_numpy(past_rows).to(device)
                        past_logits, _ = past_model(obs_t[rows], mask_t[rows])
                        action[t, past_rows] = Categorical(logits=past_logits, validate_args=False).sample().cpu().numpy()
                    if not mask[t][env_rows, action[t]].all():
                        raise RuntimeError("a network sampled an illegal move")
                    term_r[t], done[t] = env.step(action[t])
            first_row = 2
            collect_seconds = time.time() - began

            began = time.time()
            adv, ret = compute_targets(value.astype(np.float64), phi.astype(np.float64), term_r.astype(np.float64),
                                       done, args.gamma, args.lam, T)
            keep = np.flatnonzero(learner[:T].reshape(-1))
            batch = {"obs": torch.from_numpy(obs[:T].reshape(T * n, N_PLANES, 64)[keep]).to(device),
                     "mask": torch.from_numpy(mask[:T].reshape(T * n, N_ACTIONS)[keep]).to(device),
                     "action": torch.from_numpy(action[:T].reshape(-1)[keep]).to(device),
                     "logp": torch.from_numpy(logp[:T].reshape(-1)[keep]).to(device),
                     "adv": torch.from_numpy(adv.reshape(-1)[keep].astype(np.float32)).to(device),
                     "ret": torch.from_numpy(ret.reshape(-1)[keep].astype(np.float32)).to(device)}
            stats = guarded_update(model, optimizer, batch, epochs=args.epochs, minibatch=args.minibatch,
                                   clip=args.clip, value_coef=args.value_coef, entropy_coef=args.entropy,
                                   max_grad_norm=0.5)
            dropped = stats["skipped_steps"] or stats["restored"]
            del batch
            train_seconds = time.time() - began
            for record in records:  # the two look-ahead rows open the next batch
                record[0:2] = record[T:T + 2]

            updates += 1
            trained_plies += int(keep.size)
            if uses_past and updates % args.pool_updates == 0:
                pool.append(weights())
                if len(pool) > args.pool_size:
                    pool.pop(random.randrange(1, len(pool) - 1))  # keep the first and the newest
            flat_value, flat_ret = value[:T].reshape(-1)[keep], ret.reshape(-1)[keep]
            games = env.finished[:]
            del env.finished[:]
            winners = Counter(winner for _, winner, _ in games)
            total = max(len(games), 1)
            elapsed = time.time() - started
            record = {"type": "update", "minutes": elapsed / 60, "updates": updates, "plies": trained_plies,
                      "plies_per_second": (trained_plies - start_plies) / max(elapsed - eval_seconds, 1e-9),
                      "collect_seconds": collect_seconds, "train_seconds": train_seconds,
                      "explained_variance": float(1 - np.var(flat_ret - flat_value) / (np.var(flat_ret) + 1e-12)),
                      "learning_rate": optimizer.param_groups[0]["lr"], "learner_share": float(keep.size / (T * n)),
                      "games": len(games), "mean_plies": float(np.mean([p for p, _, _ in games])) if games else None,
                      "white_wins": winners[1] / total, "black_wins": winners[0] / total, "draws": winners[-1] / total,
                      "end_reasons": dict(Counter(reason for _, _, reason in games)), **stats}
            log(record)
            if updates % 10 == 1:
                print(f"[train] {elapsed / 60:6.1f} min  update {updates:5d}  {trained_plies / 1e6:7.2f}M plies  "
                      f"{record['plies_per_second']:6.0f} plies/s  collect {collect_seconds:4.1f}s train {train_seconds:4.1f}s  "
                      f"entropy {stats['entropy']:.2f}  kl {stats['approx_kl']:.4f}  ev {record['explained_variance']:.2f}  "
                      f"game {record['mean_plies'] or 0:5.1f} plies  draws {record['draws']:.2f}", flush=True)
            if dropped:
                print(f"[guard] update {updates}: {stats['skipped_steps']} training step(s) skipped for invalid numbers"
                      + ("; the whole update was dropped and the weights put back" if stats["restored"] else ""),
                      flush=True)

        run_evaluation()
        checkpoint(out / "final.pt")
        print(f"[done] {updates} updates, {trained_plies / 1e6:.2f}M plies in {(time.time() - started) / 60:.1f} min",
              flush=True)
    finally:
        if isinstance(env, ProcVec):
            env.close()


if __name__ == "__main__":
    sys.exit(main())
