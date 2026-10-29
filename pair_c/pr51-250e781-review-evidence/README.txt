PR51 independent Pair B provenance review
=======================================

Reviewed source: 250e781e32d9cdad5c61150b76b1c6717a6e1385
PR57 compatibility source: 6fa0c5d1a04dbe03c90725e6d1ebee1758120f9f
The compatibility probe loads only PR51's provenance helper against real PR57
agents in a separate interpreter. It is not a merged-stack evaluation.

Results:
- Untouched ZIP: 10 existing regressions pass, 5 fail because no Git index exists.
- Same source with a synthetic archive-only index: all 15 regressions pass.
  The local index contains exactly 550 original archive paths, no commit/remote.
- Independent value probes: 8 pass, 3 fail with assertions of desired behavior.
- Actual PR57 compatibility probes: 4 fail, one per search mode.
  These seven failures demonstrate three defect categories, not seven bugs.

Confirmed defects:
1. run_evaluation.py:91-100 hashes configured checkpoint paths that custom
   Material factories never load. A missing unused checkpoint aborts the run.
2. provenance.py:21-27 ignores agent.evaluator. All four actual PR57 Stockfish
   agents therefore produce (None, None) despite live engines and exposed
   executable paths. Device discovery uses the same restricted traversal.
3. agent_factories.py:92 re-roots a relative shutil.which result against the
   repository rather than the current working directory. Direct engine launch
   succeeds from that resolved PATH result; the new factory launch fails.

Successful controls include real Material/Stockfish and Network1/belief CPU
two-ply attempts, exact saved INI bytes/hash, both actual checkpoint hashes,
engine identity/hash, CPU tensor placement, and all 550 raw source hashes.
CUDA logical-index and MPS adapter values use doubles, not GPU experiments.
Tracked edit/deletion and untracked exclusion use a disposable local Git index.
All game attempts are capped and are not strength results.

Reproduction (PowerShell; use existing dependencies and an installed SF19):
  $env:PR51_ROOT = 'C:\path\to\PR51-250e781'
  $env:PR51_ENGINE = 'C:\path\to\stockfish.exe'
  $env:PYTHONPATH = "$env:PR51_ROOT;$env:PR51_ROOT\pair_b\src"
  $env:PYTHONDONTWRITEBYTECODE = '1'
  python -m pytest .\test_review_provenance.py -q -p no:cacheprovider

The main value probes require a Git index covering the 550 original PR51
files. Do not manufacture a commit or modify an existing working project's
index for this check. We used only a dedicated archive snapshot.

Run compatibility separately, keeping PR51_ROOT unchanged:
  $pr57 = 'C:\path\to\PR57-6fa0c5d'
  $env:PYTHONPATH = "$pr57;$pr57\pair_b\src"
  python -m pytest .\test_pr57_compatibility.py -q -p no:cacheprovider

The failing tests assert the intended corrected behavior and should become
green when fixed. Run the existing Pair C regressions independently too.
Do not combine both probe modules in one interpreter: they use different
Pair A source snapshots.

Evidence handling:
- Original source files were not patched; all 550 bytestrings match the ZIP.
- XML hostnames and local home prefixes are redacted in shared XML copies.
- Example output JSON paths are redacted; hashes retain their original
  meaning (original input bytes), not hashes of redacted copies.
- Raw outputs and XML remain local. No secrets or engine/checkpoint binaries
  are included in this package.

This review corroborates Colin's existing findings rather than claiming them
as newly discovered. The concrete real-PR57 test adds integration evidence.
Missing commit/dirty state, cross-platform hash comparison policy, and the
documented Git-index requirement remain follow-up concerns. No full suite,
formal batch, GPU inference, long-game validation, training, or merge claim.
