# Fog of War Chess

Presentation plan for a 12-minute presentation followed by 3-minute Q&A

6 November 2026. Fifteen core slides, eight hidden backups. Speakers remain unassigned.

## The argument

This presentation develops two points: hidden information requires reasoning across possible states, and better value prediction did not establish better play in our tested planner. It follows a concrete rook example before introducing the system and the experiment. Technical details stay in backup.

The planned core is 11 minutes including handovers, with one minute of contingency for a 12 minute slot. These are planned timings, not measured rehearsal times. The confirmed total slot is 15 minutes: 12 minutes presentation followed by 3 minutes Q&A.

## Run of show

| Slide | Slide purpose or finding | Planned time |
| --- | --- | --- |
| 1 | Where would you move? | 0:25 |
| 2 | The rook could be on the left | 0:25 |
| 3 | The same view can hide a different danger | 0:25 |
| 4 | Fog of War Chess | 0:50 |
| 5 | Compare a move across possible states | 0:40 |
| 6 | The agent tracks, searches and evaluates | 0:55 |
| 7 | The player acts on a partial board | 0:35 |
| 8 | Fog Lab exposes the agent’s hypotheses | 0:35 |
| 9 | Can a learned evaluator improve play? | 0:55 |
| 10 | Evaluation: prediction, play and cost | 0:50 |
| 11 | Prediction error decreased by about 20% | 0:55 |
| 12 | The games did not establish a playing gain | 1:05 |
| 13 | The learned correction took about 3× as long | 0:40 |
| 14 | Lower value error can still select the wrong move | 0:55 |
| 15 | Conclusions and next evaluation | 0:50 |

## Slide notes

### Slide 1 Where would you move?

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** You are White. Your king can move one square, and the hatched squares are hidden. Ask the audience to choose one of the three highlighted moves, and pause briefly. We will judge only whether the opponent can capture the king immediately after that move. This is a simplified, publicly configured starting position, rather than a normal chess opening.

**Transition:** The unseen pieces can change which move is dangerous.

### Slide 2 The rook could be on the left

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** Reveal a hidden position that fits the view we just saw. The black rook moves along rows and columns. If White moves diagonally left, the rook can capture the king on the next turn. These extra pieces are a reveal for the explanation; White could not see them when choosing.

**Transition:** But the same evidence also permits another position.

### Slide 3 The same view can hide a different danger

**Purpose:** Hidden information. Planned 25 seconds.

**Say:** The rook could instead be on the right. White has exactly the same visible squares, legal moves and private history. Now the right diagonal allows an immediate capture, while the left avoids that particular capture. The correct advice depends on a hidden fact.

**Transition:** This is the decision problem posed by Fog of War Chess.

### Slide 4 Fog of War Chess

**Purpose:** Game and problem formulation. Planned 50 seconds.

**Say:** The left board is a complete position known to the referee. The right board is all White is allowed to observe in this example. Players see their own pieces and reachable destinations; other squares are hidden. The visibility rules include pawn-specific details, which are in backup sources. The objective is to capture the opponent’s king, and there is no check restriction. A move changes both the board and what can be observed next. This makes it a sequential decision problem with partial information, rather than ordinary chess with a cosmetic mask.

**Transition:** How should the agent act when both hidden positions are possible?

### Slide 5 Compare a move across possible states

**Purpose:** Hidden information. Planned 40 seconds.

**Say:** Return to the three moves. Left permits an immediate king capture in possibility A; right permits one in B. Forward avoids immediate capture in both displayed positions. This does not prove it is the best move or safe indefinitely. The example shows why selecting a move from a single guessed board can be misleading. We need to compare consequences across possibilities that fit the evidence.

**Transition:** Our agent separates reconstructing possibilities, comparing actions and evaluating outcomes.

### Slide 6 The agent tracks, searches and evaluates

**Purpose:** Approach. Planned 55 seconds.

**Say:** First, use private observations and move feedback to maintain possible hidden states. Second, compare candidate actions and potential replies across those possibilities. Third, when search stops, estimate how promising the resulting positions are and choose a move. In this example the two possible rook locations lead to different consequences for the same action. The project includes trackers, search prototypes and evaluators; it is not a complete paper reproduction. The experiment later holds the outer planner to one move, so it isolates the evaluator rather than assessing the full deeper-search system.

**Transition:** Fog Lab lets us inspect this reasoning through a playable interface.

### Slide 7 The player acts on a partial board

**Purpose:** Demonstration. Planned 35 seconds.

**Say:** This is a real captured Fog Lab opening, rather than a drawn mock-up. White played e4 and the bot replied with a knight move to a6. The white pieces and reachable squares are visible; hatched squares remain hidden. The view changes as pieces move. The bot in this demonstration uses the simple material evaluator, so this is a system demonstration rather than evidence for the learned model’s strength.

**Transition:** We can also inspect what the bot thinks might be hidden.

### Slide 8 Fog Lab exposes the agent’s hypotheses

**Purpose:** Demonstration. Planned 35 seconds.

**Say:** These are two of the eight possible boards sampled by the bot in that captured opening. They are guesses about the human’s hidden pieces from Black’s private evidence. The referee’s true position is not passed to the bot. This inspection view helps us see the distinction between a known state and a hypothesis. The full screenshot and two-ply record remain available; this is not a complete game or a playing-strength result.

**Transition:** We focused one experiment on improving the value assigned to these possible outcomes.

### Slide 9 Can a learned evaluator improve play?

**Purpose:** Learning method. Planned 55 seconds.

**Say:** At decision time, shallow Stockfish gives an initial position value. Network 1 predicts a correction, which is added to that value. During training, the target comes from deeper Stockfish on full-board positions. In this experiment shallow means depth 1 and deeper means depth 11. The teacher is a training source, not an extra online search call. The network still requires the shallow engine call. The research question is whether a value closer to the deeper teacher also leads to better decisions under hidden information.

**Transition:** We therefore compare prediction quality, game outcome and computational cost.

### Slide 10 Evaluation: prediction, play and cost

**Purpose:** Experimental comparison. Planned 50 seconds.

**Say:** The baseline uses shallow Stockfish. The other agent uses the same shallow value plus Network 1’s correction. Their outer one-ply planner is the same; total computation time is not fixed. We first measure agreement with deeper Stockfish on a separate development check. We then compare the agents in games using 100 opening pairs, with colours swapped for each opening. Finally, we measure median time per move. Development prediction error and archived game score come from different evidence sets and are not pooled. The archived protocol also predates later rules changes; detailed accounting is in backup.

**Transition:** First, did the learned correction improve the value estimate?

### Slide 11 Prediction error decreased by about 20%

**Purpose:** Prediction result. Planned 55 seconds.

**Say:** The bars measure mean absolute error against depth-11 Stockfish; lower is better. Error decreases from 0.095 for shallow Stockfish to 0.076 with Network 1, about twenty percent. The development check includes 959 games and 3,818 decisions. It also helped select the network, so this is development evidence rather than a sealed test. The result answers the prediction question, but it does not establish that the agent chooses better moves.

**Transition:** The paired games test the decision outcome directly.

### Slide 12 The games did not establish a playing gain

**Purpose:** Outcome result. Planned 65 seconds.

**Say:** Network 1’s score against the shallow-Stockfish baseline is 0.515. A score of 0.5 means equal game points. The horizontal range is the 95 percent bootstrap interval across the 100 opening pairs, from 0.448 to 0.585. It includes values favouring either agent and crosses 0.5. This batch therefore does not establish an improvement in playing strength. It also does not prove equivalence. The finding is limited to this one-ply planner and archived protocol. Other evaluator comparisons and complete accounting are retained in backup.

**Transition:** The learned correction also has a computational cost.

### Slide 13 The learned correction took about 3× as long

**Purpose:** Resource result. Planned 40 seconds.

**Say:** Median move time increases from 11.1 milliseconds to 36.1 milliseconds. Network 1 still calls shallow Stockfish and then adds network computation. Holding the outer planner fixed therefore does not mean equal thinking time. In this setting, the lower prediction error came with additional cost and no established game-score improvement.

**Transition:** One reason prediction and play can differ is the ranking of close alternatives.

### Slide 14 Lower value error can still select the wrong move

**Purpose:** Interpretation. Planned 55 seconds.

**Say:** These are deliberately invented values to explain a mechanism, not experimental results. The deeper teacher slightly prefers Move A: 0.60 versus 0.59. The baseline estimates are far away, 0.80 and 0.40, but still choose A. The learned estimates, 0.58 and 0.60, are much closer overall, yet choose B. Mean absolute error improves from 0.195 to 0.015 while the selected move changes in the wrong direction. Thus average value accuracy and choosing the best action are distinct objectives. This is a possible mechanism, not a causal explanation established by our game batch.

**Transition:** The findings suggest a specific next evaluation.

### Slide 15 Conclusions and next evaluation

**Purpose:** Conclusion. Planned 50 seconds.

**Say:** The project combines hidden-state tracking, search prototypes, evaluators and a playable inspection interface. The worked example illustrates why action consequences must be considered across possible hidden states. In the archived one-ply comparison, Network 1 reduced development value error by about twenty percent, but did not establish a game-score improvement and took about three times as long per move. The next evaluation is to test learned evaluation within reviewed deeper search under a fixed computation budget. Complete-game evidence is still required before making a claim about the full system’s playing strength. End the presentation here and reserve the next three minutes for questions.

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

## Delivery and rehearsal

Assign speakers by narrative blocks only after team agreement. Each speaker must understand both findings. Record a complete rehearsal with handovers and chart pauses. Target 11 minutes of core content and preserve a one minute buffer. Cut secondary spoken detail before cutting the interpretation of the result. No rehearsal has been performed for this revision.

Use the final slide as an academic conclusion and next evaluation, then invite questions. Reserve the full three minutes for Q&A. Answer the direct question first, state evidence and limitations, and open a backup only when it supports that answer. Check that a listener can explain the central findings after one viewing. On the uncertainty plot, point to equal points and the interval before giving the conclusion. Explain the demonstration through the partial board and possible boards, without reading the move table.

## Hidden backup navigation

16: all seven archived match rows. 17: full value and move metrics. 18: offline belief context. 19: MC and TD comparison. 20: retained-search prototype. 21: evaluator inventory. 22: contribution confirmations. 23: sources and scope. Hidden slides are skipped during the core slide show. The PDF includes all pages for review.

## Sources and evidence boundaries

**Rules:** Rules and worked example: docs/drafts/presentation-assets/hidden-rook-example.json. Public custom start k7/8/7r/8/3K4/8/8/8 b - - 0 1. Alternative Black moves h6c6 / h6e6 produce identical White observations, legal feedback and private history. Only immediate king-capture consequences are shown. These are two selected possibilities, without assigned probabilities or a complete-posterior claim. Rule reference: https://github.com/Mr-Teal/CS5446_project/blob/149278181ed6d2b52dce31991fb311a2a74339d0/pair_a_prep/rules_adapter.py Game introduction follows RulesAdapter.visible_squares and terminal: own occupied squares and reachable destinations are visible, with pawn and en-passant special cases. There is no check restriction; the king can be captured. The simple displayed king example has exactly nine visible squares. Full ordinary pawn and draw rules are outside the timed explanation.

**Values:** Evaluator evidence: https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/README.md . Separate development check: 959 games, 3818 decisions, 94963 eligible children. Network 1 selection also used this check set. Full-board D11 teacher. D1 MAE 0.095, Network 1 0.076. Mean errors and rankings address different objectives. Not a sealed-test result.

**Batch:** Archived evaluator batch: https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27 . Execution a5c5fb6, stand-in rules, predates later no-move/EP updates. Network 1: paired score 0.515, bootstrap 95% interval [0.448,0.585], 100 complete colour pairs. Baseline D1 median 11.1 ms/move, Network 1 36.1. Same one-ply outer planner, 256 particles, eight hypotheses, unequal compute. This is one row of seven separate comparisons against D1. Total 1400 attempts, 1399 finished, 699 complete pairs, six capped draws. Whole-belief context was not used online. Full tables remain in backup. Null-containing intervals do not establish equivalence. Methods: https://github.com/Mr-Teal/CS5446_project/blob/7c292af5881b8c81e4ffccb7300de21650c9c0ad/pair_b/docs/evaluation-methods-draft.md

**Demo:** Actual local Fog Lab browser opening demonstration, 6 November 2026. Local historical checkout, Teal rules, material scorer, seed 0. Human e2e4, bot b8a6. Saved screenshot and two-ply record: docs/drafts/presentation-assets/. The diagnostic panel shows the bot's own hypotheses for inspection. This is not Fair mode, a full game, or a playing-strength result. It does not demonstrate the unmerged Pair A Fog Lab bot or the learned evaluator. The displayed 22 ms is this local action, not the archived batch timing.

**Search:** Search and current-scope review: https://github.com/Mr-Teal/CS5446_project/pull/33#issuecomment-6630857564 . The project includes search prototypes and a separate exact-history tracker. The archived batch isolates evaluators in a one-ply planner. A reviewed learned-leaf deeper-search comparison remains pending. PR65/66/67 mechanisms and author-reported full-agent arms remain separately reviewed, with raw evidence and implementation corrections outstanding. No complete Obscuro reproduction or new training requirement. Background: Zhang and Sandholm, https://arxiv.org/abs/2106.06068v2 and https://arxiv.org/abs/2506.01242v2 .

**Ranking:** Illustrative two-move values created only to explain a ranking mechanism, not project measurements: teacher [0.60,0.59], baseline [0.80,0.40], learned [0.58,0.60]. Mean absolute errors are 0.195 and 0.015. The baseline selects Move A; the learner selects Move B. This example does not identify the cause of the archived game result.

**Worked example:** The public custom starting position and three candidate-move checks are in presentation-assets/hidden-rook-example.json. The example concerns immediate capture after these candidate moves, without an optimality or full-posterior claim.

**Demonstration:** The screenshot and two-ply game record are in presentation-assets/. It uses a material bot on a historical checkout. The displayed single-action timing is not an archived experiment measurement.

**Course alignment:** The project guidelines, pages 3-5, emphasize an AI-familiar audience outside the topic and presentation relevance, organization, clarity, time management and Q&A. The 15-slide core develops two main points, explicitly introduces the game after the opening example and ends with conclusions and the next evaluation. The user confirmed 12 minutes presentation plus 3 minutes Q&A, superseding the older draft guideline duration.

**Contributions and AI assistance:** The existing individual contribution statements remain in backup and require each member's confirmation. Do not infer the human identity of xiaomiao-fong from the account name. Copilot assisted earlier drafts. Codex assisted the restructuring, rules-example checks and browser demonstration under Bryan's direction. No new training or formal match batch was run.
