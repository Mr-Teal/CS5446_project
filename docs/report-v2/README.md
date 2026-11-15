# Report v2 (15 Nov 2026)

Two versions of the same report text, 12-pt body, A4 with 1-inch margins, title page first:

- `report-before-ta-note.html` / `.pdf`: every label inside the figures is at least 12 pt (figures `*_12.svg`).
- `report-small-figs.html` / `.pdf`: the same text with the earlier, more detailed figures (labels about 5-8 pt).

Yellow highlights are placeholders still to fill (belief-state PPO). The team's contribution and AI-use statement is
not written yet (Section 10).

Figures: `gen_figs_12pt.py` draws the `*_12.svg` set; `gen_state_figure.py`, `gen_tracking_figure.py` and
`gen_actions_figure.py` draw the detailed set. Their data (`*.json`) came from the scripts `qa4_*.py` and `tracking_*.py`,
run on the team's rules adapter, tracker and the policy checkpoint `policy-conv-fuzzy-r2-s2`.
To rebuild a PDF: open the HTML in Chrome and print to PDF (A4, no headers), or
`chrome --headless --print-to-pdf=report.pdf report.html`.
