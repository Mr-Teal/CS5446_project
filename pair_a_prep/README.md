# Independent Pair A preparation

The opt-in [integrated chess subgame prototype](docs/chess_subgame_integration.md)
now connects sampled-tree knowledge projection, gadget boundaries, growth,
warm starts and purification. [Richer-position verification](docs/subgame_position_validation.md)
records special-rule positions and short private-observation games; it is not
playing-strength evidence or a claim of complete Obscuro reproduction.

The optional [serial one-sided search mode](docs/one_sided_search.md) now
selects individual history frontiers and retains within-turn PCFR+ state.
Its engineering evidence and updated slide materials are reproducible; it is
not yet a complete Obscuro agent or a strength-tested teacher.

This directory contains preparation tools, a rules adapter prototype, and an
exact history-preserving belief tracker with optional output sampling.
The standalone preparation tools run independently of `fow_shared`; the new
adapter reuses the merged shared rule helpers. Shared interfaces and the encoder
are unchanged; #15/#28 updates shared no-move terminal-draw semantics used by
Pair B, including stand-in rules/evaluators. Agent ownership is agreed: the rules
adapter and Obscuro belong to one Pair A member; ZS21 and the belief tracker
belong to the other, with mutual review. The 2021 ZS21 reproduction and matched
baseline are now in [zs21](zs21/README.md), with a
[portable runtime and integration guide](../zs21_runtime/README.md).
The independent Obscuro work remains as described below. See
[the PR handoff](docs/pr_handoff.md) for the earlier preparation scope.

A runnable fixed-depth chess search now connects candidate histories, PCFR+
and the evaluator plug. It can produce small validated TrainingRecord pilots;
see [chess search and label pilot](docs/chess_search.md). It does not yet
implement the paper's full Obscuro search or generate production teacher data.

An optional [incremental chess tree API](docs/chess_tree_growth.md) expands
retained frontier histories between solver rounds while preserving PCFR+
state. It leaves the default agent and shared interfaces unchanged.
The [gadget bridge](docs/chess_gadgets.md#incremental-gadget-growth) supports
the same growth with Resolve/Maxmargin paths, keys and payoff offsets preserved.

For the Pair C per-player factory interface, see the
[bounded integration handoff](docs/pair_c_handoff.md). Its Material-only config
uses real path-preserving trackers and rejects inconsistent public starts/rules.

The optional [budgeted uniform-growth agent](docs/anytime_search.md) now
alternates solving and expansion, preserves the old tree after failed growth,
and provides an observation-only action fallback if initial preparation exceeds
a budget. See [the Obscuro status map](docs/obscuro_status.md) for remaining
paper mechanisms and [budget probes](docs/budget_experiments.md) for measured
costs and short-game integration limits.

For draft slides 4-5, open [the local material viewer](presentation/index.html).
The [material guide](presentation/README.md) includes SVG export and evidence
regeneration; [the expansion audit](docs/expansion_mechanism_audit.md) separates
the paper's one-sided leaf selection from our uniform complete-cut baseline.

| Work | File | Contents |
|---|---|---|
| Chessboard viewer | [launch instructions](docs/board_viewer.md), [server](board_viewer.py) | Click-to-move chessboard, both fog perspectives, sample games and step-by-step replay using the rules adapter |
| Pair A interface draft | [interface_draft.py](interface_draft.py), [interface_draft.md](docs/interface_draft.md) | Proposed rules/tracker signatures, private observation fields and update sequence; pending review |
| Rules adapter and referee | [rules_adapter.py](rules_adapter.py) | History-preserving states, private observations, actual terminal outcomes and shared-protocol referee; see [implementation notes](docs/rules_adapter.md) |
| Belief tracker | [belief_tracker.py](belief_tracker.py), [implementation and usage](docs/belief_tracker.md) | Exact observation-only history tracking, optional output sampling, explicit capacity errors, and shared-runner integration |
| Chess search prototype | [chess_search.py](chess_search.py), [search_agent.py](search_agent.py) | Candidate replay, private-history information sets, fixed-depth PCFR+ and per-root continuation values |
| Chess gadget bridge | [chess_gadgets.py](chess_gadgets.py), [usage and semantics](docs/chess_gadgets.md) | Opponent root groups, explicit Resolve/Maxmargin inputs, shared policies and unshifted continuation labels |
| Label pilot | [label_pilot.py](label_pilot.py), [usage and limits](docs/chess_search.md) | Shared-runner games, JSONL export, repeated-run checks, tracker diagnostics and Pair B label acceptance |
| Paper implementation specifications | [paper_specs.md](docs/paper_specs.md) | Pinned v2 sources, parameters, section references, implementation checks and open questions |
| Small-game validation | [toy_games.py](toy_games.py) | Information sets, chance nodes, LP reference solutions and behavioral best-response/Nash-gap checks |
| PCFR+ with incremental toy-tree expansion | [pcfr.py](pcfr.py), [algorithm notes](docs/pcfr.md), [expansion handoff](docs/incremental_tree_handoff.md) | Predictive RM+, explicit cutoff-leaf expansion preserving solver state, and separate last/average diagnostics; simultaneous and alternating schedules |
| Fixed-tree gadgets | [gadgets.py](gadgets.py), [gadget notes](docs/gadgets.md) | Resolve enter/exit, Maxmargin offsets, hidden-root grouping and separate continuation label values |
| Knowledge restriction | [knowledge.py](knowledge.py), [notes](docs/knowledge.md) | Explicit synchronized-cut knowledge graph, I^2 restriction, frozen KLSS control and unfrozen KLUSS |
| Interactive toy explorer | [open HTML](results/toy_explorer.html), [generator](toy_visualizer.py) | Recorded PCFR+ checkpoints, tree/action probabilities, shared information sets and convergence charts; fully offline |
| Stockfish measurements | [benchmark_stockfish.py](benchmark_stockfish.py) | Fixed positions, depths 1 and 11, best-move/all-move MultiPV, raw scores and timings |
| Rules fixtures | [rules_cases.json](data/rules_cases.json), [fixtures.py](fixtures.py) | 17 special positions and acceptance checks for the implemented adapter |
| Reproduction differences | [reproduction_differences.md](docs/reproduction_differences.md) | Published settings, proposed choices, measurements and unresolved decisions |
| Verification results | [verification.md](docs/verification.md) | Test coverage, real engine runs, limitations and integration steps |

All comments, docstrings and documentation in this directory must be written
in English so teammates can read and maintain them.

## Open the chessboard viewer

For first-time setup, including fetching the branch and installing dependencies,
see [the teammate launch guide](docs/board_viewer.md#first-time-setup-for-teammates).
After setup, run from the repository root:

```powershell
pair_a_prep/.venv/Scripts/python -m pair_a_prep.board_viewer
```

Keep the terminal running and open **http://127.0.0.1:8766/** in a browser.
Each teammate must start the viewer on their own computer; this loopback
address does not connect to another teammate's server. Open the URL, not the
HTML asset or a VS Code preview. Ctrl+C stops the server.

## Setup and execution

From the project root, create a separate virtual environment. These commands
require the merged shared rule helpers for the adapter tests:

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

The PCFR+ (fixed-tree and incremental), gadget and synchronized-cut knowledge restriction tests
build on these examples. They do not establish correctness of a complete
chess search or general history-based KLUSS construction.

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
python -m pair_a_prep.fixtures --adapter pair_a_prep.rules_adapter:fixture_result
```

Only expectations listed in each fixture are checked, so more assertions
can be added as the adapter develops. Cases containing `initial_fen` and
`moves_uci` must replay the history rather than load only the final FEN.
Running without `--adapter` validates fixture structure and history only;
it does not establish that a FoW rules implementation passes the cases.

### Actual transition diagnostics

[Cross-turn reach/state audit](docs/transition_audit.md) records real private projections, checks candidate-path identities and distinguishes current CF reach ratios from cumulative solver-state conversion. Run `python -m pair_a_prep.transition_probe --output pair_a_prep/local_runs/transition-audit.json`. This offline diagnostic does not change agent decisions or authorize exact warm-state transfer.
