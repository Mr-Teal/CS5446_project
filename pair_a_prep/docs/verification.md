# Verification and handoff

Verified locally on 17 October 2026. Only `pair_a_prep/` was added. The existing
tracked files, current branch, and Pair B PR were not changed.

## Executed checks

```powershell
python -m pytest -q -p no:cacheprovider pair_a_prep/tests tests
python -m pair_a_prep.toy_games --output pair_a_prep/results/toy_reference.json
python -m pair_a_prep.fixtures
```

The test command passed **19 tests**: 15 preparation checks and the 4 existing
shared-code checks. It covers hidden versus revealed information, chance
weighting, a nonuniform equilibrium, Kuhn poker's game value, best-response
gap, input size limits, benchmark corpus safety, raw score viewpoint, fixture
history, classical-rule counterexamples and observation matching assertions.

Reference outputs: [`toy_reference.json`](../results/toy_reference.json).

| Reference problem | Player 0 equilibrium value |
|---|---:|
| Hidden matching pennies | 0 |
| First action revealed to player 1 | -1 |
| Hidden coin, P(H)=0.75 | 0.5 |
| Coin revealed before guessing | 1 |
| Three-card Kuhn poker | -1/18 |
| Biased 2x2 payoff matrix | 0.5 |

Each solved reference has an unhalved best-response gap below `1e-8`.
The LP can choose among multiple equilibria, so exact policy probabilities
are not prescribed where only the value is unique. A known-value test does
not validate knowledge-limited gadget construction, tree expansion or PCFR+.

## What the fixtures verify now

All 17 definitions load; their FENs parse, the history case replays to its final
FEN, and the annotated orthodox checkmate/stalemate/illegal-move facts were
checked using python-chess. The castle counterexample's endpoint geometry is
also checked. Applying `Board.push` alone does not validate a fog move.

**No production FoW adapter has been run against the fixtures.** Expected fog
visibility and legality are hand-derived acceptance requirements, pending
review and an adapter implementation. An adapter that passes partial
expectations may still have untested errors elsewhere.

## Real engine execution

The official Stockfish 19 binary was downloaded to a temporary directory,
then run for 72 successful benchmark calls. The binary is not included in
this repository. See [benchmark.md](benchmark.md) for settings, results,
hashes and scope. There is no completed neural-network timing, full chess
match, replicated agent or solver-label run in this preparation.

The verification environment reused numpy/scipy/pytest already installed on
the machine and chess 1.11.2 in a temporary package directory. Teammates
should use the independent requirements file and environment instructions,
rather than depending on that temporary path.

## Next integration gates

1. Review the proposed rule profile and the observation fields with Pair A.
2. Implement one rules adapter and run all fixture assertions against it.
3. Pick the agent ownership and implement a fixed-tree solver against the toy
   oracle, followed by gadget and tree-growth validation.
4. Settle belief-context evaluation and feature versioning with Pair B before
   producing teacher labels. Existing PR changes remain a separate decision.
