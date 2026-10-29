PR51 proposed provenance fixes for Zhijian
========================================
Base: 250e781e32d9cdad5c61150b76b1c6717a6e1385 (pairC)
Seven source/documentation/test paths changed; no other project changes.

Fixes:
1. A loader explicitly declares provenance_checkpoint_path on its scorer,
   evaluator or returned agent. The built-in factory records exactly the path
   passed to its network loader, or None when no checkpoint was loaded.
   The exporter never infers loaded weights from a configured unused path.
   Missing declarations yield null identity plus checkpoint_detection_notes,
   rather than silently implying that no weights were used. This is one new
   additive JSON field, documented and covered by saved-output tests.
2. Engine and device discovery recognizes scorer/evaluator/direct-agent
   layouts. CPU Stockfish/Material subclasses are recognized too.
3. A relative shutil.which result is resolved against the actual current
   working directory, not accidentally against the repository.

Tests:
- All34 Pair C regressions pass (15 existing,19 added resource cases).
- All11 independent value probes pass. The only adaptation to the old review
  script is550->551 source entries because this patch adds a regression file.
- All4 unchanged real-PR57 compatibility probes pass with the fixed helper.
- End-to-end fixture: PR57 at6fa0c5d plus these seven files, with a synthetic
 628-file local index. Real SF19 pawn handoff and its pinned production config
 each complete two four-ply capped attempts. Both engine identities/hashes,
 CPU devices, saved INI hashes and all628 source hashes match actual files.
 There are no failed games or scored terminal games; this is integration
 evidence, not strength or timing evidence. The traced run has no fallback.

Use the supplied patch against the exact PR51 head:
  git -c core.autocrlf=false apply --check pr51-provenance-fixes.patch
  git -c core.autocrlf=false apply pr51-provenance-fixes.patch
  python -m pytest pair_c\regression_tests -q

Run using the project's existing environment; the root and pair_b\src must
be importable. Git-index requirements and raw working-tree hash conventions
are intentionally unchanged, as are commit/dirty-state policy and GPU probing.
No new packages, neural training or formal batch runs are introduced.

The original review snapshots are untouched. All work was done in a separate
copy. Runtime verification indexes have no commit or remote; they are fixtures,
not claimed upstream revisions. Final integration into PR51 and its re-review
must happen at the resulting actual head; do not approve the old head merely
because this companion fix is available.
The explicit autocrlf setting preserves the supplied LF bytes during patch
application, matching the recorded raw-byte hashes.
