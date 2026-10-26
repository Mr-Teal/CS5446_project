# Fog-of-War Chess

Presentation Plan and Slide Draft

CS4246/CS5446 | AY2026/27 | 26 October 2026 | For team discussion

**Major revisions expected.** Major changes are likely as implementation,
integration, experiments and team review progress. This is a provisional
starting point, not an agreed final narrative, slide deck or allocation of
speaking roles. Slides, visuals, results, conclusions and timing may need
substantial rewriting. Recheck every claim against the final artifacts before
presenting; pending results must not be treated as established findings.

**Purpose.** Help everyone start building the presentation. Each slide below has
draft wording, a speaker outline and a visual brief. Suggested reviewers are
not assigned presenters or deadlines. The team chooses speakers, a slide tool
and the final narrative. The project report is a separate companion draft.

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
| 10 | Planned playing-strength evaluation | 1:15 |
| 11 | Historical evidence and current status | 1:15 |
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
and checked search components. Formal matches must answer the playing-strength
question. Delivered scope is narrower than the complete-reproduction proposal."

**Visual:** Three questions with status labels: development evidence, offline
context study, formal matches pending. Show a compact paper/project distinction,
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
is not the full exact belief. Source: S3. Suggested reviewer: Pair A.

### Slide 5. Grow Search Without Restarting Its Learning (1:15)

**On slide:** "Preserve solver state while adding depth." "Account for work
and retain a usable result when growth cannot finish."

**Speaker draft:** "The PCFR+ prototype works on information-set trees. New
continuations are prepared before commitment, retaining existing regrets and
strategy accumulators. Checks exercise growth, failure and fallback. They
support selected contracts, not stronger play or full Obscuro reproduction."

**Visual:** A before/after tree with unchanged old nodes and highlighted new
frontiers. Limit verification to a 20-second callout; test counts go in backup.
Note uniform growth, within-search retention rather than full cross-turn
persistence, and cooperative deadlines. Sources: S3, S7. Reviewer: Pair A.

### Slide 6. Swap the Evaluator, Keep the Interface (1:15)

**On slide:** "Material | Stockfish D1/D11 | linear correction | Network 1 |
belief network." "Learned correction still uses D1."

**Speaker draft:** "Material is simple; deeper Stockfish is a more expensive
full-board reference. Network 1 corrects a shallow estimate. The belief model
can combine a board embedding with a weighted context summary. These choices
do not consume equal compute; the existing match path is board-wise."

**Visual:** Common input/output plus a model inset: board embeddings, weighted
belief summary, board-conditioned values. Do not invent architecture layers.
Label whole-belief evaluation offline, distinct from online child evaluation.
Source: S4. Suggested reviewer: Pair B.

---

## Slides 7-9: Measurements and Insights

### Slide 7. Evaluate the Target We Actually Trained On (1:00)

**On slide:** "Teacher: full-board Stockfish D11." "Split/resample by game."
"Development check, not the sealed test set."

**Speaker draft:** "The Network 1 check has 959 games, 3,818 decisions and
94,963 eligible child rows. Whole-game splitting reduces within-game leakage,
not every repeated position. Models were compared on this check set, so it is
development evidence. These labels are not fog-of-war equilibrium targets."

**Visual:** Game-grouped split diagram beside value error, best-move agreement
and value lost. Include development-set and approximate-teacher labels. Keep
overlap counts and split hashes in backup. Source: S4. Reviewer: Pair B.

### Slide 8. Better Predictions Did Not Establish Better Moves (1:30)

**On slide:** "Value error: D1 0.095 -> Network 1 0.076."
"Value-lost difference: -0.0003; 95% interval [-0.0017, +0.0011]."

**Speaker draft:** "Value error falls about 20%, but the move-quality difference
spans zero. Regression can improve many values without changing the ranking
of important actions. The linear correction is a useful simpler baseline.
These results support better prediction, not demonstrated better selection."

**Visual:** Separate panels: a zero-based bar chart of value error
(material 0.336, D1 0.095, linear 0.084, Network 1 0.076), and the reported
Network 1-minus-D1 value-lost difference with its interval and zero line. Lower
is better. Do not invent per-model uncertainty bars from a difference interval.
Value-error difference: -0.019, interval [-0.021, -0.018]. Source: S4.

### Slide 9. Context Sensitivity Is Not Strategic Information Value (1:00)

**On slide:** "Context reduces board error by about 0.0028 across five seeds."
"The labels themselves do not depend on belief."

**Speaker draft:** "The reported checkpoint gives board error 0.074 versus
0.076 without context. Across five seeds the mean reduction is about 0.0028.
Since the labels stay fixed when the surrounding belief changes, this is
consistent with denoising. A strategic claim needs belief-dependent targets."

**Visual:** The same board beside two belief groups, labeled a conceptual diagram,
not a measured experiment. Add the checkpoint comparison in a small table;
do not pool this with slide 8's child-ranking task. Source: S4. Reviewer: Pair B.

---

## Slides 10-12: Evaluation and Takeaways

### Slide 10. Test Playing Strength With Paired Openings (1:15)

**On slide:** "Seven candidates vs D1; 200 games per pairing planned."
"Same opening, colors exchanged." "Score, uncertainty, latency and failures."

**Speaker draft:** "Evaluator-based agents share a one-ply planner, 256 particles
and eight hypotheses; random play is an additional baseline. We average complete
color-pair scores and report exclusions. Outer planning is controlled, not
elapsed time. The 60-second watchdog protects a call, not an entire move."

**Visual:** One opening, two color-swapped games, one pair score. Put 1,400
scheduled games under a conspicuous PLAN label. List source/rules, checkpoints
and engine settings as prerequisites. Source: S5. Suggested reviewers:
evaluation contributors and Pair B.

### Slide 11. Historical Checks Are Not Formal Results (1:15)

**On slide now:** "Historical D1 vs material: 20 wins / 0 draws / 0 losses;
10 color pairs." "Formal seven-way results: pending."

**Speaker draft:** "This historical check supports a bounded, lopsided pairing.
Its score is 1.00 with approximate Wilson interval 0.72-1.00. Bootstrap is
withheld for ten constant pair scores. Per-call engine reset differs from the
proposed per-game policy; this is neither a neural result nor new-batch evidence."

**Visual:** Separate historical and formal-status panels. When validated formal
artifacts arrive, replace the status panel with paired scores/intervals and
latency, identify counts/revision, and rewrite this talk track. Otherwise retain
Pending without predicting outcomes. Do not pool runs. Sources: S5, S6.

### Slide 12. What We Can Conclude (1:15)

**On slide:** "Information structure matters." "Prediction is not playing
strength." "Reproducible components; integrated evaluation next."

**Speaker draft:** "Our current contribution is a documented framework and
case-specific evidence. Better teacher agreement has not established better
decisions under fog. Next are the integrated revision, audited matches and
belief-dependent targets. Transparent limits and information-safe interfaces
support responsible experimentation; they are not performance evidence."

**Visual:** Three takeaways and a short next-step sequence, with contribution
and AI-assistance credit. Do not claim exact reproduction, superhuman play,
a fairness audit or a human study. Close with: "When does better prediction
translate into better decisions?" All speakers should understand this boundary.
Sources: S1, S4-S7.

---

## Team Handoff and Rehearsal

**Confirm ownership.** Pair A can validate slides 1-5; Pair B can validate 6-9;
evaluation contributors can validate 10-11. Bryan can check source links and
claim boundaries. WANG Zhijian can advise on workflow status; this does not
volunteer him to run the batch. LIN Tzu-Chun and all members should choose
contributions and speaking blocks together. Reviewers are not assigned speakers.

**First deliverables.** Claim a block and reviewer in the pull-request discussion,
create its visuals and transfer the wording to the agreed slide tool. For each
block record owner, speaker, source/artifact, reviewer and ready/blocked status.
Agree one deck location and integrator; avoid parallel downloaded copies.
GitHub versions this Word plan but does not provide live Word coauthoring.

**Before rehearsal.** Check rules/source identity, result eligibility, chart
denominators/units/uncertainty, speaker transitions, legibility and attribution.
Use static backups for demos. Cite sources in slide footers and a reference
slide, aligned with the report's final reference-manager bibliography.

**Timing gate.** Rehearse the full talk including handovers; target 14:00 and
stop at 15:00. Each member answers one question outside their block. Record
actual timings before cutting material; confirm the course's final format.

## Q&A and Backups

**Why not Stockfish on the true board?** That is privileged information, allowed
for offline/post-game analysis but not the agent's hidden-information decisions.

**Does the network understand information value?** Not established: D11 labels
are full-board and the online path is board-wise. Explain the required follow-up.

**Why can lower error fail to improve moves?** Regression and action ranking
are different objectives; show slide 8's value-lost interval.

**Did we reproduce Obscuro?** No complete reproduction claim. Keep a mechanism
status table with uniform growth, persistence limits and reviewed revisions.

**Is the comparison fair?** Outer planning is fixed, total compute is not.
Explain paired openings, timing, failures and engine resets.

**Prepare backup assets:** full metric tables; interval and exclusion rules;
search-test evidence; rules/version differences; the coin example; individual
contributions and AI disclosures. These are outside the timed core talk.

---

## Sources and Disclosure

S1. Zhang and Sandholm: [Subgame solving without common knowledge (2021)](https://arxiv.org/abs/2106.06068v2) and [General search techniques without common knowledge (2026)](https://arxiv.org/abs/2506.01242v2). Attribute published performance to the papers, not this project.

S2. Colin's [pinned information examples](https://github.com/Mr-Teal/CS5446_project/blob/a5c105632e1d990450445b204612d41b5fbc8293/pair_b/experiments/small_games/information_example.md); [issue 19 guidance](https://github.com/Mr-Teal/CS5446_project/issues/19#issuecomment-6406533365). Reuse these rather than creating a new experiment.

S3. [Shared contract, main 2af8f1f](https://github.com/Mr-Teal/CS5446_project/blob/2af8f1f731a978cd5a5bb1f5d5131b40ae01c72d/README.md) and [Pair A specifications/source, 5f334b1](https://github.com/Mr-Teal/CS5446_project/tree/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_a_prep). Different snapshots, not one validated final release.

S4. [Pinned evaluator documentation and linked artifacts](https://github.com/Mr-Teal/CS5446_project/blob/5f334b1e26de31e5c90d444d3a4222352e5fb3ed/pair_b/README.md). Plot the recorded values; distinguish development checks, offline beliefs, sealed tests and gameplay.

S5. [Methods draft, PR32](https://github.com/Mr-Teal/CS5446_project/blob/005f2426faf2b3a000436a26a7a72bd563c7c79e/pair_b/docs/evaluation-methods-draft.md) and [batch discussion, issue 17](https://github.com/Mr-Teal/CS5446_project/issues/17). Recheck current decisions/artifacts before changing plans into results.

S6. [Historical artifacts, PR31](https://github.com/Mr-Teal/CS5446_project/tree/8735be4cc7e06928db6d12ee2487a08bb86e5ba7/pair_b/experiments/matches/crosscheck-bryan-d1-vs-material-standard-start). Historical source: 3afc5945dfa5a98e5a90275782b8658b69bb9bcf; do not pool with the proposed batch.

S7. [PR27 review/evidence](https://github.com/Mr-Teal/CS5446_project/pull/27#issuecomment-6406920434); [PR30 review/evidence](https://github.com/Mr-Teal/CS5446_project/pull/30#issuecomment-6407182994). Heads: 7b14bbbebb80ba410f0e23127e37263b975c167a and 5f334b1e26de31e5c90d444d3a4222352e5fb3ed. Suites overlap; neither includes the separate PR28 rule update.

**Guidelines:** NUS School of Computing, CS4246/5446 Project Guidelines (Draft),
issued 26 August 2026, pages 1, 3 and 5. The report-deadline year conflicts with
the academic-year heading; confirm on Canvas rather than infer a correction.

**AI assistance:** GitHub Copilot prepared this outline, wording, visual briefs
and checks from available evidence under Bryan's direction. It is not yet
team-approved. Members must verify claims, create/review visuals, add their
own contribution and AI-use disclosures, and rehearse. No new games, training
or experiments were run. Major revisions to both this plan and the report
are expected as more work and results become available.