# Bryan's independent match-runner cross-check

Historical run of `pairb.match_experiment` from main commit
`3afc5945dfa5a98e5a90275782b8658b69bb9bcf`, audited on 22 October 2026.
Published in response to [issue #17](https://github.com/Mr-Teal/CS5446_project/issues/17).
This is the previously completed run, not a new run on the publication commit.

## Result

Stockfish 19 depth 1 against material: **20 wins, 0 draws, 0 losses**,
10 complete colour pairs, paired score 1.0, 734 plies. All games ended in
king capture. There were no failed games, ply-cap draws or recorded agent
act-budget overruns. Tracker updates included 42 rebuilds and 163 capped
updates across both sides; these limitations are retained in the audit.

The configuration uses the public standard start, seeds 0 through 9 with
both colours, stand-in rules, 256 particles, 8 hypotheses, 2,000 rebuild
tries, a 200-ply cap and a diagnostic 60,000 ms act budget. The planner is
fixed one-ply; the budget is not an enforced equal-time comparison.

## Files and provenance

- `config.json`: original machine-specific run configuration.
- `manifest.json`: original configuration, runtime, engine hash and 51 source hashes.
- `games.jsonl`: all 20 original game records, including move and tracker diagnostics.
- `summary.json`: original runner summary.
- `audit.json`: original independent audit of records, source hashes and comparison.

These five artifacts are published unchanged. Absolute Windows paths are
historical provenance, not portable paths. The audit's statement that no
GitHub publication had occurred describes its original verification time.
Its focused test run (131 passed / 13 skipped) is historical, not rerun
for publication; the skips were for the absent Pair A adapter.

The run used a downloaded source archive, not a Git checkout. Empty
`git_head` and `git_status` in the manifest therefore do not certify a clean
checkout. The independently verified source commit is given above; the
archive SHA-256 is
`22ee6dc71087a08d68e6f3b166e2dbc183c0d0596d1d42e9efd4c535e6b9a21d`.
The engine SHA-256 is
`45bc8e4969147db9c2eb533810637994619bff0eacc81ccfd9854394901bcbd0`.

To reproduce, use that source revision and its dependencies, supply a
compatible Stockfish 19 binary, and change only `stockfish_path` in a copy
of the configuration. From that revision's repository root:

```sh
PYTHONPATH=pair_b/src:. python -m pairb.match_experiment --config <config-copy.json> --out <new-output-folder>
```

The command above uses POSIX environment syntax. On Windows, set
`PYTHONPATH` to `pair_b/src;.` before running the Python command.
The historical revision predates PR #22's wall-clock watchdog: a hung
engine can stall it. A run on newer code must record its own revision and
must not be presented as an exact rerun of this snapshot.

## Comparison and limits

[Colin's comparison](../crosscheck-d1-vs-material-standard-start/) also
recorded 20 wins and 10 complete colour pairs. This is descriptive outcome
agreement on one pairing, **not statistical equivalence**. Both runners
share the game loop, one-ply bot, tracker and referee; this is not an
independent implementation of those components.

Bryan's runner resets Stockfish before every analysis call. Colin's runner
resets before each game and retains hash state within the game. Seed
mapping, platform and engine build also differ. Compare the artifacts
side by side; **do not pool them** or combine them with the formal batch.

This single run does not establish general playing strength, equal-time
performance, neural-evaluator quality or whole-belief gameplay. No
fresh-process reproducibility repeat was performed. Tracker rebuilds
weaken historical consistency. Stand-in rules and the historical source
revision must remain explicit when citing these results.
