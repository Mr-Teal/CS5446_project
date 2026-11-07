# Fog of War Chess

Presentation plan for a 12-minute presentation followed by 3-minute Q&A

7 November 2026. Twenty-eight core slides, eight hidden backups. Presenter names remain unassigned. Suggested split: Presenter 1 covers slides 1–13 (6:05), and Presenter 2 covers slides 14–28 (7:00), with one handoff after slide 13. This is a proposed allocation for team agreement.

## The argument

This presentation asks how to choose actions from incomplete observations and which learned values improve those decisions. It connects the worked example to state, evidence, action, return and policy; explains MC, TD and distillation targets; and separates offline prediction from the game outcomes of an induced decision rule. A before/after capture example shows why historical observations constrain the hidden state, and a second slide filters candidate boards using that history. Slide 11 connects belief tracking to search and the learned position values, replacing its repeated rook diagrams. The existing content is retained, with the later comparisons and ranking example split into shorter visual stages. The hypotheses slide redraws two exact saved hypotheses as native diagrams to replace its blurred crop. Detailed evidence stays in backup.

The team introduction adds 20 seconds. The two history-example slides retain 30 seconds each, and every other existing slide keeps its prior speaking allocation. The planned core therefore totals 13 minutes 5 seconds, 65 seconds beyond the 12-minute speaking slot. Delivery and rehearsal must resolve that overrun; no unrelated speaking budget has been reduced. These are planned timings, not measured rehearsal times. The confirmed total slot remains 15 minutes: 12 minutes presentation followed by 3 minutes Q&A.

## Run of show

| Slide | Slide purpose or finding | Planned time |
| --- | --- | --- |
| 1 | Fog of War Chess: project and team | 0:20 |
| 2 | Where would you move? | 0:25 |
| 3 | Possibility A: all three moves left are exposed | 0:20 |
| 4 | Possibility B: all three moves right are exposed | 0:20 |
| 5 | Possibility C: the king is already in check | 0:25 |
| 6 | Fog of War Chess | 0:35 |
| 7 | Every move can be dangerous in a hidden state | 0:40 |
| 8 | A capture reveals a hidden queen | 0:30 |
| 9 | History filters the possible boards | 0:30 |
| 10 | Decision making from private observations | 0:45 |
| 11 | Choosing a move under uncertainty | 0:35 |
| 12 | The player acts on a partial board | 0:20 |
| 13 | Fog Lab exposes the agent’s hypotheses | 0:20 |
| 14 | Three ways to learn position values | 0:25 |
| 15 | Monte Carlo learns from completed returns | 0:35 |
| 16 | TD bootstraps from the next estimate | 0:35 |
| 17 | Distillation best matched the engine teacher | 0:30 |
| 18 | MC and TD better matched recorded outcomes | 0:30 |
| 19 | Can a learned evaluator improve play? | 0:30 |
| 20 | Evaluation: prediction, play and cost | 0:25 |
| 21 | Prediction error decreased by about 20% | 0:30 |
| 22 | The games did not establish a playing gain | 0:45 |
| 23 | The learned correction took about 3× as long | 0:25 |
| 24 | The reference slightly prefers Move A | 0:20 |
| 25 | Large value errors can preserve the choice | 0:15 |
| 26 | Closer values can still change the choice | 0:20 |
| 27 | Conclusions | 0:40 |
| 28 | Next evaluation | 0:15 |

## Slide notes

### Slide 1 Fog of War Chess

**Purpose:** Project and team introduction. Planned 20 seconds.

**Say:** Hello everyone. We’re presenting our project on Fog of War Chess, where an agent has to act without seeing the full board. We looked at how to keep track of that uncertainty, and whether learning more accurate position values actually leads to better decisions.

**Transition:** I’ll start with a simple example of that uncertainty.

### Slide 2 Where would you move?

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** Imagine you’re controlling the white king. The opponent’s pieces are hidden, and the dots show all eight moves available to you. Which would you choose?

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

**Transition:** The important point in the example is the uncertainty about the state.

### Slide 7 Every move can be dangerous in a hidden state

**Purpose:** Hidden information. Planned 40 seconds.

**Say:** The observation was the same in all three cases, but the consequences of an action changed with the hidden state. These selected examples don’t tell us which move is best. They show why the agent needs to compare actions across several possible states.

**Transition:** The current observation also leaves out information we learned earlier.

### Slide 8 A capture reveals a hidden queen

**Purpose:** Historical observations. Planned 30 seconds.

**Say:** Here, our knight was visible before the opponent moved. After one opponent move, it has been captured, but the attacking piece is still hidden. We know the opponent only has a king and queen left, and the king was too far away to make that capture. So the queen must now be where our knight was. We’ve learned its location from the change in our observations.

**Transition:** That information would be lost if we only used the latest board view.

### Slide 9 History filters the possible boards

**Purpose:** Belief tracking. Planned 30 seconds.

**Say:** These boards all fit the current observation, but only one explains the capture we just saw. A belief tracker uses the observation history to keep the states that remain possible. This example narrows it down to one state; in a larger game, several may remain. We update those possibilities as new actions and observations arrive.

**Transition:** That gives the policy a more useful description of what might be happening.

### Slide 10 Decision making from private observations

**Purpose:** Sequential decision formulation. Planned 45 seconds.

**Say:** The policy has to act on partial observations, so its input needs to include history or a belief about the hidden state. Our objective is still the eventual game outcome. We use value estimates to compare actions, but whether those estimates help has to be tested through the decisions they produce.

**Transition:** Here’s how that works in our agent.

### Slide 11 Choosing a move under uncertainty

**Purpose:** Approach. Planned 35 seconds.

**Say:** The tracker supplies possible states. Search compares actions and replies across them, and the value function estimates positions where search stops. The rules provide the transitions. Our learning experiments focus on the value function and ask whether improving its predictions improves the move choice.

**Transition:** The interface helps us see what information the agent is working with.

### Slide 12 The player acts on a partial board

**Purpose:** Demonstration. Planned 20 seconds.

**Say:** This is the player’s partial view from a saved run. Some pieces are visible, while much of the board remains unknown. As moves change what we can see, the tracker carries earlier evidence forward. This demonstration uses a simple material evaluator.

**Transition:** We can also inspect the states the bot considers possible.

### Slide 13 Fog Lab exposes the agent’s hypotheses

**Purpose:** Demonstration. Planned 20 seconds.

**Say:** These are two hypotheses built from the bot’s own evidence. They show how uncertainty becomes a set of states the agent can reason over. The next question is how to value the outcomes reached during search.

**Transition:** I’ll hand over to my teammate to explain how we trained and evaluated those values.

**Delivery cues (not spoken):** Handoff to Presenter 2 after this slide.


### Slide 14 Three ways to learn position values

**Purpose:** Value learning and training targets. Planned 25 seconds.

**Say:** Thanks. We compared three training targets. Distillation learns from a stronger engine, Monte Carlo uses completed-game returns, and TD bootstraps from the next estimate. We first compared these targets using the same linear correction model. The neural model comes in the later game experiment.

**Transition:** Let’s briefly look at how the return-based targets work.

### Slide 15 Monte Carlo learns from completed returns

**Purpose:** Monte Carlo prediction. Planned 35 seconds.

**Say:** Monte Carlo uses the outcome of the completed game as the target for an earlier position. In this example, a final win gives a target of plus one. Our training uses recorded games, so the estimate reflects the policy that generated those games.

**Transition:** TD uses an estimate of what follows instead of waiting for the final result.

### Slide 16 TD bootstraps from the next estimate

**Purpose:** Temporal-difference prediction. Planned 35 seconds.

**Say:** TD bootstraps from the next position’s value. Because the players alternate, we reverse the sign to express the opponent’s estimate from our player’s perspective. At a terminal position, we use the actual outcome. We fitted these targets offline using recorded games.

**Transition:** The results depend on which prediction task we measure.

### Slide 17 Distillation best matched the engine teacher

**Purpose:** Offline teacher-prediction result. Planned 30 seconds.

**Say:** Distillation gives the lowest error against the stronger engine. That is the target it was trained to match. This comparison uses the linear model, and the training distributions also differ, so the result doesn’t isolate the effect of the target alone.

**Transition:** Predicting the recorded returns gives a different ordering.

### Slide 18 MC and TD better matched recorded outcomes

**Purpose:** Offline outcome-prediction result. Planned 30 seconds.

**Say:** MC and TD have slightly lower error on the recorded game outcomes. Those are returns from the policy that played the games, rather than optimal play. The two charts use different metrics and evaluation sets, so their error values shouldn’t be compared directly. Both results concern prediction; we still need to test the decisions.

**Transition:** We did that in a separate experiment with a neural value model.

### Slide 19 Can a learned evaluator improve play?

**Purpose:** Learning method. Planned 30 seconds.

**Say:** The neural model learns a correction to a quick engine estimate, using a stronger engine as its target. We add that correction when ranking actions. This lets us test the question at the centre of the project: does a more accurate value estimate lead to better play?

**Transition:** We evaluated prediction, game outcomes and computational cost.

### Slide 20 Evaluation: prediction, play and cost

**Purpose:** Experimental comparison. Planned 25 seconds.

**Say:** We used paired games from the same openings, swapping colours. Both agents used the same one-move outer planner, while we measured prediction error, game score and time per move. Their computational costs were different, so this wasn’t an equal-time comparison.

**Transition:** First, the prediction result.

### Slide 21 Prediction error decreased by about 20%

**Purpose:** Prediction result. Planned 30 seconds.

**Say:** The neural model reduced prediction error by about twenty percent. This was development data that also helped us choose the model, so it isn’t an independent test set. It shows closer agreement with the stronger engine, which we then need to connect to game performance.

**Transition:** Here’s what happened in the games.

### Slide 22 The games did not establish a playing gain

**Purpose:** Outcome result. Planned 45 seconds.

**Say:** The neural model took 51.5 percent of the available game points. But the uncertainty interval includes equal points, so this batch doesn’t establish an improvement. It also doesn’t establish that the agents are equivalent. The prediction gain didn’t translate into a demonstrated playing gain in this one-ply setup.

**Transition:** And the more accurate predictions took extra computation.

**Delivery cues (not spoken):** Indicate the equal-points reference and interval. Explain the result, without reading the interval endpoints.


### Slide 23 The learned correction took about 3× as long

**Purpose:** Resource result. Planned 25 seconds.

**Say:** The neural correction took about three times as long per move. So we got lower prediction error at a higher cost, without an established improvement in game score. That makes the total computation budget important when we evaluate the complete agent.

**Transition:** A simple ranking example shows why prediction error and decision quality can differ.

### Slide 24 The reference slightly prefers Move A

**Purpose:** Illustrative ranking reference. Planned 20 seconds.

**Say:** Suppose these are the reference values for two actions. The reference slightly prefers Action A. These numbers are just an illustration.

**Transition:** Now consider an inaccurate predictor.

### Slide 25 Large value errors can preserve the choice

**Purpose:** Illustrative baseline choice. Planned 15 seconds.

**Say:** Its value estimates are quite far from the reference, but it still ranks A above B. So it makes the same choice as the reference.

**Transition:** A more accurate predictor can still change that choice.

### Slide 26 Closer values can still change the choice

**Purpose:** Illustrative learned choice. Planned 20 seconds.

**Say:** Here, the estimates are closer overall, but their order is reversed, so the agent chooses B. Lower average error doesn’t guarantee that the most important ranking is preserved. This illustrates a possible explanation; we haven’t established it as the cause of our game results.

**Transition:** That’s why we need to evaluate the full decision process.

### Slide 27 Conclusions

**Purpose:** Conclusion. Planned 40 seconds.

**Say:** Our approach uses observation history to maintain possible hidden states. The learning results show why a value estimate then has to be judged within the full decision process: it can become more accurate without an established improvement in play, while costing more time.

**Transition:** Our next evaluation should test that under a controlled budget.

### Slide 28 Next evaluation

**Purpose:** Next evaluation. Planned 15 seconds.

**Say:** We’d next like to test the learned values inside deeper search, give both agents the same total thinking time, and compare complete games. That evaluation is still to be done. Thank you for listening. We’re happy to take questions.

**Delivery cues (not spoken):** Allow three minutes for Q&A. Answer the question directly and use an evidence backup when helpful.


## Questions every team member should be able to answer

**What makes this sequential decision making?** An action changes the position and what each side can observe next. The agent must account for hidden states and future replies.

**Why consider several possible boards?** The same observation can hide states with different action consequences. The rook example shows that a move can be exposed in one state and safe from immediate capture in another. The agent needs to compare actions across the states still consistent with its evidence.

**Why does the capture require history?** The current view alone leaves several queen locations possible. Remembering where our knight was and that the opponent’s king was too far away lets us identify the queen as the capturer. With only those two opponent pieces remaining, the queen must be at the capture location immediately afterward. Later moves require updating that inference.

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

The proposed two-presenter allocation keeps each person on one continuous section: Presenter 1 introduces the team and problem, historical evidence, belief tracking and demonstration (slides 1–13); Presenter 2 explains learning methods, evaluation, findings and conclusions (slides 14–28). Handoff once after slide 13. Confirm names and responsibilities with the team. Both presenters prepare for Q&A. All planned slide times are retained. Each speaker must understand both findings. Record a complete rehearsal with handovers and chart pauses. Slides 1–13 total 6:05; slides 14–28 retain 7:00. The six worked-example and game-introduction slides (2–7) take 2:45; do not repeat the rules or chess tactics. Use the retained demo slides as brief visual steps. The revised core totals 13:05. The speaker will manage delivery within the confirmed 12-minute presentation slot; existing speaking allocations have not been reduced. Cut secondary spoken detail before cutting the interpretation of the result. No rehearsal has been performed for this revision.

Use the final slide as an academic conclusion and next evaluation, then invite questions. Reserve the full three minutes for Q&A. Answer the direct question first, state evidence and limitations, and open a backup only when it supports that answer. Check that a listener can explain the central findings after one viewing. On the uncertainty plot, point to equal points and the interval before giving the conclusion. Explain the demonstration through the partial board and possible boards, without reading the move table.

## Hidden backup navigation

29: all seven archived match rows. 30: full value and move metrics. 31: offline belief context. 32: full MC/TD comparison. 33: retained-search prototype. 34: evaluator inventory. 35: contribution confirmations. 36: sources and scope. Hidden slides are skipped during the core slide show. The PDF includes all pages for review.

## Sources and evidence boundaries

**Rules:** Rules and worked example: docs/drafts/presentation-assets/hidden-rook-example.json and verify_hidden_rook_example.py. Public custom start k7/8/7r/8/3K4/8/8/8 b - - 0 1. Alternative hidden Black moves h6c6, h6e6 and h6d6 produce identical White observations, legal feedback and private history. White king d4 has all eight legal moves: c3/c4/c5, d3/d5, e3/e4/e5. A: rook c6 can capture after all three left-file moves. B: rook e6 can capture after all three right-file moves. C: rook d6 already attacks d4 and can capture after d3 or d5. All 24 move/state consequences are checked against RulesAdapter. No move avoids immediate capture across all three selected states. No assigned probabilities, optimality, inevitable-loss or complete-posterior claim. Check does not restrict legal moves under the project rules. Visibility is own occupied squares plus reachable destinations, with pawn and en-passant special cases. Rule reference: https://github.com/Mr-Teal/CS5446_project/blob/149278181ed6d2b52dce31991fb311a2a74339d0/pair_a_prep/rules_adapter.py . Destination dots follow the selected-piece convention requested by the user; reference https://support.chess.com/en/articles/8708625-how-do-i-turn-on-off-the-legal-moves-dots-on-the-board . Grey dots are legal destinations, not a safety guarantee; red dots annotate immediate capture in a revealed possibility.

**Values:** Evaluator evidence: https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/README.md . Separate development check: 959 games, 3818 decisions, 94963 eligible children. Network 1 selection also used this check set. Full-board D11 teacher. D1 MAE 0.095, Network 1 0.076. Mean errors and rankings address different objectives. Not a sealed-test result.

**Batch:** Archived evaluator batch: https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27 . Execution a5c5fb6, stand-in rules, predates later no-move/EP updates. Network 1: paired score 0.515, bootstrap 95% interval [0.448,0.585], 100 complete colour pairs. Baseline D1 median 11.1 ms/move, Network 1 36.1. Same one-ply outer planner, 256 particles, eight hypotheses, unequal compute. This is one row of seven separate comparisons against D1. Total 1400 attempts, 1399 finished, 699 complete pairs, six capped draws. Whole-belief context was not used online. Full tables remain in backup. Null-containing intervals do not establish equivalence. Methods: https://github.com/Mr-Teal/CS5446_project/blob/7c292af5881b8c81e4ffccb7300de21650c9c0ad/pair_b/docs/evaluation-methods-draft.md

**Demo:** Actual local Fog Lab browser opening demonstration, 6 November 2026. Local historical checkout, Teal rules, material scorer, seed 0. Human e2e4, bot b8a6. Saved screenshot and two-ply record: docs/drafts/presentation-assets/. The diagnostic panel shows the bot's own hypotheses for inspection. This is not Fair mode, a full game, or a playing-strength result. It does not demonstrate the unmerged Pair A Fog Lab bot or the learned evaluator. The displayed 22 ms is this local action, not the archived batch timing. The hypotheses slide redraws the exact first two saved bot_turns[0].belief FENs as native editable diagrams, preserving Fog Lab square colours and using filled white/black SVG pieces. These replace the magnified screenshot crop without generating new hypotheses.

**Search:** Search and current-scope review: https://github.com/Mr-Teal/CS5446_project/pull/33#issuecomment-6630857564 . The project includes search prototypes and a separate exact-history tracker. The archived batch isolates evaluators in a one-ply planner. A reviewed learned-leaf deeper-search comparison remains pending. PR65/66/67 mechanisms and author-reported full-agent arms remain separately reviewed, with raw evidence and implementation corrections outstanding. No complete Obscuro reproduction or new training requirement. Background: Zhang and Sandholm, https://arxiv.org/abs/2106.06068v2 and https://arxiv.org/abs/2506.01242v2 .

**Ranking:** Illustrative two-move values created only to explain a ranking mechanism, not project measurements: teacher [0.60,0.59], baseline [0.80,0.40], learned [0.58,0.60]. Mean absolute errors are 0.195 and 0.015. The baseline selects Move A; the learner selects Move B. This example does not identify the cause of the archived game result.

**Course:** CS4246/CS5446 course materials: Week 4, Lecture-sdm.pdf, PDF pages 21–22, 28, 35, 38 and 46 (return, prediction versus control, MC, TD and generalized policy iteration); Week 5, Lecture-rl-modelfree.pdf, PDF pages 5, 8, 13 and 15 (value-function approximation, sample targets and bootstrapping); Week 7, Lecture-guided-SDM.pdf, PDF pages 3–4 and 28–30 (decision-time search and leaf value estimates). This project uses a given rules model for planning; the network learns values rather than transition dynamics. The setting is a two-player imperfect-information game; it is not claimed to be a fully observed single-agent MDP.

**Mctd:** Separate offline model-free prediction study: https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/experiments/mc_td/RESULTS.md . All methods use the same linear correction model on 1217 inputs, distinct from neural Network 1. Distillation uses 638451 child rows from 6414 training games; MC/TD use 722500 trajectory positions from 6239 finished games, excluding 175 unfinished training games. Teacher MAE: Distil .0790, MC .2169, TD(0) .1846. Outcome MSE: Distil .5127, MC .4811, TD(0) .4758. Rounded core values are .079/.217/.185 and .513/.481/.476. Teacher error uses 94963 rows from 959 games; outcome MSE uses 106971 positions from 929 finished games, with 32 of 961 excluded. Outcomes follow the recorded depth-1 Stockfish plus 2–15% random behaviour policy, not optimal play. TD bootstraps negative next-player value and uses terminal outcome at the end; fitted semi-gradient TD(0) and TD(lambda=.8) reached the 15-round cap at full data. Training-row distributions differ, so the study does not isolate target choice. Archived trajectories have documented rule and engine-history limitations. Full methods, TD(lambda), move metrics, intervals and caveats remain in backup. These are recorded offline results, not a new training or playing-strength experiment.

**Targets:** The MC and TD target diagrams are pedagogical examples, not additional observations or experiment results. MC uses a completed return from the same player’s perspective. The non-terminal TD illustration uses zero immediate reward, gamma=1 and the alternating-player sign convention: a +0.4 next-player value becomes a -0.4 current-player target. Terminal positions use their recorded outcome. The real offline fitted targets are documented in the pinned MC/TD source.

**Worked example:** The public custom starting position and all eight candidate-move checks are in presentation-assets/hidden-rook-example.json. The example concerns immediate capture after these candidate moves, without an optimality or full-posterior claim.

**Demonstration:** The screenshot and two-ply game record are in presentation-assets/. It uses a material bot on a historical checkout. The displayed single-action timing is not an archived experiment measurement.

**Course alignment:** The project guidelines, pages 3-5, emphasize an AI-familiar audience outside the topic and presentation relevance, organization, clarity, time management and Q&A. The 28-slide core develops two main points, explicitly introduces the game after the opening example and ends with conclusions and the next evaluation. The user confirmed 12 minutes presentation plus 3 minutes Q&A, superseding the older draft guideline duration.

**Contributions and AI assistance:** The existing individual contribution statements remain in backup and require each member's confirmation. Do not infer the human identity of xiaomiao-fong from the account name. Copilot assisted earlier drafts. Codex assisted the restructuring, rules-example checks and browser demonstration under Bryan's direction. No new training or formal match batch was run.

**Capture history:** Constructed example in presentation-assets/capture-history-example.json and verify_capture_history_example.py. White Ka1/Nd4, Black Kf5 and an unseen queen; the illustrated hidden move is Qh4xd4. Neither White view contains the queen. All 25 hidden transitions consistent with both views and capture feedback lead to the same successor board with Qd4. The three candidate diagrams show full-state hypotheses, not direct observations. In larger positions multiple hypotheses generally remain. The queen’s inferred location is specific to this instant.


## Presentation delivery review

The spoken script addresses an RL professor and TA. It opens with a greeting and develops two points: history supports hidden-state inference, and learned values must be evaluated through decisions and outcomes. Team names stay on the title slide. No spoken passage names a board square or recites move notation. Detailed positions, numerical evidence and source records remain available for questions.

| Slides | Delivery issue | Revision |
| --- | --- | --- |
| 1 | The opening began with project description before acknowledging the audience. | Add a greeting, introduce the project and state its RL question. |
| 2–7 | The opening risked becoming a lesson in chess squares and move mechanics. | Use the red destination circles to show that identical observations can hide different action consequences. Keep all eight destinations visible. |
| 8–9 | Capture details competed with the reason for belief tracking. | Explain the inference from a disappearance and the prior observation. State what history adds beyond the current observation. |
| 10–13 | The architecture and demo could repeat the examples or narrate individual chess moves. | Connect history to possible states, search and value estimation. Use the interface as an illustration of the agent’s information. |
| 14–18 | Implementation details and numerical narration obscured the difference between learning targets. | Explain target source and evaluation objective. Keep the offline-policy, training-distribution and metric limitations that change the interpretation. |
| 19–23 | Engine settings, absolute timing and error values could distract from the experimental finding. | State the prediction gain, uncertainty in playing gain and relative computational cost. Keep exact evidence on the charts and in source notes. |
| 24–26 | Reading the illustrative numbers slowed the ranking argument. | Explain the reference choice, preserved ranking and flipped ranking without reciting each value. |
| 27–28 | The closing needed to return to the RL question and conclude as a live presentation. | Conclude on history and decision-level evaluation, state the planned controlled-budget test, thank the audience and invite questions. |

White pieces use filled white SVG artwork with dark outlines, and Black pieces use the matching black set. All worked boards keep their original piece positions. The saved partial-board demo is redrawn from its recorded visible-square and piece data, rather than retaining the outline-font screenshot. Coordinate labels and coordinate-based captions are removed from the main diagrams.
