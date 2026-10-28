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

## Review-fix snapshot

`gift_accounting_review_reference.json` and its linked `gift_accounting_clock_review_reference.json` supersede the old measurements for the corrected gift-sign/fallback code. The two hand examples still give gifts 0.25 and 0, and both final chess ledgers contain three events. The clock matrix has 48 standalone actions with 2 fallbacks and no observed overrun; its 12 capped/null live games have 48 actions with no observed fallback or overrun. These are source-specific small serial observations, not hard-time or strength guarantees; do not pool them with earlier runs.

Reproduce to fresh paths with `python -m pair_a_prep.clock_ablation --output <clock.json>`, then `python -m pair_a_prep.gift_accounting_probe --clock-report <clock.json> --output <audit.json>`. Both reports must have identical complete normalized source manifests; the audit refuses a stale clock snapshot. Original artifacts remain historical. The ledger remains audit-only and does not numerically lift ancestor gadget payments.

## Portable artifact links (review v2)

Use `gift_accounting_review_v2.json` and its linked `gift_accounting_clock_review_v2.json` for the corrected source/diagnostic snapshot. `clock_artifact.hash_convention` is `sha256_utf8_artifact_bytes_crlf_to_lf_v1`: normalize CRLF to LF before hashing serialized UTF-8 bytes. All other whitespace and JSON key ordering remain significant. This makes the immutable content link portable across Git checkout newline conversion; it is not semantic JSON canonicalization. Regressions test both the helper and the recorded report link using LF and CRLF bytes.

The v2 run has 48 standalone actions with one fallback, and 12 capped/null live games with 48 actions and one fallback. No overrun or tracker-capacity failure was observed. Timing varies between serial samples, so do not pool it with older matrices or infer a guarantee. The inherited zero-reach flag now reads the actual projection field and is covered by an end-to-end final-Decision regression. Earlier references, including the original raw-byte link, remain historical and are not relabelled.

## Post-main integration snapshot

`gift_accounting_post_main_reference.json` links to `gift_accounting_clock_post_main_reference.json` after the retained-cache repair and integration of main (#37/#38/#45). Sources match under the normalized convention. The measured clock run has 48 standalone actions, three fallbacks, zero observed overruns; its 12 capped/null live games have 48 actions, two fallbacks and zero observed overruns. Hand gifts remain 0.25/0 and the final ledgers have three events per side. Older v2/review/original matrices remain historical, with no pooling or timing guarantee.

## EP readiness metadata correction

The post-main clock report had the generator's stale PR37 pending string. It now records the passing effective EP check, with a metadata-only correction and original normalized digest. Measurements and execution manifests were preserved. The linked post-main gift audit updates its portable content hash and records the previous link/digest in its own correction entry; its game/ledger/measurement data is unchanged. No clock or game rerun occurred. The generator now copies readiness from its linked clock report. Earlier pre-rule and historical artifacts remain untouched.
