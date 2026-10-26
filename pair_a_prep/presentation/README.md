# Pair A slide material pack

Open **`index.html` in a browser**. It is completely local and needs no server,
IP address or dependencies for viewing. It displays draft slides 4 and 5 and
links to the SVGs, speaker notes and machine-readable evidence.

| File | Use |
|---|---|
| `slide4.svg` | 1600x900 vector slide: referee boundary, pipeline and replay-checked hidden hypotheses |
| `slide5.svg` | 1600x900 vector slide: actual small-tree growth with solver state retention |
| `speaker_notes.md` | 75-second scripts, transitions, backup answers and sources |
| `evidence.json` | Candidate paths/FENs, shared observation and growth assertions |

Insert the SVGs into the team's slide software as graphics; keep the text in
the speaker notes if rebuilding them as native slide objects. This pack is
initial content/visuals, not an agreed presentation deck or speaking assignment.

Regenerate deterministic SVG/evidence assets from the repository root:

```powershell
.\pair_b\.venv\Scripts\python.exe -m pair_a_prep.presentation_materials
```

The generator uses the existing chess/solver dependencies. It checks both
complete private histories, replays the hypotheses with the search validator,
and confirms the old minimizers/regrets/averages survive a real expansion.
It overwrites its four generated files (`index.html`, both SVGs, evidence),
so edit the generator rather than hand-editing those generated files. Speaker
notes and this README are maintained separately.

The two selected hypotheses have the same White evidence, but are not the
full belief population. The growth visual uses a zero heuristic to illustrate
structure; no playing-strength inference is possible. Only one sampled root
is shown and its chance parent is omitted. Black's three expanded occurrences
share a policy, rather than becoming three separate information sets.

Expansion audit: [mechanism and implementation comparison](../docs/expansion_mechanism_audit.md).
