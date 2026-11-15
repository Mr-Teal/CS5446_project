# Technical clarifications for report integration

These are replacement passages and evidence notes for PR #80, not additional report sections. Bryan should select and compress them into the existing ten-page body, then rebuild and check pagination. This document changes neither the report artifacts nor experimental results. Source snapshots below identify which implementation each statement describes; newer policy/PPO work must not be presented as part of the older value-leaf experiments.

## 1. Problem, information and representation

### Suggested replacement passage

Fog-of-war chess is a two-player, zero-sum extensive-form game with imperfect information. The referee state contains the complete piece placement, side to move, castling rights, en-passant information, clocks, and repetition-relevant history. Each player instead receives a private observation: the visibility mask, pieces or empty squares on visible squares, the side to move, a notice of its own captured piece when applicable, terminal information, and the available moves when it is that player's turn. The player also remembers its own actions and observation history. A complete referee state, a private observation, and a neural-network input are therefore different objects.

For player i, let e_i denote its private history and H_i(e_i) the rule-feasible histories consistent with that information. Our tracker maintains candidate histories h_k and exposes the empirical distribution

\[
\hat b_i(h\mid e_i)=\sum_{k=1}^{K}w_k\mathbf{1}[h=h_k],\qquad
w_k\geq0,\quad\sum_k w_k=1.
\]

The implemented tracker uses uniform weights over retained histories. This is a consistency-based approximation, not a calibrated Bayesian posterior over an opponent's play. Even a complete feasible set does not imply correct posterior probabilities: an opponent policy can assign different probabilities to feasible histories, or zero probability to some of them. Sampling, pruning and recovery can further restrict support. The word "exact" in a tracker configuration describes support enumeration under its specified update rules, not probabilistic calibration.

Fixing a complete opponent policy induces a POMDP for the remaining player, with a state augmented by any opponent memory needed to make transitions Markov. Our experiments do not identify this transition model or solve its exact Bayesian belief-state Bellman equation. They instead use sampled information sets and finite search. Thus we should describe the implementation as approximate imperfect-information game search, rather than introduce a separate category "between an MDP and a POMDP." Supplying a candidate set does not make hidden information observable, nor does it automatically produce a fully observed MDP.

### Tensor and action details

The shared belief encoder produces X in R^(K x 32 x 8 x 8), accompanied by weights w in the K-dimensional probability simplex. K is the number of encoded hypotheses, not a spatial dimension. A board has 64 squares; it is not represented as a 64-by-64 image. For Black, ranks are mirrored so that the player's home side is at the bottom; files are unchanged.

| Plane indices | Count | Meaning |
| --- | ---: | --- |
| 0–5, 6–11 | 12 | Own P/N/B/R/Q/K and hypothesised enemy P/N/B/R/Q/K occupancy |
| 12, 13 | 2 | Our visibility; enemy pieces actually visible to us |
| 14–19 | 6 | Weighted enemy-piece occupancy marginals across hypotheses |
| 20 | 1 | Population-size proxy, min(log2(N)/15, 1); retained K is used when the full population is unknown |
| 21, 22 | 2 | Opponent visibility and our pieces visible to it, computed within each hypothesis |
| 23–25 | 3 | Capture recency, ply/200, and search depth/4 |
| 26–31 | 6 | Four castling-right planes, en-passant square, and halfmove clock/100 |

Capture recency and search depth have empty/zero defaults unless supplied by the caller. These channels must not be described as guaranteed populated history features. The occupancy marginals are not a joint distribution over boards; the retained concrete hypotheses carry joint piece configurations. Neither this compressed tensor nor a current FEN is guaranteed to be a sufficient statistic for the complete private history.

The game action is a move (source square, destination square, optional promotion piece), represented in UCI form. The newer standalone policy uses 4,096 source–destination slots, a = 64*source + destination, with illegal slots masked before softmax. This is an output indexing scheme, not 4,096 legal moves in a position. Its queen-only promotion convention restricts the policy's action representation; it does not represent all underpromotions allowed by the rules. The PPO implementation also has 4,096 logits but uses its own move-type mapping; the two indices should not be assumed interchangeable.

## 2. What follows the papers, and what this project contributes

### Suggested replacement passage

Our contribution is an open implementation and empirical investigation of selected published mechanisms, with substantial computational and modelling approximations. The tracking and search ideas follow Zhang and Sandholm's fog-of-war chess work, including ZS21 and Obscuro; we do not claim to invent belief tracking, PCFR+, one-sided tree growth, resolving gadgets, or the Stockfish-based leaf transformation. Pair A implemented rule adaptation, tracking/search interfaces and prototypes of these mechanisms; Pair B investigated learned evaluators and later direct policies. The experiments provide configuration-specific evidence about value prediction, move selection and practical failure modes, rather than a reproduction of published Obscuro strength.

| Inherited idea | Local implementation / qualification |
| --- | --- |
| Observation-consistent hidden-state tracking | Enumerated candidate histories with bounded or guarded variants; uniform retained-history weights are not an inferred opponent posterior |
| PCFR+ and growing imperfect-information search | Finite sampled games with explicit round, depth, node and evaluator limits |
| Knowledge-limited subgames, resolving gadgets and purification | Selected mechanisms have local implementations and tests; not every experiment enables the same mechanism |
| Stockfish leaf values and bounded value scaling | Published lineage must be credited; our engine versions, budgets and implementations differ |

For scale context, the Obscuro paper reports an average search depth of 10.7 plies and about 1.07 million tree nodes under its reported five-second search setup, excluding enumeration. Our reported capped experiments use a maximum depth of two and root samples of four or sixteen boards. Hardware, timing scope and algorithms differ, so this is a scope warning, not a speed comparison. The paper's minimum-information-set sampling parameter of 256 should not be described as a universal fixed sample size for every Obscuro invocation.

Defensible findings are narrower than community-wide novelty claims: a lower teacher-value error did not establish improved play in the tested Network 1 comparisons; a search-trained engine-free leaf beat material evaluation in a separate weak-baseline arm; and input ablations distinguish access to hidden-piece hypotheses from the benefit of a particular set/context architecture. The available records do not establish that the full belief architecture improves gameplay, nor identify a causal explanation for the prediction-error/play-strength gap.

## 3. Keep the experimental configurations separate

The following studies are not one common search experiment. Within a study, leaf substitutions hold the stated configuration fixed; this still does not guarantee equal realised computation or identical explored trees.

| Study | Planner / tracker / limits | Result and interpretation |
| --- | --- | --- |
| Earlier one-ply matches | Weighted child-board values, no PCFR; eight sampled boards from a 256-particle setup; paired random openings; older runtime a5c5fb6 | Network 1 scored 0.515 over 200 games. This is an older one-ply protocol, not evidence about the later subgame solver. |
| Network 1 vs depth-1 Stockfish, anytime | Uniform growth, initial/max depth 1/2; four boards; up to 16 solver rounds; 4,096 nodes and 128 evaluator calls; bounded-history tracker with 8,192 retained histories, eight recovery attempts and separate 60-second tracking allowance; five-second cooperative search budget | 100 attempts; 93 terminal games and seven failures. Restricting to 44 jointly completed colour pairs gives 41–47, score 0.466, paired-bootstrap interval [0.364, 0.568]. This conditions on joint completion; it is neither equivalence nor an unconditional success-rate estimate. |
| Search-trained v2 vs material, subgame | One-sided subgame growth, depth cap two; sixteen boards; up to 1,024 rounds; 16,384 nodes and 4,096 evaluator calls; guard tracker with 96,000-state threshold; configured time_budget_ms=5000 | 77–0–11 across 88 terminal games, ten failed and two unplayed; score 0.875, game-level Wilson interval [0.790, 0.929]. This is a different model, opponent, tracker and search configuration from the Network 1 study. |

The subgame guard prunes before an update when its threshold is exceeded. That threshold is not a strict bound on transient or post-update memory. Its configured timing must not be equated with the anytime study's search-only allowance without checking runner timing scope. Neither configuration is a hard process-level time/RSS guarantee. Do not pool the intervals above: they use different units and completion rules. The anytime study treats a 200-ply cap as an unscored diagnostic, whereas the older one-ply protocol counted its cap as a draw.

## 4. Data collection, objectives and actual deployment

### Suggested replacement passage

We collected labels using our Obscuro-inspired finite-search implementation, not the unavailable original Obscuro executable. Games begin from the public initial position, with random opening moves while both trackers receive their legitimate observation streams. At labelled turns, the agent samples observation-consistent hypotheses, constructs and solves its configured finite game using Stockfish frontier evaluations, and records the agent input, root policy, root/per-hypothesis values and selected move. Failed label solves use a fallback move without fabricating a training label. Valid records already produced in a subsequently failed game can remain in the dataset, so completed-game counts and labelled-game counts differ.

The later rounds scheduled 480 games, with 445 completed games, 35 failures and 22,771 recorded positions. These are not all the data used by the played checkpoint: belief-solver-v2-sf8-g237 came from a 237-game snapshot, split into 196 training, 25 validation and 16 test games. Its label protocol used sixteen hypotheses, depth-8 Stockfish and a 30-second solve allowance. The full later dataset and the earlier checkpoint must not be described as the same training run. Roughly ten percent of label-or-fallback decisions in the later rounds used fallback moves; failures concentrated on expensive positions can bias the retained data. Complete label archives are not committed, so some reported validation numbers can be checked against handover summaries but cannot be independently recomputed from Git alone.

### Distinguish the optimisation targets

The game objective is expected terminal utility (+1 win, 0 draw, −1 loss). A reported match score instead uses 1, 0.5 and 0. They are related scales but should be defined separately. Finite-game PCFR+ updates aim at strategies for the constructed local zero-sum game, including its chosen gadget objective; they do not certify a globally optimal strategy in full fog-of-war chess.

Value training minimises a regression loss, for example

\[
L_V(\theta)=\frac1N\sum_j\bigl(v_\theta(x_j)-y_j\bigr)^2.
\]

For Network 1, y is a scaled deeper-Stockfish teacher evaluation. For solver-trained v2 it is a value produced by the specified finite-search label protocol. Neither target is automatically the optimal POMDP belief value. MAE is a reported prediction metric, not the MSE training objective. Where centipawn scores are used, the transformation is tanh(cp/600); the engine version and search depth must accompany each teacher name.

### Network identities and call sites

| Model | Input and architecture | Training / actual use |
| --- | --- | --- |
| Network 1 | 19 x 8 x 8 board planes; six residual blocks with 64 channels; value head combines board features with a depth-1 Stockfish scalar | Learns a correction v=tanh(atanh(clip(d1))+f_theta(X,d1)). It still calls depth-1 Stockfish during deployment; it is not engine-free. |
| Belief value network / search-trained v2 | Shared 32-plane hypothesis encoder, weighted context aggregation and per-board value outputs; checkpoint configuration distinguishes the variants | Trained on sets of hypotheses. The evaluated search leaf call supplies one concrete frontier board at a time, making K=1 and collapsing set context. V2 without the D1 feature is engine-free at inference. |
| New standalone policy | Shared 32-plane convolutional encoder, six 64-channel residual blocks, weighted feature aggregation, masked 4,096-slot move output | Trained on search root policies with cross-entropy, L_pi=-sum_a pi_search(a) log pi_theta(a). It can consume the whole supplied belief/fuzzy input to choose a move directly; this is a different route from the older value-leaf experiments. |
| New PPO agent | 25 observation/memory planes, four 64-channel residual blocks, policy and value heads | Direct self-play learning without the explicit tracker or Stockfish labels. Its clipped policy objective, value loss, entropy term and reward shaping require their own description; it is not continued training of the old v2 leaf. |

In these descriptions, a residual block contains two spatial convolutions and a skip connection; channels are learned feature maps, not candidate boards or chess squares. The 32-plane breakdown above belongs to the shared belief encoder and must not be used as Network 1's 19-plane or PPO's 25-plane specification.

Consequently, the older value-leaf experiments do not test the originally intended belief-aware frontier value function: the search does not propagate a full successor belief to that network. This is an implementation limitation, not proof that belief-value learning is useless. Offline ablations also do not establish the necessity of the set architecture: fuzzy/context-removed/single-board variants have similar errors in the recorded comparisons, while removing hidden-piece hypotheses hurts prediction. Report these as separate findings.

### Later work: include only after owner confirmation

The policy handover reports 58,693 relabelled positions, including data from initial games and a later self-play generation. This shows a data-generation/retraining component, but does not establish a completed iterative improvement loop for the original value network. The standalone policy and PPO handovers contain additional matches against simple opponents; these cannot be attached to the old Network 1 or v2 results. PPO does implement a separate self-play optimisation loop, but its training and match claims need the responsible authors' review before integration. No new training, policy/PPO rerun, or full raw-result recount was performed for this supporting note.

## 5. Evidence ledger and integration checks

Use the pinned snapshots rather than assuming all work is present on main. A handover assertion is weaker evidence than a committed raw record or code path. The two search-result rows above must retain their distinct configurations even if their prose is shortened.

| Evidence | Pinned source |
| --- | --- |
| Observation contract and encoder | [contracts.py](https://github.com/Mr-Teal/CS5446_project/blob/3335723852ad59ccbe5e999dbe0ce2773f7e56d0/fow_shared/contracts.py), [features.py](https://github.com/Mr-Teal/CS5446_project/blob/3335723852ad59ccbe5e999dbe0ce2773f7e56d0/fow_shared/features.py) |
| Published lineage | [ZS21, arXiv v2](https://arxiv.org/abs/2106.06068v2), [Obscuro, arXiv v2](https://arxiv.org/abs/2506.01242v2); distinguish their engine settings and the implementation's settings |
| One-ply experiment archive | [batch-2026-10-27](https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27); recorded runtime a5c5fb696bda20f0312abd2a7af020bd6388a6ad |
| Network 1 anytime results | [Pair C README and raw archive](https://github.com/Mr-Teal/CS5446_project/tree/8c7baf758e40f8a23c09b273903cff0aee38d2cb/pair_c/evaluation_20261110); runtime aaa000a034ae5275afe981402891596e660312a4 |
| Search, labels, model snapshots and ablations | [10 November detailed handover](https://github.com/Mr-Teal/CS5446_project/blob/db28b6a6d3ce0a7314c0dafabf290c1eb666b92f/pair_a_prep/docs/handover_2026-11-10.md), [12 November handover](https://github.com/Mr-Teal/CS5446_project/blob/db28b6a6d3ce0a7314c0dafabf290c1eb666b92f/pair_a_prep/docs/handover_2026-11-12.md), [implementation status](https://github.com/Mr-Teal/CS5446_project/blob/db28b6a6d3ce0a7314c0dafabf290c1eb666b92f/pair_a_prep/docs/obscuro_status.md) |
| Subgame raw matches | [strength arms archive](https://github.com/Mr-Teal/CS5446_project/tree/db28b6a6d3ce0a7314c0dafabf290c1eb666b92f/pair_a_prep/results/strength_arms_2026-11); configuration and per-file manifests, not one claimed frozen runtime for all arms |
| Later standalone policy | [policy handover](https://github.com/Mr-Teal/CS5446_project/blob/ca3993c6667fba254921d9347f566a88f74909f7/pair_b/docs/handover_policy_network_2026-11-15.md) |
| Later PPO, PR #84 snapshot | [PPO handover](https://github.com/Mr-Teal/CS5446_project/blob/f42317e0a00926357d7ab33d220743dbc3fa5cc4/pair_b/docs/handover_ppo_agent_2026-11-15.md) |

Before integration: Bryan should check narrative and the ten-page body limit; Tommy should confirm label/checkpoint provenance and the scope of the new policy/PPO results; Colin should confirm the model/input specifications and which later results are actually intended for submission. Keep unsupported or unverified later claims out of the final abstract. Rebuild report artifacts only after those selections, with a consistent model/configuration name beside every reported result.
