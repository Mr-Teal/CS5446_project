# Pair A branch handoff

## Suggested pull request

Title: **Pair A: rules adapter, fixed-tree PCFR+ and visualization tools**

Base: `main`. Head: `pair-a/rules-interface`.

This branch provides a history-preserving fog-of-war rules adapter and referee,
private observations, and a browser chessboard viewer. It also adds fixed-tree
PCFR+ with simultaneous and alternating updates, Resolve/Maxmargin gadgets,
a synchronized-cut KLSS/KLUSS prototype, and an offline toy solver explorer.
Tests and reference outputs accompany the implementations.

The shared contracts and encoder are unchanged. Pair B can use
`pair_a_prep.rules_adapter.RulesReferee` and the existing `RulesAdapter`
without waiting for the complete Obscuro agent. Run from the repository root:
the root package installation ships only `fow_shared`, not `pair_a_prep`.

## Review priorities

1. Visibility, castling, en passant, king capture and history-based draws.
2. Observation privacy and compatibility with the shared referee protocol.
3. Predictive regret updates, alternating schedule and gadget payoff signs.
4. The explicit limitations of synchronized-cut knowledge restriction.

## Validation

See [verification.md](verification.md) for executed commands and scope.
The board viewer launch guide is [board_viewer.md](board_viewer.md).
The generated toy explorer is `pair_a_prep/results/toy_explorer.html`;
the similarly named template is not the generated viewer.

## Remaining work

- General observation/history-based subgames and opponent information sets.
- Incremental tree growth, initialization, persistent search and root sampling.
- Integration with the partner's belief tracker and end-to-end agent decisions.
- Paper-specific gifts, alternative values and policy purification.
- Validated solver labels and controlled complete-agent comparisons.

The fixed-tree tests do not establish a complete Obscuro reproduction.
The rules fixtures implement the documented proposed profile, not a proof of
equivalence to every Chess.com or OpenSpiel rule.

## Commit scope

Include source, tests, documentation, the small reference outputs and the root
`.gitignore`. Exclude virtual environments, package installation metadata,
bytecode, downloaded engines, and `pair_b/.fog_lab/` local sessions and smoke
results. Those local trial matches are not agent-strength evidence for this PR.

Keep the existing branch history; no force push or history rewrite is needed.
After committing and pushing the cleanup, open the PR for review. This document
does not authorize merging it or publishing comments on anyone's behalf.
