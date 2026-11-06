# Fog of War Chess

Presentation plan for a 12-minute presentation followed by 3-minute Q&A

6 November 2026. Eighteen core slides, eight hidden backups. Speakers remain unassigned.

## The argument

This presentation asks how to choose actions from incomplete observations and which learned values improve those decisions. It connects the worked example to state, evidence, action, return and policy; explains MC, TD and distillation targets; and separates offline prediction from the game outcomes of an induced decision rule. All 15 prior core slides are retained, with three additions and shorter opening narration. Detailed evidence stays in backup.

The planned core is 11 minutes including handovers, with one minute of contingency for a 12 minute slot. These are planned timings, not measured rehearsal times. The confirmed total slot is 15 minutes: 12 minutes presentation followed by 3 minutes Q&A.

## Run of show

| Slide | Slide purpose or finding | Planned time |
| --- | --- | --- |
| 1 | Where would you move? | 0:25 |
| 2 | The rook could be on the left | 0:15 |
| 3 | The same view can hide a different danger | 0:15 |
| 4 | Fog of War Chess | 0:35 |
| 5 | Compare a move across possible states | 0:30 |
| 6 | Decision making from private observations | 0:45 |
| 7 | The agent tracks, searches and evaluates | 0:35 |
| 8 | The player acts on a partial board | 0:20 |
| 9 | Fog Lab exposes the agent’s hypotheses | 0:20 |
| 10 | Three ways to learn position values | 0:50 |
| 11 | Learning targets change what the value predicts | 1:00 |
| 12 | Can a learned evaluator improve play? | 0:40 |
| 13 | Evaluation: prediction, play and cost | 0:35 |
| 14 | Prediction error decreased by about 20% | 0:40 |
| 15 | The games did not establish a playing gain | 1:00 |
| 16 | The learned correction took about 3× as long | 0:30 |
| 17 | Lower value error can still select the wrong move | 0:50 |
| 18 | Conclusions and next evaluation | 0:55 |

## Slide notes

### Slide 1 Where would you move?

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** You are White. Your king can move one square; hatched squares are hidden. Which highlighted move would you choose? Pause briefly. We will reveal two positions consistent with the same private evidence.

**Transition:** The unseen pieces can change which move is dangerous.

### Slide 2 The rook could be on the left

**Purpose:** Hidden information. Planned 15 seconds.

**Say:** If the hidden rook is on the left, the left diagonal lets it capture the king next turn. The complete board is revealed here for the explanation.

**Transition:** But the same evidence also permits another position.

### Slide 3 The same view can hide a different danger

**Purpose:** Hidden information. Planned 15 seconds.

**Say:** The rook could instead be on the right, while White has exactly the same evidence. Now the right diagonal is dangerous. One observation does not identify a unique state.

**Transition:** This is the decision problem posed by Fog of War Chess.

### Slide 4 Fog of War Chess

**Purpose:** Game and problem formulation. Planned 35 seconds.

**Say:** Fog of War Chess reveals own pieces and reachable squares, and hides the rest. The complete state belongs to the referee. Players aim to capture the king, with no check restriction. Actions change both the position and future observations. The game supplies our test environment for decision making from incomplete information.

**Transition:** How should the agent act when both hidden positions are possible?

### Slide 5 Compare a move across possible states

**Purpose:** Hidden information. Planned 30 seconds.

**Say:** Forward avoids immediate capture in both displayed possibilities; the diagonals each fail in one. That is not an optimality claim. The point is to compare action consequences across states consistent with the evidence.

**Transition:** We can now formulate the decision problem in the course’s terms.

### Slide 6 Decision making from private observations

**Purpose:** Sequential decision formulation. Planned 45 seconds.

**Say:** Map the opening example to the course concepts. The complete position is the hidden state. The player receives an observation and retains its private history. It chooses a legal move; the objective is eventual game outcome, represented as win, draw or loss. A policy must map the available evidence to an action. The value learner is a component used by that decision rule, rather than the complete policy itself. We have a two-player imperfect-information game, not the fully observed single-agent MDP used in the introductory lectures.

**Transition:** Our architecture separates reconstructing states, planning and value estimation.

### Slide 7 The agent tracks, searches and evaluates

**Purpose:** Approach. Planned 35 seconds.

**Say:** The tracker maintains possible hidden states from private evidence. The planner compares actions and replies. A value function estimates outcomes where search stops, helping the planner choose a move. This is the course’s connection between value estimation and decision-time planning. The rules model is given, rather than learned; the learned component here estimates values. Our archived game comparison fixes the outer planner at one move.

**Transition:** The interface lets us inspect the private observations and hypotheses.

### Slide 8 The player acts on a partial board

**Purpose:** Demonstration. Planned 20 seconds.

**Say:** This captured opening shows White after e4 and the bot’s knight reply to a6. Visibility changes with the move. It is a material-bot system demonstration, not a learned-model strength result.

**Transition:** We can also inspect what the bot thinks might be hidden.

### Slide 9 Fog Lab exposes the agent’s hypotheses

**Purpose:** Demonstration. Planned 20 seconds.

**Say:** These are two of the bot’s eight sampled possible boards. They represent uncertainty from its own evidence; the referee does not supply the true board. Now we turn to the value functions used to judge possible outcomes.

**Transition:** A value learner needs targets. We compared three ways to construct them.

### Slide 10 Three ways to learn position values

**Purpose:** Value learning and training targets. Planned 50 seconds.

**Say:** The value function generalizes from training examples. Distillation fits a deeper engine’s values. Monte Carlo fits completed-game returns under the behaviour policy that generated the data. TD bootstraps from a next-position estimate, using the terminal outcome at the end. In our alternating-player representation, TD changes the sign of the next player’s value. The MC/TD study fits the same linear correction model with these targets; it is separate from neural Network 1. This is offline prediction, not an online policy-improvement loop.

**Transition:** The target source changes what prediction accuracy means.

### Slide 11 Learning targets change what the value predicts

**Purpose:** Offline value-learning result. Planned 60 seconds.

**Say:** These are recorded offline results for the same linear model. Against the engine teacher, distilled values have lower error: 0.079, compared with 0.217 for MC and 0.185 for TD(0). Against completed-game outcomes, the ordering changes: 0.513 for distillation, 0.481 for MC and 0.476 for TD(0). These are different metrics on different evaluation populations; do not compare the two axes numerically. MC and TD estimate returns under the recorded depth-1-plus-random behaviour policy, not optimal values. Distillation also trains on different rows, and TD reached a round cap. Thus this study does not isolate target choice or establish stronger play. The full TD(lambda), move and interval results are in backup.

**Transition:** We separately tested whether a neural engine-value correction improves play.

### Slide 12 Can a learned evaluator improve play?

**Purpose:** Learning method. Planned 40 seconds.

**Say:** We now return to Network 1, a neural model distinct from the linear MC/TD study. It learns a correction to depth-1 Stockfish using depth-11 values as targets. This is supervised value distillation, not a policy learned directly from game rewards. At decision time the planner adds the correction to the shallow value and uses it to rank actions. A closer teacher estimate is useful only if it improves the resulting decisions.

**Transition:** We therefore compare prediction quality, game outcome and computational cost.

### Slide 13 Evaluation: prediction, play and cost

**Purpose:** Experimental comparison. Planned 35 seconds.

**Say:** The game comparison tests neural Network 1 against shallow Stockfish with the same one-ply outer planner. Each of 100 openings is played with colours swapped. We measure teacher-prediction error, paired game score and median move time. These are separate measures of the component and the complete decision process, and the computation time is not fixed.

**Transition:** First, did the learned correction improve the value estimate?

### Slide 14 Prediction error decreased by about 20%

**Purpose:** Prediction result. Planned 40 seconds.

**Say:** Network 1 reduces development error against depth-11 Stockfish from 0.095 to 0.076, about twenty percent. This check also helped choose the model. It measures agreement with a teacher, rather than expected return or optimality of the policy induced by the planner.

**Transition:** The paired games test the decision outcome directly.

### Slide 15 The games did not establish a playing gain

**Purpose:** Outcome result. Planned 60 seconds.

**Say:** Network 1 scores 0.515 against the baseline. Equal game points is 0.5; the 95 percent bootstrap interval, 0.448 to 0.585, crosses it. The archived one-ply batch therefore does not establish improved playing strength or equivalence. The relevant control question is whether changing the value estimate changes game outcomes, rather than merely reducing prediction loss.

**Transition:** The learned correction also has a computational cost.

### Slide 16 The learned correction took about 3× as long

**Purpose:** Resource result. Planned 30 seconds.

**Say:** Median move time rises from 11.1 to 36.1 milliseconds, about three times as long. Network 1 adds computation on top of the baseline engine call. The outer planner is fixed, but thinking time is not, which motivates a fixed-budget comparison in the next study.

**Transition:** One reason prediction and play can differ is the ranking of close alternatives.

### Slide 17 Lower value error can still select the wrong move

**Purpose:** Interpretation. Planned 50 seconds.

**Say:** These are illustrative values. The teacher slightly prefers A. The baseline is inaccurate but chooses A; the learned estimates are closer overall but choose B. Average value loss and the policy induced by ranking actions are distinct objectives. This illustrates why prediction improvement need not improve decision quality; it does not prove the cause of the archived game result.

**Transition:** The findings suggest a specific next evaluation.

### Slide 18 Conclusions and next evaluation

**Purpose:** Conclusion. Planned 55 seconds.

**Say:** Our system combines private-state tracking, decision-time planning and learned value estimates. The offline MC/TD study shows that approximating an engine and predicting returns under a recorded behaviour policy are different objectives; it does not establish an optimal policy. In the separate neural Network 1 comparison, lower teacher error did not establish a game-score gain and took more computation. The next evaluation is learned values inside reviewed deeper search under a fixed budget. The central conclusion is to evaluate value learning by the decisions and returns it supports. Invite questions and reserve the next three minutes for Q&A.

**Transition:** Invite questions; use the hidden evidence slides as needed.

## Questions every team member should be able to answer

**What makes this sequential decision making?** An action changes the position and what each side can observe next. The agent must account for hidden states and future replies.

**Why consider several possible boards?** Two histories can give the same private evidence but different consequences. The rook example demonstrates this without assigning probabilities to a complete belief.

**Does the bot see the real board?** The referee owns the true state. The bot receives a private observation and reconstructs possibilities. Fog Lab reveals its hypotheses for inspection in this demonstration.

**What did the network learn?** Network 1 learns a correction to quick Stockfish using deeper full-board Stockfish values as targets. The correction still requires the quick engine call.

**Why can better predictions fail to help moves?** Average value error and ranking the best action differ. Close alternatives can swap order even when average prediction improves. This is a plausible explanation, not a causal claim established by the game batch.

**Does the game result prove no improvement?** No. The interval crosses equal points, so this batch does not establish a gain or equivalence. The conclusion is limited to the tested planner and protocol.

**Was compute equal?** The outer planner was fixed. Median time was 11.1 ms for quick Stockfish and 36.1 ms for Network 1. This was not an equal-time comparison.

**Did we reproduce the full paper?** The project contains search prototypes, trackers and evaluators. Complete reproduction and a reviewed learned-leaf deeper-search result are not established. New author-reported full-agent arms are separate from the archived evaluator batch.

**How do MC, TD and distillation differ here?** Their targets come from completed-game outcomes, bootstrapped next-position values, and a deeper engine, respectively. The offline comparison uses one linear correction model; neural Network 1 is a separate distillation study.

**Whose return do MC and TD estimate?** The recorded depth-1-plus-random behaviour policy. These offline predictions do not establish an optimal policy or an online policy-improvement loop.

**Why is the TD target negative next-state value?** Consecutive positions use the next player’s perspective. In this alternating zero-sum setting, negate that value to express it from the current player’s view; use the terminal outcome at the end.

**Is the transition model learned?** No. The game rules supply the dynamics for planning. The learned component studied here is a value estimate, so avoid calling it learned-dynamics model-based RL.

## Delivery and rehearsal

Assign speakers by narrative blocks only after team agreement. Each speaker must understand both findings. Record a complete rehearsal with handovers and chart pauses. The first five slides take two minutes in the plan; do not repeat the rules or chess tactics. Use the retained demo slides as brief visual steps. Target 11 minutes of core content and preserve a one minute buffer. Cut secondary spoken detail before cutting the interpretation of the result. No rehearsal has been performed for this revision.

Use the final slide as an academic conclusion and next evaluation, then invite questions. Reserve the full three minutes for Q&A. Answer the direct question first, state evidence and limitations, and open a backup only when it supports that answer. Check that a listener can explain the central findings after one viewing. On the uncertainty plot, point to equal points and the interval before giving the conclusion. Explain the demonstration through the partial board and possible boards, without reading the move table.

## Hidden backup navigation

19: all seven archived match rows. 20: full value and move metrics. 21: offline belief context. 22: full MC/TD comparison. 23: retained-search prototype. 24: evaluator inventory. 25: contribution confirmations. 26: sources and scope. Hidden slides are skipped during the core slide show. The PDF includes all pages for review.

## Sources and evidence boundaries

**Rules:** Rules and worked example: docs/drafts/presentation-assets/hidden-rook-example.json. Public custom start k7/8/7r/8/3K4/8/8/8 b - - 0 1. Alternative Black moves h6c6 / h6e6 produce identical White observations, legal feedback and private history. Only immediate king-capture consequences are shown. These are two selected possibilities, without assigned probabilities or a complete-posterior claim. Rule reference: https://github.com/Mr-Teal/CS5446_project/blob/149278181ed6d2b52dce31991fb311a2a74339d0/pair_a_prep/rules_adapter.py Game introduction follows RulesAdapter.visible_squares and terminal: own occupied squares and reachable destinations are visible, with pawn and en-passant special cases. There is no check restriction; the king can be captured. The simple displayed king example has exactly nine visible squares. Full ordinary pawn and draw rules are outside the timed explanation.

**Values:** Evaluator evidence: https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/README.md . Separate development check: 959 games, 3818 decisions, 94963 eligible children. Network 1 selection also used this check set. Full-board D11 teacher. D1 MAE 0.095, Network 1 0.076. Mean errors and rankings address different objectives. Not a sealed-test result.

**Batch:** Archived evaluator batch: https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27 . Execution a5c5fb6, stand-in rules, predates later no-move/EP updates. Network 1: paired score 0.515, bootstrap 95% interval [0.448,0.585], 100 complete colour pairs. Baseline D1 median 11.1 ms/move, Network 1 36.1. Same one-ply outer planner, 256 particles, eight hypotheses, unequal compute. This is one row of seven separate comparisons against D1. Total 1400 attempts, 1399 finished, 699 complete pairs, six capped draws. Whole-belief context was not used online. Full tables remain in backup. Null-containing intervals do not establish equivalence. Methods: https://github.com/Mr-Teal/CS5446_project/blob/7c292af5881b8c81e4ffccb7300de21650c9c0ad/pair_b/docs/evaluation-methods-draft.md

**Demo:** Actual local Fog Lab browser opening demonstration, 6 November 2026. Local historical checkout, Teal rules, material scorer, seed 0. Human e2e4, bot b8a6. Saved screenshot and two-ply record: docs/drafts/presentation-assets/. The diagnostic panel shows the bot's own hypotheses for inspection. This is not Fair mode, a full game, or a playing-strength result. It does not demonstrate the unmerged Pair A Fog Lab bot or the learned evaluator. The displayed 22 ms is this local action, not the archived batch timing.

**Search:** Search and current-scope review: https://github.com/Mr-Teal/CS5446_project/pull/33#issuecomment-6630857564 . The project includes search prototypes and a separate exact-history tracker. The archived batch isolates evaluators in a one-ply planner. A reviewed learned-leaf deeper-search comparison remains pending. PR65/66/67 mechanisms and author-reported full-agent arms remain separately reviewed, with raw evidence and implementation corrections outstanding. No complete Obscuro reproduction or new training requirement. Background: Zhang and Sandholm, https://arxiv.org/abs/2106.06068v2 and https://arxiv.org/abs/2506.01242v2 .

**Ranking:** Illustrative two-move values created only to explain a ranking mechanism, not project measurements: teacher [0.60,0.59], baseline [0.80,0.40], learned [0.58,0.60]. Mean absolute errors are 0.195 and 0.015. The baseline selects Move A; the learner selects Move B. This example does not identify the cause of the archived game result.

**Course:** CS4246/CS5446 course materials: Week 4, Lecture-sdm.pdf, PDF pages 21–22, 28, 35, 38 and 46 (return, prediction versus control, MC, TD and generalized policy iteration); Week 5, Lecture-rl-modelfree.pdf, PDF pages 5, 8, 13 and 15 (value-function approximation, sample targets and bootstrapping); Week 7, Lecture-guided-SDM.pdf, PDF pages 3–4 and 28–30 (decision-time search and leaf value estimates). This project uses a given rules model for planning; the network learns values rather than transition dynamics. The setting is a two-player imperfect-information game; it is not claimed to be a fully observed single-agent MDP.

**Mctd:** Separate offline model-free prediction study: https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/experiments/mc_td/RESULTS.md . All methods use the same linear correction model on 1217 inputs, distinct from neural Network 1. Distillation uses 638451 child rows from 6414 training games; MC/TD use 722500 trajectory positions from 6239 finished games, excluding 175 unfinished training games. Teacher MAE: Distil .0790, MC .2169, TD(0) .1846. Outcome MSE: Distil .5127, MC .4811, TD(0) .4758. Rounded core values are .079/.217/.185 and .513/.481/.476. Teacher error uses 94963 rows from 959 games; outcome MSE uses 106971 positions from 929 finished games, with 32 of 961 excluded. Outcomes follow the recorded depth-1 Stockfish plus 2–15% random behaviour policy, not optimal play. TD bootstraps negative next-player value and uses terminal outcome at the end; fitted semi-gradient TD(0) and TD(lambda=.8) reached the 15-round cap at full data. Training-row distributions differ, so the study does not isolate target choice. Archived trajectories have documented rule and engine-history limitations. Full methods, TD(lambda), move metrics, intervals and caveats remain in backup. These are recorded offline results, not a new training or playing-strength experiment.

**Worked example:** The public custom starting position and three candidate-move checks are in presentation-assets/hidden-rook-example.json. The example concerns immediate capture after these candidate moves, without an optimality or full-posterior claim.

**Demonstration:** The screenshot and two-ply game record are in presentation-assets/. It uses a material bot on a historical checkout. The displayed single-action timing is not an archived experiment measurement.

**Course alignment:** The project guidelines, pages 3-5, emphasize an AI-familiar audience outside the topic and presentation relevance, organization, clarity, time management and Q&A. The 18-slide core develops two main points, explicitly introduces the game after the opening example and ends with conclusions and the next evaluation. The user confirmed 12 minutes presentation plus 3 minutes Q&A, superseding the older draft guideline duration.

**Contributions and AI assistance:** The existing individual contribution statements remain in backup and require each member's confirmation. Do not infer the human identity of xiaomiao-fong from the account name. Copilot assisted earlier drafts. Codex assisted the restructuring, rules-example checks and browser demonstration under Bryan's direction. No new training or formal match batch was run.
