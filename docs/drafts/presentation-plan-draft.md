# Fog of War Chess

Presentation plan for a 12-minute presentation followed by 3-minute Q&A

7 November 2026. Twenty-six core slides, eight hidden backups. Proposed Presenter 1: slides 1–11 (5:25). Proposed Presenter 2: slides 12–26 (7:00). One handoff after slide 11; names and team agreement pending.

## The argument

The talk develops two points: observation history helps constrain hidden state, and more accurate value predictions must be evaluated through decisions, outcomes and computation. The opening uses piece icons, hidden-rook choices and a capture-history example. A single comparison places the current fog view beside candidate boards. The course formulation distinguishes hidden game state from information available to the player. One recorded bot decision then aligns its private view and hypotheses before the learning experiments.

The redundant risk-summary slide is removed. The former fog/candidate slides are one 35-second comparison, and the former two-view demo is one 35-second illustration. The retained allocations total 12:25, 25 seconds beyond the 12-minute speaking slot. All other speaking budgets are unchanged. These are unrehearsed allocations rather than a measured script runtime. Three minutes of Q&A follow separately.

## Run of show

| Slide | Slide purpose or finding | Planned time |
| --- | --- | --- |
| 1 | Fog of War Chess | 0:20 |
| 2 | Where would you move? | 0:25 |
| 3 | Possibility A: all three moves left are exposed | 0:20 |
| 4 | Possibility B: all three moves right are exposed | 0:20 |
| 5 | Possibility C: the king is already in check | 0:25 |
| 6 | Fog of War Chess | 0:35 |
| 7 | A capture reveals a hidden rook | 0:30 |
| 8 | History filters the possible boards | 0:35 |
| 9 | Information available for a decision | 0:45 |
| 10 | Choosing a move under uncertainty | 0:35 |
| 11 | One observation, several possible hidden states | 0:35 |
| 12 | Three ways to learn position values | 0:25 |
| 13 | Monte Carlo learns from completed returns | 0:35 |
| 14 | TD bootstraps from the next estimate | 0:35 |
| 15 | Distillation best matched the engine teacher | 0:30 |
| 16 | MC and TD better matched recorded outcomes | 0:30 |
| 17 | Can a learned evaluator improve play? | 0:30 |
| 18 | Evaluation: prediction, play and cost | 0:25 |
| 19 | Prediction error decreased by about 20% | 0:30 |
| 20 | The games did not establish a playing gain | 0:45 |
| 21 | The learned correction took about 3× as long | 0:25 |
| 22 | The reference slightly prefers Move A | 0:20 |
| 23 | Large value errors can preserve the choice | 0:15 |
| 24 | Closer values can still change the choice | 0:20 |
| 25 | Conclusions | 0:40 |
| 26 | Next evaluation | 0:15 |

## Slide notes

### Slide 1 Fog of War Chess

**Purpose:** Project and team introduction. Planned 20 seconds.

**Say:** Hello everyone. We’re presenting our project on Fog of War Chess, where an agent has to act without seeing the full board. We looked at how to keep track of that uncertainty, and whether learning more accurate position values actually leads to better decisions.

**Transition:** I’ll start with a simple example of that uncertainty.

### Slide 2 Where would you move?

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** You control the white king. The icons show which pieces each side has left, but the opponent’s locations are hidden. All eight moves are available. Which would you choose?

**Transition:** Here are a few positions that could be hidden behind that same view.

**Delivery cues (not spoken):** Pause briefly for the audience to consider the choice. Avoid explaining chess notation or individual squares.

### Slide 3 Possibility A: all three moves left are exposed

**Purpose:** Hidden information. Planned 20 seconds.

**Say:** In this possibility, all three moves to the left would allow the hidden rook to capture our king. Those moves are marked in red.

**Transition:** But the hidden position could be different.

**Delivery cues (not spoken):** Indicate the three red dots together, without naming their squares.

### Slide 4 Possibility B: all three moves right are exposed

**Purpose:** Hidden information. Planned 20 seconds.

**Say:** Here, the same observation hides a threat on the other side. Now all three moves to the right are dangerous.

**Transition:** A third position changes the consequences again.

### Slide 5 Possibility C: the king is already in check

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** Here, our king is already under attack. Moving up or down still allows it to be captured. All eight moves remain available under these rules.

**Transition:** That’s the setting we’re working with.

### Slide 6 Fog of War Chess

**Purpose:** Game and problem formulation. Planned 35 seconds.

**Say:** In this version of chess, the goal is to capture the opponent’s king, but we can only see part of the board. Each move changes both the position and what we can observe. That makes it a useful setting for studying decisions under partial observability.

**Transition:** History can reduce that uncertainty. Here’s an example.

### Slide 7 A capture reveals a hidden rook

**Purpose:** Historical observations. Planned 30 seconds.

**Say:** Here, our knight was visible before the opponent moved. After one opponent move, it has been captured, but the attacking piece is still hidden. We know the opponent only has a king and rook left, and the king was too far away to make that capture. So the rook must now be where our knight was. We’ve learned its location from the change in our observations.

**Transition:** What would we know if we kept only the current board view?

### Slide 8 History filters the possible boards

**Purpose:** Belief tracking. Planned 35 seconds.

**Say:** The fog view on the left matches all three boards on the right. The current view alone doesn’t locate the rook. But the capture we just saw rules out A and B, leaving C. A belief tracker keeps hypotheses consistent with the observation history, then updates them as new information arrives.

**Transition:** That distinction between the hidden state and the agent’s information matters for our RL formulation.

### Slide 9 Information available for a decision

**Purpose:** Sequential decision formulation. Planned 45 seconds.

**Say:** The Markov formulation assumes the state contains the information needed by the transition model. In our game, that underlying state is hidden. The agent instead has a current view and a private history. We use those to maintain possible boards and choose an action. The current fog view alone leaves out useful information, as the capture example showed.

**Transition:** The next step is to compare actions using that information.

### Slide 10 Choosing a move under uncertainty

**Purpose:** Approach. Planned 35 seconds.

**Say:** The tracker supplies possible states. Search compares actions and replies across them, and the value function estimates positions where search stops. The rules provide the transitions. Our learning experiments focus on the value function and ask whether improving its predictions improves the move choice.

**Transition:** The interface helps us see what information the agent is working with.

### Slide 11 One observation, several possible hidden states

**Purpose:** Demonstration. Planned 35 seconds.

**Say:** Here is one recorded bot decision, shown from Black’s perspective. On the left is what it could observe. The two hypotheses on the right place the hidden white knight differently. Both fit that observation and feed action evaluation. This run used a simple material evaluator; the next section looks at learned values.

**Transition:** I’ll hand over to my teammate to explain how we trained and tested those values.

**Delivery cues (not spoken):** Handoff to Presenter 2 after this slide.

### Slide 12 Three ways to learn position values

**Purpose:** Value learning and training targets. Planned 25 seconds.

**Say:** Thanks. We compared three training targets. Distillation learns from a stronger engine, Monte Carlo uses completed-game returns, and TD bootstraps from the next estimate. We first compared these targets using the same linear correction model. The neural model comes in the later game experiment.

**Transition:** Let’s briefly look at how the return-based targets work.

### Slide 13 Monte Carlo learns from completed returns

**Purpose:** Monte Carlo prediction. Planned 35 seconds.

**Say:** Monte Carlo uses the outcome of the completed game as the target for an earlier position. In this example, a final win gives a target of plus one. Our training uses recorded games, so the estimate reflects the policy that generated those games.

**Transition:** TD uses an estimate of what follows instead of waiting for the final result.

### Slide 14 TD bootstraps from the next estimate

**Purpose:** Temporal-difference prediction. Planned 35 seconds.

**Say:** TD bootstraps from the next position’s value. Because the players alternate, we reverse the sign to express the opponent’s estimate from our player’s perspective. At a terminal position, we use the actual outcome. We fitted these targets offline using recorded games.

**Transition:** The results depend on which prediction task we measure.

### Slide 15 Distillation best matched the engine teacher

**Purpose:** Offline teacher-prediction result. Planned 30 seconds.

**Say:** Distillation gives the lowest error against the stronger engine. That is the target it was trained to match. This comparison uses the linear model, and the training distributions also differ, so the result doesn’t isolate the effect of the target alone.

**Transition:** Predicting the recorded returns gives a different ordering.

### Slide 16 MC and TD better matched recorded outcomes

**Purpose:** Offline outcome-prediction result. Planned 30 seconds.

**Say:** MC and TD have slightly lower error on the recorded game outcomes. Those are returns from the policy that played the games, rather than optimal play. The two charts use different metrics and evaluation sets, so their error values shouldn’t be compared directly. Both results concern prediction; we still need to test the decisions.

**Transition:** We did that in a separate experiment with a neural value model.

### Slide 17 Can a learned evaluator improve play?

**Purpose:** Learning method. Planned 30 seconds.

**Say:** The neural model learns a correction to a quick engine estimate, using a stronger engine as its target. We add that correction when ranking actions. This lets us test the question at the centre of the project: does a more accurate value estimate lead to better play?

**Transition:** We evaluated prediction, game outcomes and computational cost.

### Slide 18 Evaluation: prediction, play and cost

**Purpose:** Experimental comparison. Planned 25 seconds.

**Say:** We used paired games from the same openings, swapping colours. Both agents used the same one-move outer planner, while we measured prediction error, game score and time per move. Their computational costs were different, so this wasn’t an equal-time comparison.

**Transition:** First, the prediction result.

### Slide 19 Prediction error decreased by about 20%

**Purpose:** Prediction result. Planned 30 seconds.

**Say:** The neural model reduced prediction error by about twenty percent. This was development data that also helped us choose the model, so it isn’t an independent test set. It shows closer agreement with the stronger engine, which we then need to connect to game performance.

**Transition:** Here’s what happened in the games.

### Slide 20 The games did not establish a playing gain

**Purpose:** Outcome result. Planned 45 seconds.

**Say:** The neural model took 51.5 percent of the available game points. But the uncertainty interval includes equal points, so this batch doesn’t establish an improvement. It also doesn’t establish that the agents are equivalent. The prediction gain didn’t translate into a demonstrated playing gain in this one-ply setup.

**Transition:** And the more accurate predictions took extra computation.

**Delivery cues (not spoken):** Indicate the equal-points reference and interval. Explain the result, without reading the interval endpoints.

### Slide 21 The learned correction took about 3× as long

**Purpose:** Resource result. Planned 25 seconds.

**Say:** The neural correction took about three times as long per move. So we got lower prediction error at a higher cost, without an established improvement in game score. That makes the total computation budget important when we evaluate the complete agent.

**Transition:** A simple ranking example shows why prediction error and decision quality can differ.

### Slide 22 The reference slightly prefers Move A

**Purpose:** Illustrative ranking reference. Planned 20 seconds.

**Say:** Suppose these are the reference values for two actions. The reference slightly prefers Action A. These numbers are just an illustration.

**Transition:** Now consider an inaccurate predictor.

### Slide 23 Large value errors can preserve the choice

**Purpose:** Illustrative baseline choice. Planned 15 seconds.

**Say:** Its value estimates are quite far from the reference, but it still ranks A above B. So it makes the same choice as the reference.

**Transition:** A more accurate predictor can still change that choice.

### Slide 24 Closer values can still change the choice

**Purpose:** Illustrative learned choice. Planned 20 seconds.

**Say:** Here, the estimates are closer overall, but their order is reversed, so the agent chooses B. Lower average error doesn’t guarantee that the most important ranking is preserved. This illustrates a possible explanation; we haven’t established it as the cause of our game results.

**Transition:** That’s why we need to evaluate the full decision process.

### Slide 25 Conclusions

**Purpose:** Conclusion. Planned 40 seconds.

**Say:** Our approach uses observation history to maintain possible hidden states. The learning results show why a value estimate then has to be judged within the full decision process: it can become more accurate without an established improvement in play, while costing more time.

**Transition:** Our next evaluation should test that under a controlled budget.

### Slide 26 Next evaluation

**Purpose:** Next evaluation. Planned 15 seconds.

**Say:** We’d next like to test the learned values inside deeper search, give both agents the same total thinking time, and compare complete games. That evaluation is still to be done. Thank you for listening. We’re happy to take questions.

**Delivery cues (not spoken):** Allow three minutes for Q&A. Answer the question directly and use an evidence backup when helpful.

## Questions every team member should be able to answer

**Is the state the visible board?** No. The hidden environment state and the player’s observation are different. The game state includes the configuration and relevant history; the player has a current view and private history, represented here by possible boards. This finite hypothesis representation is not a claim of an exact Markov belief state. The value evaluator scores hypothetical complete positions inside planning.

**What makes this sequential decision making?** An action changes the position and what each side can observe next. The agent must account for hidden states and future replies.

**Why consider several possible boards?** The same observation can hide states with different action consequences. The rook example shows that a move can be exposed in one state and safe from immediate capture in another. The agent needs to compare actions across the states still consistent with its evidence.

**Why does the capture require history?** The current view alone leaves several rook locations possible. Remembering where our knight was and that the opponent’s king was too far away lets us identify the rook as the capturer. With only those two opponent pieces remaining, the rook must be at the capture location immediately afterward. Later moves require updating that inference.

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

**Why is the king already in check in C?** The hidden rook already attacks the king, but the player cannot see it. These rules allow moves while in check. The vertical moves therefore remain available even though they allow a capture.

## Delivery and rehearsal

Presenter 1 covers the introduction, hidden-state examples, information formulation and the aligned recorded demo (slides 1–11, retained allocation 5:25). Presenter 2 covers learning targets, experiments, interpretation and conclusions (slides 12–26, 7:00). Handoff once after slide 11. Confirm names and responsibilities with the team. Both presenters prepare for Q&A.

The retained allocations total 12:25; the confirmed speaking slot is 12 minutes, followed by three minutes Q&A. Rehearsal must determine the actual pacing. Do not read square coordinates, narrate individual moves or read every number from a chart. Explain what the visual establishes and connect it to the decision problem.

## Hidden backup navigation

27: archived match rows. 28: full value/move metrics. 29: offline belief context. 30: full MC/TD comparison. 31: retained-search prototype. 32: evaluator inventory. 33: contribution confirmations. 34: sources and scope. These are hidden during the core talk; the PDFs include all pages.

## Sources and evidence boundaries

**Rules:** Rules and worked example: docs/drafts/presentation-assets/hidden-rook-example.json and verify_hidden_rook_example.py. Public custom start k7/8/7r/8/3K4/8/8/8 b - - 0 1. Alternative hidden Black moves h6c6, h6e6 and h6d6 produce identical White observations, legal feedback and private history. White king d4 has all eight legal moves: c3/c4/c5, d3/d5, e3/e4/e5. A: rook c6 can capture after all three left-file moves. B: rook e6 can capture after all three right-file moves. C: rook d6 already attacks d4 and can capture after d3 or d5. All 24 move/state consequences are checked against RulesAdapter. No move avoids immediate capture across all three selected states. No assigned probabilities, optimality, inevitable-loss or complete-posterior claim. Check does not restrict legal moves under the project rules. Visibility is own occupied squares plus reachable destinations, with pawn and en-passant special cases. Rule reference: https://github.com/Mr-Teal/CS5446_project/blob/149278181ed6d2b52dce31991fb311a2a74339d0/pair_a_prep/rules_adapter.py . Destination dots follow the selected-piece convention requested by the user; reference https://support.chess.com/en/articles/8708625-how-do-i-turn-on-off-the-legal-moves-dots-on-the-board . Grey dots are legal destinations, not a safety guarantee; red dots annotate immediate capture in a revealed possibility.

**Values:** Evaluator evidence: https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/README.md . Separate development check: 959 games, 3818 decisions, 94963 eligible children. Network 1 selection also used this check set. Full-board D11 teacher. D1 MAE 0.095, Network 1 0.076. Mean errors and rankings address different objectives. Not a sealed-test result.

**Batch:** Archived evaluator batch: https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27 . Execution a5c5fb6, stand-in rules, predates later no-move/EP updates. Network 1: paired score 0.515, bootstrap 95% interval [0.448,0.585], 100 complete colour pairs. Baseline D1 median 11.1 ms/move, Network 1 36.1. Same one-ply outer planner, 256 particles, eight hypotheses, unequal compute. This is one row of seven separate comparisons against D1. Total 1400 attempts, 1399 finished, 699 complete pairs, six capped draws. Whole-belief context was not used online. Full tables remain in backup. Null-containing intervals do not establish equivalence. Methods: https://github.com/Mr-Teal/CS5446_project/blob/7c292af5881b8c81e4ffccb7300de21650c9c0ad/pair_b/docs/evaluation-methods-draft.md

**Demo:** Saved Fog Lab record, 6 November 2026: docs/drafts/presentation-assets/fog-lab-demo-record.json. The revised figure uses the Black observation after the first White move (plies[0].observations.black, ply 1) and the exact first two bot_turns[0].belief FENs at that same decision point. The agent perspective and time are aligned. This is a one-ply material-evaluator run, not a learned-model result. The opening action values are tied, so the figure illustrates information and hypotheses, not action quality or playing strength. No new run or hypotheses were generated.

**Search:** Search and current-scope review: https://github.com/Mr-Teal/CS5446_project/pull/33#issuecomment-6630857564 . The project includes search prototypes and a separate exact-history tracker. The archived batch isolates evaluators in a one-ply planner. A reviewed learned-leaf deeper-search comparison remains pending. PR65/66/67 mechanisms and author-reported full-agent arms remain separately reviewed, with raw evidence and implementation corrections outstanding. No complete Obscuro reproduction or new training requirement. Background: Zhang and Sandholm, https://arxiv.org/abs/2106.06068v2 and https://arxiv.org/abs/2506.01242v2 .

**Ranking:** Illustrative two-move values created only to explain a ranking mechanism, not project measurements: teacher [0.60,0.59], baseline [0.80,0.40], learned [0.58,0.60]. Mean absolute errors are 0.195 and 0.015. The baseline selects Move A; the learner selects Move B. This example does not identify the cause of the archived game result.

**Course:** CS4246/CS5446 course materials: Week 4, Lecture-sdm.pdf, PDF pages 21–22, 28, 35, 38 and 46 (return, prediction versus control, MC, TD and generalized policy iteration); Week 5, Lecture-rl-modelfree.pdf, PDF pages 5, 8, 13 and 15 (value-function approximation, sample targets and bootstrapping); Week 7, Lecture-guided-SDM.pdf, PDF pages 3–4 and 28–30 (decision-time search and leaf value estimates). This project uses a given rules model for planning; the network learns values rather than transition dynamics. The setting is a two-player imperfect-information game; it is not claimed to be a fully observed single-agent MDP.

**Mctd:** Separate offline model-free prediction study: https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/experiments/mc_td/RESULTS.md . All methods use the same linear correction model on 1217 inputs, distinct from neural Network 1. Distillation uses 638451 child rows from 6414 training games; MC/TD use 722500 trajectory positions from 6239 finished games, excluding 175 unfinished training games. Teacher MAE: Distil .0790, MC .2169, TD(0) .1846. Outcome MSE: Distil .5127, MC .4811, TD(0) .4758. Rounded core values are .079/.217/.185 and .513/.481/.476. Teacher error uses 94963 rows from 959 games; outcome MSE uses 106971 positions from 929 finished games, with 32 of 961 excluded. Outcomes follow the recorded depth-1 Stockfish plus 2–15% random behaviour policy, not optimal play. TD bootstraps negative next-player value and uses terminal outcome at the end; fitted semi-gradient TD(0) and TD(lambda=.8) reached the 15-round cap at full data. Training-row distributions differ, so the study does not isolate target choice. Archived trajectories have documented rule and engine-history limitations. Full methods, TD(lambda), move metrics, intervals and caveats remain in backup. These are recorded offline results, not a new training or playing-strength experiment.

**Targets:** The MC and TD target diagrams are pedagogical examples, not additional observations or experiment results. MC uses a completed return from the same player’s perspective. The non-terminal TD illustration uses zero immediate reward, gamma=1 and the alternating-player sign convention: a +0.4 next-player value becomes a -0.4 current-player target. Terminal positions use their recorded outcome. The real offline fitted targets are documented in the pinned MC/TD source.

**Worked example:** The public custom starting position and all eight candidate-move checks are in presentation-assets/hidden-rook-example.json. The example concerns immediate capture after these candidate moves, without an optimality or full-posterior claim.

**Demonstration:** The archived screenshot and two-ply record remain in presentation-assets/. The revised main figure aligns the Black observation and two saved hypotheses at the same pre-action decision point. It illustrates the information pipeline with a material evaluator, not learned-model strength.

**Course alignment:** The project guidelines, pages 3-5, emphasize an AI-familiar audience outside the topic and presentation relevance, organization, clarity, time management and Q&A. The 26-slide core develops two main points, explicitly introduces the game after the opening example and ends with conclusions and the next evaluation. The user confirmed 12 minutes presentation plus 3 minutes Q&A, superseding the older draft guideline duration.

**Contributions and AI assistance:** The existing individual contribution statements remain in backup and require each member's confirmation. Do not infer the human identity of xiaomiao-fong from the account name. Copilot assisted earlier drafts. Codex assisted the restructuring, rules-example checks and browser demonstration under Bryan's direction. No new training or formal match batch was run.

**Capture history:** Verified rook example in presentation-assets/capture-history-example.json and verify_capture_history_example.py. White king stays on d4, matching the opening. White knight d6 and visible Black king f7 rule out a king capture by distance. The illustrated hidden move is Rh6xd6. The rook is unseen before and after. Nine matching historical transitions converge to the same successor board with rook d6. A/B/C reuse rook c6/e6/d6; all match the current visible-board projection, but only C explains the capture history. The standalone fog view intentionally omits capture-event history. Later opponent moves require belief propagation.



**Course formulation:** Course formulation: Week 4 Lecture-mdp.pdf, PDF pages 7 (problem representation and observations), 10 and 13–14 (transition model and Markov property); Week 5 Lecture-rl-modelfree.pdf, PDF pages 3–4 (prediction versus control); Week 10 Lecture-game.pdf, PDF page 22 (information and sequential games). The underlying game state may be hidden; it is not the current observation. Rule-relevant history can be needed beyond piece placement. The project adapts this to private observation/action history and a finite possible-board belief representation. Do not claim that the hypothesis set is an exact posterior, an exact Markov sufficient statistic, or a fully observed single-agent MDP. Learned board evaluators score hypothetical complete boards within planning; the actor does not receive the referee’s true board.

## Presentation delivery review

| Previous slides | Issue | Revision |
| --- | --- | --- |
| First board question | Remaining pieces were assumed rather than shown. | Add “Black has” and “White has” with filled piece icons. |
| 7 | The risk summary repeated the three preceding possibilities. | Remove it and transition directly from the game explanation to history. |
| 9–10 | Current fog and candidate states made the same point on separate slides. | Combine them: current view on the left, candidate states and history filtering on the right. |
| 11 | “State = complete position” blurred hidden environment state and agent input. | Use the course’s state/observation distinction, and show observation/history to possible-board belief to action. |
| 13–14 | The figure changed player perspective and decision time without explaining it. | Use one Black observation with its two saved hypotheses at the same recorded decision. |

All later experimental content, numerical evidence and unrelated speaking budgets are retained. Filled pieces, hidden-rook inference, greetings, coordinate-free speech and the single handoff are preserved.
