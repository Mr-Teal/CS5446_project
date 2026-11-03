# Paired tracker comparison

Games 0-9, first 6 plies, both private streams, three independent runs per implementation in alternating order. Time, memory and internal history limits were None; the returned sample was 16. History counts matched at every step. Entries are medians across repetitions.

| Game | Reference ms | Graph ms | Speedup | Reference owned MiB | Graph owned MiB |
| --- | --- | --- | --- | --- | --- |
| 0 | 1902.16 | 48.67 | 39.08 | 0.876 | 0.417 |
| 1 | 895.68 | 55.40 | 16.17 | 1.685 | 0.561 |
| 2 | 2526.46 | 50.85 | 49.68 | 0.648 | 0.342 |
| 3 | 5156.50 | 173.12 | 29.79 | 9.228 | 2.707 |
| 4 | 1014.63 | 47.53 | 21.35 | 1.697 | 0.515 |
| 5 | 240.11 | 13.24 | 18.14 | 0.046 | 0.045 |
| 6 | 1006.40 | 46.74 | 21.53 | 1.697 | 0.515 |
| 7 | 5635.65 | 180.65 | 31.20 | 9.228 | 2.707 |
| 8 | 725.27 | 27.82 | 26.07 | 0.535 | 0.342 |
| 9 | 5667.96 | 238.25 | 23.79 | 9.228 | 2.707 |

Aggregate update-time ratio: **28.08x** for these prefixes. This is not a full-game speedup guarantee. Owned memory measures retained Python objects, not RSS.

Full-game measurements: [report](../full-games/report.md). Raw repeated trials are archived in [trials.jsonl.gz](trials.jsonl.gz); each record identifies its original trace and hash.
