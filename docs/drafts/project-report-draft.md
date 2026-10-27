# Fog of War Chess

Search Prototypes and Learned Leaf Evaluation

CS4246/CS5446: Reinforcement Learning and Sequential Decision Making

National University of Singapore, School of Computing

Semester 1, AY2026/27

## Project Report Draft

27 October 2026 | For team review, not final submission

**Team:** DING Chiyu; PEI Shengxin; QUEK Hongqiang Colin; WANG Zhijian;
Kuah Jun Hong, Bryan; LIN Tzu-Chun.

**Draft status.** This is a full report draft assembled from the available
implementation, development results, historical validation and the completed
seven-row batch, independently audited at PR38 head 5e9393a. Publication remains
subject to the 27 October 23:59 SGT objection window. The team must confirm the
final integrated revision, contributions and conclusions before submission.

**Major revisions expected.** Major changes are likely as implementation,
integration, experiments and team review progress. This is a provisional
starting point, not an agreed final structure or account of completed work.
Sections, figures, results, conclusions and contributions may need substantial
rewriting. Recheck every claim against the final artifacts before submission;
pending results must not be treated as established findings.

**Sharing and submission.** Student numbers and email addresses are deliberately
omitted from this GitHub-review copy; restore all required team details in the
Canvas submission. The course requires a PDF, not a Word file. The main report
has a strict 10-page limit, excluding title page and references, with single
spacing, one column, at least 12-point text and one-inch margins. Manage the final
numbered Vancouver bibliography in a reference manager. This draft's references
are manually prepared and have not been imported into one.

**Reading guide.** Development-label results, historical match checks and the
archived pre-rule batch are separate evidence populations. An unmerged
experimental branch is not reviewed main functionality. Detailed review logs are linked rather than
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
full-board values rather than strategic belief-state values. A historical
20-game check favors Stockfish depth 1 over material. A separate seven-row
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
paper. At main abfc868, the budgeted prototype uses uniform complete-frontier
growth and rebuilds each turn. The later PR39–PR48 review stack adds selective
expansion, retained search, sampled gadget boundaries and purification; these
are unmerged experiments with open fixes and stale reference measurements,
not reviewed main functionality or a complete Obscuro reproduction. ZS21 and
the shared en-passant repetition fix are separately reviewed in PR37 [4,14].

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
search stack or its knowledge-limited gadgets [5,6].

---

## 4. Learned Evaluation and Data

### 4.1 Evaluators and Representation

The interchangeable evaluators include material values (1/3/3/5/9), Stockfish
depths 1 and 11, a linear correction, Network 1 and a belief-conditioned
network. Engine centipawn values are mapped into [-1,1] using tanh(cp/600),
with forced mates mapped to the endpoints and applicable fog-rule values
handled first. All returned values use the documented player perspective [3,5].

Network 1 corrects a shallow Stockfish estimate; it does not eliminate the
depth-1 engine call. A linear correction supplies a lower-complexity comparator.
The belief network uses a shared board encoder, combines each board embedding
with a weighted summary of the belief, and produces board values conditioned
on that context. The shared representation has 32 spatial planes, including
board, observation and rule-related features, with player-relative orientation.
These distinctions separate the costs of feature construction, engine work and
learned inference [3,5].

The whole-belief interface can evaluate several hypotheses jointly. However,
the existing one-ply match runner calls the belief network board by board through
its child-evaluation interface. Offline whole-belief accuracy and online
board-wise performance therefore test different uses of the same checkpoint.
We do not describe those matches as whole-belief gameplay validation [5].

### 4.2 Data Generation and Evaluation Independence

The initial labels use deeper Stockfish, not an established fog-of-war equilibrium
teacher. Network 1's practice data come from ordinary-chess trajectories used
as a stand-in. Data are partitioned by a hash of the game identifier, with
buckets 0-7 for training, 8 for validation and 9 for the held-out test. Splitting
by whole games prevents sibling positions from the same game crossing splits;
it does not prevent every transposition across independently generated games [5].

The reported development check uses 959 games from the training bucket of a
separate 1,200-game generation. It contains 3,818 parent decisions and 94,963
non-rule-decided child rows. Candidate Network 1 runs were compared on this
check set as well as validation, so these are development measurements, not
untouched final-test estimates. The repository records 168 overlapping child
positions (0.18%) with the earlier training/validation data. The sealed test
bucket is not opened as part of this draft [5].

Belief training uses synthetic observation-consistent hypotheses and full-board
Stockfish depth-11 labels. The generator can use the true board offline, but
the playing agent cannot. Since these labels do not change with the surrounding
belief, a context-sensitive model fitted to them is not thereby trained to value
information gathering or the opponent's knowledge. Such a claim needs validated
belief-state targets or a separate strategic experiment [5].

---

## 5. Evaluation Methodology

Development evaluation measures absolute value error, agreement with the best
depth-11-valued sibling move, and value lost by the selected move. Ties in the
scorer are broken in UCI order. Uncertainty for the reported differences is
estimated by resampling whole games, because positions within a game are
correlated. These metrics measure agreement with an approximate full-board
teacher, not exact fog-of-war optimality [5].

For formal play, seven candidates played Stockfish depth 1 using the same outer
planner for evaluator-based agents, 256 particles and eight hypotheses. Random
play is an additional baseline. Each pairing scheduled 200 games: 100 openings,
each played with colors exchanged. Openings use two to eight nonterminal random
legal plies with seed 0 under the recorded generation rule [6,7,13].

Colin ran all rows on one M5 Pro Mac at a5c5fb6 (main 2af8f1f plus PR34),
26–27 October. The summaries record code, engine, checkpoint and environment
identities. The batch used stand-in rules before PR28 reached main with PR15;
`no_move_rule` remains `unresolved` in these historical artifacts. No game hit a
no-move case. Keep the original provenance and never pool with post-rule runs.
Bryan independently audited the records; he did not rerun the matches [7,13].

Game scores are 1/0.5/0 for win/draw/loss. The primary estimate averages the
two scores within each complete color pair, then averages complete pairs.
Incomplete pairs, failed games and diagnostic errors are counted separately.
The protocol uses a 2,000-resample paired bootstrap when at least 20 complete,
nonconstant pair scores are available; otherwise it reports an approximate
Wilson interval for fractional pair scores and explains why bootstrap is absent.
Pair B counts a still-ongoing game at the 200-ply cap as a draw; Pair C
separately reports capped/null outcomes. Keep these protocols distinct.

Stockfish 19 uses one thread and 16 MB hash, reset before each game. A 60-second
per-call watchdog is failure protection, not an enforced action-time limit.
Report both players' mean/p95 decision latency, game wall time and tracker health.
Each row must footnote unresolved no-move exclusions or recorded no-move draws
under its pinned rule. PR28 is now on main and also changes evaluated stand-in
children, so zero no-move failures does not establish rule-version equivalence.
Compare engine binary hashes alongside source/checkpoint identities.
Outer planning, not compute/time, is controlled; timing excludes tracker updates.
Per-row intervals are not multiple-comparison-adjusted evidence [6,7].

---

## 6. Available Results and Analysis

### 6.1 Development-Set Evaluator Results

Table 1 summarizes repository-reported results on the 94,963 child rows described
in Section 4, not a fresh experiment run for this report [5].

| Evaluator | Value error | Best-move agreement | Mean value lost |
| --- | --- | --- | --- |
| Material | 0.336 | 27.7% | 0.2108 |
| Stockfish D1 | 0.095 | 42.9% | 0.0355 |
| Network 1 | 0.076 | 42.4% | 0.0352 |
| Linear correction | 0.084 | 41.5% | 0.0346 |

Network 1 reduces value error by about 20% relative to D1; the reported paired
difference is -0.019 (95% interval -0.021 to -0.018). Its difference in mean
value lost is -0.0003 (interval -0.0017 to +0.0011), which does not establish
an improvement in move selection. Lower regression error can correct many
values without changing the ranking of the few actions that matter [5].

The offline belief check uses 3,818 beliefs from the same fresh-game check
population. It is a separate task from the child-ranking table above [5].

| Belief evaluator | Board error | Weighted-position error |
| --- | --- | --- |
| Stockfish D1 | 0.080 | 0.055 |
| Planes-only belief network | 0.178 | 0.141 |
| D1-assisted belief network | 0.074 | 0.047 |
| D1-assisted network without context | 0.076 | 0.047 |

Across five seeds, context reduces board error by about 0.0028 on average;
the reported range is -0.0049 to -0.0011. Because the labels are independent
of belief, this supports a denoising interpretation, not learned strategic
information value. The planes-only model's weaker result also cautions against
assuming that representation capacity can replace adequate data or engine
features. These results do not show that the learned models are faster than D1.

### 6.2 Historical Match Cross-Check

Bryan's independently audited historical run used ten color-paired seeds from
the standard public start: D1 won all 20 games against material, with no draws
or losses and 734 plies, all ending in king capture [8]. The paired score is
1.00 with approximate Wilson 95% interval 0.72-1.00. Bootstrap is withheld:
there are only ten pairs and all pair scores are identical.

Bryan's source was 3afc594, with per-call engine reset; Colin's was 00639cb,
with per-game reset [6,8]. Bryan recorded 1,508 tracker updates, 42 rebuilds
and 163 caps. The runs share game machinery but differ in build, platform,
Python and seed mapping; both predate the watchdog. Matching aggregate scores
are not runner equivalence or neural strength evidence; the runs are not pooled.

---

### 6.3 Archived Match Batch

Table 2 reports the seven comparisons against quick Stockfish. Score and
intervals use complete color pairs (100 per row, 99 for random); W/D/L counts
every finished game (199 for random). All figures were recomputed from the
archived game records at PR38 head 5e9393a [13].

| Candidate | Score | Bootstrap 95% | W/D/L | ms/move median (p95) |
| --- | --- | --- | --- | --- |
| D1 self-play | 0.520 | 0.455–0.588 | 103/2/95 | 11.1 (23.9) |
| Random | 0.000 | Withheld* | 0/0/199 | 0.0 (0.0) |
| Material | 0.048 | 0.023–0.078 | 9/1/190 | 4.3 (7.3) |
| Linear | 0.513 | 0.455–0.573 | 98/9/93 | 14.2 (30.0) |
| Network 1 | 0.515 | 0.448–0.585 | 100/6/94 | 36.1 (52.7) |
| Belief | 0.563 | 0.495–0.630 | 111/3/86 | 149.8 (257.4) |
| D11 | 0.585 | 0.513–0.660 | 114/6/80 | 2452.2 (9054.7) |

*Random pairs all score zero, so bootstrap is withheld; Wilson 95% is
0.000–0.037. Other Wilson intervals and mean/p95 timings are in [7,13].
One TrackerLost failure excludes random game 36 and its partner from the score,
leaving 1,398 games in 699 complete pairs; 1,399 games finished overall.
There are no diagnostic errors or recorded 60-second budget overruns.

Draws include six capped/adjudicated games: two of linear's nine draws and
four of D11's six. Every other draw is repetition. Each row has zero no-move
exclusions and zero terminal no-move draws under the pinned pre-rule source.

D1 self-play spans 0.5. Linear and Network 1 do not establish improvement
over D1, consistent with the development ranking result. Belief's interval
also includes 0.5. D11's bootstrap narrowly excludes 0.5, but its Wilson
interval (0.487–0.677) includes it; no adjusted superiority claim follows.
These are separate pairings against D1, not a head-to-head ranking.

Compute differs substantially: median Network 1, belief and D11 decisions
are about 3, 13 and 220 times D1's. Belief scores single-board children in
this runner, so its row is not evidence of strategic information value.
The fixed outer planner controls neither total work nor elapsed time.
The pre-rule batch is never pooled with later-rule or historical checks.

---

## 7. Implementation Verification and Discussion

### 7.1 Scoped Verification

Exact toy examples illustrate the information distinction: revealing player
0's action to the opponent changes matching-pennies value from 0 to -1;
revealing a biased coin to its guesser changes expected payoff from 0.5 to 1 [9].
These examples explain information sets, not chess performance. Supplemental
reviews test narrower implementation contracts, with rerunnable evidence linked
below. Test counts overlap across revisions and must not be summed.

| Claim tested | Evidence | Boundary |
| --- | --- | --- |
| Growth retains prior solver state and rejects incomplete grafts | PR27: 404 existing tests plus 7 additional probes passed [10] | Tested histories and failures, not universal correctness |
| Budget accounting, fallback and diagnostics match execution | PR30: 425 existing tests plus 20 probes; 18 twice-run fixed-work cases agree excluding timing [11] | Calls are not total compute; a 10 ms probe took about 10.47 ms |

PR27's 110 focused tests are included in its 404. The reviewed revisions are
7b14bbb and 5f334b1 respectively; full identifiers and artifacts are in the
references. Their search snapshots exclude the separate no-move-rule update
in PR28 [12]. These are not final integrated-release checks. No additional
solver tests or matches were run to prepare this report draft.

### 7.2 What the Evidence Establishes

Three objectives must remain distinct: matching a full-board teacher, choosing
good actions under hidden information, and faithfully reproducing a published
search algorithm. The strongest available evaluator result concerns the first.
The second has bounded evidence from the archived fixed-planner matches;
the third requires verification of all relevant search mechanisms and their
integration. Success in one does not imply success in the others.

This distinction also sharpens the value of the project beyond a single score.
Information-safe interfaces, explicit rule checks, recorded configuration
identities, game-grouped analyses and failure-visible runners make experiments
inspectable. The learned-versus-linear comparison shows why a simpler baseline
is useful: part of the regression gain does not require the richer model, and
neither gain automatically translates into better move ranking.

For belief context, varying a model's output with other hypotheses is a useful
capacity check but is not evidence that those changes are strategically right.
A stronger experiment would hold board state fixed while changing information
structure, use validated belief-dependent targets, and compare actions under
the same search. Similarly, an equal-time search comparison must budget the
entire decision path, rather than equating a number of evaluator calls whose
internal workloads differ.

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
under his direction. Codex assisted this archive audit and revision.
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

5. emalcolin, CS5446_project contributors. Pair B: leaf evaluators, Network 1 and its practice data [Internet]. 2026 [cited 2026 Oct 26]. Revision 5f334b1e26de31e5c90d444d3a4222352e5fb3ed; contains links to the underlying checkpoint results and manifests. Available from: [pinned evaluator documentation](https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/README.md).

6. CS5446_project contributors. Match protocol [Internet]. 2026 [cited 2026 Oct 26]. Revision 2af8f1f731a978cd5a5bb1f5d5131b40ae01c72d. Available from: [pinned protocol](https://github.com/Mr-Teal/CS5446_project/blob/2af8f1f731a978cd5a5bb1f5d5131b40ae01c72d/pair_b/docs/match_protocol.md); [protocol discussion, issue 17](https://github.com/Mr-Teal/CS5446_project/issues/17).

7. bryankuah. Evaluation methods and batch validation [Internet]. 2026 Oct 27 [cited 2026 Oct 27]. PR50, revision bc8047b172c625a8b2463dbffcbb6a26da86a6b5. Available from: [pinned updated methods](https://github.com/Mr-Teal/CS5446_project/blob/bc8047b172c625a8b2463dbffcbb6a26da86a6b5/pair_b/docs/evaluation-methods-draft.md).

8. bryankuah. Independent D1-versus-material historical cross-check [Internet]. 2026 [cited 2026 Oct 26]. Publication revision 8735be4cc7e06928db6d12ee2487a08bb86e5ba7; historical run source differs as stated in the text. Available from: [pinned raw artifacts and audit](https://github.com/Mr-Teal/CS5446_project/tree/8735be4cc7e06928db6d12ee2487a08bb86e5ba7/pair_b/experiments/matches/crosscheck-bryan-d1-vs-material-standard-start).

9. emalcolin. How information changes a decision [Internet]. 2026 [cited 2026 Oct 26]. Revision a5c105632e1d990450445b204612d41b5fbc8293. Available from: [pinned worked examples and reference-data links](https://github.com/Mr-Teal/CS5446_project/blob/a5c105632e1d990450445b204612d41b5fbc8293/pair_b/experiments/small_games/information_example.md).

10. bryankuah. PR27 supplemental expansion review [Internet]. 2026 Oct 26 [cited 2026 Oct 26]. Reviewed revision 7b14bbbebb80ba410f0e23127e37263b975c167a. Available from: [review](https://github.com/Mr-Teal/CS5446_project/pull/27#issuecomment-6406920434); [rerunnable evidence, v2](https://github.com/user-attachments/files/33944209/pr27-7b14bbb-review-evidence-v2.zip).

11. bryankuah. PR30 supplemental budget and fallback review [Internet]. 2026 Oct 26 [cited 2026 Oct 26]. Reviewed revision 5f334b1e26de31e5c90d444d3a4222352e5fb3ed. Available from: [review](https://github.com/Mr-Teal/CS5446_project/pull/30#issuecomment-6407182994); [rerunnable evidence and raw results](https://github.com/user-attachments/files/33944559/pr30-5f334b1-review-evidence.zip).

12. Mr-Teal. Unify no-move terminal draws across rules and search [Internet]. PR28; 2026 [cited 2026 Oct 26]. Reviewed revision 21da153c8efdc1ae78dd1fac053c2402e1c7b3c7; not a statement that the formal batch uses this revision. Available from: [rule-update pull request](https://github.com/Mr-Teal/CS5446_project/pull/28).

13. emalcolin. Seven-row match batch [Internet]. 2026 Oct 27 [cited 2026 Oct 27]. PR38, reviewed revision 5e9393ab8537088e8ea6542ce21e11f42218ee15; execution source a5c5fb6. Available from: [pinned records, checksums and tables](https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27).

14. CS5446_project contributors. Current integration and pending search reviews [Internet]. 2026 Oct 27 [cited 2026 Oct 27]. Main abfc8686ff3e4948a310f3753b25e702226d7ca0; later work remains separately reviewed. Available from: [pinned main](https://github.com/Mr-Teal/CS5446_project/tree/abfc8686ff3e4948a310f3753b25e702226d7ca0); [PR37](https://github.com/Mr-Teal/CS5446_project/pull/37); [PR42 review discussion](https://github.com/Mr-Teal/CS5446_project/pull/42).
