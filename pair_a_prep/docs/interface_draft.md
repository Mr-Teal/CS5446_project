# Pair A minimum interface draft

Status: proposed for teammate review. No rules engine, tracker, shared schema
change, agent assignment or Pair B integration is implemented by this draft.
Signatures are in [interface_draft.py](../interface_draft.py).

## Proposed responsibilities

- Rules adapter: construct states, generate legal moves and private observations,
  apply moves, and detect actual terminal outcomes.
- Belief tracker: retain candidate states/history, expand them through the same
  adapter, filter against observations, and return the existing shared `Belief`.
- Match runner: keep the true state private and deliver observations and known
  own actions. The tracker never receives the true state or hidden enemy moves.
- Search agents: consume observations and beliefs. Search-specific opponent
  information sets, root sampling and retained search trees need separate design.

## State and observation conventions

The concrete state representation is left to the adapter implementer. A likely
implementation wraps a chess board with its move stack, an elapsed-ply counter
starting at zero, and any metadata needed to report captures. A successor must
preserve repetition history and must not mutate its parent or sibling branches.
FEN alone is insufficient to reconstruct repetition or private histories.

Moves use UCI strings, squares use algebraic names, pieces use FEN letters,
and colors use `white`/`black`. Do not equate ordinary chess legal moves or
checkmate detection with the proposed fog-of-war rules. Use the existing rules
fixtures as proposed acceptance cases; observation details still need review.

Observation fields have these proposed meanings:

| Field | Meaning |
|---|---|
| `player` | Owner of this private view |
| `side_to_move` | Acting color, explicit even for custom starts |
| `ply` | Number of moves applied since this game started; initially zero |
| `visible_squares` | Unique visible squares, including visibly empty squares |
| `visible_pieces` | Exactly those squares; `None` means visibly empty, absent means unseen |
| `legal_moves` | Available UCI moves only when this viewer acts; otherwise empty |
| `captured_own_piece_at` | Square of own piece captured in the immediately preceding move, or `None` |
| `halfmove_clock` | `None` unless the agreed observation rules reveal the counter |
| `terminal`, `outcome` | Actual termination and result from this viewer's perspective: -1, 0, +1; nonterminal result is `None` |

Snapshots must not expose mutable internal dictionaries. Terminal observations
have no legal moves. A forced-loss search evaluation is not a terminal outcome.
An experiment's move limit belongs to the runner, not to the game rules adapter.

## Calling sequence

This example is an integration sketch requiring future implementations. It is
not runnable on its own. Both trackers use the same sequence; only White's
updates are shown. The runner must also update Black after every ply.

```python
state = rules.initial_state()  # True state: runner only.
white_tracker.reset(player="white", seed=17)
white_belief = white_tracker.update(rules.observe(state, "white"))  # ply 0

# White's actual action is known to White's tracker.
state = rules.apply_move(state, "e2e4")
white_belief = white_tracker.update(
    rules.observe(state, "white"), own_move="e2e4"
)  # ply 1; Black is now acting.

# The runner applies Black's action but does not tell White what it was.
state = rules.apply_move(state, "e7e5")
white_belief = white_tracker.update(rules.observe(state, "white"))  # ply 2
```

For an own move, advance each candidate by that action and filter by the new
observation. For an opponent move, enumerate candidate opponent actions and
filter their successors. Candidate observations must be generated using the
same adapter. Weights, history identity, deduplication and sampling are tracker
decisions still to document. If the candidate set becomes empty, report the
failure instead of reading the referee's state or silently rebuilding guesses.

## Review before integration

1. Pair A: confirm these signatures, update timing, public initial position and
   ownership split. Agent ownership is not assigned by this document.
2. Pair A: confirm the visibility/capture notification rules and terminal rule
   precedence using the existing fixtures, including history-dependent cases.
3. Pair A: choose exact versus sampled tracking, history identity, weighting,
   and how surviving internal states map to shared `Hypothesis` entries.
4. Pair B: coordinate adding `side_to_move`, allowing an unknown halfmove clock,
   passing `own_move` through the runner, and serialization/feature compatibility.
   The shared `Observation`, protocols and runner are unchanged for now.
5. Before integration: demonstrate an initial/own/opponent update, independent
   successor branches, repetition-history retention, and observation privacy.

The current shared `HistoryEvent.own_move` describes the action AFTER its stored
observation. The draft tracker's `own_move` describes the action BEFORE the new
observation. A future runner must respect this difference when constructing both.
