# Our agent against misty v1.6: primary arm, 20 games, 5 s a move

Our agent scored **0-0-18** (wins-draws-losses) in 18 scored games: score 0.000, 95 % Wilson interval [0.000, 0.176].

| | Count |
|---|---|
| Games requested | 20 |
| Reached a result on the board (scored) | 18 |
| of these, recorded with an error after the last move | 0 |
| Stopped at the ply cap (not scored) | 0 |
| Failed before the end (not scored) | 2 |
| Never played | 0 |

| Our colour | Wins | Draws | Losses |
|---|---|---|---|
| White | 0 | 0 | 9 |
| Black | 0 | 0 | 9 |

Failed games by the side that raised the error: {'ours': 2}. If each of them counts against that side, the score is 0-0-20 in 20 games (0.000, [0.000, 0.161]).

Game ends: {'king_capture': 18}. Length of scored games in plies: median 61, range 39 to 137.

Per-move figures cover every recorded move, moves of failed games included.

| Per move | Our agent | Misty |
|---|---|---|
| Moves recorded | 664 | 673 |
| Time in the move call, median ms | 1,167 | 5,474 |
| Time in the move call, mean ms | 1,654 | 5,970 |
| Time in the move call, 90th percentile ms | 3,743 | 7,610 |
| Time in the move call, maximum ms | 5,111 | 12,384 |
| Move calls longer than the budget | 1 | 673 |
| Move calls longer than 1.5 times the budget | 0 | 80 |
| Belief update (outside the budget), median ms | 5.9 | 0.3 |
| Belief update (outside the budget), maximum ms | 54,577 | 8,987 |

| Search effort (each side's own measure) | Value |
|---|---|
| Ours: solver backend | native |
| Ours: PCFR+ iterations this move, median | 1,024 |
| Ours: tree nodes, median | 3,156 |
| Ours: leaf calls, median | 114 |
| Ours: fallback moves (search not finished in time) | 7 (0.011 of moves) |
| Ours: belief updates on a pruned belief, share | 0.306 |
| Misty: search iterations, median | 8,427 |
| Misty: belief size at the move, median / maximum | 281 / 14,666,979 |
| Misty: belief updates that hit its size cap | 0 |
| Misty: Stockfish leaf fallbacks | 0 |

Rule check: 1,357 positions compared between the two rule sets with no difference. Captures of a pawn that had just advanced two squares: 9 of misty's pawns (the only case where misty's observation says more than our rules would), 13 of ours.

| Game | Seed | Our colour | Outcome for us | Plies | End | Minutes |
|---|---|---|---|---|---|---|
| 1 | 1001 | white | loss | 62 | king_capture | 4.8 |
| 2 | 1002 | black | loss | 41 | king_capture | 2.8 |
| 3 | 1003 | white | loss | 44 | king_capture | 2.3 |
| 4 | 1004 | black | loss | 39 | king_capture | 2.8 |
| 5 | 1005 | white | loss | 48 | king_capture | 3.3 |
| 6 | 1006 | black | loss | 43 | king_capture | 2.7 |
| 7 | 1007 | white | loss | 48 | king_capture | 3.7 |
| 8 | 1008 | black | loss | 137 | king_capture | 15.0 |
| 9 | 1009 | white | loss | 56 | king_capture | 3.8 |
| 10 | 1010 | black | loss | 73 | king_capture | 5.0 |
| 11 | 1011 | white | failed | 81 | error | 10.8 |
| 12 | 1012 | black | loss | 65 | king_capture | 3.5 |
| 13 | 1013 | white | loss | 74 | king_capture | 4.4 |
| 14 | 1014 | black | loss | 113 | king_capture | 14.8 |
| 15 | 1015 | white | loss | 52 | king_capture | 4.3 |
| 16 | 1016 | black | failed | 59 | error | 4.5 |
| 17 | 1017 | white | loss | 60 | king_capture | 3.7 |
| 18 | 1018 | black | loss | 75 | king_capture | 5.4 |
| 19 | 1019 | white | loss | 64 | king_capture | 3.5 |
| 20 | 1020 | black | loss | 103 | king_capture | 10.5 |

Failed games:

- Game 11 (seed 1011, we were white, 81 plies, raised on the side of: ours): BeliefBudgetError: no_candidate: stopped by None; no descendants of retained support; rebuild from the private stream
- Game 16 (seed 1016, we were black, 59 plies, raised on the side of: ours): BeliefBudgetError: no_candidate: stopped by None; no descendants of retained support; rebuild from the private stream
