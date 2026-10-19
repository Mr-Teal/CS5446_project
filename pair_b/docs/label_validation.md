# Check a solver-label handoff

From the repository root, using Python 3.12+ with the shared project's dependencies
(`python -m pip install -e .`; NumPy and python-chess):

```sh
python pair_b/scripts/validate_labels.py path/to/label-run
python pair_b/scripts/validate_labels.py path/to/labels.jsonl
python pair_b/scripts/validate_labels.py path/to/label-run --pattern '*.jsonl' --require-d1
python pair_b/scripts/validate_labels.py path/to/label-run --splits path/to/training-run/splits.json
```

There is no need to install the Pair B package with its PyTorch dependency. The
command uses its source modules, starts no Stockfish process and writes no data
or training caches. It processes one belief at a time. Source imports may create
normal Python bytecode caches; use `python -B` to suppress those too.

Exit status is 0 when there are no errors, 1 on validation failure, and 2 for
invalid command arguments. Warnings do not fail the run. Example:

```text
WARNING path/to/label-run/manifest.json: absent; accepted by the training loader
PASS: 12 parsed records, 2 files, 3 games (train=2, val=1, test=0); 0 errors, 1 warnings
```

Errors include the source path and, for record checks, physical line number:

```text
ERROR path/to/label-run/part-000.jsonl:4: root_value: 0.5 differs from weighted hypothesis values 0.25 by more than 1e-06
```

## Acceptance rules

The [label definitions](label_definitions.md) specify the handoff. The command
reuses `fow_shared.recording.read_records` and the shared dataclass validation:
value count/range, normalized positive hypothesis weights, distinct position/history
pairs, legal raw policies, legal played moves and observation/history consistency.
An invalid JSON/schema record stops that file; remaining selected files are checked.
The summary counts successfully parsed records, including ones with additional
acceptance errors, and must not be read as a count of valid records.

Additional checks:

- `game_id`, `agent_name` and `config_id` must be nonblank strings.
- `root_value` must equal the belief-weighted hypothesis values within absolute
  tolerance `1e-6`, using original record numbers, before float32 conversion.
- Every record must pass the same shared encoder and current opponent-visibility
  callback as `pairb.belief_data`. FEN parsing, acting side and observed-piece
  consistency are checked. No standard-chess `Board.is_valid()` restriction is
  added: these are fog-of-war hypotheses.
- When any `played_policy:<uci>` diagnostics are present, they must cover exactly
  the legal moves, contain probabilities in `[0,1]` summing to one within `1e-6`,
  and assign positive probability to the played move. Complete absence produces
  one aggregate warning: PR5 requests them, but existing practice exports and
  the training loader do not require them.
- Supplied `d1:<i>` entries must name canonical zero-based hypothesis indices
  and contain finite values in `[-1,1]`. `--require-d1` additionally requires a
  value for every board not decided by `fow_shared.values.rule_score`, matching
  the loader's FEN-based rule check. No D1 is required otherwise. A FEN alone
  cannot establish threefold repetition history.

Folders select `part-*.jsonl` by default. Empty files and blank lines are accepted;
an entirely empty selection fails. `population_size=None`, arbitrary positive
sample sizes, and equal FENs with different `history_id` values remain accepted.

A missing manifest or missing recommended manifest fields is a warning. A supplied
manifest must be valid JSON with an object at its root; a supplied `config_id`
must match the selected records. A supplied nonnegative integer `records` count
is compared only for the default whole-folder selection, and only when no record
errors occurred. For a single file or custom pattern, the comparison is skipped
with a warning because the selection may be a subset of the run. Use the default
part filenames when you want the whole-run count check.

The summary reports **game counts** under the existing SHA1 `split_of` mapping
(buckets 0–7 train, 8 val, 9 test). With `--splits`, train/val lists from the training
script's `splits.json` must contain known, unique, nonoverlapping game IDs in their
correct hash buckets. An optional `test` list is checked the same way. If supplied,
`test_held_out_games` must match the selected data. Train/val lists need not be
exhaustive: the file records games actually used by training. The current training
script records only a test-game count, so an absent test list is explicitly warned
about. Supply the full training dataset, not a subset, for this comparison.

## What still needs the pilot

A passing report establishes structural and numerical consistency. Pair A must
still demonstrate that hypothesis values come from the final raw solver strategy,
exclude gadget opt-outs, preserve the correct root/history mapping and use the
acting-player perspective. Solver correctness and absence of hidden-information
leakage require integration evidence. Config contents, repeat-run reproducibility,
time/memory limits and restart recovery are separate pilot checks; this command
does not claim to verify them. The label-definition proposals remain proposals.

Implementation and tests were prepared with Codex assistance.
