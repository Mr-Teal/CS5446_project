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
| 3 | Possibility A: every left-file move is exposed | 0:20 |
| 4 | Possibility B: every right-file move is exposed | 0:20 |
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

**Say:** Our project uses Fog of War Chess to study decisions with incomplete information. We focused on how an agent can keep track of hidden states, and whether learning more accurate position values helps it play better.

**Transition:** Let’s start with a decision on the board.

### Slide 2 Where would you move?

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** Imagine you’re White. You can see your king, but the opponent’s pieces are hidden. The eight dots show where your king can move. Which move would you choose?

**Transition:** Let’s see what could be hidden.

**Delivery cues (not spoken):** Pause briefly after the question. Let the audience look at the eight dots.

### Slide 3 Possibility A: every left-file move is exposed

**Purpose:** Hidden information. Planned 20 seconds.

**Say:** Suppose there’s a rook on c6. Any of the three moves to the left puts our king on the same file as that rook. Black could then capture it. Those three moves are marked in red.

**Transition:** The rook could also be on the other side.

### Slide 4 Possibility B: every right-file move is exposed

**Purpose:** Hidden information. Planned 20 seconds.

**Say:** If the rook is on e6 instead, all three moves to the right allow Black to capture our king. From White’s point of view, we have exactly the same information as before, but the dangerous moves have changed.

**Transition:** There’s one more possibility.

### Slide 5 Possibility C: the king is already in check

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** A rook on d6 would already be attacking our king, even though we can’t see it. Moving up or down leaves the king on the rook’s file, so Black could still capture it. In this version of the game, being in check doesn’t prevent us from making those moves.

**Transition:** That’s one of the differences from ordinary chess.

### Slide 6 Fog of War Chess

**Purpose:** Game and problem formulation. Planned 35 seconds.

**Say:** In Fog of War Chess, we see our own pieces and the squares they can reach. The rest of the board is hidden. The referee keeps the full board, and the aim is to capture the opponent’s king. So each move changes both the position and the information we have for the next decision.

**Transition:** Let’s return to those eight moves.

### Slide 7 Every move can be dangerous in a hidden state

**Purpose:** Hidden information. Planned 40 seconds.

**Say:** Every move has a risk in at least one of these three hidden positions. The left moves are exposed in A, the right moves in B, and the vertical moves in C. None avoids an immediate capture in all three. These examples don’t tell us which move is best: that depends on how plausible each position is and what happens afterward.

**Transition:** We can also learn about hidden pieces by remembering what happened earlier.

### Slide 8 A capture reveals a hidden queen

**Purpose:** Historical observations. Planned 30 seconds.

**Say:** Here, we know Black has only a king and queen left. Before Black moves, our knight is on d4 and attacks the king on f5. After one Black move, our knight has been captured, but we still can’t see the queen. The king on f5 can’t reach d4 in one move. So the queen must have made the capture, and it must be on d4 at that moment.

**Transition:** That lets us rule out some of the hidden boards.

### Slide 9 History filters the possible boards

**Purpose:** Belief tracking. Planned 30 seconds.

**Say:** All three of these boards fit what White can see now. But only the first explains the knight’s capture. That’s why we need a belief tracker: it keeps possible boards that fit the history of what we’ve seen. In this small example, the history pins down the queen’s position. In a larger game, several boards may still fit. And if the queen moves again, we need to update those possibilities.

**Transition:** Our decisions therefore depend on both the current view and the history.

### Slide 10 Decision making from private observations

**Purpose:** Sequential decision formulation. Planned 45 seconds.

**Say:** In RL terms, the full board is the hidden state, and what the player can see is an observation. The policy uses that observation and the history to choose a move. We care about the eventual win, draw or loss. A value function helps estimate those outcomes when we compare actions. This gives us a two-player decision problem with partial observability.

**Transition:** Here’s how those parts fit together in the agent.

### Slide 11 Choosing a move under uncertainty

**Purpose:** Approach. Planned 35 seconds.

**Say:** The tracker gives us possible hidden boards. Search compares actions and replies across those boards. When search stops, a value function estimates how promising each resulting position is, and those estimates guide the move choice. The game rules tell us how positions change. Our learning experiments focus on the value estimate: does making it more accurate lead to better decisions?

**Transition:** We can see the observations and possible boards in our interface.

### Slide 12 The player acts on a partial board

**Purpose:** Demonstration. Planned 20 seconds.

**Say:** Here’s the opening in our interface. White has played e4, and the bot has moved its knight to a6. The visible squares change as the pieces move. This demonstration uses a simple material evaluator.

**Transition:** The interface also lets us inspect the bot’s possible boards.

### Slide 13 Fog Lab exposes the agent’s hypotheses

**Purpose:** Demonstration. Planned 20 seconds.

**Say:** These are two of the eight boards sampled by the bot. They’re based on its own observations, so they can differ from the true board. The agent uses these possibilities when thinking about what could happen next.

**Transition:** My teammate will now explain how we trained the position values used to compare those outcomes.

**Delivery cues (not spoken):** Handoff to Presenter 2 after this slide.


### Slide 14 Three ways to learn position values

**Purpose:** Value learning and training targets. Planned 25 seconds.

**Say:** We compared three ways to train a value estimate. Distillation learns from a stronger engine. Monte Carlo learns from the result of a completed game. TD learns from an estimate of the next position. For this comparison, we used the same linear correction model. We’ll come to the separate neural model afterward.

**Transition:** First, here’s how Monte Carlo gets its target.

### Slide 15 Monte Carlo learns from completed returns

**Purpose:** Monte Carlo prediction. Planned 35 seconds.

**Say:** Suppose we visited this position and eventually won the game. With a reward only at the end and no discounting, Monte Carlo uses plus one as the target for that earlier position. We trained on games we had already recorded. So these estimates reflect the policy that played those games, rather than an optimal policy.

**Transition:** TD can learn from an estimate before the game is finished.

### Slide 16 TD bootstraps from the next estimate

**Purpose:** Temporal-difference prediction. Planned 35 seconds.

**Say:** Suppose we estimate the next position as plus 0.4 for the opponent. From our player’s perspective, that’s minus 0.4. TD uses that estimate as its target. At the end of a game, it uses the actual outcome instead. We fitted these targets from recorded games as well.

**Transition:** We then compared what the different training targets learned.

### Slide 17 Distillation best matched the engine teacher

**Purpose:** Offline teacher-prediction result. Planned 30 seconds.

**Say:** When we measure agreement with depth-11 Stockfish, distillation has the lowest prediction error. That makes sense because its target comes from the engine. This result is for the linear model. The methods also saw different training distributions, so we can’t attribute the whole difference to the target alone.

**Transition:** The ordering changes when we predict game outcomes.

### Slide 18 MC and TD better matched recorded outcomes

**Purpose:** Offline outcome-prediction result. Planned 30 seconds.

**Say:** For the outcomes of the recorded games, MC and TD have slightly lower error. Those games came from a shallow Stockfish policy with random moves mixed in, so we’re predicting that policy’s results. The two charts use different error metrics and evaluation sets, so their numbers aren’t directly comparable. And prediction error alone doesn’t tell us how well an agent plays.

**Transition:** To test play, we used a separate neural model.

### Slide 19 Can a learned evaluator improve play?

**Purpose:** Learning method. Planned 30 seconds.

**Say:** Network 1 learns a correction to the depth-1 Stockfish estimate. We train it against depth-11 Stockfish values, then add its correction to the shallow estimate when ranking moves. The training target still comes from the engine. We then test whether using that correction leads to better play.

**Transition:** We looked at prediction accuracy, game results and the time needed for a move.

### Slide 20 Evaluation: prediction, play and cost

**Purpose:** Experimental comparison. Planned 25 seconds.

**Say:** We compared Network 1 with shallow Stockfish using the same one-ply outer planner. We played each of 100 openings twice, swapping colours. Alongside the game score, we measured prediction error and median move time. The planner was the same, but the two agents weren’t given equal thinking time.

**Transition:** First, did the predictions improve?

### Slide 21 Prediction error decreased by about 20%

**Purpose:** Prediction result. Planned 30 seconds.

**Say:** The error against depth-11 Stockfish fell from 0.095 to 0.076, a reduction of about twenty percent. We also used this development data when choosing the model, so it isn’t an independent test set. The result shows better agreement with the engine. The next question is whether that helped in the games.

**Transition:** Here are those game results.

### Slide 22 The games did not establish a playing gain

**Purpose:** Outcome result. Planned 45 seconds.

**Say:** Network 1 took 51.5 percent of the available game points, where 50 percent means equal points. But the 95 percent interval includes 50 percent. These games don’t give us enough evidence to claim an improvement. They also don’t show that the agents are equivalent. So the lower prediction error didn’t establish better play in this one-ply setup.

**Transition:** There was also a cost to using the network.

**Delivery cues (not spoken):** Point to 0.5 and the interval before explaining the conclusion. This is game-point score, not win rate.

### Slide 23 The learned correction took about 3× as long

**Purpose:** Resource result. Planned 25 seconds.

**Say:** Median move time increased from 11.1 to 36.1 milliseconds, about three times as long. The network still needs the baseline engine call, then adds its own computation. That’s why a fair next comparison should give both agents the same total thinking time.

**Transition:** A small example helps explain why lower error might still fail to improve a move.

### Slide 24 The reference slightly prefers Move A

**Purpose:** Illustrative ranking reference. Planned 20 seconds.

**Say:** These numbers are an illustration. Suppose the reference gives Move A a value of 0.60 and Move B a value of 0.59. It prefers A, but only slightly.

**Transition:** Now look at what the baseline predicts.

### Slide 25 Large value errors can preserve the choice

**Purpose:** Illustrative baseline choice. Planned 15 seconds.

**Say:** The baseline’s estimates are quite far from the reference values. But it still ranks A above B, so it makes the same choice as the reference.

**Transition:** What if the estimates get much closer?

### Slide 26 Closer values can still change the choice

**Purpose:** Illustrative learned choice. Planned 20 seconds.

**Say:** These estimates are much closer overall, but they put B above A. The prediction error is smaller, yet the chosen move has changed. This shows how a small ranking error can matter. It’s a possible explanation for the gap between prediction and play, but we didn’t establish it as the cause of our game results.

**Transition:** That brings us back to our main findings.

### Slide 27 Conclusions

**Purpose:** Conclusion. Planned 40 seconds.

**Say:** The training target matters: matching an engine and predicting recorded returns measure different kinds of accuracy. In the separate neural-model test, we got lower prediction error at a higher computational cost, but no established improvement in game score. For this task, we need to judge learned values by the moves they help choose and the results of those moves.

**Transition:** The next evaluation should test that more directly.

### Slide 28 Next evaluation

**Purpose:** Next evaluation. Planned 15 seconds.

**Say:** We’d next like to test the learned values inside deeper search, give both agents the same total thinking time, and compare complete games. That evaluation is still to be done. Thank you. We’re happy to take questions.

**Delivery cues (not spoken):** Allow three minutes for Q&A. Open an evidence backup only when it helps answer the question.


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

The proposed two-presenter allocation keeps each person on one continuous section: Presenter 1 introduces the team and problem, historical evidence, belief tracking and demonstration (slides 1–13); Presenter 2 explains learning methods, evaluation, findings and conclusions (slides 14–28). Handoff once after slide 13. Confirm names and responsibilities with the team. Both presenters prepare for Q&A. All planned slide times are retained. Each speaker must understand both findings. Record a complete rehearsal with handovers and chart pauses. Slides 1–13 total 6:05; slides 14–28 retain 7:00. The six worked-example and game-introduction slides (2–7) take 2:45; do not repeat the rules or chess tactics. Use the retained demo slides as brief visual steps. The revised core totals 13:05. The speaker will manage delivery within the confirmed 12-minute presentation slot; existing speaking allocations have not been reduced. Cut secondary spoken detail before cutting the interpretation of the result. No rehearsal has been performed for this revision.

Use the final slide as an academic conclusion and next evaluation, then invite questions. Reserve the full three minutes for Q&A. Answer the direct question first, state evidence and limitations, and open a backup only when it supports that answer. Check that a listener can explain the central findings after one viewing. On the uncertainty plot, point to equal points and the interval before giving the conclusion. Explain the demonstration through the partial board and possible boards, without reading the move table.

## Hidden backup navigation

29: all seven archived match rows. 30: full value and move metrics. 31: offline belief context. 32: full MC/TD comparison. 33: retained-search prototype. 34: evaluator inventory. 35: contribution confirmations. 36: sources and scope. Hidden slides are skipped during the core slide show. The PDF includes all pages for review.

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

**Course alignment:** The project guidelines, pages 3-5, emphasize an AI-familiar audience outside the topic and presentation relevance, organization, clarity, time management and Q&A. The 28-slide core develops two main points, explicitly introduces the game after the opening example and ends with conclusions and the next evaluation. The user confirmed 12 minutes presentation plus 3 minutes Q&A, superseding the older draft guideline duration.

**Contributions and AI assistance:** The existing individual contribution statements remain in backup and require each member's confirmation. Do not infer the human identity of xiaomiao-fong from the account name. Copilot assisted earlier drafts. Codex assisted the restructuring, rules-example checks and browser demonstration under Bryan's direction. No new training or formal match batch was run.

**Capture history:** Constructed example in presentation-assets/capture-history-example.json and verify_capture_history_example.py. White Ka1/Nd4, Black Kf5 and an unseen queen; the illustrated hidden move is Qh4xd4. Neither White view contains the queen. All 25 hidden transitions consistent with both views and capture feedback lead to the same successor board with Qd4. The three candidate diagrams show full-state hypotheses, not direct observations. In larger positions multiple hypotheses generally remain. The queen’s inferred location is specific to this instant.


## Script language review

All 28 spoken passages and their transitions were reviewed. The six names remain visible on the title slide, but the spoken introduction now states the project question. Delivery directions are separate from words intended for the audience. Slide timings and presenter allocation are unchanged.

| Slides | What sounded unnatural | Revision |
| --- | --- | --- |
| 1 | Reading all six names aloud sounded like a roll call. | Introduce the project and its question; let the title slide identify the team. |
| 2–5 | “Pause briefly” appeared in the speech; repeated legal-destination commentary and formal constraint language slowed the example. | Move the pause into a delivery cue; describe each threat directly. |
| 6–7 | “The complete state belongs to the referee” and “establish an optimal choice or a certain game loss” read like report prose. | Explain who sees the board and what the selected examples can tell us. |
| 8–9 | “Known remaining material”, “candidate full boards” and “25 possible hidden queen moves collapse” overloaded the capture explanation. | Walk through what disappeared and what we can infer. Keep the 25-transition verification in the evidence notes. |
| 10–11 | “Map the opening example to the course concepts” was a presenter instruction; the policy explanation was dense. | State the RL mapping in complete spoken sentences, then explain the agent’s process. |
| 12–13 | “Captured opening” and “material-bot system demonstration” sounded like artifact descriptions. | Describe what the interface shows and name its simple evaluator. Use a spoken handoff. |
| 14–16 | “The next two slides unpack” narrated the deck; semi-gradient and bootstrapping commentary repeated method detail. | Explain how each target is formed, preserving perspective, offline-data and policy limits. |
| 17–18 | Reading every error value and “different evaluation population” obscured the result. | State the chart’s ordering and explain why its metrics and datasets differ. Values remain on the slides. |
| 19–21 | “The actual decision process”, “teacher-prediction error” and “optimality of the policy induced by the planner” were hard to say and follow. | Describe the correction, comparison and development-data limitation directly. |
| 22–23 | “The relevant control question” sounded like an essay; score and interval details competed with the finding. | Explain game points, uncertainty and cost in ordinary spoken language, keeping the limits of the comparison. |
| 24–26 | “The decision induced by ranking values” made a simple ranking example abstract. | Explain which move each estimate chooses and why the smaller error can still change that choice. |
| 27–28 | The conclusion listed system components again; “Invite questions” and “open evidence backups” were instructions. | Conclude with the findings and next evaluation; speak the invitation, keep Q&A directions as cues. |
