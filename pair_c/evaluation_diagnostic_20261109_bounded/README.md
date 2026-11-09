# Bounded-history readiness and recovery evidence

Runtime changes address PR75's exact-history explosion, not a playing-strength
claim. Both players use the same explicit approximate tracker and anytime
planner. See [configuration and commands](../configs/network1-bounded-readiness.md).

## Complete readiness attempts

| Seed | Phase | Plies, colour-swapped games | Failed / capped | Uniform fallback / search overrun |
| --- | --- | --- | --- | --- |
| 17 | Initial bounded implementation | 67 / 14 | 0 / 0 | 0 / 0 |
| 18 | Optimized DAG pruning | 61 / 35 | 0 / 0 | 0 / 0 |

All four end by king capture. These are two readiness pairs, not a formal
batch or evidence of strength. `readiness.json` gives per-game counts. Internal
support never exceeded 8192 histories after a successful update. Actual pruning
and recovery were exercised: the seed18 first game records 12 prunes and two
rebuilds (counters include recovery work). Largest observed tracker update was
12,699.919 ms, separate from search's cooperative 5-second allowance. CPU only.

The earlier 1024-history attempt failed recovery at ply18, with its other game
completing. It is preserved, not pooled with the successful readiness pairs.
A separate initial-prune seed18 performance trial was intentionally stopped
after ply104 to optimize pruning; it is an interrupted attempt, not a completed
or failed game. Its second game was unplayed.

## Checks and source scopes

- Final tracker/factory/graph/output regressions: 208 passed, native enabled.
- Pair C regressions in a separate invocation: 47 passed.
- Seven focused bounded tests passed again after final default/format cleanup;
  these overlap the first selection and are not additional unique coverage.
- A frozen old/new pruning comparison passed 11 consecutive updates, matching
  samples, complete paths, counters and Bloom masks.
- The interrupted long game's Black stream replayed 105 updates through ply104
  with identical retained counts, prune counts and rebuild counts. Original
  measured update total was 311,967 ms; optimized replay 124,024 ms. Execution
  conditions differed and work ran concurrently: no universal speedup claimed.
- Private-stream replay audited every returned path against ALL recorded private
  observations and known own moves: 68 updates for seed17 game1 Black (initial
  implementation), 62 for seed18 game1 Black (optimized). Recovery was exercised.
  Referee FENs and actual hidden opponent actions are not used by this audit.

Runtime base was `5b7115a` (main runtime `10352fe`) with the uncommitted changes.
Seed17 predates the pruning optimization; seed18 uses it. Final delivery makes
8192 the implicit bounded default, removes an unused local import and normalizes
source line endings. All executed configs explicitly set 8192, so that default
cleanup does not change their behavior. Python 3.12.15, torch 2.14.1+cpu,
NumPy 2.5.4, python-chess 1.11.2, SF19 and the committed Network 1 checkpoint.
No checkpoint, runtime asset or native C++ source was modified.

## Raw artifacts

`bounded-readiness-evidence.zip` SHA256:

`c3e0f08c2df5bab4068e5110b075dea9ff1fd39cf8f1b8666bb4869490d52f16`

It contains original configs/provenance/game and private tracker JSONL for all
four phases (including the failed and interrupted trials), XML checks, private
replay outputs, long-prefix parity record, frozen pre-optimization tracker,
final source snapshots and native build identity. `source-sha256.json` hashes
the delivered source snapshots in the ZIP; checkout line endings may differ.
Raw logs retain local absolute paths. New untracked source was not necessarily
included by the old provenance collector; the explicit source snapshots close
that documentation gap without inventing a clean historical commit.

The full exact tracker remains available and unchanged by default. Bounded
tracking may still exhaust recovery/time; failures stay explicit and unscored.
This is not a hard process-memory bound or a guaranteed whole-turn deadline.
No PR66/67 code, new training, formal batch or revised PR74/75 score is included.
