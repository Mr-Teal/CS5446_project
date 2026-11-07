# Network 1 in Pair A search

`pairb.search_factory:Factory` loads the existing Network 1 checkpoint into the
same Pair A fixed, anytime, retained or subgame search used by Material and
Stockfish leaves. It does not construct Pair B's one-ply bot. Pair A's
`SearchFactory.load_leaf()` is the small extension point; search validation,
configuration identity, agent construction, per-game resets and cleanup stay in
the existing factory. No new model or training data is required.

Use `leaf_evaluator = network1`, `leaf_depth = 1`, a concrete `checkpoint_path`
and optionally `checkpoint_sha256`. Relative paths resolve against the project
root. `device` accepts the existing CPU/MPS/CUDA options. The engine uses the
same validated Stockfish options as the baseline, including executable hash and
UCI-name checks when supplied. Network 1 shares that one owned depth-1 engine;
it resets between games and closes when the agent closes. Material/Stockfish
configurations do not import torch.

Both loaded checkpoint and engine hashes, effective device and UCI identity
are exposed to Pair C's existing provenance collector. The agent's config ID
also includes checkpoint hash, device and engine settings. A malformed model
or failed agent construction closes the engine rather than leaking a process.

## Run the integration smoke

In the project's existing torch-enabled environment, install the local project
and Pair B as usual. Ensure Stockfish is on PATH, or edit `stockfish_path` in
both player sections of `pair_b/configs/network1-search-smoke.ini`. Then, from
the repository root:

```sh
python pair_c/run_evaluation.py pair_b/configs/network1-search-smoke.ini
```

The output directory must be fresh. The example uses the already committed
Network 1 weights, pinned by SHA256. Both players use identical fixed depth-2
search, solver rounds, rules, exact tracker and engine settings; their leaf
evaluators differ. It attempts two colour-swapped four-ply games on an explicit
public pawn fixture. `provenance.json`, copied config, `games.jsonl`,
`tracker_updates.jsonl` and `summary.json` are the handoff artifacts.

This is an integration check, not a playing-strength experiment. Capped
attempts remain unscored. Inspect failures, fallbacks, evaluator calls and
tracker work; successful exit alone does not establish full-game readiness.

## Final evaluation ownership and limits

The evaluation owner can use this factory with a separately frozen experiment
config. Agree opponent/rows, source, engine/checkpoint, seeds/colours, tracker
policy, clock scope, hardware, attempt accounting and results cutoff before
running a report batch. Keep actual records and analysis accessible for review.
This handoff does not assign another batch to Colin or Bryan, replace the
archived seven-row one-ply experiment, or import author-reported PR66/67 scores.

The search calls `evaluate_children(fen)`: it is boardwise Network 1 leaf
evaluation, not a whole-belief learned strategy. It uses reviewed main search,
not pending PR65-67 or solver-label changes. Main's exact tracker still has
documented long-history resource limits, and search clocks do not include
tracking. The smoke's depth/node limits may also cause explicit fallback on
larger games. A new full-agent result must identify its own actual config and
source. Issue20 Option B remains valid; this implementation does not reopen
solver-label training, strategic information-sensitive learning or ReBeL.
