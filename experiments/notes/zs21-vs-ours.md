# ZS21 (Zhang & Sandholm 2021, arXiv:2106.06068v2) versus the repository's ZS21 reproduction

Written 2026-11-04 13:30 SGT. Paper facts from the paper text (extracted to scratchpad/zs21-paper/paper.txt;
page = PDF page). Our facts from `pair_a_prep/zs21/`, `zs21_runtime/configs/runtime.toml`,
`zs21_runtime/docs/IMPLEMENTATION.md` and `decisions.md` (D-xx), `zs21_runtime/validation/`. The reproduction
is the partner's work (README: "ZS21 and the belief tracker belong to the other" Pair A member).

| Component | ZS21 paper | Repository reproduction | Gap |
|---|---|---|---|
| Information set I | Exact I up to transpositions, "rarely exceeds size 10^7" (App. D.3, p. 16) | Full I kept in C++ (`native_tracker.py`, position-only merging), Python oracle; transpositions merged ignoring hidden draw history (D-09). Observed: one update enumerated 27,061,529 successors and kept 3,420,428 candidates in 10.1 s (D-26) | Same object; ours hit the clock at ~3.4 M |
| Particles I' | Top up to L = 200 by uniform sampling without replacement from I \ I'; sampled roots assume the opponent knows the exact node; alternate value min(u~(h), u^) (App. D.3; Alg. 15) | `particle_floor = 200`, same rule; retained roots observed up to 2,481 (L is a floor, not a cap) (D-22) | Same |
| Solver | Exact trunk solve "e.g., with an LP solver"; Gurobi 9.0 named only for the medium games (Sec. 7, App. D.2) | Sparse sequence-form LP, SciPy/HiGHS dual simplex, one thread, feasibility 1e-8, full-game certificate at 1e-8; bounded retries at 1e-9, 1e-10 for certificate failure or HiGHS "Not Set" (zs21_highs_recovery.md) | Same method, different solver; 2 of 1,153 solves hit a HiGHS numerical failure (D-29) |
| Tree growth | Iterative deepening: expand internal leaves in the support of either player's strategy; checks, captures, promotions ordered first; depth-d limit unless in both supports (App. D.2-D.3) | Depth-limited 1-KLSS per Alg. 12/15; support-guided expansion; previous tree and strategy retained | Same |
| Knowledge limit and gadgets | 1-KLSS; reach-maxmargin, reach-resolving when margins are not all positive; gifts estimated from blueprint u* differences (Sec. 4, App. D.4) | Same two gadgets and order; gift as non-negative additive B (IMPLEMENTATION.md) | Same |
| Information penalty | Entropy term with M = 10^7; the text (2^-H |I|/M) and Alg. 15 ((1-2^-H)|I|/M) differ (App. D.3) | Text form, uniform over the current I', binary entropy of the next observation, `information_denominator = 10000000` | Same constant; one of the paper's two forms |
| Leaf | Stockfish 13 at depth 1, tanh(x / tau), tau = 6 pawns (App. D.1, p. 16) | Pinned Stockfish 13 batch build (SHA-256 recorded), depth 1, tanh(cp/600); a 6x control variant; mate scores mapped sign(n) 0.9 0.78^(|n|-1) and a +0.9 king-attack heuristic (D-07, D-16) | Same leaf; mate handling is ours (the paper gives none) |
| Rules | No check; king capture wins; "stalemate is a forced win for the stalemating player"; castling through check legal; threefold and 50-move draws declared by the implementation (App. B.1, p. 14) | Profile `paper2021_fow_no_moves_draw_v1`: king capture > fifty-move > threefold > no legal moves = DRAW (team PR #28, D-30) | Deliberate deviation: a side with no FoW-legal move draws here, wins for the opponent in the paper |
| Time per move | Not stated | 16 s from turn transfer (D-26; started at 8 s, raised when full-I updates and first solves timed out); 2 s submission reserve | Paper silent; ours needed 16 s |
| Hardware | "a single machine with 6 CPU cores" (Sec. 6, p. 9) | Windows x64 laptop; 4 single-thread Stockfish 13 workers + 1 LP thread; pixi lock covers win-64 only; POSIX DLL fix on branch pair-a/zs21-posix-support (unmerged) | Comparable core count; platform-pinned |
| Baseline | Same algorithm with imperfect-information search to depth 1, then Stockfish iterative deepening (Sec. 6) | Shared implementation with FoW depth 1 and Stockfish iterative deepening | Same |
| Result vs baseline | 59.5-40.5 over 100 games (Sec. 6, p. 10) | 34 games at 16 s: 17 W / 0 D / 17 L (white 10/0/7, black 7/0/10), old code version, 100-game plan stopped by the user 2026-10-26 (D-28). Earlier partial batches: 8 s, 20 games 9/2/9; 16 s, 13 games 6/0/7 (D-26, D-27) | Not reproduced; a 34-game sample cannot separate 50 % from 59.5 % (expected 20.2 wins, observed 17, about one standard deviation) |
| Result vs humans | ~1700 author: 2 wins in 20+; FM rated 2416: lost 1-9; estimated rating ~2000 (Sec. 6) | None | Not attempted |
| Validation | None published beyond the matches | 612 tests, release verification on Windows 2026-10-27, engine rebuild with identical values on 84 positions, 2,306 actions independently replayed, repetition-consistency record | Our evidence is about correctness of the reproduction, not strength |

## Reading

- Mechanism fidelity is high, higher than for Obscuro: exact I, L = 200 replenishment, LP trunk, 1-KLSS, both
  reach gadgets, M = 10^7 and the depth-1 Stockfish 13 leaf all match the appendix text. The open modelling choices
  are the ones the paper leaves open (mate mapping, LP solver, time budget).
- One deliberate rule change: no-legal-move positions are draws (team PR #28), where the paper makes them a win
  for the stalemating side. Rare, but it changes a terminal value and must be stated with any ZS21 number.
- The strength claim is not reproduced. The only completed batch is 17/0/17 over 34 games against the matched
  baseline, against the paper's 59.5 %. The sample is too small to call either way, and it was played by the
  old code version at 16 s per move on one laptop. The repository's own notes say this result must not be quoted
  as the delivered version's strength.
- Practical limits found while reproducing: full-I updates of millions of positions blow an 8 s budget (hence
  16 s), expansion of ~2,000 retained roots needs ~56,000 Stockfish evaluations in one turn, and HiGHS lost dual
  feasibility twice; all documented with recovery, none fully root-caused.
- A check for the report: an earlier web summary of this paper read the leaf as "depth 11"; the PDF text says
  depth 1 (the "1" after it is a footnote mark). Same artefact appeared for the Obscuro paper.

Sources: arXiv:2106.06068v2 Sec. 4, 6, 7; App. B.1, D.1-D.4, Alg. 15. Repository files as cited.
