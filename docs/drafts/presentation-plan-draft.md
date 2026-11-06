# Fog of War Chess

Presentation plan for a twelve minute talk

6 November 2026. Twelve core slides, eight hidden backups. Speakers remain unassigned.

## The argument

This presentation develops two points: hidden information requires reasoning across possible states, and better value prediction did not establish better play in our tested planner. It follows a concrete rook example before introducing the system and the experiment. Technical details stay in backup.

The planned core is 11 minutes including handovers, with one minute of contingency for a 12 minute slot. These are planned timings, not measured rehearsal times. Confirm the actual course slot with the team.

## Run of show

| Slide | Audience question or takeaway | Planned time |
| --- | --- | --- |
| 1 | Where would you move? | 0:45 |
| 2 | The rook could be on the left | 0:45 |
| 3 | The same view can hide a different danger | 0:45 |
| 4 | One decision must account for both possibilities | 1:00 |
| 5 | From a partial view to a move | 1:00 |
| 6 | A playable agent with inspectable decisions | 1:00 |
| 7 | Can a learned estimate improve the decision? | 0:45 |
| 8 | Network 1 reduced prediction error by about 20% | 1:00 |
| 9 | The games did not establish a playing gain | 1:15 |
| 10 | The learned correction took about 3× as long | 1:00 |
| 11 | Closer values can still rank the best move incorrectly | 1:00 |
| 12 | Two things to remember | 0:45 |

## Slide notes

### Slide 1 Where would you move?

**Purpose:** Hidden information. Planned 45 seconds.

**Say:** You are White. The K is your king, and you can move it one square. Grey squares are hidden. Before showing the possibilities, ask the audience to choose a move and pause. In this variant the goal is to capture the opponent's king, and moving into an attacked square is allowed. Our question is how to choose with only this partial view.

**Transition:** A hidden piece can make a move that looks safe dangerous.

### Slide 2 The rook could be on the left

**Purpose:** Hidden information. Planned 45 seconds.

**Say:** Reveal one position that fits exactly the view we just saw. The black R is a rook, which moves along rows and columns. If White moves diagonally left, the rook can capture the king on the next turn. The extra pieces here are explanatory reveals for us. White did not get to see them when choosing.

**Transition:** But this is only one possible hidden position.

### Slide 3 The same view can hide a different danger

**Purpose:** Hidden information. Planned 45 seconds.

**Say:** Now the rook is on the right. White's visible squares and legal-move feedback are unchanged. The left move avoids that immediate capture, but the right move now loses the king. Knowing only one guessed board could lead us to opposite advice. Both histories are consistent with the same private evidence.

**Transition:** We need one decision that accounts for both possibilities.

### Slide 4 One decision must account for both possibilities

**Purpose:** Hidden information. Planned 60 seconds.

**Say:** Compare three moves. Left permits an immediate king capture in the first possibility. Right permits one in the second. Forward avoids immediate capture in both of these displayed positions. We are not claiming it is optimal chess or safe forever. This small example explains why the agent should compare consequences across possible states instead of acting as if one guess were certain.

**Transition:** That gives us a simple way to explain the agent.

### Slide 5 From a partial view to a move

**Purpose:** Hidden information. Planned 60 seconds.

**Say:** The agent first keeps possible hidden states consistent with what it has observed. It considers actions and replies in those possibilities. When it cannot search further, an evaluator estimates how good each frontier position is. The agent then chooses one move using only its private information. We built search prototypes as well as evaluator-based bots. For the experiment later in the talk, we deliberately keep the outer search to one move so that we can compare the evaluators.

**Transition:** Here is the playable system that makes these possibilities visible for inspection.

### Slide 6 A playable agent with inspectable decisions

**Purpose:** Hidden information. Planned 60 seconds.

**Say:** This is a real captured opening in Fog Lab. On the left is the human player's partial view after e4 and the bot's knight reply. On the right are candidate moves and the bot's guesses about the human's hidden pieces. Point to those guesses, rather than reading the numerical table. The panel is an inspection tool for us, not the referee's true board passed to the bot. This demonstration uses the simple material evaluator. The same project also supplies learned evaluators, which we tested separately.

**Transition:** The part we tried to improve was the position estimate.

### Slide 7 Can a learned estimate improve the decision?

**Purpose:** Prediction and decisions. Planned 45 seconds.

**Say:** Quick Stockfish supplies a cheap position estimate. Deeper Stockfish supplies a full-board training target. Network 1 learns a correction to the quick estimate, so it still needs that initial engine call. The aim is to get closer to the deeper teacher without paying the full deeper-search cost. That sounds useful, but agreement with the teacher is only the first test. We also need to see which moves the agent chooses.

**Transition:** First, did the estimated values improve?

### Slide 8 Network 1 reduced prediction error by about 20%

**Purpose:** Prediction and decisions. Planned 60 seconds.

**Say:** Lower bars mean closer agreement with the deeper Stockfish teacher. On the development check, mean absolute error falls from 0.095 to 0.076, about twenty percent. That answers the prediction question positively in this setting. The check set also helped choose the model, so we call this development evidence. It does not yet tell us whether the top move is better or whether the agent scores more points in a game.

**Transition:** We then tested the decision itself by playing paired games.

### Slide 9 The games did not establish a playing gain

**Purpose:** Prediction and decisions. Planned 75 seconds.

**Say:** Network 1 played against the quick-Stockfish baseline using the same one-ply outer planner. We played each opening twice with colours swapped. Its score is 0.515, where 0.5 means equal points against the opponent. The interval shows uncertainty across opening pairs, and it crosses 0.5. This batch therefore does not establish a playing gain. It also does not prove the models are equivalent. The result belongs to this planner and protocol. The other evaluators and full accounting are in backup.

**Transition:** There is also a cost to the learned correction.

### Slide 10 The learned correction took about 3× as long

**Purpose:** Prediction and decisions. Planned 60 seconds.

**Say:** The baseline took 11.1 milliseconds per move at the median. Network 1 took 36.1, around three times as much. This is expected because the learned correction still calls quick Stockfish and then adds network work. So the experiment held the outer planner fixed, not total thinking time. More accurate values alone did not establish a playing gain, and they were more expensive. Useful evaluation needs to connect prediction quality to the decisions and resources we actually care about.

**Transition:** Why can those two measurements disagree?

### Slide 11 Closer values can still rank the best move incorrectly

**Purpose:** Prediction and decisions. Planned 60 seconds.

**Say:** The player ultimately selects an action. Imagine two candidate moves whose true values are close. A model can improve many estimates overall and still swap the top two moves. Average prediction error and selecting the best action are different objectives. This is a possible explanation, not a causal claim proved by our game results. Our separate ranking check also did not establish a gain. For the audience, the lesson is to test the decision outcome rather than assume that a better intermediate metric guarantees it.

**Transition:** That leaves two things to remember.

### Slide 12 Two things to remember

**Purpose:** Conclusion. Planned 45 seconds.

**Say:** First, hidden information means reasoning across what might be true. The rook example showed why one guessed board can be misleading. Second, judge a learned model by the decisions it improves. In our tested one-ply planner, more accurate value predictions did not establish stronger play and took more time. The next comparison is learned evaluation inside a reviewed deeper-search configuration. We have a working system and bounded evidence, rather than a claim of complete paper reproduction.

**Transition:** End here and invite questions.

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

Assign speakers by narrative blocks only after team agreement. Each speaker must understand both takeaways. Record a complete rehearsal with handovers and chart pauses. Target 11 minutes of core content and preserve a one minute buffer. Cut secondary spoken detail before cutting the interpretation of the result. No rehearsal has been performed for this revision.

Check that a listener can explain the two takeaways after one viewing. On the uncertainty plot, point to equal points and the interval before giving the conclusion. Explain the demonstration through the partial board and possible boards, without reading the move table.

## Hidden backup navigation

13: all seven archived match rows. 14: full value and move metrics. 15: offline belief context. 16: MC and TD comparison. 17: retained-search prototype. 18: evaluator inventory. 19: contribution confirmations. 20: sources and scope. Hidden slides are skipped during the core slide show. The PDF includes all pages for review.

## Sources and evidence boundaries

**Rules:** Rules and worked example: docs/drafts/presentation-assets/hidden-rook-example.json. Public custom start k7/8/7r/8/3K4/8/8/8 b - - 0 1. Alternative Black moves h6c6 / h6e6 produce identical White observations, legal feedback and private history. Only immediate king-capture consequences are shown. These are two selected possibilities, without assigned probabilities or a complete-posterior claim. Rule reference: https://github.com/Mr-Teal/CS5446_project/blob/149278181ed6d2b52dce31991fb311a2a74339d0/pair_a_prep/rules_adapter.py

**Values:** Evaluator evidence: https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/README.md . Separate development check: 959 games, 3818 decisions, 94963 eligible children. Network 1 selection also used this check set. Full-board D11 teacher. D1 MAE 0.095, Network 1 0.076. Mean errors and rankings address different objectives. Not a sealed-test result.

**Batch:** Archived evaluator batch: https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27 . Execution a5c5fb6, stand-in rules, predates later no-move/EP updates. Network 1: paired score 0.515, bootstrap 95% interval [0.448,0.585], 100 complete colour pairs. Baseline D1 median 11.1 ms/move, Network 1 36.1. Same one-ply outer planner, 256 particles, eight hypotheses, unequal compute. This is one row of seven separate comparisons against D1. Total 1400 attempts, 1399 finished, 699 complete pairs, six capped draws. Whole-belief context was not used online. Full tables remain in backup. Null-containing intervals do not establish equivalence. Methods: https://github.com/Mr-Teal/CS5446_project/blob/7c292af5881b8c81e4ffccb7300de21650c9c0ad/pair_b/docs/evaluation-methods-draft.md

**Demo:** Actual local Fog Lab browser opening demonstration, 6 November 2026. Local historical checkout, Teal rules, material scorer, seed 0. Human e2e4, bot b8a6. Saved screenshot and two-ply record: docs/drafts/presentation-assets/. The diagnostic panel shows the bot's own hypotheses for inspection. This is not Fair mode, a full game, or a playing-strength result. It does not demonstrate the unmerged Pair A Fog Lab bot or the learned evaluator. The displayed 22 ms is this local action, not the archived batch timing.

**Search:** Search and current-scope review: https://github.com/Mr-Teal/CS5446_project/pull/33#issuecomment-6630857564 . The project includes search prototypes and a separate exact-history tracker. The archived batch isolates evaluators in a one-ply planner. A reviewed learned-leaf deeper-search comparison remains pending. PR65/66/67 mechanisms and author-reported full-agent arms remain separately reviewed, with raw evidence and implementation corrections outstanding. No complete Obscuro reproduction or new training requirement. Background: Zhang and Sandholm, https://arxiv.org/abs/2106.06068v2 and https://arxiv.org/abs/2506.01242v2 .

**Worked example:** The public custom starting position and three candidate-move checks are in presentation-assets/hidden-rook-example.json. The example concerns immediate capture after these candidate moves, without an optimality or full-posterior claim.

**Demonstration:** The screenshot and two-ply game record are in presentation-assets/. It uses a material bot on a historical checkout. The displayed single-action timing is not an archived experiment measurement.

**Course alignment:** The project guidelines, pages 3-5, emphasize an AI-familiar audience outside the topic and presentation relevance, organization, clarity, time management and Q&A. The new core has two points with one visual progression per slide.

**Contributions and AI assistance:** The existing individual contribution statements remain in backup and require each member's confirmation. Do not infer the human identity of xiaomiao-fong from the account name. Copilot assisted earlier drafts. Codex assisted the restructuring, rules-example checks and browser demonstration under Bryan's direction. No new training or formal match batch was run.
