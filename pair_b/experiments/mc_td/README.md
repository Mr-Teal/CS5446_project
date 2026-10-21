# MC and TD value learning against distillation

The model-free prediction study for the D8 report: the same leaf model (a linear correction inside
tanh, on Network 1's 1,217 inputs) learned three ways, from careful Stockfish (distillation), from
game results (Monte Carlo) and from its own next value (TD(0) and TD(lambda)). `RESULTS.md` has the
setup, results, intervals, caveats and the commands; every number in it is in `results.json`.

The short answer: values learned from outcomes are 2.3 to 2.7 times further from careful
Stockfish than distilled ones (0.185 to 0.217 against 0.079), and TD beats MC on outcome error at
every training size.

## Notes

- The figures (`curve-value-error.png`, `curve-outcome-error.png`) need matplotlib, which the
  repo's venv does not have; `make_figures.py` reads only `results.json`, so any Python with
  matplotlib can redraw them.
- `cache/` is not committed (25 MB): it holds the replayed trajectories, which the first two
  commands in `RESULTS.md` write again from the D2 data in `pair_b/data/`.
- The files were checked against `results.json` when they were copied here: the seven scripts
  match its `scripts_sha256`, and `td-rounds-diagnostic.json` and `alpha-edge-check.json` match
  their recorded SHA-256. For `check-reparam.json` the recorded `sha256` is the d2-check data hash,
  not the file's: `assemble_results.py` merges the check's own `sha256` key over the file hash. The
  file's content equals the block in `results.json`; its own SHA-256 is
  `927ed7c591b3e527b94b0d87b59dde5604bcc6a66552d21a205388a142eb36a2`.
