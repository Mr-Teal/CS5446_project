# Fog of War Chess

Search Prototypes and Learned Leaf Evaluation

CS4246/CS5446 Reinforcement Learning and Sequential Decision Making

National University of Singapore School of Computing

Semester 1 AY2026/27

8 November 2026

DING Chiyu; PEI Shengxin; QUEK Hongqiang Colin; Kuah Jun Hong Bryan; WANG Zhijian; LIN Tzu-Chun.

---

## Abstract

Fog of War chess requires an agent to choose moves while reasoning about hidden pieces and private observations. We study whether a learned leaf evaluator improves decisions when search must stop before a game ends. Our system separates rules and observations, belief tracking, search, and interchangeable evaluators. On a development check set of 959 games, Network 1 reduces mean absolute error against Stockfish depth 11 from 0.095 to 0.076, but its move-selection improvement is inconclusive. A linear baseline captures much of that reduction. Learning from game outcomes with Monte Carlo and temporal-difference targets better predicts the practice policy's results, but gives worse agreement with the stronger engine. In an archived batch of 1,400 attempted games, neither Network 1 nor the linear correction establishes a score improvement over depth 1 under the same outer planner. The main finding is that value-prediction accuracy, action quality and computational cost must be evaluated separately. Belief-dependent strategic values and equal-time comparisons inside the deeper search remain future evaluation questions.

## 1 Introduction

In ordinary chess, both players can inspect the position before choosing a move. In Fog of War chess, a player sees its own pieces and the squares made visible by them. Several hidden positions may fit the same observations. A move can affect both the material position and the information available to either player. The problem therefore combines sequential decision making under uncertainty with strategic interaction.

Zhang and Sandholm introduced subgame solving with limited knowledge to avoid enumerating an impractically large common-knowledge region [1]. Their later Obscuro system develops this approach and reports superhuman Fog of War play [2]. These papers motivate our search prototypes. The published playing-strength results belong to those systems; our project investigates selected mechanisms and learned evaluation in a smaller experimental setting.

Our central question is whether a better estimate at the search frontier produces better decisions at an acceptable cost. We investigate three questions. RQ1 asks whether a learned correction to a fast chess engine improves value accuracy and move selection. RQ2 asks how the training target and access to other belief hypotheses affect the learned value. RQ3 asks whether evaluator changes improve game score when the outer planner is held fixed.

The project contributes shared rules and evaluation interfaces, search and tracking prototypes, learned and linear evaluators, and an audited match archive. The experiments show why reducing error against a full-board teacher does not by itself establish better decisions under hidden information.

## 2 Decision problem and background

### 2.1 Histories beliefs and strategies

We model play as a two-player sequential zero-sum game. A history contains the moves and observations up to a decision. Terminal utility is +1 for a win, 0 for a draw and -1 for a loss. A player's information set contains histories that its private evidence cannot distinguish. Its strategy must choose the same distribution over actions at every history in that set; otherwise it would exploit information available only to the simulator. This extends the course's treatment of strategic choice and information in extensive-form games [3].

A belief assigns weights to possible histories given the player's observations and known actions. Our sampled interface represents it as history-weight pairs B = {(h, w)}, with nonnegative weights summing to one. A hypothesis is one possible complete history, not a claim to know the true board. Histories matter because identical piece placements can have different repetition histories or imply different opponent knowledge.

For evaluator-based agents in the archived batch, a one-ply planner selects the legal move with the highest weighted average value across sampled hypotheses. Each successor is valued from the root player's perspective. This resembles expected-utility action selection, but independently valuing fully observed hypotheses can introduce strategy fusion: the continuation may implicitly choose different actions in states the player cannot distinguish [4]. We therefore treat this planner as a controlled baseline rather than a complete imperfect-information solution.

The course's MDP formulation links state, action, transition, reward and policy [5]. Here a private observation is insufficient as a fully observed Markov state, and the opponent is strategic. Beliefs represent uncertainty, while information sets constrain feasible strategies. Weighted board values alone do not account for both.

### 2.2 Search and learned continuation values

Decision-time planning searches forward from the current decision and uses an approximate value when the search stops [6]. In imperfect-information search, a local subgame also needs to account for histories outside the region being solved. Knowledge-limited subgame solving reduces this region while using continuation information at its boundary [1]. Obscuro combines such constructions with predictive counterfactual regret minimization, growing search trees and policy processing [2].

Counterfactual regret minimization updates action preferences at information sets by comparing their estimated payoffs. Our PCFR+ prototypes implement a predictive variant on finite trees. Tree growth adds continuations while retaining accumulated regrets and strategy statistics. A gadget is an auxiliary game used to express boundary choices and continuation values during local solving. Errors in those values can change the resulting strategy even if the local solver converges.

DeepStack and ReBeL demonstrate how learned continuation values can support search in imperfect-information games [7, 8]. They motivate learning at the frontier, but their guarantees and results do not transfer automatically to our sampled trees or full-board labels. The distinction between learning a value estimate and improving a policy also appears in the course's treatment of function approximation [9].

## 3 System and implementation

The system separates the referee, observations, belief tracker, decision procedure and evaluator [10]. The referee owns the true board. Each player receives its own observations, legal-action feedback and history, then updates its belief before selecting an action. True-board access is reserved for offline label generation and post-game diagnostics. This separation makes information leakage testable.

Fog rules remove ordinary chess's king-safety restrictions, and king capture can end a game. Visibility, castling, en passant and repetition require explicit handling. Rule-decided values are handled before engine or network calls because ordinary engines do not implement these terminal conditions. Shared fixtures validate specified cases rather than every external rules implementation.

Two decision procedures serve different purposes. Pair A's search prototypes construct information-set trees, apply PCFR+ updates and expand selected continuations. Exact history tracking maintains observation-consistent histories internally, although the search may receive only a sample. Returning a small sample does not bound the tracker's internal population. The sampled subgame mode adds bounded cross-turn reuse and approximate knowledge boundaries; full-history knowledge closure and numerical transfer of ancestor gadget payments remain limitations [10].

Pair B's one-ply bot instead uses a bounded particle tracker and weighted evaluations of candidate moves. This simpler planner provides a common comparison procedure for the evaluator study. The archived batch uses 256 particles and eight sampled hypotheses per decision. These settings describe an approximation, not the full number of possible histories.

The integrated repository includes tracker and solver recovery, evaluation provenance and portable native-runtime support. Packed-state and search-mechanism changes remain in development branches. The experiments below retain the source and rules actually measured [10, 11].

Checks support retained solver state, rejection of incomplete expansions, and budget/fallback accounting on tested cases. Limits are cooperative: operations in progress can overrun a requested slice. Recorded pilots include resource failures on longer histories; short action smokes establish integration rather than complete-game capacity [12].

## 4 Learned leaf evaluation

### 4.1 Data and targets

A leaf evaluator estimates a position's continuation value when search stops. We call Stockfish depth 1 quick Stockfish and depth 11 careful Stockfish. Our engines use Stockfish 19; this differs from the engine versions in the source papers. Evaluators return values in [-1, 1] with an explicit acting-player convention. A score c in centipawns becomes tanh(c/600), and a forced mate becomes +1 or -1 [13].

For the evaluator study, large-scale labels from the team's Fog of War solver were unavailable at data-generation time. We generated 8,000 practice games mixing ordinary-chess Stockfish moves with random moves, and sampled four parent positions per game. At each depth, a single engine call scores several child moves together (MultiPV). Fog-rule checks supply values where those rules decide a position.

A hash of game identity assigns 80% of games to training, 10% to validation and 10% to a sealed test bucket. The reported check set is a separate generation with a different seed: 959 games, 3,818 decisions and 94,963 eligible children after excluding rule-decided children. It also helped compare three Network 1 candidates, so the reported measurements are development results, not a sealed-test estimate [13].

### 4.2 Evaluators and learning targets

Piece values use conventional material weights 1, 3, 3, 5 and 9 as a simple floor. The linear correction adds a ridge-regression adjustment from 1,217 board features to quick Stockfish's value v1. A second parameterization keeps the prediction bounded: v = tanh(atanh(clip(v1)) + w·x + b), with the input clipped inside (-1, 1). Network 1 replaces the linear adjustment with a convolutional network of approximately 521,000 parameters. These models learn to match careful Stockfish by regression. They still require quick Stockfish, so their inference cost is additional to the engine call [13].

The belief network has approximately 562,000 parameters. It combines an embedding of each board with a weighted summary of the other boards. Its architecture can represent different values for the same board in different beliefs. Its practice labels, however, are careful Stockfish's values for each board alone. Synthetic alternatives relocate unseen opponent pieces while preserving the generating player's observation and legal-action feedback; they are not a complete posterior over legal histories [13].

We also train the bounded linear model on game outcomes. Monte Carlo (MC) uses the final result as its target. TD(0) bootstraps from the next state's estimate; because values follow the side to move, an ordinary nonterminal one-step target changes sign. TD(λ), with λ = 0.8, combines returns over different horizons. These are fitted prediction experiments using recorded trajectories, with semi-gradient targets and up to 15 TD rounds. They do not implement an online policy-improvement loop [9, 14].

## 5 Evaluation method

### 5.1 Offline prediction and action metrics

Value error is mean absolute error against careful Stockfish. Same top move measures whether the selected child's teacher value equals the best eligible sibling's value, allowing teacher ties. Value lost is the difference between that best value and the teacher value of the chosen move. Ties in an evaluator's scores use coordinate move notation (UCI) order. These metrics separate prediction accuracy from action ordering [13].

Paired differences and their 95% intervals use 2,000 bootstrap resamples of whole games because positions within a game are correlated. The MC/TD study additionally measures mean squared error against final game outcomes. Its training trajectories and outcome-evaluation population differ from the sampled children used for teacher agreement; Table 2 states the denominators [14].

### 5.2 Archived match design

Each candidate plays quick Stockfish on 100 randomly generated openings of two to eight plies, with each opening repeated after swapping colours. A win scores 1, a draw 0.5 and a loss 0. The paired score averages the two results within each complete colour pair and then averages over pairs. We report the archived bootstrap interval over pairs and the protocol's approximate Wilson interval. A game reaching the 200-ply cap counts as a draw under this batch's protocol [11, 15].

The evaluator-based agents share the one-ply planner, particle count and hypothesis count. Random selects actions directly. This design holds the outer planning configuration fixed, not total work or elapsed time: deeper engines and networks perform different internal computation. Decision latency excludes tracker updates. Stockfish uses one thread and 16 MB hash, clears state between games and retains it within a game. Its 60-second per-call watchdog is failure protection rather than an equal-time move budget.

The batch ran on 26-27 October 2026 on one M5 Pro Mac, with networks on its Apple GPU. Execution source a5c5fb6 uses the explicitly selected stand-in rules. It predates later no-move draw and en-passant repetition updates. No archived game reached a no-move ending, but that does not make its evaluated child values equivalent to later rules. All seven comparisons retain this identity and are analysed separately from later pilots [11, 15].

## 6 Results

### 6.1 Better value estimates do not establish better moves

**Table 1.** Development check results against careful Stockfish on 94,963 eligible children from 3,818 decisions in 959 games. Cost is median CPU time to evaluate a parent's children, measured separately on 300 sampled parent positions [13].

| Evaluator | Value error | Same top move | Value lost | ms per parent |
|---|---|---|---|---|
| Piece values | 0.336 | 27.7% | 0.2108 | 0.6 |
| Quick Stockfish | 0.095 | 42.9% | 0.0355 | 1.4 |
| Linear correction | 0.084 | 41.5% | 0.0346 | 1.7 |
| Linear inside tanh | 0.079 | 43.5% | 0.0348 | not timed |
| Network 1 | 0.076 | 42.4% | 0.0352 | 12.2 |

Network 1 reduces value error by about 20%. Its paired difference from quick Stockfish is -0.019, with a 95% interval [-0.021, -0.018]. The value-lost difference is -0.0003 [-0.0017, +0.0011]. That interval includes zero, so improved move selection is not established; statistical equivalence is not established either.

![Value error by position category](../../pair_b/experiments/tanh_linear/value-error-by-band.png)

**Figure 1.** Value error on the development check set, grouped by careful Stockfish's assessment. Learned corrections improve errors in positions that already favour one side, but lose accuracy in close positions. The original analysis and bin definitions are retained in the evaluator archive [13].

Figure 1 suggests why prediction and control differ. Errors in decided positions may leave the preferred move unchanged, while small errors in close positions can reverse move ordering. Average value error can reward gains away from decisions that most need accurate ranking. This interpretation would require a targeted ablation to establish causally.

Using unrounded measurements, the linear correction captures about 56% of Network 1's error reduction, rising to 83% with the bounded parameterization. Network 1 costs about nine times as much as quick Stockfish on the measured CPU. Its Apple-GPU latency is 4.4 ms per parent, still roughly three times the depth-1 call. These costs weaken the case for deploying this correction solely on the basis of its regression gain.

### 6.2 The target determines what the value learns

Distillation fits 638,451 child rows from 6,414 training games. MC/TD drop 175 unfinished training games and use 722,500 trajectory positions from 6,239 finished games. Thus the target and training-row distribution both change. MC and TD never receive careful Stockfish's values [14].

**Table 2.** The same bounded linear model trained on different targets. Teacher metrics use the Table 1 population. Outcome error uses 106,971 trajectory positions from 929 finished check games, after excluding 32 unfinished games from 961 replayed games [14].

| Training target | Value error | Outcome MSE | Same top move | Value lost |
|---|---|---|---|---|
| Careful Stockfish | 0.079 | 0.513 | 43.5% | 0.0348 |
| Game result with MC | 0.217 | 0.481 | 38.6% | 0.0505 |
| TD(0) | 0.185 | 0.476 | 42.1% | 0.0370 |
| TD(λ) with λ = 0.8 | 0.208 | 0.476 | 41.5% | 0.0415 |
| Quick Stockfish without learning | 0.095 | 0.497 | 42.9% | 0.0355 |

Outcome-trained models predict the practice games' results better than distillation, while agreeing less with the stronger engine and losing more teacher value through their selected moves. TD(0)'s outcome MSE is lower than MC's by 0.0053 [0.0010, 0.0097]. The data describe how a weak, partly random policy converts positions into outcomes. Predicting that policy's returns is a different task from approximating stronger continuation play. Better performance on one target need not transfer to the other.

Both TD methods reach the 15-round cap at full data. A separate 40-round diagnostic changes outcome MSE little and worsens teacher error, so the cap alone does not explain the observed gap. The result supports distillation for this dataset and model; it does not establish that outcome-based RL is generally inferior [14].

### 6.3 Belief context improves prediction under restricted labels

On 3,818 synthetic check beliefs, the belief network reduces board error from quick Stockfish's 0.080 to 0.074 and weighted-belief error from 0.055 to 0.047. The latter difference is -0.008 [-0.009, -0.007], resampling the 959 source games. Across five training seeds, mean board error is 0.0734 with context and 0.0762 without it; every seed improves [13].

The target value of each board is nevertheless independent of the belief. Context can help denoise these predictions without learning what hidden information is strategically worth. In particular, two beliefs containing the same board can require different strategies even when that board receives the same teacher label. Validating strategic belief value needs information-sensitive labels and controlled action comparisons, beyond this offline study.

### 6.4 Game outcomes under a common outer planner

**Table 3.** Separate comparisons against quick Stockfish. Each row schedules 200 games. Scores and intervals use complete colour pairs: 100 per row, except random with 99. W/D/L includes all finished games, including random's unpaired survivor. Cost is candidate median decision latency, excluding tracking [11, 15].

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

The controls behave as expected: random and piece values score poorly, while the self-play interval includes 0.5. Neither Network 1 nor the linear correction establishes an improvement over quick Stockfish. The belief network has a higher point estimate, but both intervals include 0.5. Only careful Stockfish's unadjusted bootstrap interval excludes 0.5, narrowly; its Wilson interval includes 0.5, and adjustment for seven comparisons removes the nominal finding. These are matches against one opponent, not a head-to-head ranking.

Network 1 takes roughly three times quick Stockfish's median decision time, the belief network thirteen times and careful Stockfish 220 times. The belief network is called on individual hypotheses in play, so its row does not test whole-belief context. The batch therefore provides bounded evidence for RQ3 under this planner and unequal computation. An independent archive audit recomputed the records' outcomes, intervals, timing aggregates and manifest hashes; it did not rerun the games [11].

## 7 Discussion and limitations

The results distinguish three uses of value. Distillation approximates a full-board teacher. MC/TD estimate returns from the recorded practice policy. A strategic value under hidden information must also reflect information sets and future decisions. These quantities answer different questions. The course's distinction between policy evaluation and control helps explain why an improvement in one prediction objective can coexist with unchanged or worse action quality [6, 9].

RQ1 finds improved teacher agreement without established action-quality gains. RQ2 shows that targets determine what is learned, while the context labels cannot identify strategic information value. RQ3 finds no established score gain for Network 1 or linear correction. These results narrow the original hypothesis.

Generalization is limited by ordinary-chess practice data, synthetic beliefs, development-set selection and approximate teacher values. The sealed test bucket is unused. Splitting by game prevents shared trajectories, but not necessarily transposed positions across datasets. MC/TD change sampled rows as well as targets, and retain some stored endings that differ from current Fog rules [14].

The match batch uses older rules, one opponent, a one-ply planner and unequal compute. Tracking time is excluded from decision latency. Its belief-network row uses singleton inputs, and its capped games follow a protocol distinct from later unscored pilot caps. Approximate knowledge boundaries, tracker growth and cooperative budgets limit the deeper search prototypes. Local solver diagnostics do not measure whole-game exploitability, and these experiments do not reproduce Obscuro's published strength.

The next evaluation should change the leaf while holding deeper search, rules, openings and whole-turn resources fixed, retaining every attempt's terminal, capped or failed status. Information-sensitive solver labels and sibling-ranking losses are further extensions. These future studies do not change the completed experiments' interpretation.

## 8 Responsible practice and team contributions

The referee-player boundary prevents unfair access to hidden true-board data. Separate offline generation and online inference paths help enforce it. Archiving configurations, seeds and failed attempts supports reproducibility; reporting null findings and unequal costs avoids overstating strength. No human study was conducted. Future human matches should identify the bot and obtain consent.

Work was divided across search, learning and evaluation. Ding Chiyu developed rules, observations, PCFR+/gadget prototypes, growth and diagnostics. Pei Shengxin's workstream covers belief tracking and ZS21. Colin developed evaluators, practice-data training, the particle bot, match runner and Fog Lab, and operated the batch. Bryan developed the linear baseline and state-preserving expansion API, audited the games, and contributed integration checks, reviews and reporting. Wang Zhijian's workstream covers Pair C evaluation and provenance. Lin Tzu-Chun's proposal responsibility covers environment and belief representation. Shared interfaces and reviews connect these workstreams [16].

Bryan used GitHub Copilot and Codex for inspection, probes, artifact checks and drafting; Codex assisted this revision's synthesis, references and layout. Ding reported Codex assistance, and the proposal disclosed Claude-assisted drafting. The team supplied design, implementation, experiments, archive review and interpretation. AI-generated text and code remain the authors' responsibility; they are not experimental evidence.

## 9 Conclusion

More accurate full-board values need not produce better decisions under hidden information. Network 1 lowers development-set teacher error by about 20%, but its action-quality and game-score gains remain inconclusive at higher cost. Linear corrections recover much of the regression gain. Outcome-based learning better predicts the practice policy while moving further from the stronger engine. Combining learned values with imperfect-information search therefore requires explicit evaluation of the target, action ordering and computational budget.


---

## References

1. Zhang BH, Sandholm T. Subgame solving without common knowledge. arXiv:2106.06068v2 [Internet]. 2021 Dec 3 [cited 2026 Nov 8]. Available from: [https://arxiv.org/abs/2106.06068v2](https://arxiv.org/abs/2106.06068v2).

2. Zhang BH, Sandholm T. General search techniques without common knowledge for imperfect-information games, and application to superhuman Fog of War chess. arXiv:2506.01242v2 [Internet]. 2026 Feb 28 [cited 2026 Nov 8]. Available from: [https://arxiv.org/abs/2506.01242v2](https://arxiv.org/abs/2506.01242v2).

3. National University of Singapore School of Computing. Game theory. CS4246/CS5446 course slides. Version 4.0. Semester 1, AY2026/27.

4. Frank I, Basin D. Search in games with incomplete information: a case study using Bridge card play. Artif Intell. 1998;100(1-2):87-123.

5. National University of Singapore School of Computing. Sequential decision making under uncertainty. CS4246/CS5446 course slides. Version 1.0. Semester 1, AY2026/27.

6. National University of Singapore School of Computing. Guided sequential decision making: decision-time and demonstration-based planning. CS4246/CS5446 course slides. Version 1.0. Semester 1, AY2026/27.

7. Moravčík M, Schmid M, Burch N, Lisý V, Morrill D, Bard N, et al. DeepStack: expert-level artificial intelligence in heads-up no-limit poker. Science. 2017;356(6337):508-13. Available from: [doi:10.1126/science.aam6960](https://doi.org/10.1126/science.aam6960).

8. Brown N, Bakhtin A, Lerer A, Gong Q. Combining deep reinforcement learning and search for imperfect-information games. In: Advances in Neural Information Processing Systems 33; 2020. Available from: [https://arxiv.org/abs/2007.13544](https://arxiv.org/abs/2007.13544).

9. National University of Singapore School of Computing. Reinforcement learning model-free techniques. CS4246/CS5446 course slides. Version 4.1. Semester 1, AY2026/27.

10. CS5446_project contributors. Shared interfaces and sampled search implementation. [software and documentation on the Internet]. 2026 [cited 2026 Nov 8]. Integrated snapshot 3335723. Available from: [https://github.com/Mr-Teal/CS5446_project/tree/3335723852ad59ccbe5e999dbe0ce2773f7e56d0](https://github.com/Mr-Teal/CS5446_project/tree/3335723852ad59ccbe5e999dbe0ce2773f7e56d0).

11. Kuah JHB, CS5446_project contributors. Evaluation methods and batch validation. [Internet]. 2026 Oct 28 [cited 2026 Nov 8]. Revision 7c292af. Archive recomputation and historical rule boundaries. Available from: [https://github.com/Mr-Teal/CS5446_project/blob/7c292af5881b8c81e4ffccb7300de21650c9c0ad/pair_b/docs/evaluation-methods-draft.md](https://github.com/Mr-Teal/CS5446_project/blob/7c292af5881b8c81e4ffccb7300de21650c9c0ad/pair_b/docs/evaluation-methods-draft.md).

12. CS5446_project contributors. Search verification and integration evidence. [Internet]. 2026 [cited 2026 Nov 8]. Historical source identities and pilot limitations. Available from: [https://github.com/Mr-Teal/CS5446_project/blob/bryankuah/report-presentation-drafts/docs/drafts/report-evidence-notes.md](https://github.com/Mr-Teal/CS5446_project/blob/bryankuah/report-presentation-drafts/docs/drafts/report-evidence-notes.md).

13. Quek HC, Kuah JHB, CS5446_project contributors. Leaf evaluators and practice-data results. [Internet]. 2026 [cited 2026 Nov 8]. Snapshot 3335723; linked data manifests, checkpoints and ablations. Available from: [https://github.com/Mr-Teal/CS5446_project/blob/3335723852ad59ccbe5e999dbe0ce2773f7e56d0/pair_b/README.md](https://github.com/Mr-Teal/CS5446_project/blob/3335723852ad59ccbe5e999dbe0ce2773f7e56d0/pair_b/README.md).

14. CS5446_project contributors. Monte Carlo and temporal-difference target comparison. [Internet]. 2026 [cited 2026 Nov 8]. Revision 1db35d6. Available from: [https://github.com/Mr-Teal/CS5446_project/blob/1db35d68638d52353381d13de20addfea58a4d99/pair_b/experiments/mc_td/RESULTS.md](https://github.com/Mr-Teal/CS5446_project/blob/1db35d68638d52353381d13de20addfea58a4d99/pair_b/experiments/mc_td/RESULTS.md).

15. Quek HC, CS5446_project contributors. Seven-row match batch. [dataset on the Internet]. 2026 Oct 27 [cited 2026 Nov 8]. Execution a5c5fb6; reviewed archive 5e9393a. Available from: [https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27](https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27).

16. CS5446_project team. Project contribution records. [Internet]. 2026 [cited 2026 Nov 8]. Contribution statements and proposal work allocation; see report evidence notes. Available from: [https://github.com/Mr-Teal/CS5446_project/pull/33](https://github.com/Mr-Teal/CS5446_project/pull/33).
