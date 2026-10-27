# Local gift partitions and cross-turn audit lineage

This follow-up makes existing counterfactual accounting explicit. Inspection
confirmed that derive_boundaries already traversed the entire saved raw tree:
discarded branches were not simply absent from its local CF computation.
The change does not add that gift a second time or claim exact old-gadget
payment lifting. Obscuro C.2 still defines the local positive-part gift.

## Retained and discarded contributions

For the union of explicit cut subtrees, compute both the full profile value
and its contribution from terminals below the retained cut. At each opponent
ancestor/action, CF delta decomposes as:

```text
full_delta = retained_delta + discarded_delta
local_gift = max(full_delta, 0)
```

The positive part must be taken **after** the contributions are combined.
Taking it separately would over-credit gifts when a positive retained
contribution is cancelled by a negative discarded contribution. The audit
records each component alongside the original ancestor infoset/action.

Hand-checkable examples in `gift_accounting_reference.json`:

- Keep payoff 0, discard payoff 1, own keep probability .5: all .25 gift comes
  from discarded branches. Ignoring them would incorrectly produce zero.
- Keep payoff 1, discard payoff -1, own keep probability .25: retained delta
  .125 plus discarded delta -.375 gives -.25 and gift 0. Summing positive parts
  would incorrectly give at least .125.

Both examples use an opponent L/R mix of .5/.5 and an R payoff of zero.
Boundary values and policies retain their original local-CF formulas. The
accounting traversal now checks the preparation deadline cooperatively too.

## Immutable lineage across saved roots

Each saved blueprint carries an immutable GiftLedger DAG. Local events record
the raw-tree/profile/chance normalization identity, group, contributions and
local gift; root references link to events from retained parent histories.
Fresh roots start with no invented parent. Repeated/shared events are deduplicated
and old events with no reachable current descendant are removed. The ledger
does not copy whole previous trees, and histories are never merged by FEN.

It is **audit only**. Ancestor gifts are not added to current alternates: raw
trees are renormalized between searches, and old gadget exit/offset payments
were removed before saving unshifted continuations. Treating all old amounts
as interchangeable would risk double counting or mixing CF units. Numerical
payment transfer still requires an explicit old-gadget representation and a
tested normalization/offset transformation. The ledger preserves evidence
needed to do that work instead of silently forgetting the previous boundary.

Diagnostics report event/ancestor counts, prior positive-event counts and the
audit-only flag. They deliberately do not sum ancestor amounts across units.
Configuration identity includes this accounting convention. Tests verify
deduplication, pruning, unknown-parent and inconsistent-term rejection, and
identical next-turn raw policies/labels with versus without the prior ledger.

## Reproduction and measured overhead

From the repository root in the existing Pair B environment:

```powershell
& .\pair_b\.venv\Scripts\python.exe -m pair_a_prep.clock_ablation --output pair_a_prep/results/gift_accounting_clock_reference.json
& .\pair_b\.venv\Scripts\python.exe -m pair_a_prep.gift_accounting_probe
& .\pair_b\.venv\Scripts\python.exe -m pytest -q tests pair_a_prep/tests
```

The probe checks that overlapping source hashes match the clock artifact,
records the gift-accounting module's hash as well, and links the exact clock
JSON by SHA-256. It includes both hand examples and a six-ply live kings game
with each player's final flat ledger. That game is capped with a null outcome;
each final ledger has 3 reachable events in the recorded run.

With accounting enabled, the same small Material clock matrix recorded zero
fallbacks/overruns in 48 standalone turns, and 1 fallback / 1 overrun in 48 live
actions. All 12 live games were capped/null, with no tracker capacity failure.
The records are retained as observed; do not infer a timing guarantee or
strength improvement from the earlier optimization run's counts.
The complete shared/Pair A suite passed **493 tests**. The overlapping focused
gift/boundary/chess/projection suite passed 28 tests. The live failure was seed
29, purification on, ply 3: preparation left no complete solving round within
the 20 ms budget, and act returned a no-label fallback at about 27.67 ms.

Remaining work: exact cross-root gadget payment lifting, missing-branch value
corrections outside the saved finite game, original engine calibration and the
team's tracker/weighting/rule agreements. This ledger does not implement those
mechanisms or resolve #37.
