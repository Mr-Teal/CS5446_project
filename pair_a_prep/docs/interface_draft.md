# Pair A minimum interface draft

Status: proposed for teammate review. A state/move prototype now lives in
[rules_adapter.py](../rules_adapter.py), reusing the merged shared rule helpers.
Private observation generation and a shared-protocol referee are now implemented;
see [rules_adapter.md](rules_adapter.md). Belief tracking remains separate.
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

`RuleState` wraps a private chess board with its full move stack, an elapsed-ply
counter starting at zero, and the immediately preceding capture's player/square.
`board_copy()` returns an independent copy including history. Direct access to
the private `_board` is unsupported. Successors preserve repetition history
and do not mutate their parent or sibling branches.
FEN alone is insufficient to reconstruct repetition or private histories.

`RulesAdapter` implements `initial_state`, `current_player`, `legal_moves`,
`apply_move` and `terminal`. It also implements `observe` using the shared `Observation` type. Move generation and actual terminal checks reuse
`fow_shared.values.fog_legal_moves` and `terminal_score`; `forced_score` is not
used to end games. Custom FEN starts with ply zero and no earlier move history.
FEN parsing is not a complete reachability validator; ordinary chess validity
checks are deliberately not imposed on fog-of-war positions.

```python
from pair_a_prep.rules_adapter import RulesAdapter

rules = RulesAdapter()
start = rules.initial_state()
after_e4 = rules.apply_move(start, "e2e4")
after_d4 = rules.apply_move(start, "d2d4")
assert start.ply == 0
assert after_e4.ply == after_d4.ply == 1
assert rules.current_player(after_e4) == "black"
```

Capture metadata is internal. The observation reveals the captured square only
to the player who lost the piece; it expires at the next ply. En passant uses
the captured pawn's actual square.

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
4. Already merged from Pair B: shared `Observation.halfmove_clock` defaults to
   `None`, and the encoder reads each hypothesis's own clock. No duplicate fix
   is needed. PR #2 also merged required `side_to_move`, own-action delivery
   and terminal tracker updates. `ObservationDraft` now aliases the shared type.
   Custom-start propagation and label definitions still need coordination. This prototype makes no
   changes to shared contracts, protocols or the runner.
5. Before integration: demonstrate an initial/own/opponent update, independent
   successor branches, repetition-history retention, and observation privacy.

The current shared `HistoryEvent.own_move` describes the action AFTER its stored
observation. The draft tracker's `own_move` describes the action BEFORE the new
observation. A future runner must respect this difference when constructing both.
