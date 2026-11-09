# Fog of War Chess

Presentation plan with a separate three-minute Q&A

9 November 2026. Twenty-eight core slides, nine hidden backups. Bryan: slides 1–13 (6:25). Colin: slides 14–28 (7:10). One handoff on slide 13.

## The argument

History constrains the possible hidden boards. The belief network receives candidate piece locations together with visibility, belief and context information. Its input has 32 feature layers per candidate, grouped as 12 piece layers, four visibility layers, seven belief layers, three context layers and six rule-state layers. The later Network 1 correction experiment uses a separate 19-plane board encoder. The presentation distinguishes the two models while asking whether learned values help decisions.

The provisional allocations total 13:35. A new 35-second visibility/belief explanation keeps one idea per slide. No unrelated speech or allocations are shortened. Actual pacing remains for rehearsal against the confirmed 12-minute presentation plus three minutes Q&A.

## Run of show

| Slide | Slide purpose or finding | Planned time |
| --- | --- | --- |
| 1 | Fog of War Chess | 0:20 |
| 2 | Where would you move? | 0:25 |
| 3 | Possibility A | 0:20 |
| 4 | Possibility B | 0:20 |
| 5 | Possibility C | 0:25 |
| 6 | Hidden state and partial observation | 0:35 |
| 7 | Inferring the rook’s location | 0:30 |
| 8 | History filters the possible boards | 0:35 |
| 9 | Search needs a value function | 0:45 |
| 10 | State representation: 12 piece layers | 0:55 |
| 11 | State representation: visibility and belief | 0:35 |
| 12 | State representation: belief input | 0:25 |
| 13 | How do we learn useful position values? | 0:15 |
| 14 | Three ways to learn position values | 0:20 |
| 15 | Monte Carlo learns from completed returns | 0:30 |
| 16 | TD bootstraps from the next estimate | 0:25 |
| 17 | Distillation best matched the engine teacher | 0:30 |
| 18 | MC and TD better matched recorded outcomes | 0:30 |
| 19 | Network 1: learning a value correction | 0:40 |
| 20 | Prediction error decreased by about 20% | 0:25 |
| 21 | The games did not establish a playing gain | 0:40 |
| 22 | The learned correction took about 3× as long | 0:25 |
| 23 | The reference slightly prefers Move A | 0:15 |
| 24 | Large value errors can preserve the choice | 0:20 |
| 25 | Closer values can still change the choice | 0:30 |
| 26 | A separate network learns from search | 0:25 |
| 27 | Does the learned evaluator help? | 0:30 |
| 28 | Conclusions and next evaluation | 0:45 |

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

**Say:** The rook could already be attacking our king without us knowing. Moving straight up or down would still leave the king exposed.

**Transition:** We have to choose a move without knowing which hidden position we’re in.

### Slide 6 Hidden state and partial observation

**Presenter:** Bryan

**Purpose:** Game and problem formulation. Planned 35 seconds.

**Say:** In Fog of War Chess, the goal is to capture the opponent’s king, but we can only see part of the board. The game has a full underlying state, while our agent receives only this partial observation.

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

**Say:** Our agent looks ahead at possible moves and replies. We limit how many moves ahead it searches. At that depth limit, many positions are still unfinished. A value function estimates how good those positions are, so search can compare the available moves. Learning these estimates is the prediction task we focus on.

**Transition:** To evaluate those positions, the model needs a numerical input.

**Delivery cues (not spoken):** Focus on the tree: follow the branches to the depth-limit line, then explain why unfinished positions need values. The board provides context and does not need narration. The drawn depth and branching are schematic, not a claim about a measured run.

### Slide 10 State representation: 12 piece layers

**Presenter:** Bryan

**Purpose:** Compare one candidate board directly with its separate numerical piece layers. Planned 55 seconds.

**Say:** Each type of piece has a separate layer for each side. We use binary encoding: a cell is one if that piece is present and zero otherwise. All layers use the same board layout, so a cell refers to the same square in every layer.

**Transition:** We also encode what we can see and infer.

**Delivery cues (not spoken):** Point to one occupied feature cell and one empty cell while the original board stays visible. Do not read out the pictured piece names. Blank cells mean zero for that piece within this candidate. The grids are channels of the same candidate, not different hypotheses.

### Slide 11 State representation: visibility and belief

**Presenter:** Bryan

**Purpose:** Distinguish current visibility from history-informed belief information. Planned 35 seconds.

**Say:** The visibility layer uses one for a square we can see and zero for one we can’t. The rook belief layer records how likely the rook is to be on each square. Here, the rook is hidden, so its visibility is zero. But all the remaining possible boards put it here because of the capture. That gives this square probability one.

**Delivery cues (not spoken):** Point at the same rook square across the visibility and belief maps. Explain visibility zero versus rook probability one. The probability is conditional on the current candidate belief; it is not a claim of calibrated certainty for an unrestricted game.

### Slide 12 State representation: belief input

**Presenter:** Bryan

**Purpose:** Combine piece, visibility/belief/context and rule-state channels into the belief-network input. Planned 25 seconds.

**Say:** So the model receives more than piece locations. It also receives what we can see and what we’ve inferred from history. Together with context and rule information, these make up thirty-two layers, each eight by eight, for each candidate board. That gives the model its input. It still has to learn how good the position is.

**Delivery cues (not spoken):** Connect the visibility-and-belief example to the full stack. Indicate the groups without reading out every count, then point to the thirty-two layers, each eight by eight. Pause after the final sentence, then advance to the question and handoff on slide 13. The groups summarize the implemented encoder without changing its tensor order.

### Slide 13 How do we learn useful position values?

**Presenter:** Bryan

**Purpose:** Bridge from state representation to Colin’s learning and evaluation section. Planned 15 seconds.

**Say:** I’ll hand over to Colin to explain how we learn these value estimates, and test whether they lead to better moves.

**Delivery cues (not spoken):** Click to this slide after finishing the representation explanation. Address the audience, then turn to Colin at the end. Colin takes over on the next slide. This is the only presenter handoff.

### Slide 14 Three ways to learn position values

**Presenter:** Colin

**Purpose:** Value learning and training targets. Planned 20 seconds.

**Say:** Thanks, Bryan. We first compared three training targets using the same linear model: a stronger engine’s values, completed-game returns, and estimates of the next position. These answer different prediction questions.

**Transition:** Here’s how Monte Carlo gets its target.

### Slide 15 Monte Carlo learns from completed returns

**Presenter:** Colin

**Purpose:** Monte Carlo prediction. Planned 30 seconds.

**Say:** Monte Carlo waits for the game to end. Here, our player eventually wins, so the earlier position gets a target of plus one. We learn from recorded games, so these returns describe the policy that played them.

**Transition:** TD can learn before the outcome is known.

### Slide 16 TD bootstraps from the next estimate

**Presenter:** Colin

**Purpose:** Temporal-difference prediction. Planned 25 seconds.

**Say:** TD uses the estimate at the next position. Because the opponent moves next, we reverse its sign to keep our player’s perspective. At the end, we use the actual outcome. These are fitted targets from recorded games.

**Transition:** What did these targets teach the models?

### Slide 17 Distillation best matched the engine teacher

**Presenter:** Colin

**Purpose:** Offline teacher-prediction result. Planned 30 seconds.

**Say:** First, how closely does each model match the stronger engine? Lower bars mean smaller errors. Distillation comes closest, which fits its training target. All three use the same linear model, but their training distributions differ, so the target alone may not explain the gap.

**Transition:** Now change what we ask them to predict.

**Delivery cues (not spoken):** Give the audience a moment to locate the three methods. Indicate the lower distillation bar, then state the finding. Do not read every value. The pause is included in the allocation.

### Slide 18 MC and TD better matched recorded outcomes

**Presenter:** Colin

**Purpose:** Offline outcome-prediction result. Planned 30 seconds.

**Say:** Here we change the question: how well does each model predict the recorded game outcome? MC and TD now do slightly better. These are returns under the policy that generated the games. Because the metric and evaluation set differ, we compare methods within each chart.

**Transition:** Neither chart tells us yet whether the agent plays better.

**Delivery cues (not spoken):** Pause briefly on the new chart before speaking. Compare the methods within this chart, without comparing its bar heights to the preceding chart. The pause is included in the allocation.

### Slide 19 Network 1: learning a value correction

**Presenter:** Colin

**Purpose:** Neural correction and paired evaluation. Planned 40 seconds.

**Say:** For that question, we tested Network 1, a separate neural model. It learns a correction to a quick engine estimate, using a deeper engine as the teacher. We compared the baseline against the baseline with this correction, checking prediction error, game score and time per move. Each opening was played twice with colours swapped, and both agents used the same one-move outer planner.

**Transition:** First, did the predictions improve?

**Delivery cues (not spoken):** Introduce this as a separate experiment from the linear MC/TD comparison. Protocol details are in the archived match backup.

### Slide 20 Prediction error decreased by about 20%

**Presenter:** Colin

**Purpose:** Prediction result. Planned 25 seconds.

**Say:** Prediction error fell by about twenty percent. This development data also helped us select the model, so it isn’t an independent test. It shows closer agreement with the teacher.

**Transition:** Did that translate into better play?

### Slide 21 The games did not establish a playing gain

**Presenter:** Colin

**Purpose:** Outcome result. Planned 40 seconds.

**Say:** The neural model scored 51.5 percent of the available points. The uncertainty interval includes an even split, so the games established neither an improvement nor equivalence. In this one-ply setup, the more accurate predictions didn’t produce a demonstrated gain in game score.

**Transition:** What did those predictions cost?

**Delivery cues (not spoken):** Indicate the equal-points reference and interval. Explain the result, without reading the interval endpoints.

### Slide 22 The learned correction took about 3× as long

**Presenter:** Colin

**Purpose:** Resource result. Planned 25 seconds.

**Say:** The correction took about three times as long per move, so this wasn’t an equal-time comparison. Extra computation could also be spent searching further ahead.

**Transition:** Here’s why prediction accuracy alone can miss what matters for choosing an action.

### Slide 23 The reference slightly prefers Move A

**Presenter:** Colin

**Purpose:** Illustrative ranking reference. Planned 15 seconds.

**Say:** Suppose these are the reference values for two actions. Higher is better, so A is preferred, although only slightly.

**Transition:** Now suppose our evaluator predicts these values.

**Delivery cues (not spoken):** Keep the reference visible for about two seconds before advancing. Indicate A and B together. Establish that the example is illustrative, not a project measurement.

### Slide 24 Large value errors can preserve the choice

**Presenter:** Colin

**Purpose:** Illustrative baseline choice. Planned 20 seconds.

**Say:** These estimates are quite far off. Which action would the agent choose? Still A, because it ranks higher. Despite the inaccurate values, the preferred action is preserved.

**Transition:** Now let’s reduce the prediction errors.

**Delivery cues (not spoken):** Pause for about two seconds after the question so the audience can make the choice silently. Indicate the selected action, without calculating the numerical error aloud.

### Slide 25 Closer values can still change the choice

**Presenter:** Colin

**Purpose:** Illustrative learned choice. Planned 30 seconds.

**Say:** Now the estimates are closer, but B ranks above A. The agent chooses B, even though the average error is smaller. A more accurate value function can still change the action ranking. This illustrates a possible explanation for our results, rather than an established cause.

**Transition:** A separate experiment learns directly from the agent’s own search.

**Delivery cues (not spoken):** Allow a brief look at the changed ranking before explaining it. Connect the reversed choice to the distinction between value accuracy and action quality. Keep the illustrative scope clear.

### Slide 26 A separate network learns from search

**Presenter:** Colin

**Purpose:** Search-generated learning targets. Planned 25 seconds.

**Say:** Search generates value targets during self-play. A separate network learns those targets, then supplies values inside search. Pair A reports one completed cycle. Repeated improvement through further cycles is still untested.

**Transition:** How did this evaluator compare with material counting?

### Slide 27 Does the learned evaluator help?

**Presenter:** Colin

**Purpose:** Preliminary results and interpretation. Planned 30 seconds.

**Say:** Pair A reports higher prediction error and no established improvement in games over material counting. The labels come from shallow material-based search, which may explain why material is hard to beat. These findings remain preliminary until the complete game records are reconciled.

**Transition:** That brings us back to our two main findings.

**Delivery cues (not spoken):** Treat the material-label explanation as a hypothesis, not an established cause. Do not present the handover’s game score as a verified strength result.

### Slide 28 Conclusions and next evaluation

**Presenter:** Colin

**Purpose:** Two findings and the next decision-level test. Planned 45 seconds.

**Say:** Observation history helps us narrow down what might be hidden. For learned values, better predictions alone weren’t enough: our correction cost more computation without an established playing gain. The separate search-trained model also has no established benefit over material. Next, we need complete game records, equal thinking time and stronger opponents to test whether learning improves the decisions our agent makes. Thank you. We’re happy to take questions.

**Delivery cues (not spoken):** Finish here and allow three minutes for Q&A. Keep the two findings distinct from proposed future evaluation.

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

## Delivery and rehearsal

Bryan covers the introduction, hidden-state examples, depth-limited search, belief representation and the handoff (slides 1–13, allocation 6:25). Colin covers learning targets, experiments, interpretation and conclusions (slides 14–28, 7:10). Handoff once on slide 13. Bryan and Colin both prepare for Q&A.

The planned allocations total 13:35; the confirmed speaking slot is 12 minutes, followed by three minutes Q&A. Rehearsal must determine the actual pacing. Do not read square coordinates, narrate individual moves or read every number from a chart. Explain what the visual establishes and connect it to the decision problem.

## Hidden backup navigation

29: archived match rows. 30: full value/move metrics. 31: offline belief context. 32: full MC/TD comparison. 33: retained-search prototype. 34: evaluator inventory. 35: contribution confirmations. 36: sources and scope. 37: archived Black-view belief demonstration. These are hidden during the core talk; the PDFs and slide-with-script Word copy include all pages.

## Sources and evidence boundaries

**Belief encoding:** Belief representation, distinct from Network 1. Exact source at https://github.com/Mr-Teal/CS5446_project/blob/10352fe54ec5c11acbad8671f165642b812eae78/fow_shared/features.py : encode_belief returns (N,32,8,8) float32 plus normalized candidate weights. The 32 feature planes group as 12 piece-location channels (0–11), 14 visibility/belief/history/context channels (12–25), and six rule-state channels (26–31). The fourteen contain current-player visibility and actually visible enemy pieces, six weighted enemy-piece occupancy maps across the candidate sample, population size, opponent visibility and our pieces visible to the opponent computed per hypothesis, capture recency, ply count and search depth. The six rule-state channels are four castling flags, en-passant availability and halfmove clock. Each candidate has its own piece and rule information and shares appropriate belief summaries. Rows are oriented to the observing player: for White the top visual row is rank eight. Weights are conditional on the supplied candidate sample, not a claim of an exact calibrated posterior or Markov sufficient statistic. Visibility callbacks inspect hypotheses, not the true referee state. The model wiring at https://github.com/Mr-Teal/CS5446_project/blob/10352fe54ec5c11acbad8671f165642b812eae78/pair_b/src/pairb/belief_net.py defaults to in_planes=32 and embeds each candidate with a weighted belief-context summary. These are input feature planes, not the depth of the neural network. Some optional belief-model variants also accept a quick-engine scalar; the 32-plane board/belief representation is distinct from that scalar and from Network 1’s 19-plane board-only encoder. These references establish implemented encoding/model interfaces, not new performance or checkpoint results. For the finer slide grouping, the fourteen channels are four visibility channels (12,13,21,22), seven belief channels (14–20: six enemy-piece probability maps and candidate-population size), and three context channels (23 capture recency, 24 ply count, 25 search depth). This semantic grouping does not reorder or modify the implemented encoder. The six rule-state channels remain 26–31. Thus 12+4+7+3+6=32. A belief probability is the sum of supplied candidate weights placing that enemy piece on the square; it is distinct from the binary current-visibility mask.

**Representation example:** Reuses the verified capture successor: 8/5k2/3r4/8/3K4/8/8/8 w - - 0 1. The king stays on d4; rook d6 and opponent king f7 match the board-to-piece-layer comparison. White observes c3/c4/c5/d3/d4/d5/e3/e4/e5. The rook at d6 is outside that view. Capture history rules out the king as captor and fixes the rook at the captured knight’s square. For the illustrative single-candidate belief with normalized weight one, executing the exact pinned 32-plane encoder verifies king plane 5 at row4/col3, rook plane 9 at row2/col3, opponent king plane11 at row1/col5, visibility plane12 with nine marked cells and zero at row2/col3, and enemy-rook probability plane17 equal to one at row2/col3. This is a deterministic consequence within the known-piece worked example and its supplied belief, not invented fractional probabilities or an empirical full posterior. Additional planes are schematic on the stack. No new training or game measurements.

**Network 1 encoding:** Separate archived Network 1 correction model. Its encode_board in pair_b/src/pairb/encode.py returns (19,8,8), made from twelve piece planes and seven turn/rule/counter planes. Network1 in pair_b/src/pairb/net1.py also receives a separate shallow-engine value. This differs from the 32-plane shared belief encoder and is not a universal project input. Archived experiment source: https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/src/pairb/encode.py . Current wiring also verified at https://github.com/Mr-Teal/CS5446_project/blob/10352fe54ec5c11acbad8671f165642b812eae78/pair_b/src/pairb/encode.py and https://github.com/Mr-Teal/CS5446_project/blob/10352fe54ec5c11acbad8671f165642b812eae78/pair_b/src/pairb/net1.py . Existing Network 1 numerical results and their scope remain unchanged.

**Search and values:** Conceptual search diagram, not a recorded game tree, action selection, branching-factor claim or complete agent architecture. The board is the history-inferred White candidate after the rook captures the knight: 8/5k2/3r4/8/3K4/8/8/8 w - - 0 1. The rules model supplies hypothetical transitions. The archived fixed-depth tree expands to its requested ply depth and assigns evaluator values to nonterminal children at the frontier (remaining == 1); terminal outcomes are resolved directly. Source: https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_a_prep/chess_search.py . Search depth is distinct from Stockfish leaf-evaluator depth. Later anytime/growing variants can extend the frontier within configured depth/node/time limits; this slide does not claim all configurations use the same fixed depth. A depth-limited search uses frontier position estimates to compare continuations. Nodes are schematic positions, with moves by both players abstracted; there are no selected chess moves, invented numerical values or preferred continuation. The diagram starts from one candidate only for illustration. It does not imply the tracker knows the true hidden board or that the agent considers only one hypothesis. This connects course decision-time search and value approximation to the project evaluator interface. The recorded Black-view material-evaluator demonstration remains hidden backup 37. No new performance evidence.

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

**Course alignment:** The project guidelines, pages 3-5, emphasize an AI-familiar audience outside the topic and presentation relevance, organization, clarity, time management and Q&A. The 28-slide core develops two main points, explicitly introduces the game after the opening example and ends with conclusions and the next evaluation. The user confirmed 12 minutes presentation plus 3 minutes Q&A, superseding the older draft guideline duration.

**Contributions and AI assistance:** The existing individual contribution statements remain in backup and require each member's confirmation. Do not infer the human identity of xiaomiao-fong from the account name. Copilot assisted earlier drafts. Codex assisted the restructuring, rules-example checks and browser demonstration under Bryan's direction. No new training or formal match batch was run.

**Capture history:** Verified rook example in presentation-assets/capture-history-example.json and verify_capture_history_example.py. White king stays on d4, matching the opening. White knight d6 and visible Black king f7 rule out a king capture by distance. The illustrated hidden move is Rh6xd6. The rook is unseen before and after. Nine matching historical transitions converge to the same successor board with rook d6. A/B/C reuse rook c6/e6/d6; all match the current visible-board projection, but only C explains the capture history. The standalone fog view intentionally omits capture-event history. Later opponent moves require belief propagation.



**Course formulation:** Course formulation: Week 4 Lecture-mdp.pdf, PDF pages 7 (problem representation and observations), 10 and 13–14 (transition model and Markov property); Week 5 Lecture-rl-modelfree.pdf, PDF pages 3–4 (prediction versus control); Week 10 Lecture-game.pdf, PDF page 22 (information and sequential games). The underlying game state may be hidden; it is not the current observation. Rule-relevant history can be needed beyond piece placement. The project adapts this to private observation/action history and a finite possible-board belief representation. Do not claim that the hypothesis set is an exact posterior, an exact Markov sufficient statistic, or a fully observed single-agent MDP. Learned board evaluators score hypothetical complete boards within planning; the actor does not receive the referee’s true board.






## Delivery and pacing

Slide 9 follows the search tree to the depth limit and explains why unfinished positions require value estimates. Keep the board as supporting context. Slide 10 explains one binary layer per piece type and side while the original board stays visible. Slide 11 defines visibility and belief separately before interpreting the same square as visibility zero and rook probability one. Click directly to the full input on slide 12. Its script connects what we see and infer to the full stack, then closes on learning position values before the slide 13 handoff. The displayed breakdown is 12 piece + 4 visibility + 7 belief + 3 context + 6 rule-state layers. The belief count includes six probability maps plus population size. Keep the single handoff after slide 13. No unrelated speech or timing guides are changed.
