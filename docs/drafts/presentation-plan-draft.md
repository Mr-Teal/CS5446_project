# Fog of War Chess

Presentation plan for a 12-minute presentation followed by 3-minute Q&A

8 November 2026. Twenty-six core slides, eight hidden backups. Bryan: slides 1–11 (5:25). Colin: slides 12–26 (7:10). One handoff after slide 11.

## The argument

Observation history helps constrain hidden state. Learned values must be evaluated through decisions, outcomes and computation. Colin presents three distinct studies: linear prediction targets, a neural correction tested in games, and a preliminary network trained from search-generated targets.

The rehearsal guide totals 12:35, allowing pauses for the comparison charts and action-ranking example. This is 35 seconds above the 12-minute presentation slot, with a separate three-minute Q&A. It is a planning guide, not a measured runtime. Prioritize understanding and natural delivery when rehearsing.

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
| 12 | Three ways to learn position values | 0:20 |
| 13 | Monte Carlo learns from completed returns | 0:30 |
| 14 | TD bootstraps from the next estimate | 0:25 |
| 15 | Distillation best matched the engine teacher | 0:30 |
| 16 | MC and TD better matched recorded outcomes | 0:30 |
| 17 | Testing a learned value correction | 0:40 |
| 18 | Prediction error decreased by about 20% | 0:25 |
| 19 | The games did not establish a playing gain | 0:40 |
| 20 | The learned correction took about 3× as long | 0:25 |
| 21 | The reference slightly prefers Move A | 0:15 |
| 22 | Large value errors can preserve the choice | 0:20 |
| 23 | Closer values can still change the choice | 0:30 |
| 24 | Learning from our own search | 0:25 |
| 25 | Does the learned evaluator help? | 0:30 |
| 26 | Conclusions and next evaluation | 0:45 |

## Slide notes

### Slide 1 Fog of War Chess

**Presenter:** Bryan

**Purpose:** Project and team introduction. Planned 20 seconds.

**Say:** Hello everyone. Today we’ll be presenting our Fog of War Chess project. Our agent has to choose moves without seeing the full board. We explored how it can keep track of what might be hidden, and whether learning more accurate position values helps it make better decisions.

**Transition:** Let’s start with a situation the agent could face.

### Slide 2 Where would you move?

**Presenter:** Bryan

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** Look at this chessboard. White has only a king left, while Black still has a king and a rook. If you were playing White, what move would you make? All eight surrounding squares are available, but you can’t see where Black’s pieces are.

**Transition:** Let’s look at what could be hidden.

**Delivery cues (not spoken):** Pause briefly for the audience to consider the choice. Avoid explaining chess notation or individual squares.

### Slide 3 Possibility A

**Presenter:** Bryan

**Purpose:** Hidden information. Planned 20 seconds.

**Say:** Suppose Black’s rook is here. Any of the three moves to the left would put our king in its path, so Black could capture it on the next turn.

**Transition:** But we don’t know that the rook is there.

**Delivery cues (not spoken):** Indicate the three threatened destinations together without describing their colour or naming squares.

### Slide 4 Possibility B

**Presenter:** Bryan

**Purpose:** Hidden information. Planned 20 seconds.

**Say:** If the rook were on the other side, the three moves to the right would allow it to capture our king instead. Our view of the board would still be exactly the same.

**Transition:** There’s another possibility.

### Slide 5 Possibility C

**Presenter:** Bryan

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** The rook could already be attacking our king without us knowing. Moving straight up or down would still leave the king exposed. In this version of chess, those moves are allowed even though Black could capture us next.

**Transition:** So what makes this different from ordinary chess?

### Slide 6 Fog of War Chess

**Presenter:** Bryan

**Purpose:** Game and problem formulation. Planned 35 seconds.

**Say:** In Fog of War Chess, we win by capturing the opponent’s king. We can only see part of the board, and the game doesn’t stop us from moving into danger. Each move changes the position and what we can see. For our agent, this means choosing actions with only partial information.

**Transition:** But the current view isn’t all the information we have.

### Slide 7 A capture reveals a hidden rook

**Presenter:** Bryan

**Purpose:** Historical observations. Planned 30 seconds.

**Say:** Now suppose we also have a knight. Before Black moves, we can see our knight and Black’s king. After Black moves, our knight has been captured. The king was too far away to capture it, so it must have been the rook. That tells us where the rook is now, even though we still can’t see it.

**Transition:** Would we know that if we kept only the latest view?

### Slide 8 History filters the possible boards

**Presenter:** Bryan

**Purpose:** Belief tracking. Planned 35 seconds.

**Say:** If we forget the capture and look only at what we can see now, all three positions fit. Remembering the capture rules out A and B, leaving C. That’s why our agent needs a belief tracker: it keeps track of which hidden boards still fit what has happened so far.

**Transition:** This changes the information our agent uses to make a decision.

### Slide 9 Information available for a decision

**Presenter:** Bryan

**Purpose:** Sequential decision formulation. Planned 45 seconds.

**Say:** The actual game state determines what can happen next, but our agent doesn’t get to see all of it. It gets a partial view and a history of its own actions and observations. We use that history to maintain possible boards. The agent then chooses a move using those possibilities. Treating the latest view as the full state would throw away information we already have.

**Transition:** How do we choose a move when several boards are still possible?

### Slide 10 Choosing a move under uncertainty

**Presenter:** Bryan

**Purpose:** Approach. Planned 35 seconds.

**Say:** We consider possible boards from the tracker and use search to compare moves and the opponent’s replies. When search stops, a value function estimates how good the resulting positions are. We already have the rules to simulate moves. What we want to learn is a better value estimate, and then test whether it helps us choose better moves.

**Transition:** Here’s what those possible boards look like in a recorded decision.

### Slide 11 One observation, several possible hidden states

**Presenter:** Bryan

**Purpose:** Demonstration. Planned 35 seconds.

**Say:** This time, we’re looking from the Black bot’s perspective. It can’t see White’s knight, so it considers different places the knight could be. These two boards both fit what it can observe. The agent has to evaluate moves across such possibilities. This particular recording used a simple material score.

**Transition:** I’ll hand over to Colin to explain how we learned and tested position values.

**Delivery cues (not spoken):** Handoff from Bryan to Colin after this slide.

### Slide 12 Three ways to learn position values

**Presenter:** Colin

**Purpose:** Value learning and training targets. Planned 20 seconds.

**Say:** Thanks, Bryan. We first compared three training targets using the same linear model: a stronger engine’s values, completed-game returns, and estimates of the next position. These answer different prediction questions.

**Transition:** Here’s how Monte Carlo gets its target.

### Slide 13 Monte Carlo learns from completed returns

**Presenter:** Colin

**Purpose:** Monte Carlo prediction. Planned 30 seconds.

**Say:** Monte Carlo waits for the game to end. Here, our player eventually wins, so the earlier position gets a target of plus one. We learn from recorded games, so these returns describe the policy that played them.

**Transition:** TD can learn before the outcome is known.

### Slide 14 TD bootstraps from the next estimate

**Presenter:** Colin

**Purpose:** Temporal-difference prediction. Planned 25 seconds.

**Say:** TD uses the estimate at the next position. Because the opponent moves next, we reverse its sign to keep our player’s perspective. At the end, we use the actual outcome. These are fitted targets from recorded games.

**Transition:** What did these targets teach the models?

### Slide 15 Distillation best matched the engine teacher

**Presenter:** Colin

**Purpose:** Offline teacher-prediction result. Planned 30 seconds.

**Say:** First, how closely does each model match the stronger engine? Lower bars mean smaller errors. Distillation comes closest, which fits its training target. All three use the same linear model, but their training distributions differ, so the target alone may not explain the gap.

**Transition:** Now change what we ask them to predict.

**Delivery cues (not spoken):** Give the audience a moment to locate the three methods. Indicate the lower distillation bar, then state the finding. Do not read every value. The pause is included in the allocation.

### Slide 16 MC and TD better matched recorded outcomes

**Presenter:** Colin

**Purpose:** Offline outcome-prediction result. Planned 30 seconds.

**Say:** Here we change the question: how well does each model predict the recorded game outcome? MC and TD now do slightly better. These are returns under the policy that generated the games. Because the metric and evaluation set differ, we compare methods within each chart.

**Transition:** Neither chart tells us yet whether the agent plays better.

**Delivery cues (not spoken):** Pause briefly on the new chart before speaking. Compare the methods within this chart, without comparing its bar heights to the preceding chart. The pause is included in the allocation.

### Slide 17 Testing a learned value correction

**Presenter:** Colin

**Purpose:** Neural correction and paired evaluation. Planned 40 seconds.

**Say:** For that question, we tested a separate neural model. It learns a correction to a quick engine estimate, using a deeper engine as the teacher. We compared the baseline against the baseline with this correction, checking prediction error, game score and time per move. Each opening was played twice with colours swapped, and both agents used the same one-move outer planner.

**Transition:** First, did the predictions improve?

**Delivery cues (not spoken):** Introduce this as a separate experiment from the linear MC/TD comparison. Protocol details are in the archived match backup.

### Slide 18 Prediction error decreased by about 20%

**Presenter:** Colin

**Purpose:** Prediction result. Planned 25 seconds.

**Say:** Prediction error fell by about twenty percent. This development data also helped us select the model, so it isn’t an independent test. It shows closer agreement with the teacher.

**Transition:** Did that translate into better play?

### Slide 19 The games did not establish a playing gain

**Presenter:** Colin

**Purpose:** Outcome result. Planned 40 seconds.

**Say:** The neural model scored 51.5 percent of the available points. The uncertainty interval includes an even split, so the games established neither an improvement nor equivalence. In this one-ply setup, the more accurate predictions didn’t produce a demonstrated gain in game score.

**Transition:** What did those predictions cost?

**Delivery cues (not spoken):** Indicate the equal-points reference and interval. Explain the result, without reading the interval endpoints.

### Slide 20 The learned correction took about 3× as long

**Presenter:** Colin

**Purpose:** Resource result. Planned 25 seconds.

**Say:** The correction took about three times as long per move, so this wasn’t an equal-time comparison. Extra computation could also be spent searching further ahead.

**Transition:** Here’s why prediction accuracy alone can miss what matters for choosing an action.

### Slide 21 The reference slightly prefers Move A

**Presenter:** Colin

**Purpose:** Illustrative ranking reference. Planned 15 seconds.

**Say:** Suppose these are the reference values for two actions. Higher is better, so A is preferred, although only slightly.

**Transition:** Now suppose our evaluator predicts these values.

**Delivery cues (not spoken):** Keep the reference visible for about two seconds before advancing. Indicate A and B together. Establish that the example is illustrative, not a project measurement.

### Slide 22 Large value errors can preserve the choice

**Presenter:** Colin

**Purpose:** Illustrative baseline choice. Planned 20 seconds.

**Say:** These estimates are quite far off. Which action would the agent choose? Still A, because it ranks higher. Despite the inaccurate values, the preferred action is preserved.

**Transition:** Now let’s reduce the prediction errors.

**Delivery cues (not spoken):** Pause for about two seconds after the question so the audience can make the choice silently. Indicate the selected action, without calculating the numerical error aloud.

### Slide 23 Closer values can still change the choice

**Presenter:** Colin

**Purpose:** Illustrative learned choice. Planned 30 seconds.

**Say:** Now the estimates are closer, but B ranks above A. The agent chooses B, even though the average error is smaller. A more accurate value function can still change the action ranking. This illustrates a possible explanation for our results, rather than an established cause.

**Transition:** A separate experiment learns directly from the agent’s own search.

**Delivery cues (not spoken):** Allow a brief look at the changed ranking before explaining it. Connect the reversed choice to the distinction between value accuracy and action quality. Keep the illustrative scope clear.

### Slide 24 Learning from our own search

**Presenter:** Colin

**Purpose:** Search-generated learning targets. Planned 25 seconds.

**Say:** Search generates value targets during self-play. A separate network learns those targets, then supplies values inside search. Pair A reports one completed cycle. Repeated improvement through further cycles is still untested.

**Transition:** How did this evaluator compare with material counting?

### Slide 25 Does the learned evaluator help?

**Presenter:** Colin

**Purpose:** Preliminary results and interpretation. Planned 30 seconds.

**Say:** Pair A reports higher prediction error and no established improvement in games over material counting. The labels come from shallow material-based search, which may explain why material is hard to beat. These findings remain preliminary until the complete game records are reconciled.

**Transition:** That brings us back to our two main findings.

**Delivery cues (not spoken):** Treat the material-label explanation as a hypothesis, not an established cause. Do not present the handover’s game score as a verified strength result.

### Slide 26 Conclusions and next evaluation

**Presenter:** Colin

**Purpose:** Two findings and the next decision-level test. Planned 45 seconds.

**Say:** Observation history helps us narrow down what might be hidden. For learned values, better predictions alone weren’t enough: our correction cost more computation without an established playing gain. The separate search-trained model also has no established benefit over material. Next, we need complete game records, equal thinking time and stronger opponents to test whether learning improves the decisions our agent makes. Thank you. We’re happy to take questions.

**Delivery cues (not spoken):** Finish here and allow three minutes for Q&A. Keep the two findings distinct from proposed future evaluation.

## Questions every team member should be able to answer

**Is the solver-trained network Network 1?** No. The original Network 1 learns a correction toward stronger-engine values. The separate solver-trained network learns targets produced by the search agent. Its experimental code and handover are separate from the archived one-ply batch.

**Have we completed an iterative learning loop?** Pair A reports one target-generation, training and deployment cycle. Repeated policy improvement has not been tested.

**Are the new findings independently verified?** The accessible label-runner code and network-loading hook have been inspected. The new dataset, checkpoint and complete per-attempt run records are not supplied in the inspected repository trees. The qualitative findings are explicitly attributed to the handover; no new performance numbers are presented. Complete game accounting and independent reproduction remain open.

**Does a non-significant network/material comparison show equivalence?** No. It establishes neither superiority nor equivalence. The reported comparison is conditional on both arms completing, and the simple greedy opponent limits how much the strongest arms can be separated.


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

Bryan covers the introduction, hidden-state examples, information formulation and the aligned recorded demo (slides 1–11, retained allocation 5:25). Colin covers learning targets, experiments, interpretation and conclusions (slides 12–26, 7:10). Handoff once after slide 11. Bryan and Colin both prepare for Q&A.

The planned allocations total 12:35; the confirmed speaking slot is 12 minutes, followed by three minutes Q&A. Rehearsal must determine the actual pacing. Do not read square coordinates, narrate individual moves or read every number from a chart. Explain what the visual establishes and connect it to the decision problem.

## Hidden backup navigation

27: archived match rows. 28: full value/move metrics. 29: offline belief context. 30: full MC/TD comparison. 31: retained-search prototype. 32: evaluator inventory. 33: contribution confirmations. 34: sources and scope. These are hidden during the core talk; the PDFs and slide-with-script Word copy include all pages.

## Sources and evidence boundaries

**Solver-trained network extension:** Separate solver-trained network extension. Pair A handover, PR73 at 8abc854ed1779013c9cc4818584108cc07f552c2: https://github.com/Mr-Teal/CS5446_project/blob/8abc854ed1779013c9cc4818584108cc07f552c2/pair_a_prep/docs/handover_2026-11-08.md . Self-play label collection code inspected at 87b30892ee5016f0c1fc7216bec7f885b76137bb: https://github.com/Mr-Teal/CS5446_project/blob/87b30892ee5016f0c1fc7216bec7f885b76137bb/pair_a_prep/label_run.py . Network evaluator hook inspected at d63de87a9d1591c7b2fc06fea8360b00494a99b9: https://github.com/Mr-Teal/CS5446_project/blob/d63de87a9d1591c7b2fc06fea8360b00494a99b9/pair_a_prep/evaluation_factories.py . These establish accessible pipeline code, not independent execution or strength validation. The new belief-solver-v1 checkpoint, solver-v1 dataset and complete per-attempt records are not in the inspected repository trees or local workspace. Handover training counts and result figures are author-reported; numerical performance claims are therefore omitted from the slides. The reported offline error is worse than material and the jointly surviving game comparison does not establish an improvement or equivalence. Complete attempted/terminal/capped/failed/killed/unplayed accounting and frozen configs/weights/engine identities still need reconciliation. Greedy-opponent ceiling and platform separation matter. One cycle is reported, not repeated policy improvement or an AlphaZero/Obscuro reproduction. The suggestion that shallow material-derived targets explain the offline result is a hypothesis. This is a separate model, target source and experiment from the archived Network 1 correction study; do not pool them.

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

## Delivery and pacing

Bryan’s slides 1–11 and 5:25 allocation are unchanged. Colin’s section is 7:10. One handoff follows slide 11. The separate MC/TD visuals and three-step action-ranking illustration remain. Treat the ranking reveals as one connected explanation, allowing time for the audience to identify the preferred action before revealing the change. The combined setup is slide 17; detailed game protocol remains in the archived-match backup. Slide 26 combines conclusions with the next evaluation.

| Colin’s section | Target |
| --- | --- |
| 12–14: training targets | 1:15 |
| 15–16: prediction comparisons | 1:00 |
| 17: neural correction and evaluation | 0:40 |
| 18–20: accuracy, games and cost | 1:30 |
| 21–23: action-ranking illustration | 1:05 |
| 24–25: preliminary search-trained model | 0:55 |
| 26: conclusions and next evaluation | 0:45 |

Each limitation is explained beside the result it qualifies. Keep the development-data selection warning, uncertainty interpretation, unequal-time comparison and preliminary-study attribution. Do not read detailed methods or source notes during the core talk. Rehearse with slide advances, the built-in pauses and the handoff. Check understanding and actual elapsed time without speeding through the charts to match an allocation.
