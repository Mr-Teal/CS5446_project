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
| 3 | Possibility A | 0:20 |
| 4 | Possibility B | 0:20 |
| 5 | Possibility C | 0:25 |
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

**Say:** Hello everyone. Today we’ll be presenting our Fog of War Chess project. Our agent has to choose moves without seeing the full board. We explored how it can keep track of what might be hidden, and whether learning more accurate position values helps it make better decisions.

**Transition:** Let’s start with a situation the agent could face.

### Slide 2 Where would you move?

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** Look at this chessboard. White has only a king left, while Black still has a king and a rook. If you were playing White, what move would you make? All eight surrounding squares are available, but you can’t see where Black’s pieces are.

**Transition:** Let’s look at what could be hidden.

**Delivery cues (not spoken):** Pause briefly for the audience to consider the choice. Avoid explaining chess notation or individual squares.

### Slide 3 Possibility A

**Purpose:** Hidden information. Planned 20 seconds.

**Say:** Suppose Black’s rook is here. Any of the three moves to the left would put our king in its path, so Black could capture it on the next turn.

**Transition:** But we don’t know that the rook is there.

**Delivery cues (not spoken):** Indicate the three threatened destinations together without describing their colour or naming squares.

### Slide 4 Possibility B

**Purpose:** Hidden information. Planned 20 seconds.

**Say:** If the rook were on the other side, the three moves to the right would allow it to capture our king instead. Our view of the board would still be exactly the same.

**Transition:** There’s another possibility.

### Slide 5 Possibility C

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** The rook could already be attacking our king without us knowing. Moving straight up or down would still leave the king exposed. In this version of chess, those moves are allowed even though Black could capture us next.

**Transition:** So what makes this different from ordinary chess?

### Slide 6 Fog of War Chess

**Purpose:** Game and problem formulation. Planned 35 seconds.

**Say:** In Fog of War Chess, we win by capturing the opponent’s king. We can only see part of the board, and the game doesn’t stop us from moving into danger. Each move changes the position and what we can see. For our agent, this means choosing actions with only partial information.

**Transition:** But the current view isn’t all the information we have.

### Slide 7 A capture reveals a hidden rook

**Purpose:** Historical observations. Planned 30 seconds.

**Say:** Now suppose we also have a knight. Before Black moves, we can see our knight and Black’s king. After Black moves, our knight has been captured. The king was too far away to capture it, so it must have been the rook. That tells us where the rook is now, even though we still can’t see it.

**Transition:** Would we know that if we kept only the latest view?

### Slide 8 History filters the possible boards

**Purpose:** Belief tracking. Planned 35 seconds.

**Say:** If we forget the capture and look only at what we can see now, all three positions fit. Remembering the capture rules out A and B, leaving C. That’s why our agent needs a belief tracker: it keeps track of which hidden boards still fit what has happened so far.

**Transition:** This changes the information our agent uses to make a decision.

### Slide 9 Information available for a decision

**Purpose:** Sequential decision formulation. Planned 45 seconds.

**Say:** The actual game state determines what can happen next, but our agent doesn’t get to see all of it. It gets a partial view and a history of its own actions and observations. We use that history to maintain possible boards. The agent then chooses a move using those possibilities. Treating the latest view as the full state would throw away information we already have.

**Transition:** How do we choose a move when several boards are still possible?

### Slide 10 Choosing a move under uncertainty

**Purpose:** Approach. Planned 35 seconds.

**Say:** We consider possible boards from the tracker and use search to compare moves and the opponent’s replies. When search stops, a value function estimates how good the resulting positions are. We already have the rules to simulate moves. What we want to learn is a better value estimate, and then test whether it helps us choose better moves.

**Transition:** Here’s what those possible boards look like in a recorded decision.

### Slide 11 One observation, several possible hidden states

**Purpose:** Demonstration. Planned 35 seconds.

**Say:** This time, we’re looking from the Black bot’s perspective. It can’t see White’s knight, so it considers different places the knight could be. These two boards both fit what it can observe. The agent has to evaluate moves across such possibilities. This particular recording used a simple material score.

**Transition:** I’ll hand over to my teammate to explain how we learned and tested position values.

**Delivery cues (not spoken):** Handoff to Presenter 2 after this slide.

### Slide 12 Three ways to learn position values

**Purpose:** Value learning and training targets. Planned 25 seconds.

**Say:** Thanks. We compared three ways to learn position values. Distillation learns to match a stronger engine. Monte Carlo learns from completed-game outcomes. TD learns from the estimate at the next position. We first compared them using the same linear model, then tested a separate neural model in games.

**Transition:** For Monte Carlo, the target comes from how the game ends.

### Slide 13 Monte Carlo learns from completed returns

**Purpose:** Monte Carlo prediction. Planned 35 seconds.

**Say:** A position might occur long before we know who wins. Monte Carlo waits for the game’s outcome and uses that return as the target. Here, the player eventually wins, so the earlier position gets a target of plus one. Because we use recorded games, we’re learning about the policy that played them.

**Transition:** TD gets its target differently.

### Slide 14 TD bootstraps from the next estimate

**Purpose:** Temporal-difference prediction. Planned 35 seconds.

**Say:** TD uses the value estimate at the next position. That next position belongs to the opponent, so we reverse the sign to put it back in our player’s perspective. At the end of the game, we use the actual outcome. We fitted these targets from recorded games, rather than learning during live play.

**Transition:** We then tested what each method learned to predict.

### Slide 15 Distillation best matched the engine teacher

**Purpose:** Offline teacher-prediction result. Planned 30 seconds.

**Say:** Distillation came closest to the stronger engine’s values, which is what it was trained to predict. The methods used the same linear model, but different training distributions. So we can’t attribute the difference to the training target alone.

**Transition:** What if we compare them against game outcomes instead?

### Slide 16 MC and TD better matched recorded outcomes

**Purpose:** Offline outcome-prediction result. Planned 30 seconds.

**Say:** MC and TD did slightly better at predicting the recorded outcomes. That means predicting returns under the policy that played those games, rather than optimal play. This chart uses a different metric and evaluation set from the previous one, so we compare methods within each chart. So far, we’ve only tested predictions.

**Transition:** To test actual play, we ran a separate experiment with a neural value model.

### Slide 17 Can a learned evaluator improve play?

**Purpose:** Learning method. Planned 30 seconds.

**Say:** For this experiment, the neural model learns a correction to a quick engine estimate, using a stronger engine as the target. We add that correction when comparing moves. The question is whether the more accurate estimates actually help the agent play better.

**Transition:** We checked prediction accuracy, game results and time per move.

### Slide 18 Evaluation: prediction, play and cost

**Purpose:** Experimental comparison. Planned 25 seconds.

**Say:** We played each opening twice, swapping the agents’ colours. Both agents looked one move ahead in the outer planner. We compared game scores and time per move, alongside a separate prediction check. Their computational costs differed, so the games weren’t an equal-time comparison.

**Transition:** Did the predictions improve?

### Slide 19 Prediction error decreased by about 20%

**Purpose:** Prediction result. Planned 30 seconds.

**Say:** Yes. Prediction error fell by about twenty percent. But we also used this development data to help choose the model, so it isn’t an independent test. The model agreed more closely with the stronger engine. The next question is whether that helped it win more points.

**Transition:** The game results were less conclusive.

### Slide 20 The games did not establish a playing gain

**Purpose:** Outcome result. Planned 45 seconds.

**Say:** The neural model scored 51.5 percent of the available points. That’s slightly above half, but the uncertainty interval includes an even split. We can’t conclude that it improved play, or that the two agents are equivalent. In this one-ply setup, the better predictions didn’t produce a demonstrated gain in game score.

**Transition:** They also came at a computational cost.

**Delivery cues (not spoken):** Indicate the equal-points reference and interval. Explain the result, without reading the interval endpoints.

### Slide 21 The learned correction took about 3× as long

**Purpose:** Resource result. Planned 25 seconds.

**Say:** The learned correction took about three times as long per move. We therefore got more accurate predictions at a higher cost, without a demonstrated gain in game score. That matters because extra computation could also be spent searching further ahead.

**Transition:** Why might smaller prediction errors still fail to improve the chosen move?

### Slide 22 The reference slightly prefers Move A

**Purpose:** Illustrative ranking reference. Planned 20 seconds.

**Say:** Consider a simple illustration, rather than a measured result. The reference values put A just above B, so A is the preferred action.

**Transition:** Now suppose our predictor gets the values wrong.

### Slide 23 Large value errors can preserve the choice

**Purpose:** Illustrative baseline choice. Planned 15 seconds.

**Say:** These estimates are far from the reference values, but A still ranks above B. Despite the large errors, the agent chooses the preferred action.

**Transition:** Now let’s make the predictions more accurate overall.

### Slide 24 Closer values can still change the choice

**Purpose:** Illustrative learned choice. Planned 20 seconds.

**Say:** The estimates are closer to the reference, but they put B above A. The agent now chooses the wrong action relative to that reference. Smaller average errors don’t necessarily preserve the ranking that matters for a decision. This could explain a gap between prediction and play, but we haven’t shown that it caused our game results.

**Transition:** That’s why we evaluate decisions as well as prediction error.

### Slide 25 Conclusions

**Purpose:** Conclusion. Planned 40 seconds.

**Say:** Observation history helps our agent narrow down what might be hidden. But once we have those possible states, a more accurate value function doesn’t automatically mean better decisions. Our learned correction improved prediction, cost more time, and did not establish a gain in game score. We need to judge it as part of the agent that uses it.

**Transition:** The next test should make that trade-off explicit.

### Slide 26 Next evaluation

**Purpose:** Next evaluation. Planned 15 seconds.

**Say:** We’d next test the learned values in deeper search, give both agents the same total thinking time, and compare complete games. That evaluation is still to be done. Thank you for listening. We’re happy to take questions.

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

## Spoken script review

The spoken passages now explain the choice, inference or result rather than narrating colours and slide layout. Existing speaking allocations, slide order and the single handoff are retained.

| Slides | Delivery issue | Revision |
| --- | --- | --- |
| 2–5 | The opening described icons, then narrated red markings. | Ask the audience what they would do and explain each hidden rook’s consequences. |
| 6–8 | The example changed the available pieces without an introduction. | Introduce the knight explicitly, explain the capture inference, then ask what a latest-view-only agent would miss. |
| 9–10 | The formulation sounded like a definition read from a report. | Connect hidden state to the information the agent actually has, then explain where the learned value function enters. |
| 11 | Left/right narration distracted from the reason the hypotheses differ. | Explain that the unseen knight can occupy different positions, then connect those possibilities to move evaluation. |
| 12–16 | Technical descriptions and transitions gave little reason to follow the comparison. | Explain how the targets arise and ask what each method predicts well. Keep the policy and evaluation caveats. |
| 17–21 | The central question was repeatedly announced. | Follow one sequence: predictions improved, game results were inconclusive, and computation increased. Retain the development-set and unequal-compute limitations. |
| 22–24 | The ranking example used generic presenter transitions. | Walk through the choice: wrong values can preserve the preferred action, while closer values can reverse it. Retain the illustrative scope. |
| 25–26 | The conclusion used abstract phrasing. | State the observed trade-off and the next equal-time deeper-search evaluation directly. |

## Visible slide copy review

Removed repeated headings, explanations of obvious colours and generic footer text from the core slides. The opening possibilities now use short titles with one consequence beside each board. Removed captions that restated the title, diagram or adjacent labels, including “Teacher agreement is one objective”. Enlarged the charts where their duplicated side commentary was removed.

Retained information needed to interpret the results: recorded-policy outcomes, different evaluation sets, development-set model selection, unequal computation, uncertainty intervals and the illustrative status of the ranking example. Full source details remain in speaker notes and the hidden evidence slides. Speech, timing, slide order and the single presenter handoff are unchanged.
