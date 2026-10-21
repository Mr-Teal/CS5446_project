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

Prepared with Codex assistance. See [the runner guide](match_experiment.md) for reproduction and interpretation.
