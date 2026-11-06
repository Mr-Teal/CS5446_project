# Fog of War Chess

Presentation plan for a 12-minute presentation followed by 3-minute Q&A

6 November 2026. Twenty-seven core slides, eight hidden backups. Speakers remain unassigned.

## The argument

This presentation asks how to choose actions from incomplete observations and which learned values improve those decisions. It connects the worked example to state, evidence, action, return and policy; explains MC, TD and distillation targets; and separates offline prediction from the game outcomes of an induced decision rule. A before/after capture example shows why historical observations constrain the hidden state, and a second slide filters candidate boards using that history. The existing content is retained, with the later comparisons and ranking example split into shorter visual stages. The hypotheses slide redraws two exact saved hypotheses as native diagrams to replace its blurred crop. Detailed evidence stays in backup.

The two history-example slides add 30 seconds each. Every existing slide keeps its prior speaking allocation. The planned core therefore totals 12 minutes 45 seconds, 45 seconds beyond the 12-minute speaking slot. Delivery and rehearsal must resolve that overrun; no unrelated speaking budget has been reduced. These are planned timings, not measured rehearsal times. The confirmed total slot remains 15 minutes: 12 minutes presentation followed by 3 minutes Q&A.

## Run of show

| Slide | Slide purpose or finding | Planned time |
| --- | --- | --- |
| 1 | Where would you move? | 0:25 |
| 2 | Possibility A: every left-file move is exposed | 0:20 |
| 3 | Possibility B: every right-file move is exposed | 0:20 |
| 4 | Possibility C: the king is already in check | 0:25 |
| 5 | Fog of War Chess | 0:35 |
| 6 | Every move can be dangerous in a hidden state | 0:40 |
| 7 | A capture reveals a hidden queen | 0:30 |
| 8 | History filters the possible boards | 0:30 |
| 9 | Decision making from private observations | 0:45 |
| 10 | The agent tracks, searches and evaluates | 0:35 |
| 11 | The player acts on a partial board | 0:20 |
| 12 | Fog Lab exposes the agent’s hypotheses | 0:20 |
| 13 | Three ways to learn position values | 0:25 |
| 14 | Monte Carlo learns from completed returns | 0:35 |
| 15 | TD bootstraps from the next estimate | 0:35 |
| 16 | Distillation best matched the engine teacher | 0:30 |
| 17 | MC and TD better matched recorded outcomes | 0:30 |
| 18 | Can a learned evaluator improve play? | 0:30 |
| 19 | Evaluation: prediction, play and cost | 0:25 |
| 20 | Prediction error decreased by about 20% | 0:30 |
| 21 | The games did not establish a playing gain | 0:45 |
| 22 | The learned correction took about 3× as long | 0:25 |
| 23 | The reference slightly prefers Move A | 0:20 |
| 24 | Large value errors can preserve the choice | 0:15 |
| 25 | Closer values can still change the choice | 0:20 |
| 26 | Conclusions | 0:40 |
| 27 | Next evaluation | 0:15 |

## Slide notes

### Slide 1 Where would you move?

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** You are White. The selected king has eight legal moves, shown by destination dots. Hatched squares are hidden. Which move would you choose? Pause briefly. We will reveal three hidden positions consistent with exactly the same private evidence.

**Transition:** The unseen rook can threaten an entire destination file.

### Slide 2 Possibility A: every left-file move is exposed

**Purpose:** Hidden information. Planned 20 seconds.

**Say:** The hidden rook is on c6. All three moves to the left—c3, c4 and c5—put the king on the rook’s file, allowing immediate capture. All eight legal destinations remain shown; red dots identify the three exposed moves in this possibility.

**Transition:** The same evidence also permits a rook on the right.

### Slide 3 Possibility B: every right-file move is exposed

**Purpose:** Hidden information. Planned 20 seconds.

**Say:** The rook could instead be on e6. All three moves to the right—e3, e4 and e5—allow immediate capture. White’s observation, legal moves and private history are unchanged. The diagram still shows all eight destinations.

**Transition:** The rook could also be on the king’s current file.

### Slide 4 Possibility C: the king is already in check

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** The hidden rook is on d6, directly along the king’s current d-file. The king is already attacked, although White cannot see the rook. Moving up to d5 or down to d3 stays on that file and permits immediate capture. In this Fog of War variant check does not restrict legal moves: all eight destinations remain available. Here “in check” describes being attacked, not an extra legal-move constraint.

**Transition:** These are three different hidden states behind the same visible board.

### Slide 5 Fog of War Chess

**Purpose:** Game and problem formulation. Planned 35 seconds.

**Say:** Fog of War Chess reveals own pieces and reachable squares, and hides the rest. The complete state belongs to the referee. Players aim to capture the king, with no check restriction. Actions change both the position and future observations. The game supplies our test environment for decision making from incomplete information.

**Transition:** How should the agent compare all eight moves across these hidden possibilities?

### Slide 6 Every move can be dangerous in a hidden state

**Purpose:** Hidden information. Planned 40 seconds.

**Say:** All eight king moves are considered. The three left-file moves permit capture in A, the three right-file moves permit capture in B, and the two moves remaining on the d-file permit capture in C. None avoids immediate capture in all three displayed states. We have not assigned probabilities or described the complete belief, so this does not establish an optimal choice or a certain game loss. It explains why we must reason about uncertainty and compare consequences instead of trusting one guessed board.

**Transition:** A capture example shows why private history matters as well as the current view.

### Slide 7 A capture reveals a hidden queen

**Purpose:** Historical observations. Planned 30 seconds.

**Say:** This separate example has known remaining material: our king and knight, and Black’s king and queen. Before Black moves, the knight on d4 attacks the visible king on f5. The queen is hidden. After one Black move, our knight has been captured on d4, but the queen is still outside our current vision. Which piece made that capture? The king on f5 is two files away, so it cannot reach d4 in a single move. With only a king and queen remaining, it must have been the queen. Check is not a movement restriction in this variant; distance rules the king out.

**Transition:** The capture tells us which hidden boards remain possible.

### Slide 8 History filters the possible boards

**Purpose:** Belief tracking. Planned 30 seconds.

**Say:** These are candidate full boards, not what White sees. All three give the same current view. Only the board with the queen on d4 can explain the knight’s capture after the earlier observation of the king on f5. The tracker advances candidate boards through possible opponent moves and retains those consistent with the full observation history. In this deliberately small example, 25 possible hidden queen moves collapse to the same successor board. In a larger game several boards can remain. We infer the queen is on d4 immediately after the capture; after later moves, the tracker must propagate that uncertainty again.

**Transition:** This is why our decision rule uses the current observation together with private history.

### Slide 9 Decision making from private observations

**Purpose:** Sequential decision formulation. Planned 45 seconds.

**Say:** Map the opening example to the course concepts. The complete position is the hidden state. The player receives an observation and retains its private history. It chooses a legal move; the objective is eventual game outcome, represented as win, draw or loss. A policy must map the available evidence to an action. The value learner is a component used by that decision rule, rather than the complete policy itself. We have a two-player imperfect-information game, not the fully observed single-agent MDP used in the introductory lectures.

**Transition:** Our architecture separates reconstructing states, planning and value estimation.

### Slide 10 The agent tracks, searches and evaluates

**Purpose:** Approach. Planned 35 seconds.

**Say:** The tracker maintains possible hidden states from private evidence. The planner compares actions and replies. A value function estimates outcomes where search stops, helping the planner choose a move. This is the course’s connection between value estimation and decision-time planning. The rules model is given, rather than learned; the learned component here estimates values. Our archived game comparison fixes the outer planner at one move.

**Transition:** The interface lets us inspect the private observations and hypotheses.

### Slide 11 The player acts on a partial board

**Purpose:** Demonstration. Planned 20 seconds.

**Say:** This captured opening shows White after e4 and the bot’s knight reply to a6. Visibility changes with the move. It is a material-bot system demonstration, not a learned-model strength result.

**Transition:** We can also inspect what the bot thinks might be hidden.

### Slide 12 Fog Lab exposes the agent’s hypotheses

**Purpose:** Demonstration. Planned 20 seconds.

**Say:** These are two of the bot’s eight sampled possible boards. They represent uncertainty from its own evidence; the referee does not supply the true board. Now we turn to the value functions used to judge possible outcomes.

**Transition:** A value learner needs targets. We compared three ways to construct them.

### Slide 13 Three ways to learn position values

**Purpose:** Value learning and training targets. Planned 25 seconds.

**Say:** We compared three value-learning targets using one linear correction model: deeper-engine values, completed-game returns and bootstrapped next-position values. Neural Network 1 is a separate study. The next two slides unpack MC and TD rather than reading the method list.

**Transition:** Monte Carlo waits for the completed return.

### Slide 14 Monte Carlo learns from completed returns

**Purpose:** Monte Carlo prediction. Planned 35 seconds.

**Say:** This is an illustrative episode from the player’s perspective. For a position visited earlier, Monte Carlo waits until the game ends and uses the completed return as its target. With only terminal reward and no discounting, an eventual win gives a target of plus one. Our offline study reuses completed recorded games; it does not update a policy online. The prediction is tied to the behaviour policy that generated those games.

**Transition:** TD can instead construct a target from its current estimate of what follows.

### Slide 15 TD bootstraps from the next estimate

**Purpose:** Temporal-difference prediction. Planned 35 seconds.

**Say:** In this non-terminal illustration the next position is valued at plus 0.4 for the opponent. Because turns alternate, its value from the current player’s perspective is minus 0.4. TD uses this bootstrapped estimate as the target; at termination it uses the actual game outcome. The real experiment fits semi-gradient targets offline. The example explains the sign and bootstrapping, rather than claiming a new result.

**Transition:** How do these target sources compare on prediction?

### Slide 16 Distillation best matched the engine teacher

**Purpose:** Offline teacher-prediction result. Planned 30 seconds.

**Say:** On the left-hand question—matching depth-11 Stockfish—the distilled linear model has the lowest recorded mean absolute error: 0.079 against 0.217 for MC and 0.185 for TD(0). This is a separate linear-model study, not Network 1. Training-row distributions differ, so it does not isolate target choice.

**Transition:** Changing the evaluation target changes the ordering.

### Slide 17 MC and TD better matched recorded outcomes

**Purpose:** Offline outcome-prediction result. Planned 30 seconds.

**Say:** Against completed-game outcomes, the recorded mean squared errors are 0.513 for distillation, 0.481 for MC and 0.476 for TD(0). These are outcomes under the depth-1-plus-random behaviour policy, not optimal play. This metric uses a different evaluation population from the previous chart; compare methods within each chart, not the axes across charts. Neither establishes stronger play.

**Transition:** We next ask whether a separate neural correction improves the actual decision process.

### Slide 18 Can a learned evaluator improve play?

**Purpose:** Learning method. Planned 30 seconds.

**Say:** We now return to Network 1, a neural model distinct from the linear MC/TD study. It learns a correction to depth-1 Stockfish using depth-11 values as targets. This is supervised value distillation, not a policy learned directly from game rewards. At decision time the planner adds the correction to the shallow value and uses it to rank actions. A closer teacher estimate is useful only if it improves the resulting decisions.

**Transition:** We therefore compare prediction quality, game outcome and computational cost.

### Slide 19 Evaluation: prediction, play and cost

**Purpose:** Experimental comparison. Planned 25 seconds.

**Say:** The game comparison tests neural Network 1 against shallow Stockfish with the same one-ply outer planner. Each of 100 openings is played with colours swapped. We measure teacher-prediction error, paired game score and median move time. These are separate measures of the component and the complete decision process, and the computation time is not fixed.

**Transition:** First, did the learned correction improve the value estimate?

### Slide 20 Prediction error decreased by about 20%

**Purpose:** Prediction result. Planned 30 seconds.

**Say:** Network 1 reduces development error against depth-11 Stockfish from 0.095 to 0.076, about twenty percent. This check also helped choose the model. It measures agreement with a teacher, rather than expected return or optimality of the policy induced by the planner.

**Transition:** The paired games test the decision outcome directly.

### Slide 21 The games did not establish a playing gain

**Purpose:** Outcome result. Planned 45 seconds.

**Say:** Network 1 scores 0.515 against the baseline. Equal game points is 0.5; the 95 percent bootstrap interval, 0.448 to 0.585, crosses it. The archived one-ply batch therefore does not establish improved playing strength or equivalence. The relevant control question is whether changing the value estimate changes game outcomes, rather than merely reducing prediction loss.

**Transition:** The learned correction also has a computational cost.

### Slide 22 The learned correction took about 3× as long

**Purpose:** Resource result. Planned 25 seconds.

**Say:** Median move time rises from 11.1 to 36.1 milliseconds, about three times as long. Network 1 adds computation on top of the baseline engine call. The outer planner is fixed, but thinking time is not, which motivates a fixed-budget comparison in the next study.

**Transition:** One reason prediction and play can differ is the ranking of close alternatives.

### Slide 23 The reference slightly prefers Move A

**Purpose:** Illustrative ranking reference. Planned 20 seconds.

**Say:** These are illustrative values, not project measurements. The deeper teacher assigns 0.60 to A and 0.59 to B, so it slightly prefers A. We will now change only the estimates used for the choice.

**Transition:** An inaccurate baseline can still rank these moves correctly.

### Slide 24 Large value errors can preserve the choice

**Purpose:** Illustrative baseline choice. Planned 15 seconds.

**Say:** The baseline estimates 0.80 and 0.40. Its mean error is large, 0.195, but it still chooses A, matching the reference ranking.

**Transition:** Now consider estimates that are much closer in absolute value.

### Slide 25 Closer values can still change the choice

**Purpose:** Illustrative learned choice. Planned 20 seconds.

**Say:** The learned estimates are 0.58 and 0.60. Mean error drops to 0.015, but the chosen move becomes B. Average prediction accuracy and the decision induced by ranking values are different objectives. This is an illustration, not a demonstrated cause of our game result.

**Transition:** That distinction connects the two experimental findings.

### Slide 26 Conclusions

**Purpose:** Conclusion. Planned 40 seconds.

**Say:** The project combines private-state tracking, decision-time planning and learned values. The offline study distinguishes agreement with an engine from predicting a recorded behaviour policy’s returns. The separate Network 1 comparison finds lower teacher error without an established game-score gain and with higher computation cost. Value learning should be assessed by the decisions and returns it supports.

**Transition:** The next evaluation should test that link inside the deeper-search system.

### Slide 27 Next evaluation

**Purpose:** Next evaluation. Planned 15 seconds.

**Say:** Evaluate learned values inside reviewed deeper search under a fixed total computation budget, and compare complete-game outcomes. This remains planned work. Invite questions and reserve the next three minutes for Q&A.

**Transition:** Invite questions; open evidence backups only as needed.

## Questions every team member should be able to answer

**What makes this sequential decision making?** An action changes the position and what each side can observe next. The agent must account for hidden states and future replies.

**Why consider several possible boards?** Three hidden rook locations give the same private evidence but different capture risks for all eight king moves. A exposes c3/c4/c5, B e3/e4/e5, and C d3/d5. No destination avoids immediate capture in all three selected examples; this is not a probability or optimality claim.

**Why does the capture require history?** The current view alone allows multiple hidden queen locations. Earlier we saw the knight on d4 and Black’s king on f5; after exactly one Black move, the knight was captured on d4. The king cannot cross two files in one move, so the queen must occupy d4 immediately after that capture. The known remaining-material assumption is essential. Check itself does not exclude the king in this variant. The tracker must propagate candidate boards again on later moves.

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

**Why is the king already in check in C?** The hidden rook on d6 attacks the king on d4 along the d-file. Check is not a legal-move restriction under these project rules, so all eight king moves remain legal, including d3 and d5; those two moves permit immediate capture.

## Delivery and rehearsal

Assign speakers by narrative blocks only after team agreement. Each speaker must understand both findings. Record a complete rehearsal with handovers and chart pauses. Slides 1–12 total 5:45; slides 13–27 retain 7:00. The first six worked-example and game-introduction slides take 2:45; do not repeat the rules or chess tactics. Use the retained demo slides as brief visual steps. The revised core totals 12:45. The speaker will manage delivery within the confirmed 12-minute presentation slot; existing speaking allocations have not been reduced. Cut secondary spoken detail before cutting the interpretation of the result. No rehearsal has been performed for this revision.

Use the final slide as an academic conclusion and next evaluation, then invite questions. Reserve the full three minutes for Q&A. Answer the direct question first, state evidence and limitations, and open a backup only when it supports that answer. Check that a listener can explain the central findings after one viewing. On the uncertainty plot, point to equal points and the interval before giving the conclusion. Explain the demonstration through the partial board and possible boards, without reading the move table.

## Hidden backup navigation

28: all seven archived match rows. 29: full value and move metrics. 30: offline belief context. 31: full MC/TD comparison. 32: retained-search prototype. 33: evaluator inventory. 34: contribution confirmations. 35: sources and scope. Hidden slides are skipped during the core slide show. The PDF includes all pages for review.

## Sources and evidence boundaries

**Rules:** Rules and worked example: docs/drafts/presentation-assets/hidden-rook-example.json and verify_hidden_rook_example.py. Public custom start k7/8/7r/8/3K4/8/8/8 b - - 0 1. Alternative hidden Black moves h6c6, h6e6 and h6d6 produce identical White observations, legal feedback and private history. White king d4 has all eight legal moves: c3/c4/c5, d3/d5, e3/e4/e5. A: rook c6 can capture after all three left-file moves. B: rook e6 can capture after all three right-file moves. C: rook d6 already attacks d4 and can capture after d3 or d5. All 24 move/state consequences are checked against RulesAdapter. No move avoids immediate capture across all three selected states. No assigned probabilities, optimality, inevitable-loss or complete-posterior claim. Check does not restrict legal moves under the project rules. Visibility is own occupied squares plus reachable destinations, with pawn and en-passant special cases. Rule reference: https://github.com/Mr-Teal/CS5446_project/blob/149278181ed6d2b52dce31991fb311a2a74339d0/pair_a_prep/rules_adapter.py . Destination dots follow the selected-piece convention requested by the user; reference https://support.chess.com/en/articles/8708625-how-do-i-turn-on-off-the-legal-moves-dots-on-the-board . Grey dots are legal destinations, not a safety guarantee; red dots annotate immediate capture in a revealed possibility.

**Values:** Evaluator evidence: https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/README.md . Separate development check: 959 games, 3818 decisions, 94963 eligible children. Network 1 selection also used this check set. Full-board D11 teacher. D1 MAE 0.095, Network 1 0.076. Mean errors and rankings address different objectives. Not a sealed-test result.

**Batch:** Archived evaluator batch: https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27 . Execution a5c5fb6, stand-in rules, predates later no-move/EP updates. Network 1: paired score 0.515, bootstrap 95% interval [0.448,0.585], 100 complete colour pairs. Baseline D1 median 11.1 ms/move, Network 1 36.1. Same one-ply outer planner, 256 particles, eight hypotheses, unequal compute. This is one row of seven separate comparisons against D1. Total 1400 attempts, 1399 finished, 699 complete pairs, six capped draws. Whole-belief context was not used online. Full tables remain in backup. Null-containing intervals do not establish equivalence. Methods: https://github.com/Mr-Teal/CS5446_project/blob/7c292af5881b8c81e4ffccb7300de21650c9c0ad/pair_b/docs/evaluation-methods-draft.md

**Demo:** Actual local Fog Lab browser opening demonstration, 6 November 2026. Local historical checkout, Teal rules, material scorer, seed 0. Human e2e4, bot b8a6. Saved screenshot and two-ply record: docs/drafts/presentation-assets/. The diagnostic panel shows the bot's own hypotheses for inspection. This is not Fair mode, a full game, or a playing-strength result. It does not demonstrate the unmerged Pair A Fog Lab bot or the learned evaluator. The displayed 22 ms is this local action, not the archived batch timing. The hypotheses slide redraws the exact first two saved bot_turns[0].belief FENs as native editable diagrams, using Fog Lab chess symbols and square colours. These replace the magnified screenshot crop without generating new hypotheses.

**Search:** Search and current-scope review: https://github.com/Mr-Teal/CS5446_project/pull/33#issuecomment-6630857564 . The project includes search prototypes and a separate exact-history tracker. The archived batch isolates evaluators in a one-ply planner. A reviewed learned-leaf deeper-search comparison remains pending. PR65/66/67 mechanisms and author-reported full-agent arms remain separately reviewed, with raw evidence and implementation corrections outstanding. No complete Obscuro reproduction or new training requirement. Background: Zhang and Sandholm, https://arxiv.org/abs/2106.06068v2 and https://arxiv.org/abs/2506.01242v2 .

**Ranking:** Illustrative two-move values created only to explain a ranking mechanism, not project measurements: teacher [0.60,0.59], baseline [0.80,0.40], learned [0.58,0.60]. Mean absolute errors are 0.195 and 0.015. The baseline selects Move A; the learner selects Move B. This example does not identify the cause of the archived game result.

**Course:** CS4246/CS5446 course materials: Week 4, Lecture-sdm.pdf, PDF pages 21–22, 28, 35, 38 and 46 (return, prediction versus control, MC, TD and generalized policy iteration); Week 5, Lecture-rl-modelfree.pdf, PDF pages 5, 8, 13 and 15 (value-function approximation, sample targets and bootstrapping); Week 7, Lecture-guided-SDM.pdf, PDF pages 3–4 and 28–30 (decision-time search and leaf value estimates). This project uses a given rules model for planning; the network learns values rather than transition dynamics. The setting is a two-player imperfect-information game; it is not claimed to be a fully observed single-agent MDP.

**Mctd:** Separate offline model-free prediction study: https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/experiments/mc_td/RESULTS.md . All methods use the same linear correction model on 1217 inputs, distinct from neural Network 1. Distillation uses 638451 child rows from 6414 training games; MC/TD use 722500 trajectory positions from 6239 finished games, excluding 175 unfinished training games. Teacher MAE: Distil .0790, MC .2169, TD(0) .1846. Outcome MSE: Distil .5127, MC .4811, TD(0) .4758. Rounded core values are .079/.217/.185 and .513/.481/.476. Teacher error uses 94963 rows from 959 games; outcome MSE uses 106971 positions from 929 finished games, with 32 of 961 excluded. Outcomes follow the recorded depth-1 Stockfish plus 2–15% random behaviour policy, not optimal play. TD bootstraps negative next-player value and uses terminal outcome at the end; fitted semi-gradient TD(0) and TD(lambda=.8) reached the 15-round cap at full data. Training-row distributions differ, so the study does not isolate target choice. Archived trajectories have documented rule and engine-history limitations. Full methods, TD(lambda), move metrics, intervals and caveats remain in backup. These are recorded offline results, not a new training or playing-strength experiment.

**Targets:** The MC and TD target diagrams are pedagogical examples, not additional observations or experiment results. MC uses a completed return from the same player’s perspective. The non-terminal TD illustration uses zero immediate reward, gamma=1 and the alternating-player sign convention: a +0.4 next-player value becomes a -0.4 current-player target. Terminal positions use their recorded outcome. The real offline fitted targets are documented in the pinned MC/TD source.

**Worked example:** The public custom starting position and all eight candidate-move checks are in presentation-assets/hidden-rook-example.json. The example concerns immediate capture after these candidate moves, without an optimality or full-posterior claim.

**Demonstration:** The screenshot and two-ply game record are in presentation-assets/. It uses a material bot on a historical checkout. The displayed single-action timing is not an archived experiment measurement.

**Course alignment:** The project guidelines, pages 3-5, emphasize an AI-familiar audience outside the topic and presentation relevance, organization, clarity, time management and Q&A. The 27-slide core develops two main points, explicitly introduces the game after the opening example and ends with conclusions and the next evaluation. The user confirmed 12 minutes presentation plus 3 minutes Q&A, superseding the older draft guideline duration.

**Contributions and AI assistance:** The existing individual contribution statements remain in backup and require each member's confirmation. Do not infer the human identity of xiaomiao-fong from the account name. Copilot assisted earlier drafts. Codex assisted the restructuring, rules-example checks and browser demonstration under Bryan's direction. No new training or formal match batch was run.

**Capture history:** Constructed example in presentation-assets/capture-history-example.json and verify_capture_history_example.py. White Ka1/Nd4, Black Kf5 and an unseen queen; the illustrated hidden move is Qh4xd4. Neither White view contains the queen. All 25 hidden transitions consistent with both views and capture feedback lead to the same successor board with Qd4. The three candidate diagrams show full-state hypotheses, not direct observations. In larger positions multiple hypotheses generally remain. The queen’s inferred location is specific to this instant.
