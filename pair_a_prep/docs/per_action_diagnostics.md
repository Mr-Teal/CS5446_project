# Production per-action diagnostics

The shared `PlyResult` now includes `diagnostics`, a copy of the numeric
diagnostics returned by the agent for that action. Pair C already serializes
these records through `dataclasses.asdict`, so `games.jsonl` now preserves
fallback, evaluator-call, solver-round, projection and policy diagnostics
when the agent supplies them. No Pair C source change is needed.

The field is additive and defaults to an empty mapping for older positional
constructors. The existing top-level `search_nodes`, `elapsed_ms` and
`over_budget` fields retain their previous meanings. The copy prevents later
reuse of an agent's mutable diagnostics dictionary from changing older plies.

## Interpretation

- `ply.diagnostics.fallback == 1` identifies a reported fallback. A missing
  field is unknown, not zero. `search_nodes == 0` alone proves neither search
  success nor fallback. Older archived records may lack `diagnostics` entirely.
- `ply.elapsed_ms` and `ply.over_budget` are measured around `act()` by the
  runner. Nested diagnostic fields with the same names are agent measurements;
  they may cover a different interval. Do not overwrite the runner fields.
- `evaluator_calls` counts the agent's reported leaf-evaluator work, not
  necessarily UCI commands or neural forward passes. Interpret it using the
  selected evaluator and caching conventions.
- `solver_root_value` and policy entries are diagnostics, not approved
  training labels. The projected-label contract remains gated.
- No new fallback summary is inferred for agents that do not report one.
  Failed attempts currently omit partial ply results in Pair C; this change
  does not provide streaming diagnostics for actions preceding a failure.

Example analysis of a successful attempt:

```python
for ply in record["plies"]:
    identity = record["player_by_color"][ply["player"]]
    diagnostics = ply.get("diagnostics", {})
    fallback = diagnostics.get("fallback")  # None means unknown.
    calls = diagnostics.get("evaluator_calls")
    elapsed_ms = ply["elapsed_ms"]
```

Group by player identity rather than colour when alternating seats. Keep
failure/cap counts beside any successful-attempt timing or fallback aggregate.

## Validation

The shared regression exercises a fallback and a non-fallback with identical
zero node counts, an agent with no diagnostics, caller-defined work keys and
reuse/mutation of the same dictionary. It checks JSON round-trip values.
The Pair A factory integration test checks the normal Pair C production
output across both player colours with a test-double evaluator.

Separately, the real Stockfish 19 pawn smoke completed two capped attempts
and eight actions, with no failures or fallbacks. Every saved diagnostic
mapping and move matched the independently traced agent decision. Both
engines were closed. The reference is
[`per_action_diagnostics_reference.json`](../results/per_action_diagnostics_reference.json).
This is bounded recording/integration evidence, not a strength result or a
fresh measurement of the older archived source.
