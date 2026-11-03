# Fog of War Chess

Presentation Plan and Slide Draft

CS4246/CS5446 | AY2026/27 | 3 November 2026 | Living draft for team discussion

**Major revisions expected.** Major changes are likely as implementation,
integration, experiments and team review progress. This is a provisional
starting point, not an agreed final narrative, slide deck or allocation of
speaking roles. Slides, visuals, results, conclusions and timing may need
substantial rewriting. Recheck every claim against the final artifacts before
presenting; pending results must not be treated as established findings.

**Living-draft workflow.** This plan and the editable PowerPoint are a current
working version, not a finished presentation. After a relevant result, code
integration or contributor update, revise the affected claim and source here,
then regenerate/review the deck and PDF together. Preserve archived experiment
identities; a new code merge does not retrospectively change an old result.
Keep speakers unassigned until the team agrees, and record actual rehearsal
times rather than calling the planned timings verified.

**Purpose.** Help everyone start building the presentation. Each slide below has
draft wording, a speaker outline and a visual brief. Suggested reviewers are
not assigned presenters or deadlines. The team chooses speakers, a slide tool
and the final narrative. The project report is a separate companion draft.

**Presentation-first pass, 3 November.** Slides 6-11 now have shorter slide
wording, a spoken explanation, a transition and a Q&A prompt. Read the "Say"
and "Transition" sections aloud; the supporting detail is not a script to
recite. The numbers and experiment identities are unchanged. Speakers must
adapt the wording to their own voice and verify explanations before rehearsal.

**Course format.** The guidelines specify approximately 15 minutes plus 5 minutes
Q&A, subject to change, in the week of 10 November 2026. A recording may be
required. The audience knows AI but not necessarily this topic. Assessment
emphasizes organization, clarity, timing and answers. Confirm the final slot
on Canvas; the report's page/font rules are not slide-count requirements.

## Run of Show

| Slide | Topic | Duration |
| --- | --- | --- |
| 1 | The decision problem | 0:45 |
| 2 | Why information changes a strategy | 1:15 |
| 3 | Questions and project scope | 1:00 |
| 4 | Information-safe architecture | 1:15 |
| 5 | Search and bounded verification | 1:15 |
| 6 | Interchangeable evaluators | 1:15 |
| 7 | Data and measurement design | 1:00 |
| 8 | Better values versus better moves | 1:30 |
| 9 | What belief context shows | 1:00 |
| 10 | Paired playing-strength evaluation | 1:15 |
| 11 | Completed batch and interpretation | 1:15 |
| 12 | Conclusions and next steps | 1:15 |

**Total:** 14:00 core content including handovers, plus 1:00 contingency buffer
for a 15:00 slot. Q&A has its own 5:00. If running late, cut secondary metrics
and the optional coin example, not the final limitations.

---

## Slides 1-3: Problem and Scope

### Slide 1. Deciding Without Seeing the Board (0:45)

**On slide:** "Fog-of-War Chess: search and learned evaluation under hidden
information." "What should an agent do when it cannot see the board?"

**Speaker draft:** "Ordinary chess asks us to calculate from a known position.
Here we also reason about hidden pieces and what the opponent knows. We separate
search from frontier evaluation so we can inspect implementation behavior and
decision quality independently."

**Visual:** The player's visible board beside two consistent hypotheses. Pair A
should select a fixture that really admits both hypotheses and the same legal
feedback. Label the player perspective; do not invent a board or present a
referee view as agent-visible. Use a static image, not a live-engine dependency.
Sources: S1, S3.

### Slide 2. One Information Set, One Decision Rule (1:15)

**On slide:** "Hidden: one response rule, value 0." "Revealed to the opponent:
conditional responses, value -1." Values are for player 0.

**Speaker draft:** "Player 0 chooses H or T; a match pays it +1, otherwise -1.
If player 1 cannot see the choice, both mix equally. Once player 1 sees it,
player 1 can always mismatch. It matters who receives the information."

**Visual:** Reveal the two histories, connect the hidden decisions with one
information-set outline, then separate the revealed decisions. Optional backup:
the coin guesser improves from expected payoff 0.5 to 1 when it sees the coin;
heads probability is 0.75 and payoffs are +1/-1. Do not call 0.5 a success
probability or interpret these values as chess strength. Source: S2.

### Slide 3. Three Questions, Different Evidence (1:00)

**On slide:** "RQ1: better prediction and ranking?" "RQ2: useful belief
context?" "RQ3: stronger play under a fixed planner?"

**Speaker draft:** "Published methods motivate the design, but their performance
is not our result. We have development measurements, a limited context study
and checked search components. The completed fixed-planner batch gives bounded
playing evidence; it does not establish Network 1 or linear gains over D1. Delivered scope is narrower than the complete-reproduction proposal."

**Visual:** Three questions with status labels: development evidence, offline
context study, archived fixed-planner matches. Show a compact paper/project distinction,
not a list of pull requests. Sources: S1, S3-S5. Suggested reviewers: Pair A
and Pair B; the team should agree opening speakers.

---

## Slides 4-6: What We Built

### Slide 4. Hidden State Stays Behind the Referee (1:15)

**On slide:** "Referee -> observation -> belief tracker -> decision."
"The agent never receives the referee's true board."

**Speaker draft:** "The referee owns the actual position. Each player gets its
own observations and legal moves. Tracking produces weighted hypotheses for
the decision procedure. Identical boards can have different knowledge or
repetition histories, so FEN is not a complete information state."

**Visual:** A pipeline with a private-state boundary and evaluator branch.
Show offline labels and post-game diagnostics as separate paths. Distinguish
Pair A's history tracker from the 256-particle match configuration; the latter
is not the full exact belief. Source: S3. Teal has volunteered review, content
and a replay-validated pair of hypotheses with the same private evidence.

### Slide 5. Grow Search Without Restarting Its Learning (1:15)

**On slide:** "Preserve solver state while adding depth." "Account for work
and retain a usable result when growth cannot finish."

**Speaker draft:** "The PCFR+ prototype works on information-set trees. New
continuations are prepared before commitment, retaining existing regrets and
strategy accumulators. Checks exercise growth, failure and fallback. They
support selected contracts, not stronger play or full Obscuro reproduction."

**Visual:** A before/after tree with unchanged old nodes and highlighted new
frontiers. Limit verification to a 20-second callout; test counts go in backup.
Distinguish the historical uniform-growth prototype from the later selective,
retained-search, gadget and purification stack. Keep the visible status line
simple: "Tracker fixes merged; full-game comparison still pending."
Put revision and test details in the notes: Teal merged PR59 at 78f687b,
including PR62/60, into main as 1492781 on 3 November. Teal reports
962 locked shared/Pair A passes and 46 Pair C passes in a separate torch-enabled
environment. Bryan's 48-test check and evidence attachment are complementary,
not additive coverage. The earlier strict ply-9 and relaxed ply-11 failures
remain historical evidence under their original limits. In unmerged PR64,
Teal reports that an optional 16-second tracker-update policy with no logical
memory cap passes those points: seed17 ends by king capture at ply39, but
seed18 fails at Black ply13 on time. There is still no complete pair or
full-agent strength result. This is a different configuration, not a correction
of the old measurements; its archive has not been independently audited for
this presentation pass. Sources: S3, S7, S10. Teal has volunteered
content and a retained-state growth visual; speaking allocation remains open.
Use S9 for review details in backup, outside the timed explanation.

### Slide 6. Where Search Stops, an Evaluator Takes Over (1:15)

**Takeaway:** The evaluator estimates a position's value when search stops.

**On slide:** A compact evaluator table: material; quick/careful Stockfish;
linear correction; Network 1; belief network. "Same interface, different cost;
learned corrections still use D1."

**Say:** "Search cannot look all the way to the end of a game. When it stops,
it needs an estimate of how good the position is. That is the leaf evaluator.
We compare several choices through the same interface. Material just counts
pieces. Quick Stockfish searches to depth one; careful Stockfish searches to
depth eleven and supplies our training targets. The linear model and Network 1
learn a correction to the quick estimate. The belief network can also use a
weighted group of possible boards. But its teacher still labels each board
separately. One cost matters throughout these comparisons: the learned
corrections still need quick Stockfish, so the network adds work rather than
replacing that engine call."

**Transition:** "First, we checked whether learning a correction actually
improved those estimates."

**Point to:** Quick/careful Stockfish first, then the correction rows.
Do not read every table cell aloud.

**If asked - is this a replacement for Stockfish?** No. The correction uses
D1 as an input. Whole-belief evaluation is an offline capability; the archived
match runner calls the belief model board by board. Source: S4.
Suggested technical check: Pair B, not an assigned speaking role.

---

## Slides 7-9: Measurements and Insights

### Slide 7. Can We Learn to Copy Deeper Stockfish? (1:00)

**Takeaway:** We test agreement with a full-board teacher, not optimal play
under hidden information.

**On slide:** "Split by game -> learn D11 values -> check values and moves."
"959 check games; 3,818 decisions; 94,963 eligible children."
"Development check, not the sealed test."

**Say:** "The training target is careful Stockfish's value of a complete board.
It is not the value of what a fog-of-war player knows. We split practice data
by whole game, so positions from one game stay together. A separate check set
contains 959 games and just over 3,800 decisions. We ask two questions:
how close are the predicted values, and do they lead us to the teacher's
preferred moves? We also used this check set to choose a Network 1 run.
That makes these development results, not a final result on the sealed test set."

**Transition:** "The two measurements gave us different answers."

**Point to:** The training target, then the two checks. Exact child counts
are available on the slide; they need not be recited.

**If asked - does splitting by game remove all leakage?** It prevents one
game crossing splits, not every repeated position. Intervals resample whole
games because positions within a game are correlated. Practice-data splits
are 80% train, 10% validation and 10% sealed test; the 959-game check is separate.
Source: S4. Suggested technical check: Pair B.

### Slide 8. Better Values Did Not Establish Better Moves (1:30)

**Takeaway:** Lower prediction error did not establish better move selection.

**On slide:** "Value error: D1 0.095 -> Network 1 0.076."
"Value-lost difference: -0.0003; 95% interval [-0.0017, +0.0011]."

**Say:** "On the left, lower bars mean closer agreement with careful Stockfish.
Network 1 reduces value error from 0.095 to 0.076, about twenty percent.
The simple linear correction also helps. But a player needs to choose a move,
not just predict a number. On the right, value lost measures how much the
teacher prefers its own best move to the move our evaluator chooses. Network 1's
change relative to quick Stockfish is tiny, and the interval crosses zero.
So this check does not establish better move selection. It also does not prove
the models are equal. Our further analysis found that the learned models gained
on more decided positions, but were worse on close positions, where a small
ranking error can change the chosen move."

**Transition:** "We also tested whether giving a network more belief context
would help."

**Point to:** D1 and Network 1 bars, pause, then the interval on the right.

**If asked - why can lower error fail to help?** Value regression and
ranking sibling moves are different objectives. Improving many values does
not guarantee the best move is ranked first.

**Interpretation guard.** An interval containing zero does not establish a tie
or equivalence. The report's band analysis shows gains concentrated in more
decided positions, with all learned variants worse than D1 on close positions.
Use the regenerated Figure 1 or a native chart from the same pinned JSON;
do not invent new measurements. The MC/TD comparison belongs in backup, with
its different training and outcome-evaluation populations stated explicitly.

**Visual:** Separate panels: a zero-based bar chart of value error
(material 0.336, D1 0.095, linear 0.084, Network 1 0.076), and the reported
Network 1-minus-D1 value-lost difference as a numeric interval. Explain that it
includes zero. Lower is better. Do not invent per-model uncertainty bars from a difference interval.
Value-error difference: -0.019, interval [-0.021, -0.018]. Source: S4.

### Slide 9. Context Helps Prediction, Not a Strategy Claim (1:00)

**Takeaway:** Context improves this prediction task, but does not establish
the strategic value of information.

**On slide:** "Context reduces board error by about 0.0028 across five seeds."
"The labels themselves do not depend on belief."

**Say:** "Here the network can use other possible boards as context when it
values one board. Across five seeds, mean error falls from 0.0762 without
context to 0.0734 with it. Every seed improves. However, the target for that
board is still the same Stockfish value, whatever the surrounding belief.
The network may be using context to make a cleaner prediction; this does not
show that it understands the strategic value of information. To test that,
we would need targets that change with what a player knows. This is a
different offline check from the move-ranking experiment on the previous slide."

**Transition:** "Prediction tests are useful, but we also wanted to see what
happened in actual games."

**Point to:** The with/without-context rows, then the fixed-target limitation.
The table shows the five-seed means; no uncertainty interval is invented.

**If asked - does the match result test this context benefit?** No. The
archived match runner uses the model one board at a time, so its belief-network
row does not test whole-belief evaluation. Source: S4.
Suggested technical check: Pair B.

---

## Slides 10-12: Evaluation and Takeaways

### Slide 10. Play Each Opening Twice, Swapping Colours (1:15)

**Takeaway:** Paired openings make the comparison more controlled, but the
evaluators still take different amounts of time.

**On slide:** One opening, two colour-swapped games, one pair score.
"1,400 attempted; 1,399 finished; 699 complete pairs."
"Same one-ply planner, not equal thinking time. Each row plays against D1."

**Say:** "For the game comparison, the evaluator-based agents use the same
simple one-ply planner; we change the evaluator, not the outer search.
Each plays against quick Stockfish inside that planner. Random play is an
additional control. We play each opening twice with colours swapped and
average the two scores. A win is one, a draw half and a loss zero.
There are seven separate comparisons, not a tournament ranking. Of 1,400
scheduled games, 1,399 finished, leaving 699 complete pairs. The failed game's
partner is excluded from paired scores, but retained in the finished-game
counts. Finally, identical outer planning does not mean equal thinking time:
the evaluators have very different costs. This is our evaluator comparison,
not a full-agent test of the deeper search."

**Transition:** "Read the next plot against the 0.5 line, and keep those costs
in mind."

**Point to:** Follow the opening into both games before introducing the
aggregate counts.

**If asked - what was fixed?** The evaluator-based agents use 256 particles
and evaluate moves on eight hypotheses. Random play is a separate baseline.
The 60-second watchdog bounds an individual call, not a whole move.

**Visual:** One opening, two color-swapped games, one pair score. State:
1,400 attempted; 1,399 finished; 699 complete pairs across seven separate
comparisons. Colin ran all rows on his M5 Pro at a5c5fb6, pre-rule, stand-in,
26–27 October. Bryan audited the archives, not a rerun. Keep counts
and unequal compute visible; retain engine policy in the notes. Source: S5, S8. Suggested reviewers:
evaluation contributors and Pair B.

### Slide 11. No Clear Playing Gain for Network 1 or Linear (1:15)

**Takeaway:** The archived matches do not establish a gain for Network 1
or linear correction over D1; compute costs differ.

**On slide:** "Score vs D1: linear 0.513; Network 1 0.515; belief 0.563;
D11 0.585." "Intervals and compute cost limit the conclusions."

**Say:** "The vertical line is a score of 0.5: equal points against the
quick-Stockfish opponent. Focus first on the linear and Network 1 rows.
Their scores are close to that line, and both intervals cross it.
This batch therefore does not establish a playing gain for either model.
The belief network scores higher, but its interval still includes 0.5.
Careful Stockfish looks promising, although the conclusion is sensitive to
the interval method and multiple comparisons. Now look at cost:
Network 1 takes about three times the baseline's median move time,
and careful Stockfish about two hundred and twenty times. These are
separate comparisons with D1, not a ranking of the models or an equal-time test."

**Transition:** "The main lesson is that better value prediction has not yet
translated into a demonstrated playing gain for Network 1 or linear correction."

**Point to:** The 0.5 line, the two bold rows, then their move times.
Do not read all seven rows aloud.

**If asked - why not claim a D11 win?** Its bootstrap interval excludes 0.5,
but its Wilson interval includes it, and a seven-row multiplicity correction
would remove the apparent result. An interval crossing the reference does
not establish equivalence.

**Visual:** Plot all seven paired scores with the archived bootstrap intervals;
random uses Wilson with a different marker. Include a 0.5 reference line.
Show median decision costs: D1 11.1 ms, Network 1 36.1, belief 149.8,
D11 2452.2. State 99 pairs for random, 100 elsewhere. W/D/L counts every
finished game; the failed random game's partner is excluded only from pairing.
Two linear and four D11 draws are 200-ply caps. No no-move failures occurred,
but the source predates both the no-move and EP repetition updates and is
never pooled with later runs. The table uses half-up rounding (S5). Keep historical
20-game D1/material checks separate in backup. Sources: S5, S6, S8.

### Slide 12. What We Can Conclude (1:15)

**On slide:** "Information structure matters." "Prediction is not playing
strength." "Audited batch; integrated search evaluation next."

**Speaker draft:** "Our current contribution is a documented framework and
case-specific evidence. Better teacher agreement has not established better
decisions under fog in the tested planner. The tracker/solver integration is
now on main. Next are successful full-game pilots, belief-dependent targets and
appropriate search ablations. Until then, the full-agent comparison is pending,
not a completed negative result. Transparent limits and information-safe interfaces
support responsible experimentation; they are not performance evidence."

**Visual:** Three takeaways and a short next-step sequence, with contribution
and AI-assistance credit. Do not claim exact reproduction, superhuman play,
a fairness audit or a human study. Close with: "When does better prediction
translate into better decisions?" All speakers should understand this boundary.
Sources: S1, S4-S7, S10.

---

## Team Handoff and Rehearsal

**Confirmed content ownership.** Teal has volunteered rules/shared-state/search
review and initial content/visuals for slides 4-5: replay-validated hypotheses
sharing private evidence, and before/after growth retaining solver state.
These illustrate implementation, not strength gains. Speakers and deck location
remain undecided. Pair B review of 6-9 and evaluation review of 10-11 are proposals.
Colin ran the Pair B batch at Zhijian's request (#17, results in #38).
LIN Tzu-Chun's role remains open.

**Contribution credits.** Teal reports rules/referee/private observations,
PCFR+/Resolve/Maxmargin prototypes, chess-history/gadget integration, pilots,
within-turn growth/budget integration and supporting tests/docs/visualizers,
with Codex assistance. Shengxin's belief-tracker/ZS21 work is reported by Teal;
ask Shengxin to confirm wording and completion. Explicitly credit Bryan's PR21
state-preserving toy expansion API, which the later chess/gadget work builds on,
and his linear baseline (#8), historical cross-check and independent batch audit.
Credit Colin's evaluators/data/training, bot/tracker/runner, protocol/batch, Fog Lab,
worked example and reviews; Colin's individual AI-use statement is still pending.

**Working artifacts.** Keep this Markdown plan, its Word copy, the editable
PowerPoint and its PDF preview together in `docs/drafts/`. The slide deck is a
reviewable starting point, not an agreed speaking allocation or a rehearsed
talk. For each block record owner, speaker, source/artifact, reviewer and the
next update needed. GitHub versions these artifacts but does not provide live
Office coauthoring; reconcile teammate edits before regenerating binaries.

**Update queue.** Search contributors: verify the current mechanism status and
replace conceptual diagrams with replay-validated examples when available.
Pair B: refresh affected slides only when new evaluator evidence is committed.
Evaluation contributors: add full-agent comparisons only after successful
pilots and a separately recorded batch. All members: confirm their own
contribution/AI wording and speaking role. These are review needs, not newly
assigned deadlines or claims that anyone has completed them.

**Before rehearsal.** Check rules/source identity, result eligibility, chart
denominators/units/uncertainty, speaker transitions, legibility and attribution.
Use static backups for demos. Cite sources in slide footers and a reference
slide, aligned with the report's final reference-manager bibliography.

**Timing gate.** Rehearse the full talk including handovers; target 14:00 and
stop at 15:00. Each member answers one question outside their block. Record
actual timings before cutting material; confirm the course's final format.

**Focused rehearsal: slides 6-11.** This block has 7:15 of the existing
14-minute core allocation. Include chart-pointing pauses and transitions;
word counts are not a substitute for a timed rehearsal. First read only the
"Say" and "Transition" passages, then repeat using just the takeaway and visual.
If over time, cut secondary counts from speech, not the result's meaning or
its key limitation.

| Slide | Speaker | Actual time | Next adjustment |
| --- | --- | --- | --- |
| 6 | Unassigned | Not measured | Confirm evaluator explanation |
| 7 | Unassigned | Not measured | Explain development-set selection |
| 8 | Unassigned | Not measured | Pause between prediction and move-quality results |
| 9 | Unassigned | Not measured | Explain why fixed labels limit the claim |
| 10 | Unassigned | Not measured | Walk through one colour pair |
| 11 | Unassigned | Not measured | Explain the reference line and costs |

Suggested targeted check for Colin: confirm the evaluator descriptions and
interpretation on slides 6-11, rather than rewriting the block from scratch.
He still needs to confirm his own contribution/AI-use wording and speaking
availability. These are requests for team agreement, not assigned roles.

## Q&A and Backups

**Why not Stockfish on the true board?** That is privileged information, allowed
for offline/post-game analysis but not the agent's hidden-information decisions.

**Does the network understand information value?** Not established: D11 labels
are full-board and the online path is board-wise. Explain the required follow-up.

**Why can lower error fail to improve moves?** Regression and action ranking
are different objectives; show slide 8's value-lost interval.

**Did we reproduce Obscuro?** No complete reproduction claim. Distinguish the
historical uniform-growth baseline, the later merged search mechanisms and
PR59's combined tracker/solver work, merged into main at 1492781. Pin any mechanism-completeness
claim to an inspected revision; prototype verification does not establish
strength or formal-match readiness.

**Is the comparison fair?** Outer planning is fixed, total compute is not.
Explain paired openings, timing, failures and engine resets.

**Prepare backup assets:** full metric tables; interval and exclusion rules;
search-test evidence (S9); rules/version differences; the coin example; individual
contributions and AI disclosures. These are outside the timed core talk.

---

## Sources and Disclosure

S1. Zhang and Sandholm: [Subgame solving without common knowledge (2021)](https://arxiv.org/abs/2106.06068v2) and [General search techniques without common knowledge (2026)](https://arxiv.org/abs/2506.01242v2). Attribute published performance to the papers, not this project.

S2. Colin's [pinned information examples](https://github.com/Mr-Teal/CS5446_project/blob/a5c105632e1d990450445b204612d41b5fbc8293/pair_b/experiments/small_games/information_example.md); [issue 19 guidance](https://github.com/Mr-Teal/CS5446_project/issues/19#issuecomment-6406533365). Reuse these rather than creating a new experiment.

S3. [Shared contract, main 2af8f1f](https://github.com/Mr-Teal/CS5446_project/blob/2af8f1f731a978cd5a5bb1f5d5131b40ae01c72d/README.md) and [Pair A specifications/source, 5f334b1](https://github.com/Mr-Teal/CS5446_project/tree/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_a_prep). Different snapshots, not one validated final release.

Use the [pinned mechanism checklist](https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_a_prep/docs/obscuro_status.md) for detailed implemented/missing distinctions; only the main boundaries belong in the talk. Teal's [content/contribution confirmation](https://github.com/Mr-Teal/CS5446_project/pull/33#issuecomment-6408509322) is not final-source validation or a speaking allocation.

S4. [Pinned evaluator documentation and linked artifacts](https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/README.md). Plot the recorded values; distinguish development checks, offline beliefs, sealed tests and gameplay.

S5. [Merged methods, PR50](https://github.com/Mr-Teal/CS5446_project/blob/7c292af5881b8c81e4ffccb7300de21650c9c0ad/pair_b/docs/evaluation-methods-draft.md) and [batch discussion, issue 17](https://github.com/Mr-Teal/CS5446_project/issues/17). PR38 merged on 28 October; PR50 merged on 2 November. Preserve the batch's pre-rule execution source rather than treating either publication date as a new run.

S6. [Historical artifacts, PR31](https://github.com/Mr-Teal/CS5446_project/tree/8735be4cc7e06928db6d12ee2487a08bb86e5ba7/pair_b/experiments/matches/crosscheck-bryan-d1-vs-material-standard-start). Historical source: 3afc5945dfa5a98e5a90275782b8658b69bb9bcf; do not pool with the archived seven-row batch.

S7. [PR27 review/evidence](https://github.com/Mr-Teal/CS5446_project/pull/27#issuecomment-6406920434); [PR30 review/evidence](https://github.com/Mr-Teal/CS5446_project/pull/30#issuecomment-6407182994). Heads: 7b14bbbebb80ba410f0e23127e37263b975c167a and 5f334b1e26de31e5c90d444d3a4222352e5fb3ed. Suites overlap; neither includes the separate PR28 rule update.

**Guidelines:** NUS School of Computing, CS4246/5446 Project Guidelines (Draft),
issued 26 August 2026, pages 1, 3 and 5. The report-deadline year conflicts with
the academic-year heading; confirm on Canvas rather than infer a correction.

**AI assistance:** GitHub Copilot prepared the earlier outline, wording, visual
briefs and checks under Bryan's direction, and assisted this presentation-only
clarity pass. Codex assisted earlier revisions and
the independent batch archive audit and scoped search reviews. It is not yet
team-approved. Members must verify claims, create/review visuals, add their
own contribution and AI-use disclosures, and rehearse. This revision adds no
new training or formal matches; S9 records the separately completed review probes. Major revisions to both this plan and the report
are expected as more work and results become available.

S8. [Reviewed batch, PR38 at 5e9393a](https://github.com/Mr-Teal/CS5446_project/tree/5e9393ab8537088e8ea6542ce21e11f42218ee15/pair_b/experiments/matches/batch-2026-10-27). Execution source a5c5fb6; paired scores and intervals, failures, timing and capped-draw notes. The later search stack is separate from this archived batch. [ZS21/shared EP delivery](https://github.com/Mr-Teal/CS5446_project/pull/37) merged at 04f992d. Main at this presentation pass is [1492781](https://github.com/Mr-Teal/CS5446_project/tree/149278181ed6d2b52dce31991fb311a2a74339d0).

S10. Tracker fixes merged; full-game comparison still pending. [Teal merged PR59 into main at 1492781 on 3 November](https://github.com/Mr-Teal/CS5446_project/pull/59#event-34991912798). Its integrated head 78f687b860a3fb95160b80be472d7fc8621a144b includes PR62/60 and the resolved runner conflict. [Teal's validation report](https://github.com/Mr-Teal/CS5446_project/pull/59#issuecomment-6593444508) and [Bryan's complementary evidence handoff](https://github.com/Mr-Teal/CS5446_project/pull/59#issuecomment-6595644283) were checked 3 November. Teal reports the native tracker built/loaded with locked Pixi and GCC 16.2.0: 962 shared/Pair A passes, zero skips; 46 Pair C passes separately in a torch-enabled environment. The locked ZS21 environment initially had 44 passes/2 torch-related failures, and combining the suites fails collection because both contain test_provenance.py. Pair A owns the [open documentation follow-up, PR63](https://github.com/Mr-Teal/CS5446_project/pull/63), at ba268d0fa05a6ed587bc183eaff14eb1aba849f1, now targeting main, covering separate invocations and the torch requirement; this adds no runtime results. His eight Stockfish 19 actions were capped/unscored, not a full-game validation. His detailed outputs remain local; these are attributed results, not independently rerun here. Bryan's separate check passed 48 selected ZS21 tests, zero skips, verified 66 runtime assets and returned unfinished_smoke after two Stockfish 13 actions. It used Python 3.12.10 rather than locked 3.12.15 and the shipped ZS21 library, not the separate shared-tracker accelerator. The [sanitized evidence ZIP](https://github.com/user-attachments/files/34303279/pr59-78f687b-native-lp-handoff.zip) records that scope. The [earlier 176-pass/16-skip check](https://github.com/Mr-Teal/CS5446_project/pull/59#issuecomment-6571745962) remains historical; do not add overlapping counts. Bryan's checks are author-assisted validation, not independent review of his own resolution. The merge itself is neither additional independent review nor new full-game evidence. The [strict ply-9/relaxed ply-11 pilot failures](https://github.com/Mr-Teal/CS5446_project/pull/62#pullrequestreview-5731608636) describe earlier configurations. New, unmerged [PR64](https://github.com/Mr-Teal/CS5446_project/pull/64) reports a different optional 16-second tracker-update policy without a logical memory cap: see its [pinned pilot record at 2870479](https://github.com/Mr-Teal/CS5446_project/blob/28704798af81e140aec43c9215ab5b1daae8ff12/pair_a_prep/results/unlimited_tracker_pilot_2026-11-03/README.md), measured runtime 0426f73d6c96a58617c320c3796e83f04e56796e. Teal reports that the old points pass; seed17 ends by king capture at ply39, but seed18 fails at Black ply13 after about 16.072 seconds. There is no complete pair. These are attributed pilot results, not an independent archive audit or rerun for this presentation pass. The cap is per update and cooperative, not a whole-action deadline; removing a logical cap does not bound process memory. Whole-turn budget agreement and successful full-game validation remain open. No formal-match readiness or strength claim. Recheck live status before presenting.

S9. Scoped reviews on 28 October: [PR42 at 2568818](https://github.com/Mr-Teal/CS5446_project/pull/42#pullrequestreview-5679229932), [PR52 at 5e74ede](https://github.com/Mr-Teal/CS5446_project/pull/52#pullrequestreview-5679231586), [PR46 at ee42c8f](https://github.com/Mr-Teal/CS5446_project/pull/46#pullrequestreview-5679261471), and [PR48 at 879818c](https://github.com/Mr-Teal/CS5446_project/pull/48#pullrequestreview-5679267479). For backup: PR52 had 185 selected tests, six detected defect mutations and four additional Black-perspective value probes; PR46 had 42 selected tests within its functional scope; PR48 had 33 selected tests, two verified 100-entry source manifests, a portable clock link and a gift-probe rerun matching non-timing fields. Counts overlap across heads and must not be summed. No new clock matrix or formal match batch was run. Projected labels remain disabled; the ledger does not transfer ancestor payments numerically. Scoped approval is not final integration approval, a timing guarantee or strength evidence.
