# Pair A: results and status up to generation-0 self-play (inputs for the report)

Written 2026-11-12. One document that compiles what Pair A's search-and-learning lane has measured up to and
including generation-0 self-play, for the final report. Numbers are copied from `handover_2026-11-10.md` in this
folder (sections cited as H 2.x), from `notes/native_port_log.md`, and from the run folders named with each table.
Nothing here uses the held-out test games. Label games and the Atlas half of generation 0 were computed on NUS HPC
Atlas (NUSREC-HPC-00001).

Not part of this document: work started on 11 November on choosing moves without search. It is on local branches,
its results are still being checked, and nothing below depends on it.

## 0. Names used here (one name per thing)

The handover used shorter names for some of these; the mapping is in the last column.

| Name | What it is | In the handover |
|---|---|---|
| Material leaf | Piece count squashed to [-1, 1] | `material` |
| Stockfish leaf, SF-d1 / SF-d8 | One Stockfish 14.1 call on one board at depth 1 or 8 | same |
| Value network v1 | `belief-solver-v1`, trained on label round 1 | network v1 |
| Value network v2, checkpoint g237 | `belief-solver-v2-sf8-g237`, trained on 237 games of label round 2 | network v2 (the arm leaf) |
| Value network v2, checkpoint 480-s1 | `belief-solver-v2-sf8-480-lr1e-3-s1`, trained on label rounds 2 + 3 | 480-game result |
| Search agent, Python solver | 16 sampled boards, a tree of our move and the reply, PCFR+ in Python | "our search" |
| Search agent, native solver | The same algorithm with C++ kernels (10 Nov) | section 7 |
| OnePlyBot | Pair B's one-ply material bot with a particle tracker; the opponent in most arms | same |
| Label round 1 / 2 / 3 | One Atlas collection of search-labelled games | same |
| Generation-0 self-play | Label games in which value network v2 replaces Stockfish as the leaf | not in the handover |
| Population / belief | Every history the tracker holds / the 16 boards sampled from it, weight 1/16 each | population / sampled hypotheses |
| Exact tracker / guard tracker | Keeps the whole population / prunes above 96,000 states | same |
| Leaf | The evaluator the search calls on one board at the edge of its tree | same |
| Solver iteration | One PCFR+ pass over the tree | PCFR+ round |
| Fallback | The move played when the search could not finish | same |
| Board error / position error | Value network accuracy against the stored search values (H 0) | same |
| Score | (wins + draws / 2) / scored games of an arm, with a 95 % Wilson interval | same |

Every value network here scores ONE board at a time when the search calls it. That has been true in every version.

## 1. What was built, in order

| Date | Step | Result in one line |
|---|---|---|
| before 9 Nov | Label round 1 (material leaf) and value network v1 | Search with value network v1 scores 0.967 against OnePlyBot (90 games) |
| 9 Nov | Label round 2: SF-d8 leaf, 30 s a move, 240 games | 11,679 positions; value network v2 |
| 10 Nov | Label round 3: same protocol, 240 more games | 480 games, 22,771 positions in all |
| 10 Nov | Input comparison, leaf mode, policy head, recipe sweep | Section 2.3 |
| 10 to 11 Nov | Strength arms with value network v2 (g237) as the leaf | 0.960 against OnePlyBot; 77-0-10 against our own search with the material leaf |
| 10 Nov | Native port of the solver, the rules, the leaf data path and the gadget path | A 2 s move now runs about 17,800 solver iterations on about 2,800 nodes |
| 10 Nov | Memory-safety fix in the solver kernel, found with AddressSanitizer | Section 2.6 |
| 10 to 11 Nov | Generation-0 self-play on the VM and on Atlas | 381 games, 27,875 positions; not yet trained on |

## 2. Results

### 2.1 Label data (H 2.1, and `PLAN` log for round 3)

| | Round 2 | Rounds 2 + 3 (`solver-v2-sf8-480`) |
|---|---|---|
| Games | 240 | 480 |
| Labelled positions | 11,679 | 22,771 |
| Split by game (train / validation / test) | 199 / 25 / 16 | 392 / 46 / 42 |
| Protocol | Search agent, Python solver; SF-d8 leaf; 30 s a move; 16 sampled boards; guard tracker | same |

Round 2 had 1,251 fallbacks (9.7 % of moves) and 16 failed games whose partial records are kept. 92 % of the
fallbacks were "budget exhausted during tree construction": scoring the first ply over 16 boards with SF-d8 can
exceed 30 s on wide positions. The labels are therefore biased against positions with many legal moves.

### 2.2 Value network v2: accuracy against the search's stored values (H 2.2)

Same 25 validation games throughout; lower is better; board error / position error.

| Evaluator | Board | Position |
|---|---|---|
| Predict zero | 0.602 | 0.576 |
| Material leaf | 0.309 | 0.286 |
| SF-d1 | 0.141 | 0.114 |
| SF-d8, the leaf that produced the labels | 0.092 | 0.070 |
| Value network v2, 99 training games | 0.377 | 0.343 |
| Value network v2, 199 training games, three training runs | 0.261 / 0.263 / 0.270 | 0.228 / 0.232 / 0.236 |
| Value network v2, checkpoint g237 (the arm leaf) | 0.260 | 0.232 |
| Value network v2, 392 training games, three training runs (480-s0 / s1 / s2) | 0.228 / 0.225 / 0.262 | 0.197 / 0.193 / 0.234 |

Readings. The network needs no engine and beats the material leaf, and it is far from SF-d1. Doubling the training
games lowered position error by about 0.035 in two of three runs; the third stopped at epoch 4 and matches the
smaller set, so the gain is real and the early-stopping rule is noisy. Two runs of the same recipe differ by about
0.015, so smaller differences are not interpretable. SF-d8 does not reach zero against its own labels because a
label is the value of a two-ply search over the belief, not of one board.

### 2.3 What the network is shown (H 2.4 to 2.7)

Position error on the 25 validation games, 240-game training set.

| Input | Position error | Difference to the full input |
|---|---|---|
| Full: the 16 sampled boards, each with the belief planes | 0.246 | |
| Fuzzy board: one picture with the chance of each enemy piece on each square, no sampled boards | 0.249 | +0.002 [-0.013, +0.020] |
| Only what we see | 0.400 | +0.154 [+0.109, +0.200] |

- The belief information is essential: without it the error rises by 0.15.
- Carrying the belief as 16 boards or as one fuzzy board makes no measurable difference.
- Leaf mode (H 2.5): the search hands the network one board at a time. Scored that way, checkpoint g237 has board
  error 0.281 against 0.260 when it sees the whole belief. A network trained on single boards from the start scores
  0.269 in leaf mode, inside the 0.015 spread between training runs.
- Policy head (H 2.6), parked: trained on the solver's root policy, which is nearly one move per position, it barely
  beats a uniform prior (top-1 agreement 0.16 to 0.18) and costs the value head 0.03 to 0.05.
- A variant that reads SF-d1 as an input (H 2.7) was closed on 9 November: a network leaf must not need an engine.

### 2.4 Strength arms (H 2.8; final 11 Nov 11:34 SGT)

Search agent with the PYTHON solver, 5 s a move, 50 chunks of 2 games with fixed seeds, 200-ply cap.

| Arm | Our leaf, tracker | Opponent | Games | Score | 95 % Wilson |
|---|---|---|---|---|---|
| `fe-s16` | Material leaf, exact | OnePlyBot | 74 | 0.919 | [0.834, 0.962] |
| `guard-fe-s16` | Material leaf, guard | OnePlyBot | 95 | 0.863 | |
| `sf14-fe-s16` | SF-d1, exact | OnePlyBot | 96 | 1.000 | [0.962, 1.000] |
| `net-fe-s16` | Value network v1, exact | OnePlyBot | 90 | 0.967 | [0.907, 0.989] |
| `netv2-fe-s16` | Value network v2 g237, exact | OnePlyBot | 99 | 0.960 | [0.901, 0.984] |
| `netv2-vs-fe-guard-s16` | Value network v2 g237, guard | Our search with the material leaf, guard | 87 | 0.885 | [0.801, 0.936] |

Readings. OnePlyBot is close to saturated for any decent leaf: the intervals of the four leaves overlap. The
informative arm is the head-to-head: the search with value network v2 beat the same search with the material leaf
77-0-10, with the whole interval above 0.5, same clock and same tracker on both sides. Two of its 50 chunks were
memory-killed at the 8 GB container cap and were not replayed; 9 games failed with a runner error and are not scored.

### 2.5 Search scale before the native port (H 2.9)

| | Obscuro (paper, Appendix D) | Search agent, Python solver |
|---|---|---|
| Tree depth | 10.7 plies on average | capped at 2 |
| Nodes per move | about 1.07 million | about 1,200 in a 3.6 s move |
| Sampled boards at the root | up to a few hundred, padded to 256 | 16 |
| What the 5 s covers | the search only | search and belief tracking |

The paper reports tree size and depth; it does not report solver iterations per move.

### 2.6 Native port (H 7, `notes/native_port_log.md`)

Same algorithm, with the Python implementation kept as the reference behind backend switches. Every step has tests
that compare the native path with the Python path.

| Step | What moved to C++ | Check | Effect |
|---|---|---|---|
| A0, A1 | The PCFR+ iteration | bit-equal on the host | Solver share of a move 30-40 % to 3-7 % |
| B1 | Fog-chess rules, move generation, observation keys | bit-equal on 60k recorded states | 12-52 ms to 0.75-2.1 ms per expansion |
| B2 | The network leaf's children, rule values and planes | bit-equal planes on 122k children | 10 ms to 0.7 ms per leaf call |
| A3/A4/D1 | Iterations in batches, incremental tree compile | bit-equal | A fresh turn 4.5 s to 0.3-0.6 s |
| D2 | The cross-turn gadget path | 3 games x 7 turns identical | Gadget turns 2.7-4.5 s to 0.25-0.6 s |
| D3/C | Root-parallel walks | bit-equal at every thread count | 2.4x iterations with 6 threads on 16k-node trees |

- At the arms' protocol (1,024 iterations, depth 2, 16 boards) a recorded move takes 0.3 to 0.6 s instead of 4.5 s
  with identical trees and moves.
- Measured in generation-0 self-play on the VM (2 s a move, GPU leaf, 11,703 labelled moves): median 2,808 nodes
  (90th percentile 12,303, cap 16,384), median 17,812 solver iterations, median 1,810 ms used.
- Memory-safety fix (kernel commit 57fa291 here, b247f35 on `pair-a/native-port`): the first native self-play run
  aborted after 11 games with a heap corruption. AddressSanitizer builds located a scratch buffer in the gadget
  controller sized by the number of groups and written once per root of a group. Fixed, with a regression test.
- Still Python: the belief tracker, the projection of the saved tree between turns, the growth sampler.
- NOT measured: the native solver in a strength arm. Every score in section 2.4 is the Python solver.

### 2.7 Generation-0 self-play (status, not a result)

Label games in which the leaf is value network v2 (checkpoint 480-s1) instead of Stockfish, played by the search
agent with the native solver. Purpose: training data for a next value network without an engine in the loop.

| | VM | Atlas |
|---|---|---|
| Leaf device, clock | GPU, 2 s a move | one CPU thread, 12 s a move (chosen by measurement) |
| Games written | 159 of 240 planned (lane paused 11 Nov) | 222 of 240 (two tasks still inside very long games) |
| Games completed without error | 143 | 197 |
| Games lost to the tracker (true history pruned by the guard) | 15 | 24 |
| Games lost to a rounding error in the stored value | 1 | 1 |
| Labelled positions | 11,703 | 16,172 |
| Fallbacks, share of plies | 210 of 12,682 (1.7 %) | 1,120 of 18,376 (6.1 %) |
| Results of completed games (white / black / draw) | 71 / 64 / 8 | 79 / 107 / 10, one at the ply limit |
| Median game length | 80 plies | 86 plies |

- The rounding error (a value of 1 + 2e-16 refused by the record contract) is fixed in this branch (ca2564d); the
  runs above used the commit before it.
- About one game in ten is lost when the guard tracker prunes the true history. There is no recovery step.
- On the VM the runner was memory-killed 14 times in about 20 hours at a 5 GB cap, by peaks of the tracker; it
  resumes by itself and replays the interrupted game.
- Training on these games has not been done. `train_belief_net.py --outcome-mix` (in this branch) can blend the
  search value with the game result. No claim is made about generation 0 improving anything.
- Data: VM `/home/dev/cs5446-review/labels/selfplay/gen0-vm`, Atlas `/hpctmp/tommy.21.31/fow/runs/gen0-atlas`.

## 3. Limits to state in the report

1. The value network is trained on beliefs and used on single boards. Measured cost: about 0.02 board error (2.3).
   The search never values a group of boards as a group.
2. The solver looks two plies ahead, with 16 sampled boards. Obscuro's averages are 10.7 plies and about a million
   nodes. Our subgame is a sampled approximation of the paper's knowledge-limited construction, without its
   padding step and without gift payments (see `obscuro_status.md`).
3. No equilibrium claim. The solver is PCFR+ with the last iterate on a sampled subgame; there is no guarantee.
4. OnePlyBot saturates. Only the head-to-head arm separates leaves, and it has 87 games.
5. Strength was measured with the Python solver only.
6. Label fallbacks bias the labels against wide positions (2.1). Single training runs differ by about 0.015.
7. Generation 0 is data, not a result.

## 4. Corrections the presentation backups need

Slide numbers of the 71-slide final deck. Each line: what the slide says, and what the measurements say.

| Slide | Says | Should say |
|---|---|---|
| 60 | Pipeline starts with "Search with piece-value scores"; "One author-reported cycle. No established improvement in play." | The labels come from the search with the SF-d8 leaf (480 games, two label rounds). In play, the search with value network v2 beat the search with the material leaf 77-0-10 (section 2.4). |
| 61 | "Higher error than the piece-value baseline"; "Improvement over the baseline not established" | True of value network v1 only. Value network v2: position error 0.193 to 0.197 against 0.286 for the material leaf (section 2.2). |
| 32 and script page 27 | "Learned-leaf comparison in deeper search remains pending"; "No result yet" | Finished 11 Nov: 0.960 against OnePlyBot (99 games), 0.885 head-to-head (87 games). |
| 66 | "Train on solver labels that use hidden information" listed as future work | Done: label rounds 2 and 3. |
| 70 | LIN Tzu-Chun "Not yet confirmed" | Recorded work for this lane: the solver-label pipeline, value network v2 training and its input comparisons, the strength arms, the native port, generation-0 self-play. The wording of the contribution and the AI-assistance statement is the author's to give. |

## 5. Where things are

- This branch: `pair-a/gen0-report-inputs-20261112` = the self-play code (`pair-a/self-play-fix`, ca2564d, which
  contains `pair-a/native-port`) merged with the pushed handover branch `pair-a/network-leaf-handover-20261110`
  (cbbc717). Code and tests are those of ca2564d; the merge added documents only.
- Detailed record: `handover_2026-11-10.md` (terms, every table with its run folder, decisions, how to reproduce),
  `notes/native_port_log.md`, `notes/label_round2_plan_log_2026-11.md`, `obscuro_status.md`.
- Checkpoints in the branch, under `pair_b/checkpoints/`: `belief-solver-v2-sf8-g237`, `belief-solver-v2-sf8`,
  `belief-solver-v2-sf8-mid`, `gen-solver-v2-sf8-lr1e-3-s{0,1,2}`, `belief-solver-v2-sf8-480-lr1e-3-s{0,1,2}`.
- Not in git: label records and self-play games (VM `/home/dev/cs5446-review/labels/`, Atlas
  `/hpctmp/tommy.21.31/fow/`), strength-arm outputs (VM `wt-net/pair_c/runs/`).
- Native kernels are built per machine: `python -m pair_a_prep.build_{pcfr,rules,leaf,belief}_kernel`. Without a
  built kernel the code falls back to the Python path silently.
