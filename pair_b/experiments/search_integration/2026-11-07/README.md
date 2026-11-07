# Learned-search integration smoke, 7 November 2026

Two production Pair C attempts completed with zero failures, four plies each,
and eight recorded legal actions. Both were capped and unscored. This is not a
strength comparison or full-game readiness result.

The existing Network 1 checkpoint was loaded on CPU into Pair A's fixed depth-2
search; the control used the same search with a depth-1 Stockfish leaf. Both
sides used the same engine executable, exact tracker, solver settings and
public pawn fixture. Colours alternated with seeds 17 and 18. The copied INI,
raw `games.jsonl` and runner `summary.json` are retained unchanged.

`environment.json` retains versions, actual engine/checkpoint hashes and hashes
of the accompanying changed source files. Local executable paths are replaced
by a placeholder; the original, larger provenance file is retained locally.
The run used a source snapshot based on main 36f81fb, not a local Git commit.
The environment used Python 3.12.15, torch 2.2.2 and NumPy 1.26.4 on Intel macOS;
this does not certify the newer dependency lock or another platform.

Final targeted validation: **506 Python tests passed, zero skips**, covering
Fog Lab, real Network 1/engine integration, the existing search factories and
Pair C regression tests. **52 JavaScript tests passed**. Browser checks covered
material and Quick Stockfish replies, fair-game hiding and disabled save, and
the bot controls at widths 320, 375, 390, 768 and 1440. The longer original Bot
label was used for the viewport stress check; the delivered label is shorter.
The existing 100-ms resize debounce must settle before measuring board layout.

Reproduce from a project environment with torch and Stockfish available:

```sh
python pair_c/run_evaluation.py pair_b/configs/network1-search-smoke.ini
python -m pytest -q pair_b/tests/test_lab_pair_a_bot.py pair_b/tests/test_lab_session.py pair_b/tests/test_lab_server.py pair_b/tests/test_lab_scorers.py pair_b/tests/test_lab_record.py pair_b/tests/test_search_factory.py pair_b/tests/test_network_evaluator.py pair_a_prep/tests/test_stockfish_factory.py pair_a_prep/tests/test_evaluation_factories.py pair_c/regression_tests
node --test pair_b/tests/js/*.test.mjs
```

Use a fresh output directory. No model training, formal match batch, PR33 edit,
or approval attributed to Colin was performed. Codex assisted under Bryan's
direction. Browser integration derives from xiaomiao-fong's PR69; this version
uses main's search and a separate browser-only pruning wrapper instead of the
unreviewed final-integration/solver-label stack.
