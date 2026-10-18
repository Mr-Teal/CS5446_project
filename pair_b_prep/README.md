# Pair B evaluator validation

Standalone local preparation for Colin's Network 1 and later belief evaluator.
No training or engine installations are performed by this tool. Python 3.10+
standard library is sufficient for the demo.

## Run now

From the repository root:

```sh
python3 -m pair_b_prep.harness
python3 -m unittest pair_b_prep.test_harness -v
python3 -m pytest tests pair_b_prep -q
```

Outputs in `pair_b_prep/results/demo/`:

- `report.json`: checks, configuration, platform and fixture/harness hashes.
- `samples.jsonl`: every timed call, child count, values and move ranking.
- `summary.csv`: per-position median/min/max milliseconds.

**The dummy uses fixture answers: it only demonstrates plumbing.** Passing does
not validate Stockfish, a network, chess strength or useful inference latency.
Never report dummy timings as model results. Fault-injection tests verify that
common integration errors are detected.

## Connect Colin's code

Complete `adapter_example.py` with his actual model constructor. It deliberately
raises until implemented; there is no silent fallback. Use the shared fow_shared
package and model dependencies in the real evaluator's environment.

```sh
python3 -m pair_b_prep.harness --adapter pair_b_prep.adapter_example:build --config model_config.json --out pair_b_prep/results/network1 --repeats 30 --warmups 3
```

The config JSON contains the options your adapter needs (checkpoint/engine paths,
etc.) and is copied into the report. Do not include secrets. A factory receives
this dictionary and returns a bundle with:

- `evaluator`: name and the three merged LeafEvaluator methods.
- `make_turn(spec)`: builds genuine shared AgentInput/Belief/Observation/Hypothesis
  objects from the probe specification. The demo uses structural stand-ins only.
- `metadata`: checkpoint hash, evaluator commit, encoder version, engine build and
  settings, device, and caching policy. Set demo_only to false for real adapters.
- Optional `synchronize()`: synchronize GPU work before/after timed inference.
- Optional `before_sample()`: reset caches/engine if required, outside timing.
- Optional `close()`: release engines/resources even after a failure.

An adapter elsewhere must be importable, e.g. by setting PYTHONPATH. Use a distinct
output directory per run: existing report files in that directory are replaced.
Failed checks return exit code 1 and skip timing. Manual checks remain explicit
and do not block the smoke benchmark. Factory/load errors are visible exceptions.

## What is checked

- Finite [-1,1] scores and opposite named White/Black perspectives.
- Child scores use the parent mover's perspective, not the child side to move.
- Exact move sets where fixtures contain `moves`; partial required-move checks
  where they contain `required_moves`. Partial cases are not full legality tests.
- Missing kings, available king capture, terminal fifty-move draws, and draws
  reached before capture. The castling escape tests availability, not learned value.
- Board batch ordering and single/batch consistency.
- Belief grouping, hypothesis order, unknown observation clock, input mutation,
  output count, optional policy coverage and probability normalization.

The belief probes use hypothesis clocks 10 and 30 and observation clock None.
They are constructed API probes, not claims about reachable observation histories.
Default numerical tolerance is 1e-6. Engine hash reuse or stochastic inference may
require deterministic configuration or a justified tolerance. Investigate rather
than widening tolerance to hide sign, order or rule mistakes.

## Manual integration checks still required

1. Inspect the real encoder: separate clocks must encode as 0.1 and 0.3, using the
   merged plane layout and vertical Black mirror. Model outputs need not differ
   simply because the clock differs. Reuse shared encoder regression tests.
2. Audit referee/hidden-state data flow. A black-box harness cannot prove that
   an evaluator never reads hidden globals or other private data.
3. Run repetition tests using complete board histories in the shared rules layer.
   FEN-only calls cannot carry repetition history.
4. Validate full legality and visibility with Pair A's agreed rules fixtures.
5. Check the checkpoint's training assumptions: parent MultiPV versus child
   evaluation, engine depth/settings, score perspective and exact preprocessing.
6. If Network 1's belief method ignores belief context and scores boards separately,
   document that explicitly. Missing methods must not be presented as validated.

## Benchmark limits

Timing encloses evaluate_children, including shallow Stockfish, encoding and
inference if the real adapter performs them there. Startup, validation and
before_sample are excluded. Asynchronous GPU adapters need the synchronization
hook. Repeated warmed-up positions may hit caches; disable or disclose caching.
Later add an uncached representative game-position benchmark. These seven small
contract fixtures cannot establish practical throughput or playing strength.

Rankings sort descending parent-perspective score with lexicographic tie-breaks;
raw values are saved to allow tie-aware comparisons. No teacher-error or win-rate
claim is computed here. Those require real evaluator outputs, a game-split dataset
and match experiments. Compare all models under identical settings and reserve
final test games from tuning. A tanh score is not automatically a win probability.

## Source and handoff

Based on PR #1 inspected read-only in this conversation:
https://github.com/Mr-Teal/CS5446_project/pull/1
Merged commit: a8458d86462613f2486094da7d99f20e3757bb91 (18 October 2026).
This tool is not a vendored copy or replacement for fow_shared.

The adapter also supports the required `Observation.side_to_move` in PR #2
(`pair-b/interface-item-4`, inspected at
`a5b89dd65fb2e7622126713caec49aca3eafa7f0`). It sets this to the acting player,
not ply parity, and omits the keyword only for the older main contract. Both
contracts use schema v1, so compatibility is detected from dataclass fields.
All 11 preparation tests pass against main and separately against PR #2's actual
`contracts.py`, read from GitHub into an isolated temporary package. This checks
contract compatibility, including Black at an even ply; it is not a full branch,
runner, engine or trained-model integration test. No shared files are changed.

When Colin's artifacts arrive: implement the adapter, record provenance, run and
investigate the checks, finish manual validation, and benchmark real evaluators
outside results/demo. Hand Pair A the evaluator, checkpoint/config and real report.
Ask Pair A for a small genuine TrainingRecord, exact target semantics, and a date
for a full game accepting an evaluator. No message has been sent.

The root pytest configuration discovers only tests/. Use the explicit command above
to include pair_b_prep without changing project-wide configuration. Generated
results are ignored within this folder.

Prepared with Codex assistance; real-model integration remains pending.
