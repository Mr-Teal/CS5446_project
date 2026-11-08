# Obscuro (Zhang & Sandholm, arXiv:2506.01242v2) versus our Pair A agent

Written 2026-11-04 13:00 SGT. Paper facts come from the paper text (page/appendix cited; extracted to
scratchpad/obscuro-paper/paper.txt from the arXiv PDF). Our facts come from the code at pair-a/solver-labels
87b3089 (label_run.py, anytime_agent.py, one_sided.py, search_policies.py, tail_guard.py, belief_tracker.py)
and the arm configurations in PLAN.md / verification-log. "Labels" = the label-collection setting; "fe-s16" =
the strength arm with the same search budget.

| Component | Obscuro (paper) | Ours | Gap |
|---|---|---|---|
| Position set P | Full set of positions consistent with the observations, enumerated every move; "usually \|P\| <= 10^6" (Sec. 3); average 17,264 (App. D) | Exact history DAG; exact arms: unbounded until the container cap; label/guard arms: pruned uniformly to 96,000 states when exceeded. Measured over the exact-s16 arm: median 188 states, mean 19,528, p99 451,806, max 2,199,651 (tail_guard.py) | Same object and similar average size; they keep it exact, we prune the tail |
| Sampled subgame roots I | "no more than a few hundred positions" (Sec. 3); padded to MinInfosetSize = 256 by sampling P without replacement (Fig. 9, App. C.1) | 16 hypotheses (sample_size 16) | 16x fewer roots |
| Empty or short set | Pad from P; new states give the opponent perfect information with alternate value min{v~(h), v*} (App. C.1) | No replenishment. A belief with no consistent hypothesis raises; the arm counts the game as aborted, the label runner (87b3089) logs it and moves on | Missing mechanism; ~13 % of 5 s label games at 96k |
| Solver | PCFR+, last iterate, one CFR thread (Sec. 3.2, 3.4) | PCFR+ (Farina, Kroer & Sandholm 2021 local PRM+), alternating schedule, last iterate (pcfr.py; config policy raw_last_iterate) | Same algorithm |
| Tree growth | One-sided GT-CFR: explorer's sampling policy = 1/2 uniform over the current support + 1/2 argmax of u + C*sigma*sqrt(N(I))/(1+N(I,a)), C = 1, variance with prior samples -1 and +1 (App. C.4); two expansion threads in parallel with the solver | Same mixture and same score with C fixed at 1 and the same (-1, +1) prior (one_sided.py distribution); serial, one process | Same rule, no parallelism |
| Depth | Average search depth 10.7 plies (App. D) | initial_depth 1, max_depth 2 (label_run.py:200; fe-s16 the same) | ~5x shallower |
| Tree size | Average 1,070,552 nodes / 14,404 infosets per search; 181,421 nodes carried over from the previous move (App. D) | Caps: 16,384 nodes, 4,096 evaluator calls, 1,024 rounds; growth stops at 70 % of the clock | ~65x smaller trees |
| Knowledge limit | KLUSS: 2-knowledge-limited unfrozen subgame solving (App. C.6) | Sampled synchronous I^2 projection from the saved tree with finite-cut boundaries (config knowledge saved_sampled_tree_synchronized_I2); no full asynchronous knowledge closure (obscuro_status.md) | Approximation of the paper's construction |
| Gadgets | Maxmargin while the exit-always check holds, else Resolve; Resolve root weights alpha(J) = 1/2 (y(J)/sum y + 1/m); alternate and gift values from the current profile, not best response (App. C.1-C.3) | Serial Maxmargin/Resolve switching; gift accounting is audit-only (no ancestor payments) | Partially implemented |
| Leaf | Stockfish 14, MultiPV, depth 1, one call per expanded node, clamped to [-1, +1] "in the same manner as ZS21"; new infoset initialized on Stockfish's best child (App. C.5) | sf14-fe-s16 arm: Stockfish 14.1 depth 1 via tanh(cp/600); labels and fe-s16: material count tanh(cp/600); new infoset initialized on the heuristic best child (initial_policy heuristic_best) | Leaf matches in the sf14 arm; the labels use the weaker material leaf by design (speed, no engine in the loop) |
| Move selection | Last iterate; Maxmargin mixes among at most MaxSupport = 3 "stable" actions, Resolve plays the top action; stable = in the support at every iteration after half the budget (App. C.8, Fig. 8) | purify_policy: same rule (top 3 stable in Maxmargin, top action in Resolve); StableSupport intersects supports after the half budget | Same |
| Cross-turn reuse | Saved partial tree Gamma-hat and its strategies reused every move (Sec. 3) | Saved sampled tree projected and rebased each turn (rebase_solver, seed_new) | Same idea, smaller tree |
| Time | 5 s per move for AI matches (not counting position enumeration); 3+2 against humans | 5 s per move; the clock includes tracking, so the belief update eats into the search on big-belief turns | Comparable nominal budget, less effective search time |
| Hardware | Human matches: one 6-core Intel i5 desktop; ablations: AMD EPYC, 10 cores (5 per side) (App. D) | Atlas: 1 CPU core per game; homelab: one Python process per game in a capped container; Python, not a compiled engine | Roughly 5 cores vs 1, and interpreter overhead |
| Game length | 116.6 plies average (App. D); no ply cap mentioned | 200-ply cap; label games average 64.5 plies | Our cap truncates long games |
| Opponents and results | 85.1 % vs ZS21 over 1,000 games; 97 % over 100 games vs humans rated 1450-2006; 80 % (+16 -4, +241 Elo) over 20 games vs the #1 player rated 2318 (Sec. 4) | fe-s16 0.924 and sf14-fe-s16 1.000 over 100 games vs the Material OnePlyBot (256/8/2000); exact vs guard parity on shared seeds | Not comparable: different opponents, no human or ZS21 baseline |
| Ablations (paper) | Purification off 70.2 %, KLUSS off 58.0 %, one-sided off 53.3 %, non-uniform Resolve off 53.3 %, simple-eval vs full 81.9 %; each doubling of time 52-57 % (Sec. 4.1-4.2) | Our arms vary leaf (material vs Stockfish), belief handling (exact / pruned / guard), sample size (s16/s64/s256) | Different axes |

## What follows for the report and for the labels

- The algorithmic skeleton is the paper's: PCFR+ last iterate, one-sided GT-CFR with the same exploration score
  and mixture, the same purification and stability rule, Stockfish-14 depth-1 leaf in the sf14 arm.
- The scale is not: 16 roots instead of 256, depth 2 instead of ~10.7, ~16k nodes instead of ~1.07M, one Python
  process instead of three threads on 5 cores. The paper's 5 s is also search time only; ours includes tracking.
- Two mechanisms are absent or approximate: root replenishment when the sampled set is short or empty (the
  cause of our dead-belief games), and the full KLUSS knowledge closure (ours is a sampled synchronous
  projection). Gift payments to ancestors are audited, not applied.
- The labels therefore encode a 2-ply, 16-root, material-leaf equilibrium value. The paper's search would give a
  different (deeper, engine-informed) target. Say so where the labels are described.

Sources: arXiv:2506.01242v2 (Secs. 3-4, App. C.1, C.4, C.5, C.8, D); repository files cited above.
