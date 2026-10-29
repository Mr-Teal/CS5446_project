# Pair C Match Evaluation

This runner plays a configurable number of complete Fog-of-War chess games between two independently constructed players. Each side has its own Agent factory, Agent, model resources, and tracker factory. Each game receives a new tracker per player. The default configuration is an ablation example: it uses the same Pair B `OnePlyBot` factory class twice, loading a different scorer for each player, and Pair B's `ParticleTracker` for both players.

## Run

From the repository root, activate the Python environment that has the project dependencies installed, then run:

```powershell
python pair_c/run_evaluation.py
```

The default configuration is `pair_c/evaluate_config.ini`. An alternative INI file can be passed as the first argument:

```powershell
python pair_c/run_evaluation.py path/to/another_config.ini
```

## Configuration

See `evaluate_config.ini` for configuration details.

## Evaluate Other Agents

Each player section specifies an Agent factory and a tracker factory, both in `python.module:FactoryClass` form. Each factory receives that player's INI settings as strings.

**Agent factory**

1. Set `factory` to your factory class.
2. Implement `load_model()` to return an Agent with `name`, `reset(player, seed)` and `act(turn) -> Decision`. Implement `reset_game()` to clear per-game model state; stateless models may use `pass`. The factory and Agent are reused across games.
3. Follow the Pair B example in `agent_factories.py`: replace the marked method bodies and leave `__init__` unchanged.

**Tracker factory**

1. Set `tracker_factory` to your tracker factory class.
2. Implement `create_tracker()` using the template's signature to return a fresh tracker for each game. It must provide `reset(player, seed)` and `update(observation, own_move=None) -> Belief`. The shared game loop calls these methods; no factory `reset_game()` is needed.
3. Follow the Pair B example in `tracker_factories.py`: replace the marked method body and leave `__init__` unchanged. Parse your tracker's options there; other trackers do not need Pair B's particle settings.

Choose a tracker compatible with your Agent. Pair B's `ParticleTracker` leaves `candidate_moves` empty; Pair A's search requires a tracker that supplies complete candidate paths. See `fow_shared/interfaces.py` for the shared interfaces and `evaluate_config.ini` for a complete configuration example.

## Something about 'Rules'

The current evaluation pipeline supports passing a `rules` object into your tracker through `create_tracker(rules, initial_fen=None)`. The runner creates this object from the match-level `rules` setting (`standin` or `teal`) and passes it to the referee and both tracker factories.

This `rules` object is not a component required by `fow_shared`. The shared interfaces define the methods of an Agent, tracker and referee, but do not require them to accept a rules object or define a shared `Rules` interface.

I included the `rules` argument because Pair B's `GameReferee` and `ParticleTracker` support receiving one. If your Agent and tracker do not use a separate rules object, keep the `rules` parameter in your factory's `create_tracker` signature so the runner can call it, and simply leave it unused in the method body. You do not need to add a rules dependency to your implementation.

## Results

The output directory contains:

- `evaluate_config.ini`: a copy of the exact configuration used.
- `hash_rules.json`: an exact copy of the classification rules used for this run.
- `provenance.json`: Python, PyTorch and CUDA versions, automatically detected hardware,
  evaluation start time (UTC ISO 8601), and the original configuration's absolute
  path and SHA-256. `sha256.config` hashes the INI after CRLF-to-LF normalization;
  `sha256.config_raw` hashes the exact bytes saved in `evaluate_config.ini`.
  CPU detection supports Windows, macOS and Linux. `player_devices`
  records each player's effective device, backend and corresponding GPU model,
  using loaded network tensors before the Agent/scorer's device field. CUDA
  indices follow PyTorch's mapping, including `CUDA_VISIBLE_DEVICES`.
  CPU players have a `null` GPU model. Unknown devices or failed GPU detection
  have a `detection_note`; configuration values are not used to guess hardware.
  On macOS, MPS is recorded as the backend. Its GPU model is obtained from
  `system_profiler` only when a single adapter makes the identity unambiguous;
  otherwise the model is `null` with an explanation. CUDA means
  `torch.version.cuda` (PyTorch's build CUDA version, not the driver or local toolkit).
  CUDA is `null` for CPU-only PyTorch; both software fields are `null` if PyTorch
  cannot be imported because it is not installed. MPS runs do not require CUDA;
  a standard macOS PyTorch build records `cuda_version: null`.
  Start time is captured on entry to `run()`, before model loading.
  `git_commit` records the full HEAD commit ID and `git_status` records
  `git status --porcelain=v1 --untracked-files=all` lines, including staged,
  unstaged and non-ignored untracked files. An empty list means clean; `null`
  means the query failed. `git_detection_notes` records per-query errors,
  including a repository with no commit. Git metadata and source hashes are
  collected sequentially after loading players, before games and output creation;
  keep the checkout unchanged during collection and evaluation. Status does not
  capture ignored files or the contents of untracked files.
  All hashes are grouped under `sha256`: `config`, `player_a_checkpoint`, and
  `player_b_checkpoint`. Checkpoint hashes come from the loaded component's
  explicit `provenance_checkpoint_path`, not the configured `checkpoint_path`.
  The built-in factory records the resolved file passed to its network loader,
  or `None` for a non-network scorer. `checkpoint_paths` records absolute paths.
  Custom factories should set `provenance_checkpoint_path` on their returned
  Agent, `agent.scorer`, or `agent.evaluator` to the actual loaded checkpoint
  path (preferably absolute), or explicitly to `None` when none was loaded.
  A missing declaration produces null path/hash and an explanation under
  `checkpoint_detection_notes`; it is not evidence that no weights were used.
  Stale unused INI paths are ignored. Files are hashed in chunks; an unreadable
  declared loaded checkpoint fails the run rather than silently omitting its
  hash. Keep checkpoints unchanged throughout loading
  and evaluation so these hashes describe the loaded weights.
  `stockfish.a` and `stockfish.b` record each player's actual engine executable
  path and the running engine's UCI `name` and `author`. The built-in factory
  resolves project-relative paths or PATH commands before starting the engine,
  and uses that same absolute path for provenance. Executable file hashes are
  stored in `sha256.player_a_stockfish` and `sha256.player_b_stockfish`.
  Network scorers' nested Stockfish instances are included; players without an
  engine (including pure belief networks) have `null` metadata and hashes.
  Resource discovery checks `agent.scorer`, then `agent.evaluator`, then the
  Agent itself, using the first non-null component. Its nested `stockfish`
  instance is also supported. This includes Pair A's managed Stockfish leaves;
  their CPU device is recognized through the evaluator's base classes.
  Custom factories wrapping engines should expose `provenance_executable_path`
  on their engine scorer; missing launch-path metadata is explicitly noted.
  Executables must remain unchanged during loading and evaluation; unreadable
  recorded executables fail provenance collection instead of omitting the hash.
  `sha256.source_files` is a separate mapping from project-relative file
  paths to individual hashes; no aggregate source hash is calculated.
  `source_discovery` is `git` when the project root is a Git repository root:
  `git ls-files --cached -z` discovers its tracked files. When Git is absent
  or the project root is not a repository root, it is `filesystem` and all files
  below the project root are discovered, including caches, ignored files and
  `.git` contents. Directory symlinks are not traversed; they are recorded as
  unreadable entries. Git metadata is `null` with notes in filesystem mode.
  Other Git discovery or status errors abort the run with their cause.
  The `[output] hash_rules` path selects the JSON rules (relative to the project
  root or absolute); omitted settings default to `pair_c/hash_rules.json`.
  The copied rules are read once when loading the INI. Their version,
  `crlf-to-lf-v1`, defines SHA-256 over bytes with CRLF replaced by LF for
  listed text extensions and filenames. Extension and filename matching is
  case-insensitive; listed binary extensions take precedence, and unknown
  extensions default to binary. Standalone CR bytes and all other bytes are
  unchanged. Checkpoints and engines always use raw bytes, regardless of their
  extension. `hash_rules_path` records the original rules path.
  Source hashes describe current working-tree contents, including unstaged edits.
  In Git mode untracked files are excluded, even when not ignored; a tracked
  file deleted before hashing is recorded as `null`. A file that disappears
  during filesystem scanning is also `null`. Other individual read failures
  are recorded as `{"error": "..."}` at the file's path and do not stop the run.
  Directory scanning failures abort because their contents cannot be listed.
  Collection happens before creating the new output directory. File sets in
  filesystem mode can differ across machines and from Git mode.
  An optional isolated smoke check is available via `python pair_c/provenance.py`.
- `games.jsonl`: one JSON record per attempted game, including player identities, Agent/tracker factory paths and colors, seed, winner, termination reason, every move, and per-move elapsed time. Failed games are recorded with an error.
- `summary.json`: Agent/tracker factory paths, wins, draws, losses, win rate, score rate, completed/failed game counts, move timing, and over-budget counts.

Win rate is `wins / games_scored`; score rate is `(wins + 0.5 * draws) / games_scored`.
`games_scored` includes only observed terminal outcomes. `games_completed` counts
successful runner attempts, including `games_capped`; capped attempts have
`winner: null` and remain separate from terminal draws. Both capped and failed
attempts are excluded from outcome rates. Timing includes successful capped
attempts. A run containing only caps has unavailable outcome rates and can
still exit successfully because a cap is a configured stopping condition.

For the included factory, `leaf_depth` must agree with the scorer: Material=0,
Stockfish D1/Network1/belief=1, and Stockfish D11=11. Mismatches raise before
model/engine loading. This validates metadata without changing Pair B's API;
custom search factories should use separate options for their search depth.

## Relation to the Paper

Obscuro's primary AI comparison was a 1,000-game match against ZS21. The paper reports that its AI-versus-AI time budget was usually 5 seconds per move for the main search loop; this excluded legal-position enumeration. This runner defaults to 5,000 milliseconds and records the budget, but the current baseline agent does not enforce it. The paper does not specify the color schedule for the main match. This runner alternates colors each game as a simple, explicit balancing choice. The current `standin` rules and Pair B one-ply players are development baselines, not a reproduction of the paper's complete systems or result.
