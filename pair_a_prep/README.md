# Independent Pair A preparation

This directory contains preparation tools that run independently of
`fow_shared` and Pair B's PR. The preparation work added files only under
`pair_a_prep/`; it did not change the existing shared interfaces, encoder,
root README or dependencies. Neither ZS21 nor Obscuro is implemented here,
and agent ownership, team settings and delivery dates remain to be agreed.

| Work | File | Contents |
|---|---|---|
| Paper implementation specifications | [paper_specs.md](docs/paper_specs.md) | Pinned v2 sources, parameters, section references, implementation checks and open questions |
| Small-game validation | [toy_games.py](toy_games.py) | Information sets, chance nodes, LP reference solutions and behavioral best-response/Nash-gap checks |
| Stockfish measurements | [benchmark_stockfish.py](benchmark_stockfish.py) | Fixed positions, depths 1 and 11, best-move/all-move MultiPV, raw scores and timings |
| Rules fixtures | [rules_cases.json](data/rules_cases.json), [fixtures.py](fixtures.py) | 17 special positions and acceptance checks for a future adapter |
| Reproduction differences | [reproduction_differences.md](docs/reproduction_differences.md) | Published settings, proposed choices, measurements and unresolved decisions |
| Verification results | [verification.md](docs/verification.md) | Test coverage, real engine runs, limitations and integration steps |

All comments, docstrings and documentation in this directory must be written
in English so teammates can read and maintain them.

## Setup and execution

From the project root, create a separate virtual environment. These commands
do not require Pair B's PR to be merged:

```powershell
python -m venv pair_a_prep/.venv
pair_a_prep/.venv/Scripts/python -m pip install -r pair_a_prep/requirements.txt
pair_a_prep/.venv/Scripts/python -m pytest -q pair_a_prep/tests tests
```

Generate small-game reference results and validate the rules fixture definitions:

```powershell
pair_a_prep/.venv/Scripts/python -m pair_a_prep.toy_games --output pair_a_prep/results/toy_new.json
pair_a_prep/.venv/Scripts/python -m pair_a_prep.fixtures
```

For engine measurements, point `--engine` to your Stockfish executable and
choose a new output filename:

```powershell
pair_a_prep/.venv/Scripts/python -m pair_a_prep.benchmark_stockfish --engine "C:/path/to/stockfish.exe" --output pair_a_prep/results/stockfish_new.jsonl
```

See [benchmark.md](docs/benchmark.md) for measurement settings and the output
format. The benchmark script refuses to overwrite existing measurements.
The Stockfish binary is not included in the repository; the recorded pilot
used an official release downloaded to a temporary directory.

## Using the small games to validate either agent

`Node` identifies decision information through `player` and `infoset`;
chance nodes carry probabilities. A pure strategy selects one action per
information set, so indistinguishable hidden nodes must share that action.
The tool enumerates both players' pure strategies, constructs a payoff
matrix and solves two LPs to obtain strategies and best-response bounds.
This is a small-game reference solver and does not scale directly to chess.

The current examples include matching pennies with hidden or revealed
actions, hidden or revealed coin guessing, and Kuhn poker.
`behavioral_nash_gap(root, policies)` checks a future solver's behavioral
strategies. Each player's policy uses the format
`{infoset: {action: probability}}`. Converting an LP solution over pure
strategies into a behavioral strategy requires conditional reach
probabilities; simply averaging actions independently at each information
set is not generally equivalent.

These examples do not yet validate KLSS/KLUSS gadget construction or
implement PCFR+.

## Connecting a future rules adapter to the fixtures

Provide a callable identified by `module:function`. It receives the complete
fixture dictionary and returns a mapping with this structure:

```python
{
    "legal_moves": ["e1g1"],
    "visible_squares": ["e1", "f1", "g1"],
    "visible_pieces": {"e1": "K", "f1": None, "g1": None},
    "terminal": False,
    "winner": None,
    # Hidden observation fields should be omitted or None.
}
```

The example above illustrates the return format, not a complete correct
observation for a particular fixture. Run the adapter checks with:

```powershell
python -m pair_a_prep.fixtures --adapter your_adapter:inspect_case
```

Only expectations listed in each fixture are checked, so more assertions
can be added as the adapter develops. Cases containing `initial_fen` and
`moves_uci` must replay the history rather than load only the final FEN.
Running without `--adapter` validates fixture structure and history only;
it does not establish that a FoW rules implementation passes the cases.
