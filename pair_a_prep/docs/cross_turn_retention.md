# Cross-turn sampled-history retention

`RetainedPCFRAgent` is opt-in: the normal anytime agent still rebuilds each turn.
The evaluation factory accepts `search_mode=retained` and `growth=one_sided`
(or the uniform baseline). The agent is named `retained-...prototype-v1`, with
an additional warm-start configuration revision. It is not complete Obscuro.

## What is retained

After a successful turn, save that private input, expanded tree and solver.
At a later turn of the same player:

1. Require the new private stream to extend the saved stream and observation.
   Replay every new candidate from the public initial position. Existing
   observation, known-own-action, FEN and repetition validation still applies.
2. Match each new candidate's full move prefix against a saved candidate; follow
   its hypothetical suffix through the saved tree. This uses candidate actions,
   never a hidden referee action. Verify the resulting own private-memory key.
3. Copy a saved nonterminal subtree when available. Keep its frontier contexts,
   including repetition stacks and both private memories. Otherwise build that
   new candidate's shallow tree through the ordinary evaluator interface.
4. Use exactly the new input belief's root distribution. No unweighted saved
   candidate is inserted into a posterior. Different paths sharing a FEN remain
   different histories. Excluded roots leave the new solver tree.
5. Rebase compatible private-infoset minimizers, predictors, averages and cached
   opponent policies. Copy state to avoid mutating the saved solver on failure.
   Old rounds persist, but each new turn gets its own rounds/final-round budget.
6. Commit the new saved snapshot only when solving returns a valid decision.
   reset() clears it for the next game. Cooperative budget/capacity failures keep
   the previous snapshot; act() retains the existing no-label fallback behavior.

Diagnostics distinguish reused/fresh roots, retained infosets, discarded previous
root prefixes, total solver rounds and `solver_rounds_this_turn`. Tree node caps
do not bound temporary copying workspace or the tracker's exact enumeration.
Depth is measured from the retained tree rather than reset to initial_depth.

## Root replenishment contract proposed for tracker review

`replenish_histories(retained, population, target, seed)` preserves every retained
path, then samples unseen validated histories without replacement to a target
floor. The target never truncates retained roots; insufficient supply returns
all available candidates. Identity is (FEN, full candidate path), not FEN alone.
The helper returns candidates, not a normalized Belief or guessed posterior.

This helper is deliberately not wired into exact tracker internals. Agreement
with the tracker owner is still needed on:

- How to supply a finite, evidence-consistent population without enumerating an
  exploding exact tree or exposing the referee's hidden state.
- Which probability model/weights apply after retained-plus-fresh selection.
- Whether to offer an explicit separate history-preserving particle tracker,
  including resampling/recovery, while keeping the exact oracle unchanged.
- Whether the paper's target 256 is feasible. It is a floor; max_candidates is
  an independent fail-fast resource limit, not permission to truncate silently.

The live agent currently reuses only candidates already returned by the shared
tracker. It does not claim paper-specific replenishment or solve tracker growth.

## Verified scope and next integration

Reproduce from the repository root with:

```powershell
& .\pair_b\.venv\Scripts\python.exe -m pair_a_prep.cross_turn_experiment
& .\pair_b\.venv\Scripts\python.exe -m pytest -q tests pair_a_prep/tests
```

`results/cross_turn_reference.json` records source hashes, configurations,
per-move times and last-turn reuse diagnostics. Both four-ply Material games
were capped with null outcomes. Each player's last turn reused three histories
and received four new solver rounds (eight accumulated). The toy session changed
Maxmargin to Resolve at round 1 while preserving both own continuation infosets.
The complete shared/Pair A suite passed 458 tests on this development stack.

Tests compare retained trees/frontier memories against direct reconstruction,
check fresh rebuilding, reject altered private observations, retain same-FEN
distinct paths, preserve all roots above the target floor, and play repeated
live turns under both growth modes. Each later turn receives fresh solve rounds.

The finite-cut boundary module is available in `subgame_boundaries.py`; it is
not applied automatically to this raw sampled-root agent. Mapping a partially
retained chess tree into KLUSS boundaries, assigning novel-root min(heuristic,
previous value), and carrying group/control state across automatic modes need
separate integration and validation. Do not use an old gadget boundary for a
fresh root without constructing the missing opponent-private context.
