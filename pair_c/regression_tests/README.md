# Regression tests

This folder holds focused checks for individual review issues. Add each future
issue under its own heading with the original feedback, response, and test command.

## Review issue 1: Reset engine state between games (see #17)

**Original feedback**:

> The agents/scorers are reused across games with new_game_each_call=False, but OnePlyBot.reset() does not clear Stockfish state. In a two-game probe, neither scorer's new_game() was called.
>
> Please clear every scorer's engine before each game, including Stockfish inside network evaluators, while retaining the hash within a game. This matches the proposed policy in #17.

**Rebuttal / response:**

1. Added `reset_game()` to the factory interface and updated the runner to call each player's factory hook before every game.
2. Users can clear Stockfish or other game-specific state in `reset_game()`. The example in `pair_c/agent_factories.py` demonstrates resetting both direct Stockfish scorers and Stockfish inside network evaluators.
3. Users remain responsible for managing any other state across games, such as hashes and caches.

`test_reset_game.py` runs two short games through the real runner and game loop.
It checks that both factories' `reset_game()` callbacks run before each
game, including between the first game's end and the second game's start.

Run from the repository root: `python -m pytest pair_c/regression_tests/test_reset_game.py -v`.

## Review issue 2: Return a failure exit status

**Original feedback**:

> With an agent that raises, both games were recorded as failed, but the CLI still exited with status 0.
>
> Please retain the logs and summary, then return a nonzero exit status when any game fails so batch runs can detect it.

**Rebuttal / response:**

1. The CLI now checks `games_failed` after the runner saves its results and the CLI prints the complete summary and output directory. Any failed game causes exit status `1`; a run with all games completed retains exit status `0`.
2. Per-game exceptions still allow later games to run. `games.jsonl`, `summary.json`, and the configuration copy are retained, and calling `run()` directly still returns the summary.
3. The terminal summary now includes the failed-game count. When games fail, stderr explains the failure and where the logs and summary were saved.

`test_failure_exit_status.py` launches the real CLI in a subprocess with lightweight
agents and the real two-game loop. It covers two cases: both games succeed, or
the first game fails and the second succeeds. Each case checks the process exit
status, both game records, saved summary counts, and terminal summary. The failure
case also checks the agent's recorded error, confirming that the second game still
runs after the first fails. No Stockfish process, checkpoint, or torch is required.

Run from the repository root:

```powershell
python -m pytest pair_c/regression_tests/test_failure_exit_status.py -v
```

## Review issue 3: Allow each player to supply its tracker

**Original feedback**:

> The runner always constructs ParticleTracker, whose hypotheses lack the complete candidate_moves paths required by Pair A's search. Using our current agent reproduced:
>
> ValueError: hypothesis needs a complete candidate_moves path
>
> Could we support a tracker factory or explicit tracker choice per player? Pair A's exact tracker can support bounded integration tests; a scalable history-preserving tracker remains separate work.

**Rebuttal / response:**

1. Each player can select its own `tracker_factory`; trackers are created per game and follow the player when colors alternate.
2. `tracker_factories.py` provides a Pair B example. Each factory handles its own tracker settings.
3. Pair A can supply its exact tracker. A scalable history-preserving tracker remains separate work.

`test_tracker_factory.py` contains one normal-flow test: two players use ParticleTracker and a test path tracker for two games with alternating colors. It checks tracker outputs, complete candidate paths and fresh instances. Actual Pair A integration is not verified.

Run from the repository root:

```powershell
python -m pytest pair_c/regression_tests/test_tracker_factory.py -v
```

## Follow-up: outcome accounting and depth metadata

`test_outcome_accounting.py` checks terminal-only W/D/L denominators while
retaining successful capped attempts in timing. It also runs the real CLI
with two one-ply caps: zero scored games, zero terminal draws, unavailable
outcome rates and successful exit after writing both records.

`test_leaf_depth_metadata.py` checks all five built-in scorer IDs reject
inconsistent depth metadata before loading resources, and that a valid D11
setting reaches the constructor unchanged. No real engine/checkpoint is used.

Run all focused regression checks from the repository root:

```powershell
python -m pytest -q pair_c/regression_tests
```

## Review issue 4: Save evaluation provenance

**Original feedback**:

> Source/checkpoint/engine provenance remains necessary before using this runner for broader experiments. #17's formal Pair B runner and #34's merge gates are unchanged.

**Rebuttal / response:**

Added `provenance.json` to each evaluation's output directory. It records:

1. Runtime environment: Python, PyTorch and PyTorch-build CUDA versions, automatically detected CPU model, and evaluation start time in UTC.
2. Each player's effective inference device, backend and corresponding GPU model. CPU players have no GPU model; macOS MPS is recorded separately from CUDA. Unknown hardware is accompanied by a detection note.
3. The original configuration's absolute path and each player's checkpoint path.
4. Each player's Stockfish executable path and the running engine's UCI name and author, including engines nested inside network scorers. Players without an engine have `null` entries.
5. A grouped `sha256` section containing configuration hashes, separate checkpoint and Stockfish executable hashes for both players, and a nested `source_files` mapping. File discovery uses Git when available and falls back to the filesystem as described in Issue 6.

**Cross-platform hash follow-up** (Colin's review at `250e781`):

> 3. The hashes are raw working-tree bytes. On a Windows checkout with core.autocrlf=true, 395 of 550 source hashes, and the config hash, differ from a Mac checkout of the same clean commit. Pair A normalises CRLF to LF before hashing (pair_a_prep/provenance.py), and with that rule all 550 match. Reusing that helper, or hashing git blob bytes, would let your runs and mine be compared.

The `[output] hash_rules` setting selects `pair_c/hash_rules.json` by default.
Its `crlf-to-lf-v1` rules classify source files by extension or filename:
text hashes normalize CRLF to LF, while listed binary and unknown types use raw
bytes. Checkpoints and engine executables always use raw bytes. `sha256.config`
normalizes CRLF; `sha256.config_raw` hashes the exact saved INI. Each run saves
the exact rule file as `hash_rules.json`. The previous raw source/config hash
convention differs from this version; compare results using their saved rules.

`test_provenance.py` constructs an INI with Player A on CPU and Player B on GPU.
It covers CUDA and macOS MPS configurations using simulated torch/hardware
responses, lightweight legal-move agents and nested engine metadata. Temporary
checkpoint and engine files are hashed without loading models or starting an
engine. The real runner, game loop and provenance writer generate the output.

The test checks the saved field structure and actual values: exact INI bytes,
configuration/checkpoint/engine hashes, declared checkpoint paths, UCI identity,
CPU/CUDA/MPS device metadata and software versions. A temporary Git repository,
rules, INI, text and binary files verify CRLF/LF equivalence, actual content
changes, binary hashes, chunk-boundary normalization and saved rule bytes.
The factory double explicitly declares checkpoint metadata to simulate a loader;
actual GPU inference, checkpoint loading and engine execution are not exercised.

The test uses different checkpoint and engine contents for each player and
checks each reported hash against its file. A separate test swaps their contents
while keeping the paths unchanged, then checks the hashes against the files and
the previous report. Comparing reports reveals the content change; provenance
collection itself does not issue an alert. Players may also share files.

Run from the repository root:

```powershell
python -m pytest pair_c/regression_tests/test_provenance.py -v
```

## PR51 follow-up: actual loaded resources

`test_provenance_resources.py` covers unused/missing configured checkpoints,
explicit loaded-checkpoint declarations, direct/scorer/evaluator engine discovery,
CPU evaluator subclasses, relative PATH resolution, and dynamic tracked-file
hash changes/deletions. Checkpoint declarations are supplied by loaders, never
inferred from an INI or a hard-coded factory name. Unknown declarations produce
an explicit detection note. See Issue 4 for the current working-tree hash rules
and Issue 6 for source discovery without Git.

Run with `python -m pytest pair_c/regression_tests -q`.

## Review issue 5: Record actual loaded resources

**Original feedback** (Bryan's review of PR #51 at `250e781`):

> Unused checkpoints (P2): run_evaluation.py, lines 91–100 records the configured net1/belief checkpoint paths and hashes for custom Material-only SearchFactory agents. A nonexistent unused checkpoint aborts before play. Please report only checkpoints actually loaded, via an explicit agent/factory resource contract, rather than special-casing one factory name.
>
> PR57 engine metadata omitted (P2): provenance.py, lines 21–27 returns no engine/hash for real, live Stockfish agents from PR #57 at 6fa0c5d in all four modes. Their actual leaf exposes the executable path and UCI identity under agent.evaluator. Please support that resource location consistently for engine and device discovery. This is a direct compatibility probe, not a merged-stack run.
>
> Relative PATH launch regression (P2): agent_factories.py, line 92 resolves a relative shutil.which result against the repository instead of the current directory. The same result launches Stockfish directly but fails through this factory. Resolve the discovered path against the working directory before using/storing it.

**Rebuttal / response:**

Integrated Bryan's proposed PR #51 fix package:

1. Checkpoint provenance now uses an explicit `provenance_checkpoint_path` declaration on the agent, scorer or evaluator. An explicit `None` means no checkpoint was loaded; a missing declaration produces a detection note. Unused configuration paths are not hashed.
2. Engine and device discovery supports scorer, evaluator and direct-agent resource layouts, including CPU Stockfish evaluator subclasses.
3. Relative paths returned by `shutil.which()` are resolved against the current working directory.
4. The existing provenance test now checks recorded values, and Bryan's resource regression cases cover checkpoint declarations, engine and device discovery, relative PATH resolution and tracked source hashes.

Git-state reporting, cross-platform hash policy and ZIP source discovery were addressed in subsequent changes. Bryan reported passing checks on his isolated fix package. The Pair C regression tests also passed on Zhijian Wang's computer after integration of that package; independent review of the updated PR remains pending.

Run the focused tests from the repository root:

```powershell
python -m pytest pair_c/regression_tests/test_provenance.py pair_c/regression_tests/test_provenance_resources.py -v
```

Run all Pair C regression tests with `python -m pytest pair_c/regression_tests -q`.

## Follow-up: isolate resource test from Git metadata

**Original feedback**:

> test_provenance_resources.py:30-31 stubs discover_sources but not git_provenance, so 2 tests fail in a ZIP copy.

The parameterized resource test now stubs both source discovery and Git
provenance, using a temporary source file and a simulated modified-file status.
It checks the file's actual hash without depending on a real repository. The two
parameter cases can run in a ZIP copy without Git metadata.

Run from the repository root:

```powershell
python -m pytest pair_c/regression_tests/test_provenance_resources.py -v
```

## Review issue 6: Record Git commit and working-tree status

**Original feedback** (Colin's review of PR #51 at `250e781`):

> 2. There is no commit or dirty-tree record, only the working-tree bytes of tracked files. A reader cannot tell which commit ran, and an untracked module that is imported and runs is missed without any flag. Pair B's runner records git_commit and git_status (pairb/provenance.py:63, play_matches.py:359); the same two fields would cover it.

**Rebuttal / response:**

1. `provenance.json` records the full HEAD as `git_commit` and porcelain status lines as `git_status`, including staged, unstaged and non-ignored untracked files. A clean status is an empty list; query failures are `null` with details in `git_detection_notes`.
2. The fields are captured before play and output creation. In Git mode, status does not hash untracked files or include ignored files.
3. `source_discovery` records `git` for tracked-file discovery, or `filesystem` when Git is missing or the project root is not a Git repository root. Filesystem discovery includes all files, including ignored files and caches; Git metadata is null with explanatory notes. Directory symlinks are not traversed and are recorded as errors. Other Git failures abort the run.
4. Individual file read errors are recorded as `{"error": "..."}` in `sha256.source_files` while hashing continues; missing files are recorded as `null`. Directory enumeration errors abort. Text/binary hash rules apply in both modes.
5. `test_git_provenance.py` uses temporary repositories and files to check Git state, missing Git, a non-repository directory, file read errors and Git failures. `test_provenance.py` checks the fields in the saved JSON.

The Git root comparison uses filesystem identity rather than path spelling.
`test_git_provenance.py` simulates differently cased paths and both possible
identity results, so this behavior can be checked on case-sensitive and
case-insensitive filesystems without relying on either filesystem's behavior.

Run from the repository root with the project root and `pair_b/src` on `PYTHONPATH`:

```powershell
python -m pytest pair_c/regression_tests/test_git_provenance.py pair_c/regression_tests/test_provenance.py -v
```

Run all Pair C regression tests with `python -m pytest pair_c/regression_tests -q`.
