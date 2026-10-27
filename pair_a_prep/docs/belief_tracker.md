# Belief tracker

`pair_a_prep.belief_tracker.BeliefTracker` implements both the shared
`fow_shared.interfaces.BeliefTracker` protocol and `BeliefTrackerDraft`.
The implementation uses `RulesAdapter` for every hypothetical transition and
observation. It never receives a referee, true board, or hidden opponent move.
The source baseline is `pair-a/rules-interface` at
`c55de7a787caffe68fb4e2f5e0812fdfce00f652` (downloaded 2026-10-21).

## Usage

Run from the repository root, where `fow_shared` and `pair_a_prep` are importable:

```python
from pair_a_prep.belief_tracker import BeliefTracker

tracker = BeliefTracker(sample_size=256)
tracker.reset(player="white", seed=17)
initial_belief = tracker.update(initial_white_observation)
after_our_move = tracker.update(next_white_observation, own_move="e2e4")
after_their_move = tracker.update(following_white_observation)
```

The observation arguments above come from the match runner. They are all
White's views, including the snapshot while Black is to move. Each update
returns the existing shared `Belief`, including off-turn and terminal views.
`own_move` led to the new observation; `HistoryEvent.own_move` instead belongs
to the snapshot before the move. The shared runner already handles that timing.

For a public custom start, configure both trackers and the referee identically:

```python
from pair_a_prep.rules_adapter import RulesReferee

fen = "4k3/4r3/8/8/8/8/8/4K3 b - - 0 1"
referee = RulesReferee(initial_fen=fen)
trackers = {p: BeliefTracker(initial_fen=fen) for p in ("white", "black")}
```

These objects work with `fow_shared.evaluation.play_game`, which calls
`reset(player, seed)` itself. `reset(..., initial_fen=fen)` also supports the
draft interface for direct use; that override applies only to the current game.
The next reset without an override uses the constructor's initial position.
A custom FEN is public configuration, never an undisclosed referee midgame FEN.
It starts at elapsed ply zero and cannot reconstruct earlier repetitions.

## Inference and identity

1. Reset creates one candidate at the public start and resets the seeded RNG.
2. The initial observation filters that candidate without advancing it.
3. After our move, apply the supplied action to every candidate.
4. After an opponent move, enumerate every fog-legal action for every candidate.
5. Generate each successor's private observation and retain exact matches.
6. Return all survivors, or a uniform sample without replacement, as hypotheses.

Matching checks viewer, side to move, ply, visible square set, every visible
piece or empty square, legal action set, own capture notification, termination,
and outcome. An explicitly supplied halfmove clock is checked against the
candidate's clock; `None` supplies no clock evidence. The current rules adapter
always hides that clock. Move/square ordering is irrelevant.

Each candidate retains an independent `RuleState` with the complete move stack,
its hypothetical UCI path, and a deterministic SHA-256 history ID derived from
the public root FEN and successive moves. No FEN-based transposition merging
is performed. Different paths reaching the same FEN remain different hypotheses,
preserving repetition history and the information needed to replay hypothetical
private views later. The tracker does not construct the opponent's search infosets.
FEN output uses the adapter's standard six-field FEN, including en passant
targets after double pawn pushes. The FEN alone still does not encode history.

## Population, weights, sampling and budgets

- By default, `sample_size=None` returns every survivor. A positive `sample_size`
  caps only the returned sample. Internal inference still uses every survivor,
  including hypotheses absent from previous samples.
- `population_size` counts consistent **histories**, not distinct FEN strings,
  before output sampling. The tracker's property reports the retained count;
  before reset it is zero, and before the first observation it is one public root.
- `weighting="uniform"` assigns `1 / sample_count` to each returned history.
  This is a uniform feasible-history convention. It is not a posterior under
  a learned opponent policy, nor under an opponent choosing uniformly at every
  node (which would require products of inverse branching factors).
- Sampling is without replacement and reproducible for the same seed and input
  stream. Output ordering follows deterministic candidate order. History IDs
  depend on the public initial position and path, not the sample or seed.
- Optional `max_candidates` limits retained exact histories. Exceeding it raises
  `BeliefCapacityError`; it never silently truncates, resamples the population,
  fabricates a population estimate, or adds the true state. It is not a time
  budget: many rejected successors may still need to be examined.

Tracking and returned serialization grow with the full surviving history set;
move stacks and hypothetical paths also grow with game length. This is an exact
reference implementation for bounded experiments, not a demonstrated solution
for millions of states or unrestricted full-length games. In a sampled belief,
the actual path need not appear in the sample; it remains in the internal set
when all public-start and observation assumptions hold.

## Failure behavior

Call reset before update. Wrong players, invalid actions, an own action supplied
on the opponent's turn, missing own actions, duplicate/skipped plies, wrong
turn alternation and updates after termination raise `ValueError`.
An inconsistent observation producing no survivors also raises `ValueError`.
All of these and explicit capacity failures leave the last accepted population,
observation and RNG unchanged. The caller can correct the input and retry.
Stored observations detach their piece dictionaries from caller-owned snapshots.

The rules profile remains `paper_fow_v1_proposed`; unresolved behavior such as
zero legal moves without an existing terminal outcome is inherited from the
adapter. This implementation does not add new draw rules or forced-loss endings.

## Local environment and verification

The containing NUSWORK project requires its parent `pixi.toml` / `pixi.lock`.
The `darkchess` environment was added using the official Pixi workflow:
<https://pixi.prefix.dev/latest/tutorials/multi_environment/>.
It excludes the default feature and contains Python 3.12, NumPy, SciPy, pytest,
and PyPI `python-chess==1.999` (the imported `chess` package is 1.11.2).
Pixi 0.77.0 emitted an environment entry missing `features`; adding the required
`features=[]` fixed validation. `python-chess` was unavailable from the configured
Conda channels, so it was installed through Pixi's PyPI dependency support.
Other existing environment declarations were retained.

From this downloaded repository root:

```powershell
pixi run -e darkchess python -m pytest -q tests pair_a_prep/tests pair_b_prep
pixi run -e darkchess python -m pair_a_prep.fixtures --adapter pair_a_prep.rules_adapter:fixture_result
```

The dedicated tests cover hand-derived hidden moves, a full-path enumeration
oracle, same-FEN distinct histories, private-stream equivalence, sampling and
reset determinism, recovery of a previously unsampled candidate, explicit
capacity failure, input rejection and atomic retries, all 17 fixture starts for
both players, special transitions, hidden promotions, history-dependent draws,
seeded short games and real shared-runner games through terminal snapshots.
The runner examples use scripted actions solely for integration testing; they
do not implement ZS21/Obscuro or establish playing strength.

Executed validation on 2026-10-21: 291 tests and 2 subtests passed in 16.00 seconds
across the three test directories above (95 tests cover the new tracker), with
all 17 rules-adapter fixtures passing separately. See
[`belief_tracker_verification.json`](../results/belief_tracker_verification.json)
for versions, commands, source hashes and the verified change scope. Pair B's
neural training/Stockfish-dependent suite was not part of this run.
