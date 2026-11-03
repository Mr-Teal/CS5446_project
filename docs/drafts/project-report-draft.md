# Fog of War Chess

Search Prototypes and Learned Leaf Evaluation

CS4246/CS5446: Reinforcement Learning and Sequential Decision Making

National University of Singapore, School of Computing

Semester 1, AY2026/27

## Project Report Draft

3 November 2026 | Living draft for team review, not final submission

**Team:** DING Chiyu; PEI Shengxin; QUEK Hongqiang Colin; WANG Zhijian;
Kuah Jun Hong, Bryan; LIN Tzu-Chun.

**Living-draft status.** This report records the available implementation,
development results, historical validation and archived seven-row batch,
independently audited at PR38 head 5e9393a. Integrating a reviewed section is
not a declaration that the report is finished. Continue revising it as the
team's implementation, experiments and interpretation develop.

**Update routine.** When relevant code, evidence or contributor information
changes, update the affected claim and its pinned source, then regenerate the
Word/PDF and check the page limit, figures and denominators again. Preserve
historical experiment identities rather than silently relabeling old results
as measurements of newer code. Keep unperformed experiments and unconfirmed
contributions explicit. Reconcile teammates' edits before regenerating files.

**Sharing and submission.** Student numbers and email addresses are deliberately
omitted from this GitHub-review copy; restore all required team details in the
Canvas submission. The course requires a PDF, not a Word file. The main report
has a strict 10-page limit, excluding title page and references, with single
spacing, one column, at least 12-point text and one-inch margins. Manage the final
numbered Vancouver bibliography in a reference manager. The Word draft embeds
20 source records; `report-sources.xml` is the shareable source library.
Numbered citations remain manually maintained, not linked citation fields.
Complete metadata/style review and field linking before submission.

**Reading guide.** Development-label results, historical match checks and the
archived pre-rule batch are separate evidence populations. An unmerged
experimental branch remains separate from main even after scoped approval.
Detailed review logs are linked rather than
reproduced in the main report. Remove this cover guidance before final submission.

---

## Abstract

Fog-of-war chess combines tactical calculation with uncertainty about hidden
pieces and an opponent's knowledge. This project studies the engineering and
evaluation of search and learned leaf values in that setting, drawing on
knowledge-limited subgame solving and Obscuro [1,2]. We develop a shared
observation/evaluation interface, search prototypes, interchangeable leaf
evaluators, and a reproducible match protocol. Development-set measurements
show that a learned correction reduces value error against Stockfish depth-11
labels from 0.095 to 0.076, but does not establish better move choice. A
belief-conditioned network also improves label error, although its labels are
full-board values rather than strategic belief-state values. A seven-row
batch completed 1,399 of 1,400 scheduled games: Network 1 and linear correction
do not establish improvement over depth 1; the belief row remains inconclusive.
Scoped checks support tree growth and budget/fallback behavior. The contribution is a documented experimental
framework and analysis of these distinctions, not an exact reproduction of
the published agents or a demonstrated improvement in general playing strength.

## 1. Introduction and Objectives

In ordinary chess, both players observe the board and can search over legal
continuations from a known position. Fog-of-war chess removes that shared state
description. A move may reveal pieces or change what the opponent can infer,
so a board's tactical value does not by itself describe the strategic value of
an information state. This makes the game a useful setting for sequential
decision making under uncertainty and adversarial interaction.

Zhang and Sandholm's work addresses subgame solving when common-knowledge
reasoning is prohibitively large [1]. Their later Obscuro system combines
advances in imperfect-information search and demonstrates superhuman fog-of-war
play [2]. We use these papers as methodological references. Their reported
performance is not a result of this project.

Our practical question is whether learned frontier evaluation can improve the
accuracy-cost trade-off within a controlled decision procedure. We separate
three questions: **RQ1**, does a learned correction improve full-board label
error and move ranking; **RQ2**, what does belief context contribute when the
training labels themselves are not belief-dependent; and **RQ3**, do evaluator
changes improve playing score under a fixed outer planner, with computation
cost reported? Existing development evidence addresses RQ1 and part of RQ2.
The completed fixed-planner batch addresses RQ3 within its recorded rules,
openings and compute limitations.

The original proposal envisaged a staged reconstruction followed by
solver-labeled belief learning. The current evidence supports a narrower
claim: useful components and independently checked behaviors have been built,
but the entire proposed pipeline has not been validated as one final system.
This report distinguishes delivered functionality, planned integration and
measured results rather than treating the proposal as evidence of completion.

---

## 2. Problem Formulation and Background

### 2.1 Information and Decision Making

Let a history describe the moves and observations leading to a decision.
Histories that the acting player cannot distinguish belong to one information
set. A valid behavioral strategy must assign the same action distribution at
all histories in that information set. Choosing a different move because the
simulator knows the hidden board would introduce information unavailable to
the player. A belief instead assigns probabilities to possible histories or
states, conditional on the player's observations and known actions.

Our interfaces represent a belief with sampled complete-board hypotheses and
weights normalized over the sample. This sample is not necessarily the full
set of consistent histories. Two histories can reach the same board position
while differing in repetition history, private observations or the opponent's
information. Consequently, equality of FEN strings is not sufficient grounds
for merging them in information-sensitive search [3].

The agent receives its own observations, legal-action feedback, history and
belief. The referee alone owns the actual game state. This boundary is essential:
evaluation on reconstructed hypotheses is permitted, but using the referee's
true board during move selection would invalidate the imperfect-information
experiment. Offline label generation and post-game diagnostics are distinct
from an agent's information access during play.

### 2.2 Search Without Common Knowledge

Conventional imperfect-information subgame solving can require reasoning over
the common-knowledge closure of the current information set. In games where
private observations create a large closure, that requirement can make local
search impractical. Knowledge-limited subgame solving restricts the relevant
knowledge structure while accounting for continuation values outside the
locally solved region [1]. It is more than independently solving sampled
fully observed boards.

Obscuro develops search techniques including predictive counterfactual regret
minimization, growing trees and knowledge-limited subgame constructions [2].
Counterfactual regret updates compare actions at an information set while
respecting the player's information constraints. Frontier estimates make
truncated search possible, but their approximation error can influence the
computed strategy. Retaining accumulated solver state during growth avoids
restarting all previous learning when a deeper continuation is added.

Our implementation follows selected mechanisms, not every mechanism of either
paper. The uniform-growth prototype rebuilds its search each turn. The later
search stack adds selective expansion, retained search, sampled gadget
boundaries and purification. Main 02bb041 includes that stack, the evaluation
methods and Pair C deliveries. PR62/60 are incorporated into PR59; its runner
conflict is resolved at 78f687b, but PR59 remains unmerged into main.
Native/required-environment checks and exact-head review remain. Merge status does not establish full
reproduction or validate the final integrated agent, and it does not change
the source revision of the archived match batch [4,5].

---

## 3. System and Search Approach

### 3.1 Shared Contracts and Rules

The shared package separates the referee, observation stream, belief tracker,
agent and leaf evaluator. A decision records both the raw root distribution and
the action actually selected. Training records contain a game identifier,
configuration identity and acting-player value convention, supporting replay
and whole-game data splits [3]. The following sequence describes the runtime
boundary, not a claim that every experimental agent uses the same search.

| Stage | Information consumed | Output and safeguard |
| --- | --- | --- |
| Referee and observation | Actual game state, held by the referee | Player-visible squares and legal actions; no true-board record passed to the agent |
| Belief update | That player's observations and known own moves | Weighted hypotheses; approximation and recovery events remain diagnosable |
| Decision and recording | Observation, belief, evaluator and configured budget | Policy and selected legal move; runtime, work and provenance records |

Fog rules differ from ordinary chess legality: king-safety restrictions are
removed, king capture can end a game, and visibility, castling and en passant
require explicit handling. History is needed for repetition. A heuristic
forced-loss estimate is not the same as a referee-terminal result. Shared
rule checks precede engine calls, including positions ordinary Stockfish
cannot safely analyze. Fixture agreement supports tested cases; it does not
prove equivalence to every Chess.com or OpenSpiel rule detail [3,4].

### 3.2 Search and Tracking Variants

Pair A's preparation includes explicit information-set trees, a fixed-tree
predictive counterfactual regret minimization (PCFR+) solver, knowledge/gadget
components, history-based tracking, and incremental chess-tree expansion [4].
The exact-history tracker and the bounded particle tracker used in Pair B
matches are different configurations; the latter's 256-particle setting is not
a claim that the complete consistent-state population contains 256 boards.

During incremental expansion, new continuations are prepared before being
committed. Existing minimizers, regrets and strategy accumulators should survive
a successful graft; an unsuccessful preparation should leave a usable prior
tree. The budgeted uniform-growth prototype tracks node and evaluator-call caps,
reserves rounds for final solving and reports why growth stopped. Its clock is
cooperative: an in-progress evaluator or solver operation is not preempted [4].

The evaluation runner's one-ply belief planner is simpler: it scores legal
candidate moves using weighted evaluations across sampled hypotheses. This
controls the outer decision procedure when comparing leaf evaluators. It is
not the same algorithm as the imperfect-information PCFR+ search, and match
results from that runner cannot establish the effectiveness of the deeper
search stack or its knowledge-limited gadgets [6,7].

---

## 4. Learned Leaf Evaluation

### 4.1 The Leaf Problem

A chess search cannot look to the end of the game. It stops at some depth and
needs a value for each position where it stops. We call such a position a leaf,
and the function that values it a leaf evaluator. Obscuro uses Stockfish at
depth 1, which we call "quick Stockfish" [2]. A more accurate leaf could let a
search see further for the same cost. DeepStack [8] and ReBeL [9] use learned
leaf values in this way.

Our leaf evaluators all answer the same calls. They value the children of a
position, one board, or a whole belief. A belief is the set of boards that a
player thinks possible, each with a weight. Values are in [−1, 1], from the
view of the player to move. Positions that the fog-of-war rules decide, such as
a king that can be captured, get an exact value first. A search can therefore
change its evaluator by changing one argument.

This is the core of RQ1 in Section 1: does a more accurate leaf value give
better moves?

### 4.2 Data

Pair A's solver could not yet label fog-of-war positions in large numbers. We
therefore trained on practice data from ordinary chess. We generated 8,000
games that mix quick Stockfish moves with random moves. Where the fog-of-war
rules end a game differently, those rules give the result.

From each game we take four positions. Stockfish 19 values every child of each
position at depth 1 and at depth 11. As in Obscuro's leaf, one engine call at
the parent scores all its children [2]. We call the depth-11 engine "careful
Stockfish" and use its value as the target. A score of *c* centipawns
(hundredths of a pawn) becomes the value tanh(*c*/600). A forced mate is +1 or
−1.

A hash of the game ID puts 80% of the games in training, 10% in validation and
10% in a sealed test set. One game is therefore never in two sets. Our results
use a separate check set of 959 games, made with a different seed. It holds
3,818 decisions, with 94,963 children that the rules do not decide. The check
set also chose between three Network 1 runs, so its results are development
results [6].

### 4.3 Evaluators

Besides quick and careful Stockfish, we compare five evaluators. Here *v*₁ is
quick Stockfish's value.

- **Piece values:** a material count with weights 1, 3, 3, 5 and 9. This is the
  floor.
- **Linear correction:** *v*₁ plus a linear function of 1,217 board features,
  fitted by ridge regression. Bryan built this simple baseline.
- **Linear, inside tanh:** the same correction inside the tanh, *v* =
  tanh(atanh(*v*₁) + **w**·**x** + *b*).
- **Network 1:** *v* = tanh(atanh(*v*₁) + *f*(board)), where *f* is a
  convolutional network with 521,000 weights. It learns careful Stockfish's
  value by regression. This is distillation: a fast model learns to copy a
  slow, stronger one.
- **Belief network:** a network with 562,000 weights that values all boards of
  a belief together. Each board's value can therefore use the other boards. Its
  labels are careful Stockfish's values of each board alone.

The learned evaluators correct *v*₁. They still need the quick Stockfish call,
so their cost adds to it.

---

## 5. Evaluation Method

**Offline.** We compare each evaluator with careful Stockfish on the check set.
**Value error** is the mean absolute difference from careful Stockfish's value.
**Same top move** is how often the evaluator's best child is also careful
Stockfish's best child. **Value lost** is how much lower careful Stockfish
values the evaluator's choice than its own best child. Positions from one game
are correlated. Each 95% interval therefore comes from 2,000 resamples of whole
games. Evaluators are compared on the same positions.

**In play.** A simple one-ply bot keeps 256 sampled boards that fit what it has
seen. At each move, it values every legal move on 8 of these boards. It then
plays the move with the highest average value. Both sides use this bot, and
only the leaf evaluator changes. The opponent is always quick Stockfish.

Each match plays 100 random openings of 2 to 8 plies (single moves), each twice
with the colours swapped. A win scores 1, a draw 0.5 and a loss 0. The paired
score is the mean over complete pairs of games, so 0.5 means equal strength. We
give a bootstrap interval over pairs and Wilson's interval. A game that reaches
200 plies counts as a draw [7,10].

This design holds the work per move equal, not the time. The bot treats each
sampled board as if it were the true board, a known weakness called strategy
fusion [11]. It is a baseline for comparing leaves, not the team's agent.

---

## 6. Results

Sections 6.1 and 6.2 answer RQ1. Section 6.3 answers RQ2, and Section 6.4
answers RQ3.

### 6.1 Better Values, Not Better Moves

**Table 1.** Leaf evaluators on the check set (959 games), against careful
Stockfish. Time is the median CPU cost to value the children of one position.

| Evaluator | Value error | Same top move | Value lost | ms per position |
|---|---|---|---|---|
| Piece values | 0.336 | 27.7% | 0.2108 | 0.6 |
| Quick Stockfish | 0.095 | 42.9% | 0.0355 | 1.4 |
| Linear correction | 0.084 | 41.5% | 0.0346 | 1.7 |
| Linear, inside tanh | 0.079 | 43.5% | 0.0348 | not timed |
| **Network 1** | **0.076** | 42.4% | 0.0352 | 12.2 |

Network 1's value error is 20% lower than quick Stockfish's. The difference is
−0.019 (95% interval −0.021 to −0.018). Its value lost differs by −0.0003
(−0.0017 to +0.0011). The interval includes zero, so these results do not
establish an improvement in move selection; they do not establish equivalence.

Figure 1 shows why. On decided positions, Network 1 halves the error. On close
positions, every learned evaluator is worse than quick Stockfish. In a decided
position, most moves keep the same result, so errors there change few choices.
In a close position, a small error can change the best move. The learned gain
therefore falls where it matters least. This agrees with a known result: a
greedy policy can be optimal long before its values are accurate [12].

![Figure 1. Value error by how decided the position is, on the check set. The learned evaluators gain on positions that lean one way or are decided. They lose on close positions.](../../pair_b/experiments/tanh_linear/value-error-by-band.png)

Most of the gain needs no network. The linear correction gets 56% of Network
1's gain, and 83% inside the tanh. Network 1 also costs more: about 9 times
quick Stockfish's time on a CPU, and 3 times on an Apple GPU. A leaf for search
must rank the moves of close positions well. This points to labels from real
fog-of-war positions, and to a training loss that ranks sibling moves.

### 6.2 Copy a Stronger Engine, Not Game Results

Can a leaf learn from game results instead? We fitted the "linear, inside tanh"
model to four targets [12,13]. Distillation uses 638,451 child rows from 6,414
training games. MC/TD exclude 175 unfinished training games, using 722,500
trajectory positions from 6,239 finished games. The methods therefore differ
in training-row distributions as well as targets. Two targets are careful
Stockfish's value (distillation) and the final result (Monte Carlo, MC). The
other two are temporal-difference targets: TD(0), and TD(λ) with λ = 0.8. TD
uses fitted value iteration, with up to 15 rounds. MC and TD never see careful
Stockfish.

**Table 2.** The same model trained on four targets. Value error and move
metrics use 94,963 child rows and 3,818 decisions from 959 check games. Outcome
error is the mean squared difference from the final game result, using 106,971
trajectory positions from 929 finished games; 32 unfinished games are excluded
from 961 replay games [13].

| Target | Value error | Outcome error | Same top move | Value lost |
|---|---|---|---|---|
| **Careful Stockfish (distillation)** | **0.079** | 0.513 | **43.5%** | **0.0348** |
| Game result (MC) | 0.217 | 0.481 | 38.6% | 0.0505 |
| TD(0) | 0.185 | **0.476** | 42.1% | 0.0370 |
| TD(λ), λ = 0.8 | 0.208 | 0.476 | 41.5% | 0.0415 |
| Quick Stockfish, no learning | 0.095 | 0.497 | 42.9% | 0.0355 |

Values learned from game results are worse than quick Stockfish alone. Their
value error is 0.18 to 0.22, and they choose worse moves. MC gets worse with
more data: its value error grows from 0.098 at 100 games to 0.217 at 6,414
games.

These models predict game results slightly better than distillation does. But
the results come from weak practice play. The models therefore learn how weak
play ends from a position, not how good play values it. TD predicts results
better than MC, by 0.005 (0.001 to 0.010), as its lower-variance targets
suggest [12]. Learning from results would need a strong player and far more
games, as in AlphaZero [14].

### 6.3 The Belief Network

On practice beliefs, the belief network values boards better than quick
Stockfish. Its board error is 0.074, against 0.080. Its error on the belief's
weighted value is 0.047, against 0.055, a difference of −0.008 (−0.009 to
−0.007). The other boards of the belief help a little. Over five seeds, board
error is 0.0734 with them and 0.0762 without them, and every seed improves.

But each label is the value of one board alone. The labels do not depend on the
belief, or on what either player knows. The gain is therefore best read as
noise reduction, not as a value for hidden information. That test needs labels
that depend on the belief, such as values from Pair A's solver.

### 6.4 Play Against Quick Stockfish

**Table 3.** Each row schedules 200 games of one evaluator against quick
Stockfish, both inside the one-ply bot. Score and intervals use complete colour
pairs (100 per row, 99 for random); W/D/L counts every finished game (199 for
random). The first row, quick Stockfish against itself, is a control. Time is
the median per move.

| Evaluator | Score | Bootstrap 95% | Wilson 95% | W/D/L | ms per move |
|---|---|---|---|---|---|
| Quick Stockfish | 0.520 | 0.455–0.588 | 0.423–0.615 | 103/2/95 | 11.1 |
| Random moves | 0.000 | none\* | 0.000–0.037 | 0/0/199 | 0.005 |
| Piece values | 0.048 | 0.023–0.078 | 0.020–0.108 | 9/1/190 | 4.3 |
| Linear correction | 0.513 | 0.455–0.573 | 0.416–0.608 | 98/9/93 | 14.2 |
| Network 1 | 0.515 | 0.448–0.585 | 0.418–0.611 | 100/6/94 | 36.1 |
| Belief network | 0.563 | 0.495–0.630 | 0.465–0.656 | 111/3/86 | 149.8 |
| Careful Stockfish | 0.585 | 0.513–0.660 | 0.487–0.677 | 114/6/80 | 2,452 |

\* All complete random-row pairs score 0, so the bootstrap has no spread.
One game failed when quick Stockfish's bot had no sampled board left that
fitted its observations. The surviving partner remains in W/D/L; the
incomplete pair is excluded only from paired estimates (99 pairs, 198 games).
Six draws reached the 200-ply cap: two linear and four careful-Stockfish games.

The control rows behave as expected. Quick Stockfish against itself scores
0.520. Random moves and piece values lose almost every game. Neither Network 1
nor the linear correction establishes a score improvement over quick Stockfish
in this batch: all their intervals include 0.5. These intervals do not establish
equivalence. As in Section 6.1, better values did not demonstrate better moves
in these experiments.

The belief network and careful Stockfish score above 0.5, but the evidence is
weak. Only careful Stockfish's bootstrap interval excludes 0.5, and a
correction for testing seven rows would remove that result. The rows are
separate matches against one opponent, so they do not rank the evaluators.

The costs differ greatly. Per move, Network 1 takes about 3 times as long as
quick Stockfish, the belief network 13 times and careful Stockfish 220 times.
The bot calls the belief network on one board at a time, so this row does not
test whole-belief evaluation.

All rows ran on one computer with one fixed code version, on 26 and 27 October
2026. Bryan checked the game records independently. The batch ran before the
team added a draw rule for positions with no legal move. No game reached such a
position [15].

### 6.5 Our Leaf Inside Pair A's Search

**Pending experiment, not a result.** No full-agent comparison is reported in
this draft. The intended comparison holds Pair A's search fixed and changes
the leaf evaluator, starting with quick Stockfish. It depends on a tracker and
integrated agent that complete full games within the agreed resource limits.
The one-ply batch in Table 3 is not a substitute. When this experiment becomes
available, add its own pinned configuration, paired outcomes, exclusions and
costs; do not pool it with the archived batch.

---

## 7. Implementation Verification and Discussion

### 7.1 Scoped Verification

Exact toy examples illustrate the information distinction: revealing player
0's action to the opponent changes matching-pennies value from 0 to -1;
revealing a biased coin to its guesser changes expected payoff from 0.5 to 1 [16].
These examples explain information sets, not chess performance. Supplemental
reviews test narrower implementation contracts, with rerunnable evidence linked
below. Test counts overlap across revisions and must not be summed.

A separate historical 20-game D1-versus-material check has archived records
and an independent audit [17]. It is not the material row of the seven-row batch
and is not pooled with that batch's estimates.

| Claim tested | Evidence | Boundary |
| --- | --- | --- |
| Growth retains prior solver state and rejects incomplete grafts | PR27: 404 existing tests plus 7 additional probes passed [18] | Tested histories and failures, not universal correctness |
| Budget accounting, fallback and diagnostics match execution | PR30: 425 existing tests plus 20 probes; 18 twice-run fixed-work cases agree excluding timing [19] | Calls are not total compute; a 10 ms probe took about 10.47 ms |

The focused tests are subsets, not additional independent samples. These
historical search snapshots predate the no-move-rule update [20]. Later scoped
checks cover diagnostics, label rejection, fallback recovery and weighted
values. Combined PR59 head 78f687b recorded 176 passes and 16 native-backend
skips, with four focused probes reusing existing scenarios [5]. This was
author-assisted validation, not independent review of the resolution.
Native/locked-runtime verification remains; strict ply-9 and relaxed ply-11
memory failures persist. These checks do not establish release correctness
or playing strength. This editorial revision runs no new experiments.

### 7.2 What the Evidence Establishes

Three objectives must remain distinct: matching a full-board teacher, choosing
good actions under hidden information, and faithfully reproducing a published
search algorithm. The strongest available evaluator result concerns the first.
The second has bounded evidence from the archived fixed-planner matches;
the third requires verification of all relevant search mechanisms and their
integration. Success in one does not imply success in the others.

The simpler linear baseline explains much of the network's regression gain,
without establishing better move ranking. Recorded configurations, rule checks
and game-grouped analyses make that distinction inspectable.

For belief context, the next discriminating experiment holds the board fixed
while changing information structure, uses validated belief-dependent targets,
and compares actions under the same search. An equal-time comparison must also
budget the entire decision path, not equate evaluator calls with different
internal workloads.

---

## 8. Limitations, Responsible AI and Next Steps

Limitations include development-set selection, approximate labels, synthetic
beliefs, uncertain transfer from ordinary chess, different rule/search revisions
and unequal compute in a pre-rule match batch. Paper engine versions and search differ. Results establish
neither exact reproduction nor human-level/general strength; subgame diagnostics
are not whole-game exploitability.

Responsible use requires **transparency** through records, **accountability**
through attribution/review, and **fair play** through information boundaries.
Future human matches require consent and bot identification. No human study,
fairness audit or social benefit is claimed.

Next, review and pin the integrated search revision, then investigate
belief-dependent targets and search ablations. A post-rule batch is a separate
team decision, not a prerequisite for preserving these archived results. Retain positive, negative and
inconclusive results.

## 9. Team Contributions and AI Assistance

Teal confirmed his prototype work; other members' statements remain provisional.

| Member(s) | Contribution reflected in current records |
| --- | --- |
| DING Chiyu | Rules/referee/private observations; PCFR+, Resolve/Maxmargin prototypes; chess-history/gadget integration; label pilots/provenance; within-turn growth and budgeted-agent integration; tests, diagnostics, documentation and visualizers |
| PEI Shengxin | Belief tracker and ZS21 (division reported by Teal); await Shengxin's confirmation of wording/completion |
| QUEK Hongqiang Colin | Pair B evaluators and practice-data/training; one-ply bot, particle tracker, play_matches runner; protocol and seven-row batch (PR38); Fog Lab; worked information example; PR15/28 reviews |
| Kuah Jun Hong, Bryan | Linear correction baseline (PR8); state-preserving toy PCFR+ expansion API (PR21), used by later chess/gadget integration; independent cross-check and batch archive audit; scoped reviews, methods and report/presentation drafts |
| WANG Zhijian | Pair C evaluation workflow; own wording/completion to confirm. Colin operated the Pair B batch at Zhijian's request |
| LIN Tzu-Chun | Role and completed contribution await confirmation |

GitHub Copilot assisted Bryan's inspections, probes, artifact checks and drafting
under his direction. Codex assisted the archive audit, scoped search reviews
and this document revision.
Teal reports Codex assistance; the proposal records
Claude-assisted drafting. Others must disclose their use. Human verification
and team approval remain necessary.

## 10. Conclusion

The project provides search and evaluation components with traceable evidence.
Better full-board prediction has not yet established better decisions under
hidden information. The audited fixed-planner batch does not establish gains
for Network 1 or linear correction over D1. Its limited, unequal-compute
comparisons do not establish full-agent strength or strategic belief value.

---

## References

1. Zhang BH, Sandholm T. Subgame solving without common knowledge [Internet]. arXiv:2106.06068v2; 2021 Dec 3 [cited 2026 Oct 26]. Available from: [https://arxiv.org/abs/2106.06068v2](https://arxiv.org/abs/2106.06068v2).

2. Zhang BH, Sandholm T. General search techniques without common knowledge for imperfect-information games, and application to superhuman Fog of War chess [Internet]. arXiv:2506.01242v2; 2026 Mar 3 [cited 2026 Oct 26]. Available from: [https://arxiv.org/abs/2506.01242v2](https://arxiv.org/abs/2506.01242v2).

3. CS5446_project contributors. Shared code and integration contract [Internet]. 2026 [cited 2026 Oct 26]. Revision 2af8f1f731a978cd5a5bb1f5d5131b40ae01c72d. Available from: [pinned repository README](https://github.com/Mr-Teal/CS5446_project/blob/2af8f1f731a978cd5a5bb1f5d5131b40ae01c72d/README.md).

4. CS5446_project contributors. Pair A search implementation, specifications and reproduction differences [Internet]. 2026 [cited 2026 Oct 26]. Revision 5f334b1e26de31e5c90d444d3a4222352e5fb3ed. Available from: [pinned Pair A source](https://github.com/Mr-Teal/CS5446_project/tree/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_a_prep); [detailed mechanism checklist](https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_a_prep/docs/obscuro_status.md).

5. CS5446_project contributors, bryankuah. Integration status and scoped search reviews [Internet]. 2026 Nov 3 [cited 2026 Nov 3]. Main 02bb0410ce3a17ce308d900a26b0ad453bfe20f5 includes the later search stack and PR50/51. PR62 merged into PR59 at 44d806d; PR60 was automatically marked merged through ancestry. The runner conflict with main is resolved at PR59 head 78f687b860a3fb95160b80be472d7fc8621a144b, but PR59 remains open and unmerged into main. PR61 merged into the report draft branch, not main. Combined-head evidence: 176 passes, 16 native-backend skips and four focused probes reusing existing scenarios; counts are not additive independent coverage. No native execution, locked-runtime suite, new solver-recovery probe or matches were run; archived artifacts were preserved. Exact-head review and native/required-environment checks remain. Historical reviewed heads: PR42 25688180178589d41daadfaa5a23117a115fe96d; PR52 5e74ede8ef874a3bdc31564830e889f113951f87; PR46 ee42c8f8e41858431e000825a437ee39b2e88b7b; PR48 879818c16518e1d706cf60fe5f666979d532aec9. Those historical scoped reviews are not tests of this main snapshot. Available from: [pinned main](https://github.com/Mr-Teal/CS5446_project/tree/02bb0410ce3a17ce308d900a26b0ad453bfe20f5); [PR59 combined-head evidence](https://github.com/Mr-Teal/CS5446_project/pull/59#issuecomment-6571745962); [PR62 integration](https://github.com/Mr-Teal/CS5446_project/commit/44d806d51e959a348d3a9ea31354654a6195ee2e); [PR37 delivery](https://github.com/Mr-Teal/CS5446_project/pull/37); [PR42 review](https://github.com/Mr-Teal/CS5446_project/pull/42#pullrequestreview-5679229932); [PR52 review](https://github.com/Mr-Teal/CS5446_project/pull/52#pullrequestreview-5679231586); [PR46 review](https://github.com/Mr-Teal/CS5446_project/pull/46#pullrequestreview-5679261471); [PR48 review](https://github.com/Mr-Teal/CS5446_project/pull/48#pullrequestreview-5679267479).

6. emalcolin, CS5446_project contributors. Pair B: leaf evaluators, Network 1 and its practice data [Internet]. 2026 [cited 2026 Oct 26]. Revision 5f334b1e26de31e5c90d444d3a4222352e5fb3ed; contains links to the underlying checkpoint results and manifests. Available from: [pinned evaluator documentation](https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/README.md).

7. CS5446_project contributors. Match protocol [Internet]. 2026 [cited 2026 Oct 26]. Revision 2af8f1f731a978cd5a5bb1f5d5131b40ae01c72d. Available from: [pinned protocol](https://github.com/Mr-Teal/CS5446_project/blob/2af8f1f731a978cd5a5bb1f5d5131b40ae01c72d/pair_b/docs/match_protocol.md); [protocol discussion, issue 17](https://github.com/Mr-Teal/CS5446_project/issues/17).

8. Moravčík M, Schmid M, Burch N, Lisý V, Morrill D, Bard N, et al. DeepStack: expert-level artificial intelligence in heads-up no-limit poker. Science. 2017;356(6337):508-13.

9. Brown N, Bakhtin A, Lerer A, Gong Q. Combining deep reinforcement learning and search for imperfect-information games. In: Advances in Neural Information Processing Systems 33 (NeurIPS 2020); 2020.

10. bryankuah. Evaluation methods and batch validation [Internet]. 2026 Nov 2 [cited 2026 Nov 2]. Merged PR50, revision 7c292af5881b8c81e4ffccb7300de21650c9c0ad. Available from: [pinned updated methods](https://github.com/Mr-Teal/CS5446_project/blob/7c292af5881b8c81e4ffccb7300de21650c9c0ad/pair_b/docs/evaluation-methods-draft.md).

11. Frank I, Basin D. Search in games with incomplete information: a case study using Bridge card play. Artificial Intelligence. 1998;100(1-2):87-123.

12. Sutton RS, Barto AG. Reinforcement learning: an introduction. 2nd ed. Cambridge (MA): MIT Press; 2018.

13. CS5446_project contributors. Monte Carlo and temporal-difference target comparison [Internet]. 2026 [cited 2026 Nov 2]. Revision 1db35d68638d52353381d13de20addfea58a4d99. Available from: [pinned experimental setup and exclusions](https://github.com/Mr-Teal/CS5446_project/blob/1db35d68638d52353381d13de20addfea58a4d99/pair_b/experiments/mc_td/RESULTS.md); [results and sample counts](https://github.com/Mr-Teal/CS5446_project/blob/1db35d68638d52353381d13de20addfea58a4d99/pair_b/experiments/mc_td/results.json).

14. Silver D, Hubert T, Schrittwieser J, Antonoglou I, Lai M, Guez A, et al. A general reinforcement learning algorithm that masters chess, shogi, and Go through self-play. Science. 2018;362(6419):1140-4.

15. emalcolin. Seven-row match batch [Internet]. 2026 Oct 27 [cited 2026 Oct 27]. PR38, reviewed revision 5e9393ab8537088e8ea6542ce21e11f42218ee15; execution source a5c5fb6. Available from: [pinned records, checksums and tables](https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27).

16. emalcolin. How information changes a decision [Internet]. 2026 [cited 2026 Oct 26]. Revision a5c105632e1d990450445b204612d41b5fbc8293. Available from: [pinned worked examples and reference-data links](https://github.com/Mr-Teal/CS5446_project/blob/a5c105632e1d990450445b204612d41b5fbc8293/pair_b/experiments/small_games/information_example.md).

17. bryankuah. Independent D1-versus-material historical cross-check [Internet]. 2026 [cited 2026 Oct 26]. Publication revision 8735be4cc7e06928db6d12ee2487a08bb86e5ba7; historical run source differs as stated in the text. Available from: [pinned raw artifacts and audit](https://github.com/Mr-Teal/CS5446_project/tree/8735be4cc7e06928db6d12ee2487a08bb86e5ba7/pair_b/experiments/matches/crosscheck-bryan-d1-vs-material-standard-start).

18. bryankuah. PR27 supplemental expansion review [Internet]. 2026 Oct 26 [cited 2026 Oct 26]. Reviewed revision 7b14bbbebb80ba410f0e23127e37263b975c167a. Available from: [review](https://github.com/Mr-Teal/CS5446_project/pull/27#issuecomment-6406920434); [rerunnable evidence, v2](https://github.com/user-attachments/files/33944209/pr27-7b14bbb-review-evidence-v2.zip).

19. bryankuah. PR30 supplemental budget and fallback review [Internet]. 2026 Oct 26 [cited 2026 Oct 26]. Reviewed revision 5f334b1e26de31e5c90d444d3a4222352e5fb3ed. Available from: [review](https://github.com/Mr-Teal/CS5446_project/pull/30#issuecomment-6407182994); [rerunnable evidence and raw results](https://github.com/user-attachments/files/33944559/pr30-5f334b1-review-evidence.zip).

20. Mr-Teal. Unify no-move terminal draws across rules and search [Internet]. PR28; 2026 [cited 2026 Oct 26]. Reviewed revision 21da153c8efdc1ae78dd1fac053c2402e1c7b3c7; not a statement that the formal batch uses this revision. Available from: [rule-update pull request](https://github.com/Mr-Teal/CS5446_project/pull/28).

---

## Editorial Revision Checklist

**Working notes for the team.** Complete this pass once the project scope,
results and interpretation are stable. The draft currently reads too much
like an implementation audit in places. These are known writing problems to
resolve, not new experimental findings. Keep the evidence and uncertainty
while making the argument easier to follow. Remove this section from the
submitted report after completing the checks.

**1 Reduce GitHub bookkeeping.** PR numbers, commit hashes, test counts and
publication-window details interrupt the academic explanation. Move operational
history and detailed validation into linked technical notes. In the main text,
retain the source and rules needed to interpret each result. Check: a reader
can follow the argument without opening a pull request.

**2 Consolidate repeated qualifications.** Several sections repeat that the
work does not establish playing strength or full reproduction. Explain each
limitation where it affects interpretation, then collect the remaining limits
in Section 8. Check: uncertainty is preserved without repeating the same
disclaimer throughout the report.

**3 Explain technical terms before using them.** Terms such as projected
root sets, counterfactual reach, purification and ancestor-payment transfer
need a plain explanation of their purpose and what can go wrong. Keep precise
terminology after that explanation. Check: a classmate familiar with AI can
understand the design without knowing the codebase.

**4 Strengthen the research narrative.** Connect the research questions to the
design choices, experiments and conclusions. Explain why we selected the
baselines, what the results changed in our understanding, and which decisions
followed. Check: each major section advances that argument rather than listing
components or completed work. Do not invent motivations or experiences.

**5 Replace generic and formulaic prose.** Review stock transitions, repeated
sentence patterns and broad responsible-AI statements. Tie discussion to this
project's information boundaries, data, attribution and experimental practice.
Check: every paragraph makes a specific, supported point in direct language.

**6 Have the team review the voice and interpretation.** Contributors should
verify the account of their work and revise passages they would not naturally
say or cannot explain. Resolve provisional contribution and AI-use statements.
Check: the authors can defend the wording and conclusions; editing must not
hide assistance or turn uncertain findings into stronger claims.

**7 Check readability after the rewrite.** Shorten dense paragraphs, use a
diagram or compact table where it clarifies the method, and explain captions,
units and denominators. Recheck Word and Markdown agreement, bibliography,
12-point text, one-inch margins and the ten-page main-text limit. Check: the
rendered report reads coherently from start to finish, with no clipped tables
or awkward page breaks. Final team approval and submission details are still
required.
