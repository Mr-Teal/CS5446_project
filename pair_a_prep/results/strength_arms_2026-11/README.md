# Strength arms, 5 to 11 November 2026: raw game records

The records behind section 2.4 of `pair_a_prep/docs/handover_2026-11-12.md` (table 2.8 of
`handover_2026-11-10.md`). They are here so that the scores can be recomputed without access to the machine the
arms ran on. All arms ran on one VM (AMD Ryzen 7 9700X, RTX 5070 Ti, Python 3.12.14, torch 2.11.0+cu128), not on
Atlas.

## Files

| File | Arm | Player A | Player B |
|---|---|---|---|
| `strength-fe-s16.tar.gz` | `fe-s16` | Search agent (Python solver), material leaf, exact tracker | OnePlyBot |
| `strength-guard-fe-s16.tar.gz` | `guard-fe-s16` | same, guard tracker (96,000 states) | OnePlyBot |
| `strength-sf14-fe-s16.tar.gz` | `sf14-fe-s16` | same, Stockfish 14.1 depth-1 leaf, exact tracker | OnePlyBot |
| `strength-net-fe-s16.tar.gz` | `net-fe-s16` | same, value network v1, exact tracker | OnePlyBot |
| `strength-netv2-fe-s16.tar.gz` | `netv2-fe-s16` | same, value network v2 (checkpoint g237), exact tracker | OnePlyBot |
| `strength-netv2-vs-fe-s16.tar.gz` | `netv2-vs-fe-s16` | value network v2, exact tracker | Search agent, material leaf, exact tracker |
| `strength-netv2-vs-fe-guard-s16.tar.gz` | `netv2-vs-fe-guard-s16` | value network v2, guard tracker | Search agent, material leaf, guard tracker |
| `driver-netv2.log` | | the launcher's log of the three `netv2` arms: every chunk's start, exit code and duration | |
| `recount.py` | | recomputes everything below from the records | |
| `source_states.py` | | lists the code states of the network arms from the recorded file hashes | |

Each archive holds one folder per chunk, `strength-<arm>-c<N>/`, with `evaluate_config.ini` (the exact
configuration of that chunk), `games.jsonl` (one row per game: seed, colours, status, winner, termination, and every
ply with its move, time and search diagnostics), `summary.json` (written only when the chunk finished),
`hash_rules.json`, and for the network arms `provenance.json` (start time, hardware, SHA-256 of the configuration
and of the checkpoint). `tracker_updates.jsonl` is left out for size; it is on the VM.

## Protocol

50 chunks of 2 games per arm. Chunk N plays seeds 1001 + 2(N - 1) and the next one, colours alternating, 5 s a move,
200-ply cap, 16 sampled boards, solver capped at 1,024 iterations, 16,384 nodes and 4,096 leaf calls. A chunk runs in
its own container with an 8 GB memory cap and a time limit per chunk (1,800 s in the earlier arms, 10,800 s in the
later `netv2` runs). A chunk that is killed or cut off is not replayed.

## Reconciliation (output of `recount.py`)

| Arm | Finished chunks | Cut off after some games | No record | Game rows | Reached a result | Failed | Never played |
|---|---|---|---|---|---|---|---|
| `fe-s16` | 37 | 13 | 0 | 79 | 79 | 0 | 21 |
| `guard-fe-s16` | 49 | 0 | 1 (chunk 1) | 98 | 95 | 3 | 2 |
| `sf14-fe-s16` | 50 | 0 | 0 | 100 | 96 | 4 | 0 |
| `net-fe-s16` | 46 | 4 | 0 | 93 | 91 | 2 | 7 |
| `netv2-fe-s16` | 50 | 0 | 0 | 100 | 99 | 1 | 0 |
| `netv2-vs-fe-s16` | 1 | 3 | 46 | 2 | 2 | 0 | 98 |
| `netv2-vs-fe-guard-s16` | 48 | 2 (chunks 41, 47) | 0 | 98 | 88 | 10 | 2 |

No game stopped at the ply limit. Every game that reached a result ended by king capture. A failed game ended with a
runner error and is never scored: in 16 games the tracker lost every consistent history (all arms except
`sf14-fe-s16`), in 4 games the Stockfish leaf timed out or died (`sf14-fe-s16` only).
`netv2-vs-fe-s16` was abandoned after chunks 2 and 3 were memory-killed; `netv2-vs-fe-guard-s16` replaces it.

## Scores, two conventions

"Finished chunks" counts only games of chunks that finished; this is what `netv2_scores.py` and the handover of
10 November report. "All completed" counts every game that reached a result, including the first game of a chunk
whose second game was killed. They differ by a few games. Score = (wins + draws / 2) / scored games from player A's
side, with a 95 % Wilson interval.

| Arm | Finished chunks: W-D-L, score | All completed: W-D-L, score |
|---|---|---|
| `fe-s16` | 68-0-6 of 74, 0.919 [0.834, 0.962] | 73-0-6 of 79, 0.924 [0.844, 0.965] |
| `guard-fe-s16` | 82-0-13 of 95, 0.863 [0.780, 0.918] | the same |
| `sf14-fe-s16` | 96-0-0 of 96, 1.000 [0.962, 1.000] | the same |
| `net-fe-s16` | 87-0-3 of 90, 0.967 [0.907, 0.989] | 88-0-3 of 91, 0.967 [0.908, 0.989] |
| `netv2-fe-s16` | 95-0-4 of 99, 0.960 [0.901, 0.984] | the same |
| `netv2-vs-fe-s16` | 2-0-0 of 2 | the same |
| `netv2-vs-fe-guard-s16` | 77-0-10 of 87, 0.885 [0.801, 0.936] | 77-0-11 of 88, 0.875 [0.790, 0.929] |

In the head-to-head arm the one extra game is a loss for the network side (chunk 47, seed 1093) whose partner game
was memory-killed. The "all completed" row is the one to quote: it does not drop a result because of what happened
to another game.

## Identities, and what is not frozen

- Checkpoints (SHA-256 of `best.pt`): value network v2 checkpoint g237
  `cc069423f19bc427da5e300fe0645e6ab477df8e117eda018d34ba9107cd6d6d`; value network v1
  `48251445d554afce9567853674d2c6844daf91776bc0ed6a8c1499852ca7c1be`. Each network chunk's `provenance.json`
  repeats the hash it loaded.
- Configuration: `evaluate_config.ini` in every chunk folder, with its SHA-256 in `provenance.json`.
- Code: not one frozen commit, but recorded file by file. The runner could not read the git commit inside its
  container (`provenance.json` has `git_commit: null`), so it stored a SHA-256 of every source file for each chunk of
  the network arms. `source_states.py` lists the distinct code states from those hashes:
  - `net-fe-s16`: one state for all 50 chunks.
  - `netv2-vs-fe-guard-s16` (the head-to-head): three states. Between them only files outside the arm's code path
    changed: an experiment script (`profile_move.py`), the training script, four Fog Lab modules and the merge tool.
    The search, the leaf, the tracker interface and the match runner are identical in all 50 chunks.
  - `netv2-fe-s16`: five states. One file on the leaf's import path changed, between chunks 3 and 4:
    `pair_b/src/pairb/belief_net.py` gained an optional policy head, which is off for this checkpoint. The other
    changes are training, offline-evaluation, experiment and Fog Lab files.
  - The launcher logged the working tree's commit at each start: d63de87 with uncommitted changes to the
    network-leaf factory, then 14502df.
  - `fe-s16`, `guard-fe-s16` and `sf14-fe-s16` ran earlier from the working tree of `pair-a/obscuro-mechanisms`
    (head cca2fe2) with an older runner that wrote no `provenance.json`; their code state at run time is not recorded.
- A rerun from one clean commit has not been done.

## Verify

    mkdir records && for f in strength-*.tar.gz; do tar xzf "$f" -C records; done
    python3 recount.py records
    python3 source_states.py records
