# Reproduction decisions and differences

Status on 17 October 2026. **Proposed** is not team approval. This preparation
does not accept or modify [Pair B PR #1](https://github.com/Mr-Teal/CS5446_project/pull/1).

| Item | Reference | This repository / preparation | Status and consequence |
|---|---|---|---|
| Source versions | [Z21 v2](https://arxiv.org/pdf/2106.06068v2); [O26 v2](https://arxiv.org/pdf/2506.01242v2) | Pin these in the spec | Verified reference choice |
| Source code and opponents | Original evaluation setting is not available here | We have interface code, not the original agents | No claim of exact result reproduction |
| Engine version | See source map in `paper_specs.md` | Stockfish 19 pilot; production choice pending | Version change must be reported |
| Depth 11 | Project proposal comparison setting | Extra experimental condition | Do not present as the paper's leaf setting |
| Full tracker versus search sample | Different purposes | Full tracking not implemented; sample budget not frozen | Never describe 256 as full exact belief size |
| Engine/network input | Shared interface under review | Existing encoder 26 planes; PR proposes 32 | Avoid generating final teacher data before agreement |
| Counter visibility | Profile-dependent | Existing mandatory `halfmove_clock` needs review | Do not expose hidden referee state by default |
| Rules backend | Paper profile, Chess.com and OpenSpiel need comparison | 17 proposed acceptance fixtures | No production FoW adapter implemented |
| Hardware | Record separately from published hardware | Pilot host reports 16 logical CPUs; engine uses one thread | Do not reuse proposal's desktop specifications as measurements |
| Solve budget | Must specify included work | Pilot times UCI analysis; tracker/search absent | Engine call cost is not full move latency |
| Training labels | Depend on a validated solver | No teacher-label run in this preparation | Raw engine benchmark rows are not TrainingRecord labels |
| Agent ownership and dates | Team allocation | Still unassigned in this work | No schedule promised on teammates' behalf |

## How to record later decisions

Each agreed experiment should name the rules profile and its source revision,
tracker policy (including any truncation), root sample policy, agent code
revision, evaluator version, feature version, engine executable hash, Threads,
Hash, depth/limit, seed and time-budget scope. Record observed machine details
with the run instead of copying the proposal's assumed hardware.

If a full tracker must be capped, retain the fact that the candidate population
is now approximate. Do not set a falsely exact population count, silently
insert the true board, or recover an empty belief from referee state. An empty
belief should produce a diagnostic failure until a documented recovery method
is chosen.

Game-level train/validation/test grouping and raw versus played policy need
agreement with Pair B. The independent benchmark intentionally avoids both
their `values.py` conversion and their proposed LeafEvaluator interface.

## Rules profile caveats

The fixtures use the proposed paper profile: no king-safety restriction on
moves, special fog visibility, actual king capture for a referee win, automatic
history-based draws, and no automatic insufficient-material draw. They assert
ordinary stalemate can still have fog moves; a forced-loss heuristic must not
be confused with an already finished game. The clock and repetition count are
treated as hidden unless a different environment profile is explicitly chosen.

Review these choices together before calling the fixture set authoritative.
The official [Chess.com explanation](https://support.chess.com/en/articles/8708650-what-is-fog-of-war-chess)
helps with special visibility. Check the chosen [OpenSpiel dark_chess source](https://github.com/google-deepmind/open_spiel/blob/master/open_spiel/games/dark_chess/dark_chess.cc)
if using that backend; its observation and draw behavior must not be assumed
identical. A FEN cannot supply threefold-repetition history by itself.
