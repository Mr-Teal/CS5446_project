# Full-game BeliefTracker measurements


A frozen implementation replayed 10 existing complete ZS21 agent/baseline games, with 1286 private observation updates across both players, including 633 decision-turn observations. This is tracker replay validation, not new training or a new tournament.

Every game ran from the standard start through the referee's terminal observation. Time, memory and internal history limits were None; prune was never called. The output sample of 16 limits returned data only. An external audit verified true-history membership after every update.

Histories count complete candidate paths. Stored states count current board/counter nodes; the DAG also retains shared past nodes and edges. Owned memory counts reachable Python objects once each. Process peak RSS includes both trackers, the interpreter, audit temporaries and allocator retention; it is not an individual update's exclusive peak. Timing covers update() only, excluding observation generation and external audits. MiB=2^20 bytes.

## Per-game results


| Source game | Plies | Peak histories | Peak state nodes | Total update s | P95 ms | Peak tracker-owned MiB | Process peak RSS MiB |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 104 | 443,871,725,117,909,214 | 990,143 | 259.54 | 2,683.64 | 1,645.53 | 4,479.79 |
| 1 | 72 | 12,366,739,440 | 271,474 | 79.65 | 1,774.42 | 384.76 | 1,225.95 |
| 2 | 34 | 3,276 | 397 | 0.28 | 14.40 | 0.62 | 49.17 |
| 3 | 85 | 26,464,857,062,450 | 144,035 | 92.79 | 3,289.82 | 310.24 | 725.99 |
| 4 | 65 | 50,744,192 | 19,732 | 3.29 | 89.49 | 28.15 | 130.43 |
| 5 | 51 | 4,435,128 | 306,001 | 46.93 | 1,627.41 | 442.01 | 1,179.91 |
| 6 | 128 | 170,063,309,408,190,345,000 | 7,615 | 37.85 | 419.00 | 76.11 | 353.14 |
| 7 | 16 | 4,156 | 2,069 | 0.48 | 54.95 | 2.71 | 47.71 |
| 8 | 30 | 2,562 | 971 | 0.31 | 22.69 | 1.29 | 45.52 |
| 9 | 48 | 5,336,316 | 61,369 | 20.57 | 987.52 | 116.73 | 366.23 |

## Grouped by output history count


| Size range | Updates | Empirical frequency | Median ms | P95 ms | Mean owned MiB | Max owned MiB |
| --- | --- | --- | --- | --- | --- | --- |
| [10^0, 10^1) | 156 | 12.13% | 0.80 | 2.20 | 0.03 | 0.05 |
| [10^1, 10^2) | 215 | 16.72% | 2.45 | 5.83 | 0.07 | 0.20 |
| [10^2, 10^3) | 169 | 13.14% | 6.08 | 17.49 | 0.28 | 0.85 |
| [10^3, 10^4) | 142 | 11.04% | 8.27 | 84.71 | 0.96 | 6.53 |
| [10^4, 10^5) | 143 | 11.12% | 8.74 | 99.96 | 1.29 | 6.33 |
| [10^5, 10^6) | 139 | 10.81% | 20.90 | 896.79 | 6.60 | 79.14 |
| [10^6, 10^7) | 100 | 7.78% | 84.97 | 3,700.69 | 37.35 | 442.01 |
| [10^7, 10^8) | 44 | 3.42% | 169.72 | 10,216.53 | 52.68 | 428.04 |
| [10^8, 10^9) | 40 | 3.11% | 47.02 | 12,578.99 | 45.28 | 397.02 |
| [10^9, 10^10) | 25 | 1.94% | 709.23 | 17,095.26 | 120.00 | 1,645.53 |
| [10^10, 10^11) | 15 | 1.17% | 852.96 | 5,236.17 | 45.15 | 231.24 |
| [10^11, 10^12) | 16 | 1.24% | 364.45 | 2,117.71 | 50.47 | 103.74 |
| [10^12, 10^13) | 21 | 1.63% | 60.48 | 2,396.88 | 42.35 | 262.57 |
| [10^13, 10^14) | 7 | 0.54% | 44.96 | 3,206.01 | 19.71 | 49.56 |
| [10^14, 10^15) | 9 | 0.70% | 68.38 | 4,842.42 | 35.28 | 62.50 |
| [10^15, 10^16) | 15 | 1.17% | 20.28 | 2,622.35 | 28.79 | 76.11 |
| [10^16, 10^17) | 20 | 1.56% | 7.35 | 141.23 | 21.90 | 29.85 |
| [10^17, 10^18) | 5 | 0.39% | 21.42 | 54.14 | 18.02 | 23.14 |
| [10^19, 10^20) | 3 | 0.23% | 8.94 | 50.20 | 11.68 | 11.68 |
| [10^20, 10^21) | 2 | 0.16% | 31.34 | 52.70 | 11.78 | 11.79 |

## Grouped by output stored-state count


| Size range | Updates | Empirical frequency | Median ms | P95 ms | Mean owned MiB | Max owned MiB |
| --- | --- | --- | --- | --- | --- | --- |
| [10^0, 10^1) | 357 | 27.76% | 2.33 | 5.38 | 1.14 | 27.60 |
| [10^1, 10^2) | 397 | 30.87% | 3.91 | 22.18 | 1.25 | 27.61 |
| [10^2, 10^3) | 294 | 22.86% | 14.72 | 86.93 | 3.14 | 53.56 |
| [10^3, 10^4) | 154 | 11.98% | 150.18 | 1,708.14 | 17.20 | 88.15 |
| [10^4, 10^5) | 73 | 5.68% | 1,812.81 | 6,572.32 | 92.23 | 363.64 |
| [10^5, 10^6) | 11 | 0.86% | 13,479.24 | 70,799.81 | 437.59 | 1,645.53 |

## Grouped by input stored-state count


| Size range | Updates | Empirical frequency | Median ms | P95 ms | Mean owned MiB | Max owned MiB |
| --- | --- | --- | --- | --- | --- | --- |
| [10^0, 10^1) | 362 | 28.15% | 2.34 | 5.30 | 1.02 | 27.61 |
| [10^1, 10^2) | 394 | 30.64% | 4.02 | 17.34 | 1.26 | 27.82 |
| [10^2, 10^3) | 293 | 22.78% | 15.57 | 140.28 | 3.45 | 32.49 |
| [10^3, 10^4) | 153 | 11.90% | 138.18 | 2,952.82 | 19.90 | 116.03 |
| [10^4, 10^5) | 73 | 5.68% | 1,665.44 | 17,934.63 | 105.93 | 442.01 |
| [10^5, 10^6) | 11 | 0.86% | 3,581.94 | 65,534.51 | 305.69 | 1,645.53 |

Update cost depends on incoming nodes, available moves, filtering strength and historical-path filtering. A small output can follow a large input, so output history count alone cannot predict runtime.

## Decision-turn observations only


| Size range | Updates | Empirical frequency | Median ms | P95 ms | Mean owned MiB | Max owned MiB |
| --- | --- | --- | --- | --- | --- | --- |
| [10^0, 10^1) | 146 | 23.06% | 2.53 | 5.75 | 1.13 | 27.59 |
| [10^1, 10^2) | 197 | 31.12% | 3.91 | 22.71 | 1.33 | 27.61 |
| [10^2, 10^3) | 154 | 24.33% | 15.53 | 154.85 | 3.16 | 53.56 |
| [10^3, 10^4) | 87 | 13.74% | 148.50 | 2,846.48 | 14.71 | 79.14 |
| [10^4, 10^5) | 39 | 6.16% | 2,136.69 | 6,182.39 | 83.38 | 363.64 |
| [10^5, 10^6) | 10 | 1.58% | 15,177.78 | 75,478.81 | 438.54 | 1,645.53 |

## Interpretation and limits


Each frequency is the number of updates in its bin divided by the table's total update count. These are empirical frequencies for preselected games 0-9 under their particular policies. Longer games contribute more observations, and adjacent observations are correlated. They are not universal probabilities for FoW positions. JSON also includes means, maximum times and decision-turn history-size frequencies. Interrupted development pilots are excluded.

Raw traces are in game-*.jsonl; merged per-update data are in updates.jsonl. summary.json records seeds, source/game hashes, budgets and all statistics.
