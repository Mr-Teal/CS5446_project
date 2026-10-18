# Rules adapter implementation

Status: implemented against `paper_fow_v1_proposed` fixtures; teammate review
is still needed before freezing the rules profile. This is not an agent or
belief tracker. No shared contracts or Pair B evaluators are changed here.

## Public API

`RulesAdapter` constructs `RuleState`, lists moves, applies moves to independent
successors, checks actual terminal outcomes and returns the shared `Observation`.
`RuleState.board_copy()` retains history; `fen` alone does not. Internal full
states belong to the runner or to inferred tracker candidates, never agent input.

`visible_squares(state, player)` can also supply the shared feature encoder's
opponent visibility calculation through a caller-owned wrapper. Its player
argument always identifies the viewer, independent of the side to move.

## Observation construction

1. Include every square occupied by the viewer's pieces.
2. Include the destinations of their pseudo-legal moves, ignoring check.
   Sliders stop at blockers; empty pawn diagonals are not revealed. Blocked
   pawn forward squares are not revealed by that pawn.
3. A currently available en passant capture reveals the destination and the
   capturable pawn. Off-turn views do not inherit the acting player's ep right.
4. Read piece symbols only for the resulting visible squares; visibly empty
   squares have `None`. Each observation owns a separate dictionary, so editing
   it cannot change internal state or another snapshot.
5. Expose legal moves only for the acting viewer and only before termination.
   Set `side_to_move` explicitly and keep `halfmove_clock=None`.
6. Report the previous move's captured square only to the player whose piece
   was captured. En passant reports the pawn's square, not the destination.
   This notification expires at the next ply.
7. At termination, return an outcome from each viewer's perspective and no
   legal moves. Visibility remains computed from their pieces; termination does
   not reveal the full board. Checkmate/forced-loss estimates do not end games.

The snapshot dictionary is detached, not deeply immutable. Treat observations
as read-only. The board's underscore attribute is private by convention, not a
security sandbox. No complete private observation history is stored in RuleState;
the runner and tracker retain their own histories.

## Referee integration

```python
from pair_a_prep.rules_adapter import RulesReferee

referee = RulesReferee()
referee.reset(seed=17)
white_view = referee.observe("white")
referee.apply("e2e4")
black_view = referee.observe("black")
```

`RulesReferee` implements the existing shared `Referee` protocol and works with
`play_game`. Rules are deterministic; reset accepts the protocol's seed without
using randomness. Calling `winner()` before termination raises `ValueError`.
Invalid moves and moves after termination are rejected without changing state.

A constructor `initial_fen` is supported for standalone custom-position checks.
Custom starts must be public and configured consistently in both trackers;
automatic custom-start propagation through the shared runner is still pending.

## Verification

```powershell
python -m pair_a_prep.fixtures --adapter pair_a_prep.rules_adapter:fixture_result
python -m pytest -q tests pair_a_prep/tests
```

The observation tests cover all 17 fixtures including visibility, hidden
counters and terminal results, plus off-turn views, hidden-state equivalence,
capture notification lifetime, detached snapshots and referee reset. A scripted
five-ply game uses the real referee and shared runner through king capture and
checks both trackers' terminal updates. Its tracker is explicitly a shape-only
probe, not an inference implementation or evidence of playing strength.

Still pending: teammate review of the proposed visibility/capture rules, real
belief tracking and search integration, and an explicit policy for rare positions
with zero fog-legal moves but no shared terminal outcome. Such positions are not
silently declared ordinary-chess draws by this adapter.
