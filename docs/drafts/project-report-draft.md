# Better Value Predictions, Same Moves

Value Estimation for Belief-Sampled Fog of War Chess

CS4246/CS5446 Reinforcement Learning and Sequential Decision Making

National University of Singapore School of Computing

Semester 1 AY2026/27

13 November 2026

DING Chiyu; PEI Shengxin; QUEK Hongqiang Colin; KUAH Jun Hong Bryan; WANG Zhijian; LIN Tzu-Chun.

---

## Abstract

Fog of War chess hides the opponent's pieces, so a player must act on a belief about the position rather than a known board. Against a fixed opponent this is a partially observable Markov decision process (POMDP), whose optimal play requires values over beliefs. We study a common tractable simplification: a rule-based tracker supplies boards consistent with the player's observations, each board is scored by a full-board value function, and the scores are averaged, as in QMDP and determinization. Within it we ask whether reducing value-prediction error improves decisions. A learned correction to depth-1 Stockfish (Network 1) reduces error against depth-11 Stockfish by 20%, yet the value lost by chosen moves and game scores do not measurably improve; a linear correction recovers most of the gain. Models trained on game outcomes with Monte Carlo and temporal-difference targets predict results better but select moves that lose more deep-engine value, and belief context improves prediction without an established game gain. A search agent using Network 1 scores 46.59% (95% interval 36.36%–56.82%) against the same agent using depth-1 values. Under this approximation, lower average value error is not sufficient for better decisions.

## 1 Introduction

Perfect-information chess engines far exceed human strength, but many real decisions are made with hidden information. Fog of War chess keeps the moves of chess but hides information. Each player sees only their own pieces and the squares those pieces can reach, and a game is won by capturing the opponent's king. One view can be consistent with several hidden positions in which the same move is safe in one and loses the game in another [1]. The strongest published agents treat the game as a two-player imperfect-information game and combine subgame solving with large-scale search [2, 3].

Against a fixed opponent, the problem is a POMDP: optimal play needs a value function over beliefs, which is intractable here because beliefs range over very large sets of hidden histories [4, 5]. We therefore study a standard simplification. A rule-based tracker computes the boards consistent with the player's private observations, so belief inference is not learned. Each sampled board is scored as if it were fully observed and the scores are averaged. In POMDP terms this is the QMDP approximation [6]; in game search it is determinization, or perfect-information Monte Carlo search [7, 8]. It reduces the problem to predicting full-board values, at the known costs of ignoring the value of information and of strategy fusion.

Search with learned values at its frontier underlies strong game agents [9-11], and within our simplification value estimation is the bottleneck. Deep engine search gives accurate values but is slow: in our matches, depth-11 Stockfish takes about 220 times as long per move as depth 1. We ask: RQ1, does a learned correction that reduces the error of cheap depth-1 values also improve move selection and game score? RQ2, how do the training target (deep-engine values versus game outcomes) and belief context change what the value function learns? RQ3, does a stronger search planner change these conclusions?

We contribute a Fog of War environment with private observations and consistency tracking, interchangeable value functions, two search planners and audited match records [12-14]. Our main finding is that substantial reductions in value error do not translate into measurably better decisions, and we analyse why.

## 2 Problem formulation

### 2.1 Fog of War chess as a POMDP

The referee state s_t comprises piece placement, side to move, castling and en-passant rights, clocks and repetition history. After each ply a player receives a private observation o_t: its own pieces, the squares they can reach with their contents (including visible emptiness), its legal actions when it is to move, notice of captured own pieces and the game result. Unseen squares are unknown, not empty, and legal actions are themselves evidence.

Against a fixed opponent policy, the game is a POMDP (S, A, T, O, R) [4, 5]. A contains our legal moves; T applies our move and then the opponent's response; O gives our private feedback; R is +1/0/-1 at the end of the game, without discounting. If the opponent keeps private memory, that memory belongs in the hidden state. With e_t denoting our history of observations and own actions, the belief b(s) = P(s | e_t) is updated by b'(s') = η O(o' | s', a) Σ_s T(s' | s, a) b(s), where η normalizes [5]. Optimal play maximizes a value function V*(b) defined over beliefs. A masked board is not a Markov state: earlier evidence changes which hidden positions remain possible. Our experiments always face a fixed opponent, so this formulation describes them. When the opponent adapts, the problem is a two-player imperfect-information game, or partially observable stochastic game, whose strongest agents compute equilibrium strategies [3, 15, 16].

### 2.2 Our simplification: sampled beliefs and full-board values

We make two simplifications. First, belief inference uses rules rather than learning. The search tracker enumerates histories consistent with e_t and samples K of them uniformly, giving an empirical belief b_hat(h) = (1/K) Σ_k 1[h = h_k]. When tracking is exact this has the correct support, but uniform weights are not the Bayesian posterior, because they ignore how likely the opponent was to choose each move. The archived one-ply experiments use an approximate particle tracker instead (Section 3).

Second, the value of a belief is approximated by averaging full-board values, V(b) ≈ Σ_h b_hat(h) V_full(h), and the one-ply planner chooses the move maximizing the averaged value of the successor boards. This is the QMDP approximation: it values each hidden board as if it would become fully visible after the move [6]. In game search the same idea is determinization, or perfect-information Monte Carlo search [7, 8]. It is cheap and often strong, but it assigns no value to gathering information, and it can assume different follow-up moves in boards the player cannot tell apart (strategy fusion) [7, 8]. Within this approximation, decision quality depends on how well V_full ranks successor boards.

### 2.3 Value functions and search

Our value functions V_full score full boards from the moving player's perspective in [-1, 1]: piece values, Stockfish 19 at depth 1 (D1, fast) and depth 11 (D11, slow), and learned corrections of D1 toward D11. Beyond one-ply lookahead, a second planner runs predictive counterfactual regret minimization (PCFR+) on a growing tree over sampled hypotheses, adapting knowledge-limited subgame solving [2, 3]. Like DeepStack and ReBeL [10, 11], it relies on values at the search frontier, but without their guarantees for our sampled trees and full-board labels. Learning to predict values and improving decisions are distinct goals [17]; whether the first delivers the second is our central question. Table 1 lists the course methods this problem calls for, why some cannot be applied directly here, and what we use instead.

**Table 1.** Course methods: what applies to Fog of War chess and what we use instead.

| Course method | Why not applied directly | What we use instead |
|---|---|---|
| Exact POMDP / belief-state MDP solution [4, 5] | Beliefs range over very large sets of hidden histories, and transitions need a model of the opponent's policy | Rule-based tracking of consistent histories, sampled to K boards (Section 2.2) |
| Bayesian belief update [5] | Requires the opponent's action probabilities, which we do not have | Uniform weights over consistent histories: correct support, not a posterior |
| Belief-space value function V(b) [4, 5] | Training labels would need belief-level search or solver output, which we did not generate | Average of full-board values (QMDP / determinization) [6-8] |
| Decision-time tree search such as MCTS [9] | Searching sampled full boards independently causes strategy fusion across indistinguishable states [7] | One-ply lookahead as a controlled baseline; PCFR+ over information sets [2, 3] |
| Game-theoretic equilibrium solving [15] | Full-game solving at published scale exceeds our compute; our evaluations face a fixed opponent | Local PCFR+ subgame solving within node, call and time budgets (Section 3) |
| Model-free RL with MC and TD [17] | An online self-play improvement loop was not implemented within the project timeline | MC and TD fitted to recorded games, and distillation from deep Stockfish (Section 4.2) |

## 3 System

A referee holds the true board. Each agent receives only its private observations and its own actions, and its value functions see only boards inferred from them; offline labels and post-game diagnostics use separately recorded complete positions [12]. Visibility covers own squares and the squares own pieces can move to, ignoring check. Pawn diagonals reveal capturable pieces, an available en-passant capture reveals the target pawn, and blocked forward pawn squares stay hidden unless another piece sees them. Kings can be captured, and rule-decided positions are scored before any engine or network call. Fixtures test visibility, castling, en-passant and draw cases.

Two trackers implement the first simplification of Section 2.2. The search tracker starts from the public initial position, applies our known moves, enumerates every possible opponent move, regenerates the feedback each would produce and keeps only matching histories; complete tracking therefore returns exactly the consistent support. To bound memory, the version used in the search batch keeps at most 8192 uniformly chosen histories after each update and, if later evidence eliminates them all, replays the full private observation stream to recover. Pruning can drop the true history and recovery can fail (Section 6.5) [18]. The one-ply experiments instead use a 256-particle tracker that relocates hidden pieces to fit current feedback without certifying the complete past. Training beliefs for the belief network are synthetic: hidden pieces are relocated consistently with the generating observation, without requiring a legal complete history [13].

![Agent information flow and replaceable leaf evaluator](report-assets/agent-pipeline.png)

**Figure 1.** Private evidence feeds tracking and decision making; a value function scores the frontier. Both planners share this boundary, but swapping value functions does not equalise computation [12, 13].

Value functions receive boards in a shared 32-plane encoding: 12 piece, four visibility, seven belief-summary, three context and six rule-state planes. Belief summaries are occupancy marginals of the sampled boards, not a joint posterior, so the encoding is not a sufficient statistic of the belief. Network 1 uses the 19 board planes plus the D1 score; the belief network uses all 32 [13].

The search planner groups sampled histories into information sets, runs PCFR+ and grows the tree under node, evaluator-call and time budgets; the search batch uses its uniform-growth anytime mode rather than every optional mechanism [12]. Budgets are cooperative rather than hard deadlines, and earlier pilots exposed long-game tracking failures [19]. Each experiment retains the rules and source revision it was run with [12, 14].

## 4 Learned leaf evaluation

### 4.1 Data and targets

D1 and D11 (quick and careful Stockfish in the tables) use Stockfish 19, which differs from the engine versions in the source papers. Values use the acting-player perspective in [-1, 1]: tanh(c/600) for centipawns c, and ±1 for forced mate [13].

Solver labels were unavailable at generation time. We sampled four parents from each of 8,000 ordinary-chess practice games mixing Stockfish and random moves. MultiPV scores child moves together; Fog-rule checks override rule-decided positions.

A hash of game identity assigns 80% of games to training, 10% to validation and 10% to a sealed test bucket. The reported check set is a separate generation with a different seed: 959 games, 3,818 decisions and 94,963 eligible children after excluding rule-decided children. It also helped compare three Network 1 candidates, so the reported measurements are development results, not a sealed-test estimate [13].

### 4.2 Evaluators and learning targets

Material uses weights 1/3/3/5/9. Ridge correction uses 1,217 board features and D1 value v1; its bounded version is v = tanh(atanh(clip(v1)) + w·x + b), clipping inside (-1, 1). Network 1 substitutes a 521,000-parameter CNN correction. Both regress toward D11 and still incur the D1 engine call [13].

The 562,000-parameter belief network combines board embeddings with weighted belief context. Its architecture can vary a board's prediction with context, but practice labels are each board's belief-independent careful-Stockfish value. Synthetic candidates have the limitations in Section 3 [13].

We also train the bounded linear model on game outcomes. Monte Carlo (MC) uses the final result as its target. TD(0) bootstraps from the next state's estimate; because values follow the side to move, an ordinary nonterminal one-step target changes sign. TD(λ), with λ = 0.8, combines returns over different horizons. These are fitted prediction experiments using recorded trajectories, with semi-gradient targets and up to 15 TD rounds. They do not implement an online policy-improvement loop [17, 20].

## 5 Evaluation method

### 5.1 Offline metrics

Mean absolute error measures agreement with D11. Same top move allows teacher ties; value lost is best eligible sibling teacher value minus the chosen move's teacher value. Evaluator ties use UCI order [13]. Paired differences use 2,000 bootstrap resamples of whole games to preserve within-game dependence. MC/TD also measure final-outcome MSE on a different trajectory population, stated in Table 3 [20].

### 5.2 Archived one-ply matches

Each candidate faces the D1-evaluator agent on 100 random openings of two to eight plies, repeated with colours swapped. D1 scores hypothetical full boards; its agent still receives only private observations and tracked hypotheses, not an omniscient view. Win/draw/loss scores are 1/0.5/0; averages use complete colour pairs. We retain pair-bootstrap and approximate Wilson intervals. This protocol counts a 200-ply cap as a draw [14, 21].

Evaluator agents share one-ply planning, particle and hypothesis counts; random selects actions directly. Total work differs. Decision latency excludes tracking. Stockfish uses one thread, 16 MB hash, clears between games and retains state within games; its 60-second call watchdog is not an equal-time move budget.

The one-ply batch ran on 26–27 October with an earlier rule implementation, before later no-move-draw and en-passant-repetition fixes. No no-move endings occurred, but child values need not match later rules. Its seven comparisons remain separate from later games [14, 21].

### 5.3 Later search comparison

We schedule 50 colour pairs (seeds 1001–1050) of the search agent using Network 1 against the same agent using D1. Both use four hypotheses, depth 1 growing to at most 2, 16 solver rounds, 4096 nodes and 128 evaluator-call caps. Search allows five cooperative seconds; bounded-history tracking separately allows 60 seconds and eight replays. Equal caps imply neither equal work/reached depth nor a hard whole-turn deadline. The 200-ply diagnostic cap is unscored; only jointly clean terminal pairs contribute to score, while failures remain separate [22].

Tracking and Stockfish 19 (one thread, 16 MiB hash) run on CPU and Network 1 on a laptop GPU. The archive pins code, configurations, checkpoint and engine versions [22].

## 6 Results

### 6.1 Lower value error does not yield better move choices

**Table 2.** Development check against D11: 94,963 eligible children, 3,818 decisions, 959 games. Cost: median CPU time per parent's children, separately timed on 300 parents [13].

| Evaluator | Value error | Same top move | Value lost | ms per parent |
|---|---|---|---|---|
| Piece values | 0.336 | 27.7% | 0.2108 | 0.6 |
| Quick Stockfish | 0.095 | 42.9% | 0.0355 | 1.4 |
| Linear correction | 0.084 | 41.5% | 0.0346 | 1.7 |
| Linear inside tanh | 0.079 | 43.5% | 0.0348 | not timed |
| Network 1 | 0.076 | 42.4% | 0.0352 | 12.2 |

Network 1 reduces error about 20%: paired difference -0.019, 95% interval [-0.021, -0.018]. Value-lost difference is -0.0003 [-0.0017, +0.0011]; neither improved selection nor equivalence is established.

Linear correction captures 56% of Network 1's error reduction, or 83% with bounded parameterization. Network 1 costs nine times D1 on CPU; on a laptop GPU it takes 4.4 ms per parent, still three times D1.

Errors in decided positions may not change actions, whereas small errors in close positions can reverse rankings. Figure 2 suggests this explanation, but a targeted ablation is needed for causality.

![Value error by position category](../../pair_b/experiments/tanh_linear/value-error-by-band.png)

**Figure 2.** Development error by teacher assessment. Corrections improve decided positions but worsen close ones; bin definitions and analysis remain archived [13].

### 6.2 The training target determines what the value learns

Distillation fits 638,451 child rows from 6,414 training games. MC/TD drop 175 unfinished training games and use 722,500 trajectory positions from 6,239 finished games. Thus the target and training-row distribution both change. MC and TD never receive careful Stockfish's values [20].

**Table 3.** Bounded linear model, different targets. Teacher population: Table 2. Outcome MSE: 106,971 positions/929 finished check games; 32 unfinished excluded from 961 replayed games [20].

| Training target | Value error | Outcome MSE | Same top move | Value lost |
|---|---|---|---|---|
| Careful Stockfish | 0.079 | 0.513 | 43.5% | 0.0348 |
| Game result with MC | 0.217 | 0.481 | 38.6% | 0.0505 |
| TD(0) | 0.185 | 0.476 | 42.1% | 0.0370 |
| TD(λ) with λ = 0.8 | 0.208 | 0.476 | 41.5% | 0.0415 |
| Quick Stockfish without learning | 0.095 | 0.497 | 42.9% | 0.0355 |

Outcome-trained models better predict practice returns but worsen teacher agreement/action value. TD(0)'s outcome MSE improves over MC by 0.0053 [0.0010, 0.0097]. Predicting a weak, partly random policy's returns differs from approximating stronger continuation play.

Both TD methods reach 15 rounds. A 40-round diagnostic barely changes outcome MSE and worsens teacher error; the cap alone does not explain the gap. This dataset/model result does not establish general inferiority of outcome-based RL [20].

### 6.3 Belief context improves prediction, not demonstrated decisions

On 3,818 synthetic check beliefs, the belief network reduces board error from quick Stockfish's 0.080 to 0.074 and weighted-belief error from 0.055 to 0.047. The latter difference is -0.008 [-0.009, -0.007], resampling the 959 source games. Across five training seeds, mean board error is 0.0734 with context and 0.0762 without it; every seed improves [13].

Each board's target is belief-independent. Context can denoise predictions without learning information's strategic value: different beliefs may require different strategies despite the same board label. Establishing strategic value needs information-sensitive labels and action comparisons.

### 6.4 Game outcomes with one-ply lookahead

**Table 4.** Against D1, 200 games/row. Scores/intervals: complete colour pairs (100/row; random 99). W/D/L: all finished games, including random's unpaired survivor. Cost: candidate median decision latency, excluding tracking [14, 21].

| Evaluator | Score | Bootstrap 95% | Wilson 95% | W/D/L | ms per move |
|---|---|---|---|---|---|
| Quick Stockfish | 0.520 | 0.455-0.588 | 0.423-0.615 | 103/2/95 | 11.1 |
| Random moves | 0.000 | withheld | 0.000-0.037 | 0/0/199 | 0.005 |
| Piece values | 0.048 | 0.023-0.078 | 0.020-0.108 | 9/1/190 | 4.3 |
| Linear correction | 0.513 | 0.455-0.573 | 0.416-0.608 | 98/9/93 | 14.2 |
| Network 1 | 0.515 | 0.448-0.585 | 0.418-0.611 | 100/6/94 | 36.1 |
| Belief network | 0.563 | 0.495-0.630 | 0.465-0.656 | 111/3/86 | 149.8 |
| Careful Stockfish | 0.585 | 0.513-0.660 | 0.487-0.677 | 114/6/80 | 2,452 |

There are 1,399 finished games and 699 complete colour pairs. One random-row game failed because quick Stockfish's tracker found no board consistent with its observations. Its surviving partner remains in W/D/L but is excluded from paired estimates. Random's bootstrap is withheld because every complete pair scores zero. Six draws reached the 200-ply cap: two linear and four careful-Stockfish games. All other draws were repetitions.

Random/material controls score poorly and self-play includes 0.5. Network 1/linear gains are unestablished. Belief-network intervals include 0.5. Careful Stockfish's bootstrap interval narrowly excludes 0.5, but Wilson includes it and seven-comparison adjustment removes the nominal finding. These separate matches against D1 are not a head-to-head ranking.

Network 1, belief network and D11 take respectively three, thirteen and 220 times D1's median decision time. The belief network receives singleton hypotheses, so this row does not test whole-belief context. An independent audit recomputed outcomes, intervals, timings and hashes without rerunning games [14].

### 6.5 Game outcomes with search

All 100 planned games were attempted: 93 reached a terminal result and seven failed, with none capped, missing or unplayed. Failures affected six pairs, leaving 44 clean pairs (88 games). On those pairs, Network 1 recorded 41 wins, 47 losses and no draws: a paired score of 46.59%, with a whole-pair bootstrap 95% interval of 36.36%–56.82%. The analysis uses 20,000 whole-pair resamples. It establishes neither a Network 1 advantage nor statistical equivalence [22].

Failures comprise four replay-support losses, two update timeouts and one pruning timeout. Six excluded pair seeds and raw failures remain in the archive. Surviving partners do not enter paired scoring: the estimate conditions on joint completion, not all scheduled seeds. Six of the seven failures occurred in the D1-leaf agent's tracker; scoring all 93 terminal games instead gives 46.24%. Earlier readiness games on two other seeds are reported separately [22].

Against the same search agent using D1 leaves, the Network 1 variant has a 46.59% clean-pair score, not an established improvement. Completion is 93% of attempts; this is a separate reliability measure. Table 4's random/material controls establish a performance floor for the older one-ply system, not for this search batch. Neither study compares our search to a POMDP-optimal agent, the published Obscuro agent, or one-ply under matched whole-turn compute. We therefore report measured baseline-relative performance, without claiming published strength or a search-algorithm advantage.

## 7 Discussion and limitations

Why do better predictions not give better moves? Under the QMDP-style approximation a move is chosen by comparing averaged successor values, so only errors that change the ranking of candidate moves matter. Learned corrections improve decided positions, where rankings rarely change, but slightly worsen close positions, where they do (Figure 2). Mean absolute error therefore weights the wrong positions for decision making. Ranking-aware or decision-weighted losses are a natural next step, although a targeted ablation is needed to establish this cause.

The training target matters as much as the model. Distillation predicts a full-board teacher, and MC and TD predict returns of the weak practice policy that generated the data; neither encodes the value of information. Belief context helps prediction even with belief-independent labels, but the belief-space value V(b) that a POMDP requires needs labels that depend on what the player knows [4, 5]. Better full-board accuracy also cannot recover what the averaging approximation discards: QMDP-style values never reward moves that reveal information, and determinization can suffer strategy fusion [6-8].

For the research questions: on RQ1, a 20% error reduction leaves move-level value lost and one-ply game scores unchanged. On RQ2, outcome targets trade teacher agreement for outcome prediction, and belief context denoises prediction without demonstrated strategic value. On RQ3, the search planner shows no Network 1 gain either.

Data are ordinary-chess practice games with synthetic beliefs, results are development-set measurements against approximate teacher values, game splits do not exclude all transpositions, and MC/TD change training rows as well as targets [13, 20]. The one-ply batch uses older rules, one opponent, unequal compute and single-board belief-network inputs; the search batch conditions on joint completion. Neither tracker has established posterior calibration or true-history retention, and cooperative budgets limit search. We compare against fixed baselines, not a POMDP-optimal agent, matched whole-turn compute or published Obscuro strength. Future work should train belief-space values with information-sensitive labels, evaluate with decision-aware error measures and compare planners under equal whole-turn resources.

## 8 Responsible practice and team contributions

Private referee-player boundaries and separate offline labeling prevent hidden-board access. Archived configs, seeds and failures support reproducibility; null findings and unequal costs remain explicit. No human study was conducted; future matches should disclose the bot and obtain consent.

Ding Chiyu developed rules/observations, PCFR+/gadget search, growth/diagnostics and evaluation integration with bounded-history replay. Pei Shengxin covers tracking and the Zhang-Sandholm agent [2]. Colin developed evaluators, training/data, particle bot, runner and Fog Lab, and operated the batch. Bryan developed linear correction and expansion API, audited games, and contributed integration/reviews/reporting. Wang Zhijian covers evaluation/provenance. Lin Tzu-Chun's proposal responsibility covers environment/belief representation [23].

Bryan used GitHub Copilot and Codex for inspection, probes, artifact checks, drafting, synthesis, references and layout across revisions. Ding used Codex for implementation/validation and this report's clarification, source checks and regeneration. The proposal disclosed Claude-assisted drafting. The authors remain responsible for design, code, experiments and interpretation; AI output is not experimental evidence.

## 9 Conclusion

Against a fixed opponent, Fog of War chess is a POMDP. We studied a common simplification, averaging full-board values over boards consistent with the player's observations, and asked whether better value prediction yields better decisions. It did not, measurably. Network 1 cut value error by 20% without improving move-level value or game score; a linear correction recovered most of that gain more cheaply; outcome-trained targets predicted results better but agreed less with deep-engine move values; and a search agent using Network 1 scored 46.59% against its depth-1 counterpart. Under partial observability, average prediction error is the wrong yardstick for a value function: decision-relevant errors and belief-dependent values matter, and the averaging approximation itself limits what better full-board values can achieve.

## References

1. CS5446_project contributors. Replay-checked hidden-rook example. [Internet]. 2026 [cited 2026 Nov 8]. Three observation-identical histories and 24 checked move/state consequences. Available from: [https://github.com/Mr-Teal/CS5446_project/blob/03a01e8d97317b36e63f77a5c67359c9c5b3742f/docs/drafts/presentation-assets/hidden-rook-example.json](https://github.com/Mr-Teal/CS5446_project/blob/03a01e8d97317b36e63f77a5c67359c9c5b3742f/docs/drafts/presentation-assets/hidden-rook-example.json).

2. Zhang BH, Sandholm T. Subgame solving without common knowledge. arXiv:2106.06068v2 [Internet]. 2021 Dec 3 [cited 2026 Nov 8]. Available from: [https://arxiv.org/abs/2106.06068v2](https://arxiv.org/abs/2106.06068v2).

3. Zhang BH, Sandholm T. General search techniques without common knowledge for imperfect-information games, and application to superhuman Fog of War chess. arXiv:2506.01242v2 [Internet]. 2026 Feb 28 [cited 2026 Nov 8]. Available from: [https://arxiv.org/abs/2506.01242v2](https://arxiv.org/abs/2506.01242v2).

4. National University of Singapore School of Computing. Sequential decision making under uncertainty. CS4246/CS5446 course slides. Version 1.0. Semester 1, AY2026/27.

5. Kaelbling LP, Littman ML, Cassandra AR. Planning and acting in partially observable stochastic domains. Artif Intell. 1998;101(1-2):99-134. Available from: [https://www.cassandra.org/arc/papers/aij98.pdf](https://www.cassandra.org/arc/papers/aij98.pdf).

6. Littman ML, Cassandra AR, Kaelbling LP. Learning policies for partially observable environments: scaling up. In: Machine Learning Proceedings 1995. San Francisco (CA): Morgan Kaufmann; 1995. p. 362-70. Available from: [https://doi.org/10.1016/B978-1-55860-377-6.50052-9](https://doi.org/10.1016/B978-1-55860-377-6.50052-9).

7. Frank I, Basin D. Search in games with incomplete information: a case study using Bridge card play. Artif Intell. 1998;100(1-2):87-123.

8. Long J, Sturtevant NR, Buro M, Furtak T. Understanding the success of perfect information Monte Carlo sampling in game tree search. Proc AAAI Conf Artif Intell. 2010;24(1):134-40. Available from: [https://doi.org/10.1609/aaai.v24i1.7562](https://doi.org/10.1609/aaai.v24i1.7562).

9. National University of Singapore School of Computing. Guided sequential decision making: decision-time and demonstration-based planning. CS4246/CS5446 course slides. Version 1.0. Semester 1, AY2026/27.

10. Moravčík M, Schmid M, Burch N, Lisý V, Morrill D, Bard N, et al. DeepStack: expert-level artificial intelligence in heads-up no-limit poker. Science. 2017;356(6337):508-13. Available from: [doi:10.1126/science.aam6960](https://doi.org/10.1126/science.aam6960).

11. Brown N, Bakhtin A, Lerer A, Gong Q. Combining deep reinforcement learning and search for imperfect-information games. In: Advances in Neural Information Processing Systems 33; 2020. Available from: [https://arxiv.org/abs/2007.13544](https://arxiv.org/abs/2007.13544).

12. CS5446_project contributors. Shared interfaces and sampled search implementation. [software and documentation on the Internet]. 2026 [cited 2026 Nov 8]. Integrated snapshot 3335723. Available from: [https://github.com/Mr-Teal/CS5446_project/tree/3335723852ad59ccbe5e999dbe0ce2773f7e56d0](https://github.com/Mr-Teal/CS5446_project/tree/3335723852ad59ccbe5e999dbe0ce2773f7e56d0).

13. Quek HC, Kuah JHB, CS5446_project contributors. Leaf evaluators and practice-data results. [Internet]. 2026 [cited 2026 Nov 8]. Snapshot 3335723; linked data manifests, checkpoints and ablations. Available from: [https://github.com/Mr-Teal/CS5446_project/blob/3335723852ad59ccbe5e999dbe0ce2773f7e56d0/pair_b/README.md](https://github.com/Mr-Teal/CS5446_project/blob/3335723852ad59ccbe5e999dbe0ce2773f7e56d0/pair_b/README.md).

14. Kuah JHB, CS5446_project contributors. Evaluation methods and batch validation. [Internet]. 2026 Oct 28 [cited 2026 Nov 8]. Revision 7c292af. Archive recomputation and historical rule boundaries. Available from: [https://github.com/Mr-Teal/CS5446_project/blob/7c292af5881b8c81e4ffccb7300de21650c9c0ad/pair_b/docs/evaluation-methods-draft.md](https://github.com/Mr-Teal/CS5446_project/blob/7c292af5881b8c81e4ffccb7300de21650c9c0ad/pair_b/docs/evaluation-methods-draft.md).

15. National University of Singapore School of Computing. Game theory. CS4246/CS5446 course slides. Version 4.0. Semester 1, AY2026/27.

16. Hansen EA, Bernstein DS, Zilberstein S. Dynamic programming for partially observable stochastic games. In: Proceedings of AAAI-04. 2004. p. 709-15. Available from: [https://cdn.aaai.org/AAAI/2004/AAAI04-112.pdf](https://cdn.aaai.org/AAAI/2004/AAAI04-112.pdf).

17. National University of Singapore School of Computing. Reinforcement learning model-free techniques. CS4246/CS5446 course slides. Version 4.1. Semester 1, AY2026/27.

18. CS5446_project contributors. Bounded history inference with private-stream replay recovery. [software on the Internet]. 2026 [cited 2026 Nov 11]. Measured runtime aaa000a. Available from: [https://github.com/Mr-Teal/CS5446_project/blob/aaa000a034ae5275afe981402891596e660312a4/pair_a_prep/bounded_tracking.py](https://github.com/Mr-Teal/CS5446_project/blob/aaa000a034ae5275afe981402891596e660312a4/pair_a_prep/bounded_tracking.py).

19. CS5446_project contributors. Search verification and integration evidence. [Internet]. 2026 [cited 2026 Nov 8]. Historical source identities and pilot limitations. Available from: [https://github.com/Mr-Teal/CS5446_project/blob/92af3ce1ee3a9fb52c6ec9db5d7a88a92b4c0531/docs/drafts/report-evidence-notes.md](https://github.com/Mr-Teal/CS5446_project/blob/92af3ce1ee3a9fb52c6ec9db5d7a88a92b4c0531/docs/drafts/report-evidence-notes.md).

20. CS5446_project contributors. Monte Carlo and temporal-difference target comparison. [Internet]. 2026 [cited 2026 Nov 8]. Revision 1db35d6. Available from: [https://github.com/Mr-Teal/CS5446_project/blob/1db35d68638d52353381d13de20addfea58a4d99/pair_b/experiments/mc_td/RESULTS.md](https://github.com/Mr-Teal/CS5446_project/blob/1db35d68638d52353381d13de20addfea58a4d99/pair_b/experiments/mc_td/RESULTS.md).

21. Quek HC, CS5446_project contributors. Seven-row match batch. [dataset on the Internet]. 2026 Oct 27 [cited 2026 Nov 8]. Execution a5c5fb6; reviewed archive 5e9393a. Available from: [https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27](https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27).

22. CS5446_project contributors. Network 1 vs Stockfish D1 evaluation. [dataset on the Internet]. 2026 Nov 10 [cited 2026 Nov 11]. 100 attempted games; pinned returned archive. Available from: [https://github.com/Mr-Teal/CS5446_project/blob/8c7baf758e40f8a23c09b273903cff0aee38d2cb/pair_c/evaluation_20261110/README.md](https://github.com/Mr-Teal/CS5446_project/blob/8c7baf758e40f8a23c09b273903cff0aee38d2cb/pair_c/evaluation_20261110/README.md).

23. CS5446_project team. Project contribution records. [Internet]. 2026 [cited 2026 Nov 8]. Contribution statements and proposal work allocation; see report evidence notes. Available from: [https://github.com/Mr-Teal/CS5446_project/pull/33](https://github.com/Mr-Teal/CS5446_project/pull/33).
