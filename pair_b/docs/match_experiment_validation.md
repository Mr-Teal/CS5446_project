# Match experiment validation and development pilot

Validated on 21 October 2026 using Python 3.12 on an Intel Mac, CPU Network 1 and Stockfish 19.
This is a workflow pilot, not a final playing-strength comparison.

## Checks

From the repository root, with Pair B dependencies installed:

```sh
PYTHONPATH=pair_b/src:. python -m pytest \
  pair_b/tests/test_match_experiment.py pair_b/tests/test_bot.py \
  pair_b/tests/test_tracker.py pair_b/tests/test_rules.py \
  tests/test_match_loop.py -q -p no:cacheprovider
```

**114 passed, 4 skipped** in 121.05 seconds. The four skips need Pair A's rules adapter,
which is absent from main. Eight tests cover the new runner, including colour pairing,
score perspective, failures, repeatability and protection against overwriting output.
This is a selected regression run, not a full-repository or Pair A solver validation.

The eight-game smoke run (one seed, both colours, four evaluators, eight-ply cap)
was repeated in a fresh process: every move sequence matched.

## Longer pilot

Use `pair_b/experiments/pilot.json` with `seeds` changed to `[4246]` and set
`stockfish_path` for the installed engine. All other settings stay the same:
standard public start, stand-in rules, 32 particles, at most four hypotheses,
200 rebuild tries and an 80-ply cap. Each candidate plays depth-1 Stockfish
once as White and once as Black. All eight games ended by king capture; none
failed or reached the ply cap.

| Candidate | W–D–L | Total plies | Median candidate act time (ms) | Tracker rebuild events, both players |
|---|---:|---:|---:|---:|
| Material | 0–0–2 | 31 | 6.19 | 2 |
| Depth-1 Stockfish | 1–0–1 | 26 | 44.06 | 10 |
| Linear correction | 1–0–1 | 90 | 45.80 | 39 |
| Network 1 | 1–0–1 | 26 | 151.37 | 10 |

There is only **one colour pair per candidate**. These results do not establish
relative strength. Act times exclude tracker updates, and positions differ between
candidates. The budget is diagnostic only, not enforced. Tracker rebuilding weakens
historical consistency: investigate its effect before expanding the experiment.

## Provenance

The executed source base was `deb84b021ac80017f141540bb5e2b68d9f7167b7` plus this
runner. Latest main `849b64d95b74c7efb06abe622f2f6b3a8ddea1c8` changes only the Fog Lab
guide/README relative to that base. This PR applies the new files directly on latest
main. The pilot's raw records and machine-specific manifest remain local; they are
not included as portable fixtures. The following hashes identify the executed runner,
engine and checkpoints.

```json
{
  "runner_sha256": "0f55dc419a4ef106a6a832c6305433300a3465690a12181ff09da720b9361d61",
  "engine_sha256": "8eed61129d1493c5d1f2fd9323f0c54c47ac49319911fbde18c6b9c87e8b13c5",
  "checkpoint_sha256": {
    "pair_b/checkpoints/linear-v1/best.npz": "27388ccb0ec0a67d8a5984cfb2e577b911b91e811a6e26d7191436d2819a2593",
    "pair_b/checkpoints/net1-v2/best.pt": "ab470346acb5eb37947e3ab0eb43c005894ae72569ca016d7635fc2be6f9171f"
  },
  "packages": {
    "chess": "1.11.2",
    "numpy": "1.26.4",
    "torch": "2.2.2"
  }
}
```

## Windows integration of PR #14 and PR #15

Validated locally on 21 October 2026 with Python 3.12.10, Windows 11,
chess 1.11.2, NumPy 2.5.4, CPU PyTorch 2.14.1 and Stockfish 19.
This is a separate run from the historical Mac pilot above.

The source was downloaded as browser-authenticated GitHub archives:

- PR #14: `c9ee931e7d216899d49271d74b5ffb6026153658`.
- PR #15: `f28a2afed0d5a22721e5a3d83944d3fd43dbb654`.

The local integration adds PR #15's Pair A files, README and ignore file to the
PR #14 snapshot. Shared and existing Pair B Python source matched across both
snapshots. The only production-code change is using `Path.as_posix()` for
repository-relative `source_sha256` keys. The original Windows manifest test
failed before this fix and passed afterward.

### Regression results

The [runner guide's integration command](match_experiment.md#rules-integration-regression)
completed with **175 passed, 0 skipped** in 158.50 seconds. It covers the runner,
bot, tracker, shared match loop, both rules wrappers and Pair A's rules/observations.
Runner tests now exercise both explicit rules choices, verify every recorded
source hash and distinguish a fifty-move draw from a ply-limit draw.

All **17 rules fixtures passed** with the actual adapter:

```powershell
python -m pair_a_prep.fixtures --adapter pair_a_prep.rules_adapter:fixture_result
```

With only the Pair A adapter import deliberately blocked in a separate process,
the runner tests gave **9 passed, 9 explicitly skipped**. This checks that the
PR #14 tests still work before PR #15 is available; the combined run had no skips.
`python -m pip check` reported no broken requirements.

### Repeated experiments

Copy `pair_b/experiments/pilot.json`, set `rules` to `"teal"`, `seeds` to `[4246]`,
and `stockfish_path` to the installed Stockfish 19 executable. Keep CPU, the public
standard start, all four candidates, the depth-1 opponent and tracker settings
unchanged. Use an eight-ply cap for smoke checks and 80 for the development pilot.
Run each config twice, in separate Python processes and new output directories:

```powershell
python -m pairb.match_experiment --config teal-smoke.json --out teal-smoke-001
python -m pairb.match_experiment --config teal-smoke.json --out teal-smoke-002
python -m pairb.match_experiment --config teal-pilot.json --out teal-pilot-001
python -m pairb.match_experiment --config teal-pilot.json --out teal-pilot-002
```

- Smoke: eight games / four colour pairs / 64 plies per run. Every game reached
  the eight-ply cap; these draws are plumbing checks, not strength evidence.
- Pilot: eight games / four colour pairs / 173 plies per run. Every game ended by
  king capture, with no failures, incomplete pairs or ply-cap draws.
- Both repetitions had identical manifests and complete semantic game records,
  including move sequences, winners, scores, search-node counts and tracker
  diagnostics. Only `elapsed_ms`, `wall_ms` and the timing-derived `over_budget`
  fields were excluded from equality.

First 80-ply-cap run, with tracker rebuilds counted across both players:

| Candidate | W-D-L | Total plies | Median candidate act time (ms) | Tracker rebuild events |
|---|---:|---:|---:|---:|
| Material | 0-0-2 | 31 | 6.64 | 2 |
| Depth-1 Stockfish | 1-0-1 | 26 | 64.33 | 10 |
| Linear correction | 1-0-1 | 90 | 41.45 | 39 |
| Network 1 | 1-0-1 | 26 | 155.90 | 10 |

There were six act-budget overruns in the first pilot and five in its repeat,
across both players. The 1,000 ms budget is diagnostic, not enforced; act timing
excludes tracker maintenance. There is only one colour pair per evaluator.
Investigate rebuilds and implement the agreed budget policy before scaling or
making strength/equal-time claims. No training or final-test-set selection ran.
Pair A's complete solver suite, UI and full Pair B training suite were not tested.

### Local provenance and retained evidence

The Stockfish ZIP matched the SHA-256 published on the official `sf_19` release:
`3c8bf1f9ea66a09350a40df4f632288285ac206d99f33ab5842c408fc30b48a7`.

- Executed runner: `d54e3c3a9dbe1e919cb727b2c9b2e3351611ef7b822dba92a65a4a9462b77101`.
- Windows engine: `45bc8e4969147db9c2eb533810637994619bff0eacc81ccfd9854394901bcbd0`.
- Both checkpoint hashes match those in the historical provenance block above.

The local workspace retains configurations, all four run directories, test logs,
JUnit results, snapshot hashes and machine-readable reproducibility checks under
`.agent/validation` alongside the integration folder. Each run has its own
manifest, games and summary. These machine-specific outputs are not part of the
portable PR patch.

This is an archive-based integration, not a Git checkout: the runner's
`git_head` and `git_status` fields are empty. They do not certify a clean tree.
Use the pinned archive commits, retained patch and verified source hashes instead.
The validation itself did not push a branch, merge a PR or post review comments.

Prepared with Codex assistance. See [the runner guide](match_experiment.md) for reproduction and interpretation.
