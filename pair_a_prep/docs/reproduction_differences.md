# Reproduction decisions and differences

Updated 21 October 2026. **Proposed** is not team approval. Shared changes
already merged to main are the integration baseline for this branch.

| Item | Reference | This repository / preparation | Status and consequence |
|---|---|---|---|
| Source versions | [Z21 v2](https://arxiv.org/pdf/2106.06068v2); [O26 v2](https://arxiv.org/pdf/2506.01242v2) | Pin these in the spec | Verified reference choice |
| Source code and opponents | Original evaluation setting is not available here | We have interface code, not the original agents | No claim of exact result reproduction |
| Engine version | See source map in `paper_specs.md` | Stockfish 19 pilot; production choice pending | Version change must be reported |
| Depth 11 | Project proposal comparison setting | Extra experimental condition | Do not present as the paper's leaf setting |
| Full tracker versus search sample | Different purposes | Exact history tracking implemented in `belief_tracker.py`; optional output sample leaves internal population intact; search budget not frozen | Never describe 256 as full exact belief size; see [tracker notes](belief_tracker.md) for identity and weighting |
| Engine/network input | Shared contract | Merged encoder uses 32 planes | Keep feature metadata consistent with the evaluator |
| Counter visibility | Profile-dependent | Adapter observations hide `halfmove_clock`; hypotheses retain their own clocks | Do not expose hidden referee state |
| Rules backend | Paper profile, Chess.com and OpenSpiel need comparison | Rules adapter passes all 17 proposed fixtures | Passing fixtures does not prove backend equivalence |
| Hardware | Record separately from published hardware | Pilot host reports 16 logical CPUs; engine uses one thread | Do not reuse proposal's desktop specifications as measurements |
| Solve budget | Must specify included work | Pilot times UCI analysis; tracker/search absent | Engine call cost is not full move latency |
| Training labels | Depend on a validated solver | No teacher-label run in this preparation | Raw engine benchmark rows are not TrainingRecord labels |
| Agent ownership and dates | Team allocation | One member owns rules/Obscuro; partner owns ZS21/tracker; mutual review | Complete agents and delivery dates are not established by these prototypes |

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

The shared contract distinguishes raw root policy from the played action and
provides game IDs for whole-game data splits. Final solver labels still require
end-to-end validation. The independent engine benchmark retains its own raw
score measurements rather than serving as a teacher-label generator.

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
