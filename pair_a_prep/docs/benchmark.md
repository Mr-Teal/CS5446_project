# Stockfish measurement method and pilot

Measured 17 October 2026 using the official [Stockfish 19 release](https://github.com/official-stockfish/Stockfish/releases/tag/sf_19).
This measures raw orthodox-board UCI calls, independently of Pair B's
evaluator, score conversion and labels. The source corpus is
[`benchmark_positions.json`](../data/benchmark_positions.json): four opening
positions and two endgames. Six positions cannot represent all FoW frontiers.

## Local results

Raw records: [`stockfish19_pilot.jsonl`](../results/stockfish19_pilot.jsonl).
Each row includes the root FEN, score viewpoint, returned moves and raw cp/mate
scores. The file starts with machine/engine/configuration metadata and ends
with a summary. There were 72 successful calls, no failed calls.

| Requested depth | MultiPV mode | Calls | Median wall ms | Mean wall ms | p95 wall ms |
|---|---|---:|---:|---:|---:|
| 1 | Best move only | 18 | 6.669 | 6.713 | 7.276 |
| 1 | All legal moves | 18 | 8.696 | 8.981 | 11.886 |
| 11 | Best move only | 18 | 25.393 | 24.771 | 48.318 |
| 11 | All legal moves | 18 | 552.815 | 552.644 | 1102.640 |

The p95 uses the nearest-rank convention across this small combined sample.
These are timing observations, not uncertainty intervals or independent
performance estimates. The repetition count is three per position/condition.
Do not reuse the proposal's 243 ms or 0.5 ms as measurements of this host.

## Reproducibility settings

- Engine identifies itself as Stockfish 19; Threads=1, Hash=16 MiB.
- Official archive: `stockfish-windows-x86-64-universal.zip`, tag `sf_19`.
- Archive SHA-256: `3c8bf1f9ea66a09350a40df4f632288285ac206d99f33ab5842c408fc30b48a7`.
- Executable SHA-256: `45bc8e4969147db9c2eb533810637994619bff0eacc81ccfd9854394901bcbd0`.
- Python 3.9.12; chess module 1.11.2; Windows 10 build 19045.
- Host reports 16 logical CPUs. Raw metadata records the CPU identifier.
- Jobs are shuffled with seed 17. The transposition hash is cleared before
  each trial; other process state can persist.
- An untimed depth-1 warmup occurs after process startup. Startup took about
  458 ms in this run and is not included in trial wall times.
- Trial wall times cover `engine.analyse` and its UCI overhead, including the
  new-game notification. Hash clearing, FEN construction and validation occur
  before the timer. A 30-second per-command engine timeout is configured.
- `all` requests as many MultiPV lines as ordinary legal moves. Distinct root
  move coverage is checked. `best` requests one line. Engine-reported times,
  nodes, NPS, hashfull and actual depths are retained separately.

The script leaves Stockfish's other options at that build's defaults; the
executable hash is therefore part of the run identity. No tablebase path is
configured by this tool. It does not measure peak memory or GPU latency.

## Running another measurement

From the project root in the documented environment:

```powershell
python -m pair_a_prep.benchmark_stockfish --engine "C:/path/to/stockfish.exe" --output pair_a_prep/results/new_run.jsonl --depths 1 11 --modes best all --repeats 3 --threads 1 --hash-mb 16 --seed 17
```

Choose a new output filename; the script deliberately refuses to overwrite.
It parses and checks every corpus position before starting the engine.
Malformed, finished and orthodox-invalid positions are rejected, including
positions where the nonmoving king is capturable. This corpus deliberately
does not exercise Stockfish's behavior on FoW-only states.

Raw centipawns refer to the player to move at the root. A mate result retains
its signed distance. No tanh conversion or FoW win interpretation is applied.
The tool is neither an implementation of `LeafEvaluator` nor a data generator
for Pair B's `TrainingRecord`.

Before budgeting a long teacher run, repeat on actual safe leaf samples from
the replicated search and measure tracker/search/evaluation components
separately. Do not multiply this small corpus mean by an assumed expansion
count to promise a label completion date.
