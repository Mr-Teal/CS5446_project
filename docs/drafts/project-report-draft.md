# Fog-of-War Chess

Search Prototypes and Learned Leaf Evaluation

CS4246/CS5446: Reinforcement Learning and Sequential Decision Making

National University of Singapore, School of Computing

Semester 1, AY2026/27

## Project Report Draft

26 October 2026 | For team review, not final submission

**Team:** DING Chiyu; PEI Shengxin; QUEK Hongqiang Colin; WANG Zhijian;
Kuah Jun Hong, Bryan; LIN Tzu-Chun.

**Draft status.** This is a full report draft assembled from the available
implementation, development results and historical validation evidence. Formal
match results remain pending. The team must confirm the final integrated
revision, contribution statements and conclusions before submission.

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
proposed formal batch are separate evidence populations. Pending means not yet
reported here, not a score of zero. Detailed review logs are linked rather than
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
20-game check favors Stockfish depth 1 over material; it is not the planned
multi-evaluator evaluation. Scoped checks support state-preserving tree growth
and budget/fallback behavior. The contribution is a documented experimental
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
The formal experiment for RQ3 remains pending.

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
paper. In particular, the current budgeted prototype grows frontiers uniformly
and rebuilds its search for each turn. State retention during one tree's growth
must not be confused with complete cross-turn persistence, paper-faithful
one-sided expansion or all of Obscuro's purification and gadget transitions [4].

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

For formal play, the proposed protocol compares seven candidates against
Stockfish depth 1 using the same outer planner for evaluator-based agents,
256 particles and eight sampled hypotheses. Random play is an additional
action-selection baseline. Each pairing schedules 200 games: 100 openings,
each played with colors exchanged. Openings use two to eight nonterminal random
legal plies with seed 0 under the recorded generation rule [6,7].

| Candidate versus Stockfish D1 | Scheduled games | Paired score and interval |
| --- | --- | --- |
| Material | 200 | Pending |
| Stockfish D1 (symmetry check) | 200 | Pending |
| Stockfish D11 | 200 | Pending |
| Network 1 | 200 | Pending |
| Belief-conditioned network | 200 | Pending |
| Linear correction | 200 | Pending |
| Random action | 200 | Pending |

**Status:** these 1,400 games are a plan, not completed results in this report.
The final source/rules revision, machine, checkpoint identities and validated
run artifacts must accompany the completed table. The runner of record proposed
in the protocol discussion is play_matches; a workflow wrapper must preserve
its semantics rather than silently substitute another experiment [6,7].

Game scores are 1/0.5/0 for win/draw/loss. The primary estimate averages the
two scores within each complete color pair, then averages complete pairs.
Incomplete pairs, failed games and diagnostic errors are counted separately.
The protocol uses a 2,000-resample paired bootstrap when at least 20 complete,
nonconstant pair scores are available; otherwise it reports an approximate
Wilson interval for fractional pair scores and explains why bootstrap is absent.

Stockfish 19 uses one thread and 16 MB hash, reset before each game. A 60-second
per-call watchdog is failure protection, not an enforced action-time limit.
Report both players' decision latency, game wall time, tracker health and
termination causes. The comparison fixes outer planning work, not engine work
or elapsed time. Decision timing excludes tracker updates. Per-row intervals
do not establish multiple-comparison-adjusted superiority [6,7].

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

The historical source is 3afc5945dfa5a98e5a90275782b8658b69bb9bcf. It resets
Stockfish before every call, unlike the proposed per-game reset. Its 1,508
tracker updates include 42 rebuilds and 163 capped updates. Colin reported
the same aggregate W/D/L in his separate runner [6], but the runs share game
machinery and differ in engine policy. They are not pooled, do not establish
runner equivalence, and provide no neural-evaluator strength result.

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
The second needs the planned matches and a clear description of the planner;
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
beliefs, uncertain transfer from ordinary-chess trajectories, different
rule/search revisions, and pending formal matches. The papers use different
engine versions and search procedures. Our results do not establish exact
reproduction, human-level play or general strength; subgame diagnostics are
not whole-game exploitability.

Responsible use emphasizes **transparency** through inspectable records,
**accountability** through named contributions and review, and **fair play**
through information boundaries. Any future human matches need participant
consent and clear bot identification. No human study, fairness audit or
real-world social benefit is claimed.

Next, pin the integrated revision, complete the paired batch and audit its
counts and exclusions. Belief-dependent labels and controlled search ablations
can then address questions beyond full-board regression. Retain positive,
negative and inconclusive results.

## 9. Team Contributions and AI Assistance

This allocation reflects the available project records; each member must
confirm their final contribution statement before submission.

| Member(s) | Contribution reflected in current records |
| --- | --- |
| DING Chiyu; PEI Shengxin | Pair A: rules, tracking and search work, with implementation/review responsibilities to confirm individually |
| QUEK Hongqiang Colin | Pair B: evaluators, training/development evaluation, match protocol and worked toy exposition |
| Kuah Jun Hong, Bryan | Pair B: independent cross-checks, scoped reviews and evidence sharing; evaluation-methods and report drafting |
| WANG Zhijian | Evaluation workflow contribution; final batch operation and results to confirm |
| LIN Tzu-Chun | Final role and completed contribution require confirmation; not inferred from proposal membership |

GitHub Copilot assisted Bryan with inspection, probe generation/execution,
artifact checks and this draft. Bryan directed the scope and authorized earlier
sharing; human verification and team approval remain necessary. The proposal
records Claude-assisted drafting. Other members must add their own AI-use
disclosures; this statement does not cover all team work.

## 10. Conclusion

The project provides search and evaluation components with traceable evidence.
Better full-board prediction has not yet established better decisions under
hidden information. Final playing-strength conclusions must come from validated
matches, not regression error, passing tests or historical D1-versus-material wins.

---

## References

1. Zhang BH, Sandholm T. Subgame solving without common knowledge [Internet]. arXiv:2106.06068v2; 2021 Dec 3 [cited 2026 Oct 26]. Available from: [https://arxiv.org/abs/2106.06068v2](https://arxiv.org/abs/2106.06068v2).

2. Zhang BH, Sandholm T. General search techniques without common knowledge for imperfect-information games, and application to superhuman Fog of War chess [Internet]. arXiv:2506.01242v2; 2026 Mar 3 [cited 2026 Oct 26]. Available from: [https://arxiv.org/abs/2506.01242v2](https://arxiv.org/abs/2506.01242v2).

3. CS5446_project contributors. Shared code and integration contract [Internet]. 2026 [cited 2026 Oct 26]. Revision 2af8f1f731a978cd5a5bb1f5d5131b40ae01c72d. Available from: [pinned repository README](https://github.com/Mr-Teal/CS5446_project/blob/2af8f1f731a978cd5a5bb1f5d5131b40ae01c72d/README.md).

4. CS5446_project contributors. Pair A search implementation, specifications and reproduction differences [Internet]. 2026 [cited 2026 Oct 26]. Revision 5f334b1e26de31e5c90d444d3a4222352e5fb3ed. Available from: [pinned Pair A source](https://github.com/Mr-Teal/CS5446_project/tree/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_a_prep).

5. emalcolin, CS5446_project contributors. Pair B: leaf evaluators, Network 1 and its practice data [Internet]. 2026 [cited 2026 Oct 26]. Revision 5f334b1e26de31e5c90d444d3a4222352e5fb3ed; contains links to the underlying checkpoint results and manifests. Available from: [pinned evaluator documentation](https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/README.md).

6. CS5446_project contributors. Match protocol [Internet]. 2026 [cited 2026 Oct 26]. Revision 2af8f1f731a978cd5a5bb1f5d5131b40ae01c72d. Available from: [pinned protocol](https://github.com/Mr-Teal/CS5446_project/blob/2af8f1f731a978cd5a5bb1f5d5131b40ae01c72d/pair_b/docs/match_protocol.md); [protocol discussion, issue 17](https://github.com/Mr-Teal/CS5446_project/issues/17).

7. bryankuah. Evaluation methods and batch validation [Internet]. 2026 Oct 26 [cited 2026 Oct 26]. Draft PR32, revision 005f2426faf2b3a000436a26a7a72bd563c7c79e. Available from: [pinned methods draft](https://github.com/Mr-Teal/CS5446_project/blob/005f2426faf2b3a000436a26a7a72bd563c7c79e/pair_b/docs/evaluation-methods-draft.md).

8. bryankuah. Independent D1-versus-material historical cross-check [Internet]. 2026 [cited 2026 Oct 26]. Publication revision 8735be4cc7e06928db6d12ee2487a08bb86e5ba7; historical run source differs as stated in the text. Available from: [pinned raw artifacts and audit](https://github.com/Mr-Teal/CS5446_project/tree/8735be4cc7e06928db6d12ee2487a08bb86e5ba7/pair_b/experiments/matches/crosscheck-bryan-d1-vs-material-standard-start).

9. emalcolin. How information changes a decision [Internet]. 2026 [cited 2026 Oct 26]. Revision a5c105632e1d990450445b204612d41b5fbc8293. Available from: [pinned worked examples and reference-data links](https://github.com/Mr-Teal/CS5446_project/blob/a5c105632e1d990450445b204612d41b5fbc8293/pair_b/experiments/small_games/information_example.md).

10. bryankuah. PR27 supplemental expansion review [Internet]. 2026 Oct 26 [cited 2026 Oct 26]. Reviewed revision 7b14bbbebb80ba410f0e23127e37263b975c167a. Available from: [review](https://github.com/Mr-Teal/CS5446_project/pull/27#issuecomment-6406920434); [rerunnable evidence, v2](https://github.com/user-attachments/files/33944209/pr27-7b14bbb-review-evidence-v2.zip).

11. bryankuah. PR30 supplemental budget and fallback review [Internet]. 2026 Oct 26 [cited 2026 Oct 26]. Reviewed revision 5f334b1e26de31e5c90d444d3a4222352e5fb3ed. Available from: [review](https://github.com/Mr-Teal/CS5446_project/pull/30#issuecomment-6407182994); [rerunnable evidence and raw results](https://github.com/user-attachments/files/33944559/pr30-5f334b1-review-evidence.zip).

12. Mr-Teal. Unify no-move terminal draws across rules and search [Internet]. PR28; 2026 [cited 2026 Oct 26]. Reviewed revision 21da153c8efdc1ae78dd1fac053c2402e1c7b3c7; not a statement that the formal batch uses this revision. Available from: [rule-update pull request](https://github.com/Mr-Teal/CS5446_project/pull/28).