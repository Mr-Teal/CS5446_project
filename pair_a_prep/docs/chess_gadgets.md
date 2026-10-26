# Chess roots to Resolve and Maxmargin

`chess_gadgets.py` connects the existing private-history chess tree to the generic
fixed-tree gadgets. It prepares opponent root groups, accepts externally supplied
gadget parameters, solves the gadget with PCFR+, and exports continuation labels.
This is an opt-in bridge; the default `FixedDepthPCFRAgent` and pilot CLI retain
their original sampled-root game.

## Root grouping

`prepare_chess_roots(turn, evaluator, ...)` builds the chess tree once, retaining
the reconstructed `HistoryRoot` objects in belief order. It returns:

| Field | Meaning |
|---|---|
| `root_ids` | Stable IDs derived from each FEN and complete candidate path; independent of input order or arbitrary `history_id` aliases |
| `opponent_infosets` | Opponent colour plus the hash of the opponent's complete hypothetical private stream at the root cut |
| `groups` | Opponent infoset to root IDs |
| `belief_weights` | The original sample weights keyed by root ID; used for labels only |
| `chess_tree` | Full-width fixed-depth continuations and their shared private-history infosets |

Do not group by FEN, root ID or the current observation alone. Histories that
return to the same FEN can leave different opponent memories. Duplicate complete
paths are rejected even when supplied under different history ID aliases.

In the current public-start tracker, both the initial board and our own past
actions are fixed. Distinct candidate paths therefore differ in the opponent's
own actions, which that opponent remembers. Root groups will generally be
singletons. This is a consequence of the sampled information structure, not a
reason to erase memory or artificially merge roots. Within future continuations,
our invisible moves can still lead to the same opponent infoset.

The existing gadget preserves all player-0 continuation keys across roots. It
refines player-1 keys by the root group the opponent learned in the gadget,
never by hidden root identity. Thus our current policy stays shared, and the
opponent must use one distribution for indistinguishable continuation histories.

## Three separate kinds of weight/value

`roots.build(...)` requires these external inputs:

1. `alternate_player0[J]`: player 0's exit payoff for each opponent root group.
   Player 0 is the acting chess player, including Black. Negate an alternate
   expressed as the opponent's utility before supplying it. Finite values beyond
   `[-1, 1]` are permitted as gadget payoffs, not as TrainingRecord targets.
2. `reach_mass[root_id]`: nonnegative conditional root mass. Every group needs
   positive total mass. The gadget normalizes masses within each group.
3. `group_prior[J]`: an explicitly supplied probability distribution over groups
   in Resolve. Resolve root probability is this prior times conditional reach
   mass. Maxmargin has an opponent selector instead and rejects a group prior.

None of these is automatically inferred from belief weights, a leaf estimate or
history counts. The bridge does not compute the paper's alternate/gift values
or Resolve root distribution. Caller-supplied constants are experimental inputs,
not a claim that those paper mechanisms have been implemented.

## Minimal runnable example

With the Pair B environment and Pair A requirements installed, run from the
repository root:

```python
from pairb.material import MaterialEvaluator
from fow_shared.contracts import AgentInput
from pair_a_prep.belief_tracker import BeliefTracker
from pair_a_prep.chess_gadgets import prepare_chess_roots
from pair_a_prep.rules_adapter import RulesAdapter

public_fen = "7k/8/8/8/8/8/8/K7 w - - 0 1"
rules = RulesAdapter()
observation = rules.observe(rules.initial_state(public_fen), "white")
tracker = BeliefTracker(public_fen)
tracker.reset("white", 17)
turn = AgentInput(observation, tracker.update(observation), 1000)

roots = prepare_chess_roots(turn, MaterialEvaluator(), initial_fen=public_fen, depth=2)
group = roots.opponent_infosets[0]
root_id = roots.root_ids[0]

# Explicit synthetic parameters for this one-root example only.
resolve = roots.build({group: 0.0}, reach_mass={root_id: 1.0},
                      mode="resolve", group_prior={group: 1.0})
margin = roots.build({group: 0.0}, reach_mass={root_id: 1.0}, mode="maxmargin")
solution = resolve.solve(rounds=100, schedule="alternating")
record = solution.training_record(seed=17, game_id="one-root-gadget-example")
print(record.root_value, record.hypothesis_values)
```

The game ID above is a fixture ID, not an independent full-game training sample.
For nonzero current plies, provide the complete private `AgentInput.history`
and candidate paths, just as required by `build_chess_tree`.

## Labels and solver objective

`ChessGadget.evaluate_profile(profile)` can evaluate an externally supplied raw
behavior profile, including profiles produced by another solver. `solve()` is a
fixed-work convenience wrapper around the existing PCFR+ implementation.

The returned `ChessGadgetValues` separates:

- `root_policy`: our shared raw strategy, before purification.
- `hypothesis_values`: unshifted continuation values in original belief order,
  under that same profile, even for roots the gadget never enters.
- `root_value`: the original belief-weighted mean of those continuation values.
- `gadget_value`: the solver objective, which can include opt-out values or
  Maxmargin offsets and must not replace the training target.

`training_record()` samples the raw policy using the supplied integer seed,
includes `played_policy:<uci>` diagnostics, and stores the separate gadget
objective in `solver_root_value`. No D1 input features are generated here.
The solution's `configuration` records mode, solve settings and all supplied
group/root parameters. Its digest is the record's `config_id`; it identifies
this explicit fixture configuration, not a frozen production label protocol.

## Verification and limits

The small chess tests cover both player colours, same-FEN distinct histories,
shared current policies, shared invisible-action opponent policies, different
visible-action policies, strict input maps, root reordering, independent LP
objectives and unshifted labels. An analytic two-root fixture has belief weights
`(0.9, 0.1)`, reach masses `(7, 3)` and Resolve prior `(0.1, 0.9)`. Its continuation
values `(0.8, -0.6)` give label `0.66`, while the Resolve objective is `-0.46`.
With alternate values `(0.3, -0.2)`, the Maxmargin objective is `-0.4` and the
label is still `0.66`. An always-exit fixture checks that labels also exclude
opt-out payoffs.

```powershell
.\pair_b\.venv\Scripts\python.exe -m pytest -q pair_a_prep/tests/test_chess_gadgets.py
```

`max_nodes` and the optional preparation deadline apply to the chess tree.
Gadget cloning/validation and `solve()` add work and do not enforce a wall-clock
limit. These finite fixture solves are not an anytime agent. The original
trees must not be mutated after construction. This work does not implement
knowledge closure, paper-derived gifts/alternates/priors, root replenishment,
mode switching, incremental tree growth, persistence or purification. It leaves
the generic PCFR+ solver unchanged so tree-growth work can proceed separately.

Cloned estimates preserve the `cutoff` flag for future growth integration.
The [original chess tree can now grow incrementally](chess_tree_growth.md),
but growing a gadget solver still requires path/key/offset mapping and is not
supported by that API.
