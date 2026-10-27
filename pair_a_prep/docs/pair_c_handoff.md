# Bounded Pair A handoff to Pair C

This supplies the factories/configuration needed to use the per-player hooks
in PR26. It does not merge that PR or make a full-game strength claim.

## Files

- `evaluation_factories.py`: independent Material search agents and fresh exact
  history trackers, with per-game lifecycle and optional resource cleanup.
- `data/pair_c_smoke.ini`: two colour-swapped six-ply games, uniform growth
  against fixed depth 1. Both use Material; no engine, checkpoint or GPU.

From a checkout containing both PR26 and this handoff, run at the repository
root (choose a fresh output directory in the INI for every run):

```powershell
.\pair_b\.venv\Scripts\python.exe pair_c/run_evaluation.py pair_a_prep/data/pair_c_smoke.ini
```

The factories do not import `pair_c`, so existing Pair A tests/imports work
before PR26 merges. Only the CLI command above requires the Pair C runner.

## Input boundary and limits

Both players' `public_initial_fen` must equal the match-level `initial_fen`.
The tracker factory validates this before play, and requires `rules=teal` so
the referee's capture notices match the exact tracker's observation semantics.
It creates new trackers for each game; factories follow player identities
when colours swap. Candidate paths are complete, as required by the search.

Material's `leaf_depth` is **0**. Search depth is a separate option:
`search_depth` for fixed search, or `initial_depth`/`max_depth` for growth.
`solver_rounds`, node/evaluator limits and `stop_on_time` control work. The
example disables the clock for reproducibility; 1000ms is diagnostic only.

The exact internal tracker still has an explicit capacity limit. Sampling
only bounds returned hypotheses, not internal enumeration. This example is
deliberately short and small. Do not use it as the formal Pair B batch config.

## Independent PR26 re-review

At original head **869870ded16a7cec9886d5eb803d2bcaae2c3778**:

- The author's four regression tests passed in a snapshot with unchanged
  original Pair C files.
- Additional fresh-process probes confirmed Material loads with torch blocked;
  direct and both nested network Stockfish reset paths each called `new_game`
  twice. These use lightweight scorer doubles, not actual engine/checkpoints.
- Two six-ply games with the real Pair A search agents and exact trackers
  completed without errors, with A playing White then Black. This validates
  complete path compatibility through later turns, not playing strength.
- All 11 original Pair C files were verified unchanged against the PR archive.
  Pair A and the shared-rule implementation were supplied as integration
  dependencies, and shared/Pair B imports resolved inside the snapshot.

Two remaining issues were reproduced:

1. Two games capped after one ply produced `draws=2`, score rate 0.5, although
   neither game reached a terminal outcome. Six-ply smoke games were likewise
   reported as draws. Separate capped attempts from observed terminal outcomes
   before using outcome rates.
2. `scorer_id=stockfish-d11` with `leaf_depth=1` constructs depth 11, silently
   disagreeing with metadata. The factory can reject known scorer/depth
   mismatches locally; no Pair B API change is required for that validation.

The independent `pair-a/pr26-review-fixes` branch (8aad65c) addresses both:

- Counts `games_scored`/`games_capped` separately, stores capped winners as null,
  and excludes caps from outcome rates while retaining their timing.
- Validates built-in scorer/depth agreement before loading resources, without
  changing Pair B's API. Also fixes the reset-test command in the test README.
- All 13 Pair C regressions pass (including the original four). The real Pair A
  smoke was repeated against that fixed candidate: two capped six-ply attempts,
  zero failures, zero scored games/draws, and unavailable outcome rates. Moves
  match the original runner's smoke exactly.

These are proposed follow-up changes, not changes to the author's PR26 branch.
Until they are integrated, use `games.jsonl.stopped_at_ply_limit` and exclude
those records when interpreting smoke outcomes. Local raw reports remain
under ignored `pair_a_prep/local_runs/`; the compact evidence is in
`results/evaluation_handoff_reference.json`.

No full Pair B suite, long-game tracker validation, actual Stockfish/network
execution, formal batch or new model training is covered by this handoff.

## Retained depth contract

The optional retained factory requires `max_depth >= 3` (default 3). A saved tree must contain a nonterminal two plies below its old root for next-turn reuse. Merely switching the supplied shallow anytime smoke config to retained mode is rejected. Reused branches are restored to `initial_depth` before solving, including mixed fresh/deep roots; normal limits still apply, so recovery can fail explicitly. The baseline anytime smoke configuration is unchanged.

Subgame mode now defaults to 1024 nodes and 48 evaluator calls, matching the richer-position validation budget. Smaller explicitly configured budgets remain possible and may fall back. `diagnostics["fallback"] == 1` identifies fallback; a reported zero search-node count alone is insufficient. Pair C should retain this flag in exported records. Projected subgame training labels remain disabled pending the complete solver-root/weight contract.
