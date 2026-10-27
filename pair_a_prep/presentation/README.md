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
| `slide5-clock-backup.svg` | Recorded clock/purification table; optional backup for slide 5 |

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
It overwrites `index.html`, both main SVGs and evidence; when both clock JSON
artifacts are available, it also generates `slide5-clock-backup.svg`,
so edit the generator rather than hand-editing those generated files. Speaker
notes and this README are maintained separately.

The two selected hypotheses have the same White evidence, but are not the
full belief population. The growth visual uses a zero heuristic to illustrate
structure; no playing-strength inference is possible. Only one sampled root
is shown and its chance parent is omitted. One history leaf grows while the
other two retain estimates. Later expanded occurrences of the same information
set share its existing policy.

The updated slide 5 shows 3 frontiers becoming 5, not whole-cut growth to 9.
See [the implementation and measured work](../docs/one_sided_search.md) and
`../results/one_sided_reference.json` for the separate Material smoke. The
visual uses a zero heuristic; do not present its nodes as Material match data.

Expansion audit: [mechanism and implementation comparison](../docs/expansion_mechanism_audit.md).

Clock backup: [matrix, submission guard and recorded limitations](../docs/clock_purification_ablation.md).
It adds a backup page, not a new agreed speaking assignment or final team deck.
