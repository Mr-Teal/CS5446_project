# Fixed-depth chess search and label pilot

This is a runnable integration prototype, **not a complete Obscuro or KLUSS
reproduction**. It connects the exact tracker, private histories, a fixed-depth
chess tree, the existing PCFR+ solver and the shared TrainingRecord format.

## Files and data flow

| File | Responsibility |
|---|---|
| `chess_search.py` | Replay sampled candidate histories; reconstruct both private streams; expand a full-width tree to a fixed ply depth |
| `search_agent.py` | Implement `reset/act`, solve with PCFR+, sample the raw last-iterate policy, and expose continuation labels |
| `label_pilot.py` | Run small games through the shared runner, export labels, repeat the run, and invoke Pair B's acceptance checker |
| `tests/test_chess_search.py` | Check hidden information, perfect recall, terminal history, signs, oracle agreement and export integration |

```text
public initial FEN + AgentInput (own observations, own actions, sampled paths)
  -> replay each hypothetical path with RulesAdapter
  -> construct both players' private memories
  -> chance over roots using input belief weights
  -> fixed-depth full-width chess tree with shared information sets
  -> PCFR+ raw last-iterate profile
  -> Decision and per-root continuation values
  -> TrainingRecord JSONL
```

## State reconstruction and information sets

Each hypothesis must supply `candidate_moves` from the publicly agreed initial
FEN through the current ply. `AgentInput.history` must contain the player's
snapshot after every earlier ply, with the own action attached to the snapshot
before that action. Replay checks every snapshot and known action, the current
observation, and the final hypothesis FEN. FEN-only roots are rejected.

During replay the adapter produces both players' hypothetical observations.
Each player's memory is a hash chain over their own observations and own
actions only, including off-turn snapshots and capture notices. Ordering of
square and legal-move sets is canonicalized. A node's information-set key uses
the acting player's memory, never its full FEN, hypothesis ID, root index, or
an unseen opponent action. The opponent memory is hypothetical, not a claim
that the agent knows the opponent's actual private history.

All candidate roots must match the same current private history. Their root
policy is shared. If different histories return to the same FEN, the streams
can still distinguish them; repetition also uses the replayed board's stack.
The test suite includes hidden White actions that Black cannot distinguish:
the resulting chess game is a 3x3 matrix checked with the independent LP oracle.

## Tree and values

- Player 0 is the current player, including when that player is Black.
- Chance selects a hypothesis with its supplied belief weight. This is an
  explicit sampled-root game; these are not the paper's gadget root priors.
- Every legal action is expanded to `depth` plies. No top-k action filtering,
  transposition merging or knowledge restriction is performed.
- At each parent of the frontier, call `evaluate_children(fen)` and check exact
  legal-action coverage and finite values in `[-1, 1]`. Within one tree, identical
  FEN evaluations are reused. Input estimates are from that parent mover's view,
  then converted to player 0's view.
- Actual terminal outcomes override leaf estimates using the retained history.
  Nonterminal frontier estimates use the FEN-only evaluator interface; they are
  not complete repetition-aware continuation searches.
- A blocked state without a referee result raises `UnresolvedNoMoveError`,
  including at the frontier. No new draw, loss or pass rule is introduced.

The generic evaluator plug supports `evaluate_children`, including Pair B's
Material and Stockfish leaves. It does **not** use `evaluate_beliefs`; no claim
is made that the whole-belief network context is exercised by this search.

## Agent usage

After installing Pair B and Pair A's requirements, run from the repository root:

```python
from pairb.material import MaterialEvaluator
from pair_a_prep.search_agent import FixedDepthPCFRAgent, SearchConfig

agent = FixedDepthPCFRAgent(
    MaterialEvaluator(),
    SearchConfig(depth=2, rounds=16, max_nodes=5000),
    initial_fen=public_initial_fen,
)
agent.reset(player="white", seed=17)
decision = agent.act(turn)
```

The referee and both trackers must use the same public initial FEN. Supply the
exact tracker's sampled output to keep the root count small; its internal
population still needs a separate `max_candidates` limit. The agent does not
own, update or inspect the referee or a tracker. The caller owns evaluator
lifetime and engine configuration.

`stop_on_time=True` checks the deadline during replay, construction and between
solver rounds. It cannot interrupt an evaluator call or a solver round. If tree
construction times out or exceeds `max_nodes`, it raises and publishes no
partial label. If the complete tree fits but solving runs out of time, the
current valid profile is returned, possibly with zero rounds. Timings and
overruns are recorded. This is not a hard real-time guarantee.

Each call rebuilds the tree and solver; no cross-turn strategy is retained.
`reset` clears the random stream and previous result. Raw and played policies
are identical here; the chosen move is sampled with the seeded RNG.

## Run a small label pilot on Windows

Use the existing Pair B Python 3.12 environment. Install Pair A's extra test/LP
dependencies once (the module form also works when `uv` is not on PATH):

```powershell
python -m uv pip install --python pair_b/.venv/Scripts/python.exe -r pair_a_prep/requirements.txt
```

Run a material pilot without an engine:

```powershell
.\pair_b\.venv\Scripts\python.exe -m pair_a_prep.label_pilot --out pair_a_prep/local_runs/material-pilot
```

Add D1 input features for Pair B's D1-dependent models:

```powershell
.\pair_b\.venv\Scripts\python.exe -m pair_a_prep.label_pilot --out pair_a_prep/local_runs/material-with-d1 --include-d1 --stockfish "C:/path/to/stockfish.exe"
```

Switch the search frontier evaluator itself:

```powershell
.\pair_b\.venv\Scripts\python.exe -m pair_a_prep.label_pilot --out pair_a_prep/local_runs/stockfish-pilot --evaluator stockfish-d1 --include-d1 --stockfish "C:/path/to/stockfish.exe"
```

Defaults: two seeds, six plies per game, four output hypotheses, 2,000 internal
exact histories, search depth two, 16 alternating rounds, 5,000 tree nodes. The
public start contains two separated kings, making privacy/branching checks
cheap. Those fixtures have little value diversity and are not a training set.
For other small public fixtures use `--initial-fen`; the standard chess start
is possible but is not a demonstrated full-game workload.

Output directories cannot be overwritten. A pilot writes:

- `part-000.jsonl`: shared TrainingRecords with nonempty game IDs.
- `manifest.json`: record count, configuration ID, prototype flag and data hash.
- `report.json`: settings, source hashes, dirty-tree status, engine identity/hash,
  game outcomes or unfinished caps, tracker growth/times, Python allocation peak,
  repeat agreement and label acceptance results. A failed run records its error;
  it must not be used as an accepted export.

Each pilot repeats its fixed work in-process and compares hypotheses, policies,
values, moves and numerical work counters exactly, excluding measured elapsed
times and over-budget flags. A JSONL round trip is checked too. Stockfish is
cleared before every call for these reproducibility experiments. This policy
differs from the engine-state reuse intended for later production search.

Labels evaluate every candidate continuation under the **same final raw
profile**, then set `root_value` to the input-belief-weighted mean. No gadget
opt-out, margin or alternate value enters the target. Optional `d1:<index>`
features are separate evaluator inputs, not teacher targets. The D1 feature is
FEN-based, matching Pair B's existing feature convention.

Recheck an export independently:

```powershell
.\pair_b\.venv\Scripts\python.exe pair_b/scripts/validate_labels.py pair_a_prep/local_runs/material-with-d1 --require-d1 --require-played-policy
```

Use fresh game IDs/seeds for separate datasets. The pilot identifier includes
the search configuration, evaluator name, public start and seed; it deliberately
repeats in exact reruns, which must not be concatenated as independent games.

## Verified scope on 22 October 2026

Material plus optional D1 features: two six-ply games, 12 accepted labels,
maximum 269 tree nodes and 105 exact histories. Both games remained unfinished
at the diagnostic cap; they are not reported as referee draws. A fresh Python
process reproduced all 12 semantic records exactly.

Stockfish D1, a public Black rook-versus-king tactical start: one accepted label,
99 tree nodes, Black captures the king on the first move. Each pilot also passed
its own repeated-run check, JSONL round trip and Pair B's strict label checks
with zero errors and zero warnings.

These are pipeline checks. They establish neither agent strength, useful
training quality, long-run scalability nor full paper reproduction. Full KLUSS
subgame construction, Resolve/Maxmargin integration, gifts, dynamic tree growth,
persistence and purification remain separate work before production labels.
