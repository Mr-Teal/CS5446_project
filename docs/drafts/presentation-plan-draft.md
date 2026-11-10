# Fog of War Chess

Presentation plan with a separate three-minute Q&A

10 November 2026. Story-first revision: 27 core slides and 20 hidden backups, 47 slides total. Bryan presents 1–15; Colin presents 16–27. One handoff remains on slide15.

## The argument

Bryan establishes why observation history and belief representation matter. Colin starts with an audience choice: would a more accurate evaluator necessarily choose the preferred move? A two-move illustration reveals the distinction between score accuracy and action ranking. The real, separate neural-correction experiment then tests teacher agreement, game outcomes and computation. Its prediction improvement did not establish stronger play and cost more computation. A separate linear-model study asks what the prediction target should be, before returning to the preliminary search-trained belief network. The conclusion is decision-level evaluation, not lower prediction error alone.

## Delivery approach

Invite a prediction before revealing the ranking example or the game finding. Pause, then explain one consequence rather than reciting chart values. The ranking example is illustrative, not a diagnosis of the match results. Keep model identities and uncertainty explicit. Detailed numerical charts remain available in hidden backups 40–47; existing backups 28–39 retain their numbers. Nothing was removed for timing. Bryan's original guides remain; Colin's rebuilt story has not been timed, so the former 12:55 total is no longer a timing estimate for this revision. The confirmed slot remains 12 minutes plus three minutes Q&A; rehearsal is a later task.

## Run of show

| Slide | Slide purpose or finding | Timing |
| --- | --- | --- |
| 1 | Fog of War Chess | 0:15 |
| 2 | Where would you move? | 0:25 |
| 3 | Possibility A | 0:20 |
| 4 | Possibility B | 0:20 |
| 5 | Possibility C | 0:25 |
| 6 | Hidden state and partial observation | 0:35 |
| 7 | Inferring the rook’s location | 0:30 |
| 8 | History filters the possible boards | 0:35 |
| 9 | Search needs a value function | 0:45 |
| 10 | State representation: 12 piece layers | 0:55 |
| 11 | State representation: visibility | 0:15 |
| 12 | State representation: rook belief | 0:25 |
| 13 | State representation: king belief | 0:30 |
| 14 | State representation: belief input | 0:25 |
| 15 | How do we learn useful position values? | 0:15 |
| 16 | Which evaluator would you trust? | Rehearsal pending |
| 17 | What move will this evaluator choose? | Rehearsal pending |
| 18 | Now make the estimates more accurate | Rehearsal pending |
| 19 | So we tested the agent—not just its scores | Rehearsal pending |
| 20 | The scores got closer. Did play improve? | Rehearsal pending |
| 21 | The games did not settle the question | Rehearsal pending |
| 22 | More computation, without an established gain | Rehearsal pending |
| 23 | What are we teaching the model to predict? | Rehearsal pending |
| 24 | Change the question, change the best predictor | Rehearsal pending |
| 25 | Predicting outcomes is not choosing better moves | Rehearsal pending |
| 26 | Can our own search become the teacher? | Rehearsal pending |
| 27 | Better predictions are a means, not the goal | Rehearsal pending |

## Slide notes

### Slide 1 Fog of War Chess

**Presenter:** Bryan

**Purpose:** Project and team introduction. Planned 15 seconds.

**Say:** Hello everyone. I’m Bryan, and Colin and I will be presenting our team’s Fog of War Chess project.

**Transition:** Let’s begin with an example.

### Slide 2 Where would you move?

**Presenter:** Bryan

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** Look at this chessboard. White has only a king left, while Black still has a king and a rook. If you were playing White, what move would you make?

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

**Say:** The rook could already be attacking our king without us knowing. Moving straight up or down would still leave the king exposed.

**Transition:** We have to choose a move without knowing which hidden position we’re in.

### Slide 6 Hidden state and partial observation

**Presenter:** Bryan

**Purpose:** Game and problem formulation. Planned 35 seconds.

**Say:** In Fog of War Chess, the goal is to capture the opponent’s king, but we can only see the squares that our pieces are able to move to. The game has a full underlying state, while our agent receives only this partial observation.

**Transition:** But the current view isn’t all the information we have.

### Slide 7 Inferring the rook’s location

**Presenter:** Bryan

**Purpose:** Historical observations. Planned 30 seconds.

**Say:** Now suppose we also have a knight. After Black moves, the knight has been captured. Black’s king was too far away, so the rook must have captured it. That tells us the rook’s location, even though it remains hidden.

**Transition:** Would we know that if we kept only the latest view?

### Slide 8 History filters the possible boards

**Presenter:** Bryan

**Purpose:** Belief tracking. Planned 35 seconds.

**Say:** If we forget the capture and look only at what we can see now, all three positions fit. Remembering the capture rules out A and B, leaving C. That’s why our agent needs a belief tracker: it keeps track of which hidden boards still fit what has happened so far.

**Transition:** How does the agent use these possible boards to choose a move?

### Slide 9 Search needs a value function

**Presenter:** Bryan

**Purpose:** Locate value estimation at the search depth limit. Planned 45 seconds.

**Say:** Our agent looks ahead at possible moves and replies. At the search depth limit, many positions are still unfinished. A value function estimates how good those positions are, so search can compare the available moves. Learning these estimates is the prediction task we focus on.

**Transition:** To evaluate those positions, the model needs a numerical input.

**Delivery cues (not spoken):** Focus on the tree: follow the branches to the depth-limit line, then explain why unfinished positions need values. The board provides context and does not need narration. The drawn depth and branching are schematic, not a claim about a measured run.

### Slide 10 State representation: 12 piece layers

**Presenter:** Bryan

**Purpose:** Compare one candidate board directly with its separate numerical piece layers. Planned 55 seconds.

**Say:** Each type of piece has a separate layer for each side. We use binary encoding: a cell is one if that piece is present and zero otherwise.

**Transition:** Next, we encode which squares we can see.

**Delivery cues (not spoken):** Point to one occupied feature cell and one empty cell while the original board stays visible. Do not read out the pictured piece names. Blank cells mean zero for that piece within this candidate. The grids are channels of the same candidate, not different hypotheses.

### Slide 11 State representation: visibility

**Presenter:** Bryan

**Purpose:** Show the binary layer recording which squares are currently visible. Planned 15 seconds.

**Say:** The visibility layer is also binary: one for a square we can see, and zero for one we can’t.

**Delivery cues (not spoken):** Compare the visible area in the observation with the ones in the visibility grid. Blank cells mean zero. Finish the definition, then advance directly to the rook-belief slide.

### Slide 12 State representation: rook belief

**Presenter:** Bryan

**Purpose:** Distinguish enemy-piece probability layers from binary piece and visibility layers. Planned 25 seconds.

**Say:** Unlike the piece and visibility layers, a piece’s belief layer uses probabilities. From the capture, we know where the hidden rook must be, so its square has probability one.

**Delivery cues (not spoken):** Keep the same fog observation on screen. Point to the single one in the rook-belief grid at the hidden capture square. It represents certainty within this known-piece example because all remaining candidates agree on the rook location. Do not name a square or suggest the rook is visible. Contrast piece and current-visibility layers with enemy-piece probability layers; do not say every other feature channel is binary.

### Slide 13 State representation: king belief

**Presenter:** Bryan

**Purpose:** Show how equally weighted candidate boards produce an uncertain enemy-piece belief layer. Planned 30 seconds.

**Say:** But we’re still unsure where the enemy king is. In this example, three possible boards have equal weight. Each puts the king on a different square, so its belief layer assigns one third to each of those squares.

**Delivery cues (not spoken):** Compare the black king across the three candidates, then point to the three marked cells in the belief map. Do not name squares or read every label. Each candidate still has a binary king-piece layer; the fractional king-belief map summarizes the candidate set and is shared across candidates. All three candidates keep the same White king and Black rook. These are illustrative candidates with uniform weights, not a measured tracker snapshot or calibrated probabilities for every possible game state.

### Slide 14 State representation: belief input

**Presenter:** Bryan

**Purpose:** Combine piece, visibility/belief/context and rule-state channels into the belief-network input. Planned 25 seconds.

**Say:** So the model receives more than piece locations. It also receives what we can see and what we’ve inferred from history. Together with context and rule information, these make up thirty-two layers, each eight by eight, for each candidate board. That gives the model its input. It still has to learn how good the position is.

**Delivery cues (not spoken):** Connect the visibility-and-belief example to the full stack. Indicate the groups without reading out every count, then point to the thirty-two layers, each eight by eight. Pause after the final sentence, then advance to the question and handoff on slide 15. The groups summarize the implemented encoder without changing its tensor order.

### Slide 15 How do we learn useful position values?

**Presenter:** Bryan

**Purpose:** Bridge from state representation to Colin’s learning and evaluation section. Planned 15 seconds.

**Say:** I’ll hand over to Colin to explain how we learn these value estimates, and test whether they lead to better moves.

**Delivery cues (not spoken):** Click to this slide after finishing the representation explanation. Address the audience, then turn to Colin at the end. Colin takes over on the next slide. This is the only presenter handoff.

### Slide 16 Which evaluator would you trust?

**Presenter:** Colin

**Purpose:** Invite a prediction before presenting any results. Timing pending rehearsal.

**Say:** Thanks, Bryan. Let me start with a choice. Two evaluators score the same possible moves. One has larger prediction errors; the other is more accurate overall. Which would you trust to choose the move? Hold that thought. We will use a small illustrative example first, then come back to what happened in our agent.

**Transition:** Start with the less accurate evaluator.

**Delivery cues (not spoken):** Pause and look at the audience after the question. Accept a show of hands or a quiet prediction; do not require a response to continue. These are illustrative evaluators, not measured project models. Do not reveal the reversal yet.

### Slide 17 What move will this evaluator choose?

**Presenter:** Colin

**Purpose:** Show that larger score errors can preserve the reference ranking. Timing pending rehearsal.

**Say:** The reference slightly prefers A: point six zero versus point five nine. Higher scores are better. This first evaluator is quite far off, but look at its estimates. Which move will it choose? A. Its scores are inaccurate, yet it preserves the reference's preferred move.

**Transition:** Now give it much more accurate estimates.

**Delivery cues (not spoken):** Establish the reference on the left once. Ask which move the estimates on the right select, pause, then click once to reveal the answer. The next click advances. Do not recite all four values. These illustrative scores are not win probabilities. Detailed error calculations are in backups 43–45.

### Slide 18 Now make the estimates more accurate

**Presenter:** Colin

**Purpose:** Reveal the difference between score accuracy and action ranking. Timing pending rehearsal.

**Say:** The reference has not changed. These new estimates are much closer to it. Which move ranks higher now? B. So the more accurate evaluator changes the choice away from the reference's preferred move. The lesson is not that accuracy is bad. It is that reducing average error does not guarantee the same action ranking.

**Transition:** That is a possibility illustrated by two moves—not an explanation we have proved for our games. So let us look at the real agent test.

**Delivery cues (not spoken):** Keep the reference fixed on the left. Pause before revealing B with one click; the next click advances. Let the audience notice the reversal before explaining it. Distinguish the conceptual example from the measured experiment that follows.

### Slide 19 So we tested the agent—not just its scores

**Presenter:** Colin

**Purpose:** Introduce the correction experiment through its practical question: do closer scores lead to better play? Timing pending rehearsal.

**Say:** Can we turn a fast engine's rough judgement into better moves? We trained a correction to bring its scores closer to a deeper engine's evaluation. Then we tested the part that matters: playing games. We compared the same agent with and without the correction, using matched openings and playing both colours. That lets us ask whether better-looking scores actually translate into better play.

**Transition:** First, did the correction make the scores more accurate?

**Delivery cues (not spoken):** Trace the two evaluator choices into the same move-selection procedure. The deeper engine is the teacher, not a second playing opponent in this diagram. This is the archived Network 1 study. Keep the 19-plane correction and 32-plane belief network distinct.

### Slide 20 The scores got closer. Did play improve?

**Presenter:** Colin

**Purpose:** Give one prediction finding, then invite the audience to anticipate the game result. Timing pending rehearsal.

**Say:** Yes: the correction reduced error against the teacher by about twenty percent. It was learning the prediction task we gave it. This was development data also used for model selection, not an independent test. Now, if you only saw that improvement, what would you expect to happen in the games?

**Transition:** Here is what the game comparison could actually tell us.

**Delivery cues (not spoken):** Point to the single headline, then pause after the question. Do not read the error values or extra metrics; the complete chart is in backup 40. Do not invite a prediction and immediately answer it yourself.

### Slide 21 The games did not settle the question

**Presenter:** Colin

**Purpose:** Explain uncertainty visually without a recital of interval endpoints. Timing pending rehearsal.

**Say:** The corrected agent took just over half the available game points. Wins earn one point, draws half, and losses zero. But the uncertainty interval crosses the even-split line. So these games did not establish that the correction made the agent stronger. They did not establish equal strength either. Better prediction was demonstrated on that development task; stronger play was not established here.

**Transition:** And there was a practical cost to that correction.

**Delivery cues (not spoken):** Point first to the dot, then the interval crossing 50 percent. Do not read the endpoints: backup 41 retains the full chart and values. The dot is game-point share, not win rate. Do not say the correction failed because of the earlier ranking example; causation was not established.

### Slide 22 More computation, without an established gain

**Presenter:** Colin

**Purpose:** Turn the runtime measurement into a practical decision. Timing pending rehearsal.

**Say:** The correction also took about three times as long per move. The outer move-selection procedure was the same, but the computation was not equal. That changes the practical question: if we give both agents the same thinking time, which makes better decisions? That is the comparison we still need—not just another check of prediction error.

**Transition:** There is another question behind the prediction test: what are we teaching the model to predict?

**Delivery cues (not spoken):** Compare the lengths of the two cost bars, not their underlying millisecond values. Backup 42 preserves the full timing chart. This is a cost finding in the tested setup, not evidence that the extra time caused the uncertain game result.

### Slide 23 What are we teaching the model to predict?

**Presenter:** Colin

**Purpose:** Motivate the separate linear-model study through the meaning of its targets. Timing pending rehearsal.

**Say:** An accurate prediction of what? In a separate study with simple linear models, we compared three ways to set the target. Distillation asks the model to copy an engine's score. Monte Carlo asks it to learn from the outcome of a completed game. Temporal difference, or TD, uses the next position's value estimate. They are learning to answer different questions.

**Transition:** So we should not expect the same method to look best under every prediction test.

**Delivery cues (not spoken):** Use the three target-source cards as a guide. Say explicitly that this is a separate linear-model study, not the neural correction being retrained. Detailed MC/TD examples remain in backups 28–29, and the full comparison is in backup 34.

### Slide 24 Change the question, change the best predictor

**Presenter:** Colin

**Purpose:** Present the two offline findings as a contrast rather than two numerical charts. Timing pending rehearsal.

**Say:** When the question was 'Can you match the engine teacher?', distillation did best. When it was 'Can you predict these recorded outcomes?', MC and TD did slightly better. That is the useful contrast. The methods also saw different training positions, so we cannot attribute the difference to the target alone.

**Transition:** But neither question is the same as asking whether the agent now plays better.

**Delivery cues (not spoken):** Point to each question and its result. Do not introduce the MAE/MSE values here; the original numerical charts are retained in backups 46–47. Compare methods within each task, not error magnitudes across different metrics and evaluation sets.

### Slide 25 Predicting outcomes is not choosing better moves

**Presenter:** Colin

**Purpose:** Connect the supporting study back to prediction versus decision quality. Timing pending rehearsal.

**Say:** Those recorded games tell us what happened under the agent that generated them. Predicting its outcomes is not the same as finding a better way to play, and it does not tell us what optimal play would achieve. So our recurring question is: does the learned value help the decisions made by the planner?

**Transition:** That motivated a preliminary direction: could our own search supply useful learning targets?

**Delivery cues (not spoken):** Use the contrast between the prediction question and the decision question. Do not claim MC or TD improved playing strength. This is the interpretation of the separate offline study, not a fourth experiment.

### Slide 26 Can our own search become the teacher?

**Presenter:** Colin

**Purpose:** Return to Bryan's belief network with a motivated preliminary extension. Timing pending rehearsal.

**Say:** Now we return to the belief network Bryan described. In one preliminary, author-reported cycle, self-play search started with scores based on the pieces each side had left. It generated training targets for the belief network, and that network was then used inside search. This connects the learning target to our own planner. It is an initial direction, not an established improvement in play.

**Transition:** So the main takeaway is not simply to make the prediction error smaller.

**Delivery cues (not spoken):** Trace one pass through the diagram. Do not draw or claim a repeated improvement loop. The baseline weights piece types rather than counting them equally. The full preliminary findings and record-reconciliation limits remain in backup 30.

### Slide 27 Better predictions are a means, not the goal

**Presenter:** Colin

**Purpose:** Close with one decision-level takeaway linking both presenters. Timing pending rehearsal.

**Say:** Bryan showed why observation history matters for representing what may be hidden. We then learned to match a teacher more closely, but did not establish stronger play, and used more computation. The goal is not a smaller number on an error chart. It is better decisions under uncertainty. Our next evaluation needs complete game records, equal thinking time and stronger opponents. Thank you—we are happy to take questions.

**Delivery cues (not spoken):** Finish the takeaway before inviting questions. Leave this slide visible. The search-trained extension remains preliminary; do not add another results discussion at the end.

## Additional Q&A explanations

### Backup 28 Monte Carlo learns from completed returns

Untimed. Open only when useful for a question.

**Suggested explanation:** For a recorded game that our player wins, the Monte Carlo target for an earlier position is plus one. These targets reflect the policy that generated the games.

### Backup 29 TD bootstraps from the next estimate

Untimed. Open only when useful for a question.

**Suggested explanation:** TD uses the next position's estimate. Consecutive positions use opposite players' perspectives, so we reverse the sign. Terminal positions use the recorded outcome.

### Backup 30 Search-trained model: initial results

Untimed. Open only when useful for a question.

**Suggested explanation:** The author-reported search-trained model had higher prediction error than the piece-value baseline and no established playing improvement. Reproducing material-derived labels is a hypothesis, not a diagnosed cause; complete game accounting remains open.

### Backup 31 No clear playing gain for Network 1 or linear

Untimed. Open only when useful for a question.

**Suggested explanation:** These rows are separate comparisons against quick Stockfish, not a ranking of all evaluators. Keep the paired denominators, uncertainty intervals, capped draws and unequal computation explicit.

### Backup 32 Better values did not establish better moves

Untimed. Open only when useful for a question.

**Suggested explanation:** Closer teacher values and better action selection are different measurements. This development check did not establish the reported move-choice gain; it does not establish equivalence.

### Backup 33 Belief context improves the offline prediction task

Untimed. Open only when useful for a question.

**Suggested explanation:** Belief context improved the offline prediction task across the reported seeds. Fixed board-based teacher labels do not establish the strategic value of information or stronger online play.

### Backup 34 Backup: copying an engine versus learning returns

Untimed. Open only when useful for a question.

**Suggested explanation:** The full linear comparison retains its different training distributions and evaluation tasks. MC/TD estimate returns under the recorded behaviour policy, not an optimal policy.

### Backup 35 Retaining solver state as search grows

Untimed. Open only when useful for a question.

**Suggested explanation:** These checks concern retained search state and selected growth contracts. They are not playing-strength evidence or a complete reproduction claim.

### Backup 36 Where search stops, an evaluator takes over

Untimed. Open only when useful for a question.

**Suggested explanation:** The evaluator interface is interchangeable, but computation differs. Learned corrections still require the quick-engine call.

### Backup 37 Backup: attribution and open team confirmations

Untimed. Open only when useful for a question.

**Suggested explanation:** Use the recorded contribution statements and AI-assistance disclosures. Do not infer identities or attribute one teammate's reviews to another.

### Backup 38 Sources and scope

Untimed. Open only when useful for a question.

**Suggested explanation:** Source links and evidence boundaries are retained in the speaker notes and plan. Keep archived experiments distinct from preliminary search-trained findings.

### Backup 39 One observation, several possible hidden states

Untimed. Open only when useful for a question.

**Suggested explanation:** This archived Black-view demonstration illustrates private observations and candidate hypotheses with a material evaluator, not learned-model strength.

### Backup 40 The correction matched the teacher more closely

Untimed. Open only when useful for a question.

**Suggested explanation:** The correction reduced error against the deeper engine by about twenty percent. It learned to imitate the teacher more closely. This result comes from the development data used for model selection, so it is not an independent test.

### Backup 41 The games did not establish stronger play

Untimed. Open only when useful for a question.

**Suggested explanation:** A win earns one game point, a draw half a point, and a loss zero. The corrected agent earned 51.5 percent of the available points. The uncertainty interval crosses 50 percent, an even split, so this comparison did not establish stronger play. It also did not establish that the agents were equally strong.

### Backup 42 The correction took about 3× as long

Untimed. Open only when useful for a question.

**Suggested explanation:** The corrected agent took about three times as long per move. That extra computation did not produce an established game-score improvement in this setup. To judge the practical benefit, we would need to compare agents given the same thinking time.

### Backup 43 Which move does the reference prefer?

Untimed. Open only when useful for a question.

**Suggested explanation:** Move selection depends on which action ranks highest. Here is an illustrative example. The reference values slightly prefer A over B.

### Backup 44 Less accurate value estimates

Untimed. Open only when useful for a question.

**Suggested explanation:** These estimates are far from the reference values. Which move would the evaluator choose? It still chooses A. The values are inaccurate, but their ranking preserves the reference’s preferred move.

### Backup 45 More accurate value estimates

Untimed. Open only when useful for a question.

**Suggested explanation:** Now the estimates are much closer. Which move ranks higher? B does. The estimates got closer, but the selected move changed away from the reference’s preferred move. Lower average error therefore need not preserve the best-ranked action. This is an illustration, not a diagnosis of our game results.

### Backup 46 Distillation best matched the teacher

Untimed. Open only when useful for a question.

**Suggested explanation:** Lower error is better. If we measure agreement with the engine teacher, distillation performs best. That matches its training objective. The methods also saw different training positions, so this comparison does not isolate the effect of the target alone.

### Backup 47 MC and TD better predicted recorded outcomes

Untimed. Open only when useful for a question.

**Suggested explanation:** Here, lower error is also better, and MC and TD do slightly better. These are outcomes from games played by the agent that generated the records; they do not tell us what optimal play would achieve. The best predictor depends on the prediction task. Neither chart, by itself, tells us which trained agent plays better.

## Questions every team member should be able to answer

**How is the belief input encoded?** Each candidate receives 32 feature planes: twelve piece-location layers, four visibility layers, seven belief layers, three context layers and six rule-state layers. The encoder also returns the candidate weights, and the belief network combines per-candidate embeddings with a weighted belief summary. This is distinct from Network 1, which uses nineteen board planes plus a quick-engine scalar. Neither representation grants access to the true hidden state; these are finite candidate-based inputs, not a claim of an exact calibrated Markov belief.


**Is the solver-trained network Network 1?** No. The original Network 1 learns a correction toward stronger-engine values. The separate solver-trained network learns targets produced by the search agent. Its experimental code and handover are separate from the archived one-ply batch.

**Have we completed an iterative learning loop?** Pair A reports one target-generation, training and deployment cycle. Repeated policy improvement has not been tested.

**Are the new findings independently verified?** The accessible label-runner code and network-loading hook have been inspected. The new dataset, checkpoint and complete per-attempt run records are not supplied in the inspected repository trees. The qualitative findings are explicitly attributed to the handover; no new performance numbers are presented. Complete game accounting and independent reproduction remain open.

**Does a non-significant network/material comparison show equivalence?** No. It establishes neither superiority nor equivalence. The reported comparison is conditional on both arms completing, and the simple greedy opponent limits how much the strongest arms can be separated.


**Is the state the visible board?** No. The hidden environment state and the player’s observation are different. The game state includes the configuration and relevant history; the player has a current view and private history, represented here by possible boards. This finite hypothesis representation is not a claim of an exact Markov belief state. The value evaluator scores hypothetical complete positions inside planning.

**What makes this sequential decision making?** An action changes the position and what each side can observe next. The agent must account for hidden states and future replies.

**Why consider several possible boards?** The same observation can hide states with different action consequences. The rook example shows that a move can be exposed in one state and safe from immediate capture in another. The agent needs to compare actions across the states still consistent with its evidence.

**Why does the capture require history?** The current view alone leaves several rook locations possible. Remembering where our knight was and that the opponent’s king was too far away lets us identify the rook as the capturer. With only those two opponent pieces remaining, the rook must be at the capture location immediately afterward. Later moves require updating that inference.

**Does the bot see the real board?** The referee owns the true state. The bot receives a private observation and reconstructs possibilities. Fog Lab reveals its hypotheses for inspection in this demonstration.

**What did Network 1 learn?** Network 1 learns a correction to quick Stockfish using deeper full-board Stockfish values as targets. The correction still requires the quick engine call.

**Why can better predictions fail to help moves?** Average value error and ranking the best action differ. Close alternatives can swap order even when average prediction improves. This is a plausible explanation, not a causal claim established by the game batch.

**Does the game result prove no improvement?** No. The interval crosses equal points, so this batch does not establish a gain or equivalence. The conclusion is limited to the tested planner and protocol.

**Was compute equal?** The outer planner was fixed. Median time was 11.1 ms for quick Stockfish and 36.1 ms for Network 1. This was not an equal-time comparison.

**Did we reproduce the full paper?** The project contains search prototypes, trackers and evaluators. Complete reproduction and a reviewed learned-leaf deeper-search result are not established. New author-reported full-agent arms are separate from the archived evaluator batch.

**How do MC, TD and distillation differ here?** Their targets come from completed-game outcomes, bootstrapped next-position values, and a deeper engine, respectively. The offline comparison uses one linear correction model; neural Network 1 is a separate distillation study.

**Whose return do MC and TD estimate?** The recorded depth-1-plus-random behaviour policy. These offline predictions do not establish an optimal policy or an online policy-improvement loop.

**Why is the TD target negative next-state value?** Consecutive positions use the next player’s perspective. In this alternating zero-sum setting, negate that value to express it from the current player’s view; use the terminal outcome at the end.

**Is the transition model learned?** No. The game rules supply the dynamics for planning. The learned component studied here is a value estimate, so avoid calling it learned-dynamics model-based RL.

**Why is the king already in check in C?** The hidden rook already attacks the king, but the player cannot see it. These rules allow moves while in check. The vertical moves therefore remain available even though they allow a capture.

## Hidden backup navigation

- **28:** Monte Carlo learns from completed returns
- **29:** TD bootstraps from the next estimate
- **30:** Search-trained model: initial results
- **31:** No clear playing gain for Network 1 or linear
- **32:** Better values did not establish better moves
- **33:** Belief context improves the offline prediction task
- **34:** Backup: copying an engine versus learning returns
- **35:** Retaining solver state as search grows
- **36:** Where search stops, an evaluator takes over
- **37:** Backup: attribution and open team confirmations
- **38:** Sources and scope
- **39:** One observation, several possible hidden states
- **40:** The correction matched the teacher more closely
- **41:** The games did not establish stronger play
- **42:** The correction took about 3× as long
- **43:** Which move does the reference prefer?
- **44:** Less accurate value estimates
- **45:** More accurate value estimates
- **46:** Distillation best matched the teacher
- **47:** MC and TD better predicted recorded outcomes

## Sources and evidence boundaries

**Belief encoding:** Belief representation, distinct from Network 1. Exact source at https://github.com/Mr-Teal/CS5446_project/blob/10352fe54ec5c11acbad8671f165642b812eae78/fow_shared/features.py : encode_belief returns (N,32,8,8) float32 plus normalized candidate weights. The 32 feature planes group as 12 piece-location channels (0–11), 14 visibility/belief/history/context channels (12–25), and six rule-state channels (26–31). The fourteen contain current-player visibility and actually visible enemy pieces, six weighted enemy-piece occupancy maps across the candidate sample, population size, opponent visibility and our pieces visible to the opponent computed per hypothesis, capture recency, ply count and search depth. The six rule-state channels are four castling flags, en-passant availability and halfmove clock. Each candidate has its own piece and rule information and shares appropriate belief summaries. Rows are oriented to the observing player: for White the top visual row is rank eight. Weights are conditional on the supplied candidate sample, not a claim of an exact calibrated posterior or Markov sufficient statistic. Visibility callbacks inspect hypotheses, not the true referee state. The model wiring at https://github.com/Mr-Teal/CS5446_project/blob/10352fe54ec5c11acbad8671f165642b812eae78/pair_b/src/pairb/belief_net.py defaults to in_planes=32 and embeds each candidate with a weighted belief-context summary. These are input feature planes, not the depth of the neural network. Some optional belief-model variants also accept a quick-engine scalar; the 32-plane board/belief representation is distinct from that scalar and from Network 1’s 19-plane board-only encoder. These references establish implemented encoding/model interfaces, not new performance or checkpoint results. For the finer slide grouping, the fourteen channels are four visibility channels (12,13,21,22), seven belief channels (14–20: six enemy-piece probability maps and candidate-population size), and three context channels (23 capture recency, 24 ply count, 25 search depth). This semantic grouping does not reorder or modify the implemented encoder. The six rule-state channels remain 26–31. Thus 12+4+7+3+6=32. A belief probability is the sum of supplied candidate weights placing that enemy piece on the square; it is distinct from the binary current-visibility mask.

**Representation example:** Reuses the verified capture successor: 8/5k2/3r4/8/3K4/8/8/8 w - - 0 1. The king stays on d4; rook d6 and opponent king f7 match the board-to-piece-layer comparison. White observes c3/c4/c5/d3/d4/d5/e3/e4/e5. The rook at d6 is outside that view. Capture history rules out the king as captor and fixes the rook at the captured knight’s square. For the illustrative single-candidate belief with normalized weight one, executing the exact pinned 32-plane encoder verifies king plane 5 at row4/col3, rook plane 9 at row2/col3, opponent king plane11 at row1/col5, visibility plane12 with nine marked cells and zero at row2/col3, and enemy-rook probability plane17 equal to one at row2/col3. This is a deterministic consequence within the known-piece worked example and its supplied belief, not invented fractional probabilities or an empirical full posterior. Additional planes are schematic on the stack. No new training or game measurements.

**King belief example:** Illustrative three-candidate extension of the known-piece capture example, not an archived tracker snapshot. White king d4 and Black rook d6 are fixed in every candidate; Black king is at f7, f8 or g7. All three have White to move, no castling or en-passant rights and the same counters. All three match the current nine-square observation. Each candidate has weight 1/3. Executing the exact shared encoder verifies shape (3,32,8,8), binary enemy-king plane11 for each candidate and the same enemy-king probability plane19 with 1/3 at the three locations in every candidate. The enemy-rook probability plane17 remains one at d6. Fractions are probabilities conditional on this illustrative candidate set, with zeros elsewhere in the map. The current Pair A and Pair B trackers return uniform weights over their returned candidate histories: https://github.com/Mr-Teal/CS5446_project/blob/10352fe54ec5c11acbad8671f165642b812eae78/pair_a_prep/belief_tracker.py and https://github.com/Mr-Teal/CS5446_project/blob/10352fe54ec5c11acbad8671f165642b812eae78/pair_b/src/pairb/tracker.py . The layer calculation is implemented in https://github.com/Mr-Teal/CS5446_project/blob/10352fe54ec5c11acbad8671f165642b812eae78/fow_shared/features.py . No claim that candidates have different learned weights or that the probability maps alone replace the candidate boards.

**Network 1 encoding:** Separate archived Network 1 correction model. Its encode_board in pair_b/src/pairb/encode.py returns (19,8,8), made from twelve piece planes and seven turn/rule/counter planes. Network1 in pair_b/src/pairb/net1.py also receives a separate shallow-engine value. This differs from the 32-plane shared belief encoder and is not a universal project input. Archived experiment source: https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/src/pairb/encode.py . Current wiring also verified at https://github.com/Mr-Teal/CS5446_project/blob/10352fe54ec5c11acbad8671f165642b812eae78/pair_b/src/pairb/encode.py and https://github.com/Mr-Teal/CS5446_project/blob/10352fe54ec5c11acbad8671f165642b812eae78/pair_b/src/pairb/net1.py . Existing Network 1 numerical results and their scope remain unchanged.

**Search and values:** Conceptual search diagram, not a recorded game tree, action selection, branching-factor claim or complete agent architecture. The board is the history-inferred White candidate after the rook captures the knight: 8/5k2/3r4/8/3K4/8/8/8 w - - 0 1. The rules model supplies hypothetical transitions. The archived fixed-depth tree expands to its requested ply depth and assigns evaluator values to nonterminal children at the frontier (remaining == 1); terminal outcomes are resolved directly. Source: https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_a_prep/chess_search.py . Search depth is distinct from Stockfish leaf-evaluator depth. Later anytime/growing variants can extend the frontier within configured depth/node/time limits; this slide does not claim all configurations use the same fixed depth. A depth-limited search uses frontier position estimates to compare continuations. Nodes are schematic positions, with moves by both players abstracted; there are no selected chess moves, invented numerical values or preferred continuation. The diagram starts from one candidate only for illustration. It does not imply the tracker knows the true hidden board or that the agent considers only one hypothesis. This connects course decision-time search and value approximation to the project evaluator interface. The recorded Black-view material-evaluator demonstration remains hidden backup 39. No new performance evidence.

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

**Demonstration:** The archived screenshot and two-ply record remain in presentation-assets/. The archived backup figure aligns the Black observation and two saved hypotheses at the same pre-action decision point. It illustrates the information pipeline with a material evaluator, not learned-model strength.

**Course alignment:** The project guidelines, pages 3-5, emphasize an AI-familiar audience outside the topic and presentation relevance, organization, clarity, time management and Q&A. The 27-slide core develops two main points, explicitly introduces the game after the opening example and ends with conclusions and the next evaluation. The user confirmed 12 minutes presentation plus 3 minutes Q&A, superseding the older draft guideline duration.

**Contributions and AI assistance:** The existing individual contribution statements remain in backup and require each member's confirmation. Do not infer the human identity of xiaomiao-fong from the account name. Copilot assisted earlier drafts and the 10 November clarity and story-first revisions under Bryan's direction. Codex assisted the restructuring, rules-example checks and browser demonstration under Bryan's direction. No new training or formal match batch was run.

**Capture history:** Verified rook example in presentation-assets/capture-history-example.json and verify_capture_history_example.py. White king stays on d4, matching the opening. White knight d6 and visible Black king f7 rule out a king capture by distance. The illustrated hidden move is Rh6xd6. The rook is unseen before and after. Nine matching historical transitions converge to the same successor board with rook d6. A/B/C reuse rook c6/e6/d6; all match the current visible-board projection, but only C explains the capture history. The standalone fog view intentionally omits capture-event history. Later opponent moves require belief propagation.



**Course formulation:** Course formulation: Week 4 Lecture-mdp.pdf, PDF pages 7 (problem representation and observations), 10 and 13–14 (transition model and Markov property); Week 5 Lecture-rl-modelfree.pdf, PDF pages 3–4 (prediction versus control); Week 10 Lecture-game.pdf, PDF page 22 (information and sequential games). The underlying game state may be hidden; it is not the current observation. Rule-relevant history can be needed beyond piece placement. The project adapts this to private observation/action history and a finite possible-board belief representation. Do not claim that the hypothesis set is an exact posterior, an exact Markov sufficient statistic, or a fully observed single-agent MDP. Learned board evaluators score hypothetical complete boards within planning; the actor does not receive the referee’s true board.
