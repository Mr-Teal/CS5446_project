# Windows anytime readiness evidence, 9 November 2026

`windows-readiness.zip` contains the original copied configuration, provenance,
games and tracker JSONL, hash rules and summary for BOTH runs, plus the native
build manifest. SHA256:

`61d2875e7c31123034756d86523f6105927132f62ef26be9ce14fb59c8173485`

- `512m-python-failed`: one tracker memory failure at ply60 and one 14-ply
  terminal game. Retained as failure evidence, not pooled with the next run.
- `native-uncapped`: two terminal seed-17 colour-swapped games (46/14 plies),
  zero failures/caps/fallbacks/search overruns. Native exact tracking, 60 s per
  update, no logical memory cap. Not a strength result or a hard resource guarantee.

Runtime source is main `10352fe`; candidate config/docs were uncommitted during
validation. No runtime source changes were made. The delivered INI adds
expected engine name/hash checks to the tested local INI. The actual engine
hash/name are already recorded in provenance; engine path/output are host-local.
Raw records retain original absolute local paths. The tested device is CPU,
not Pair C's CUDA. Commands and limits are in the linked config guide.

No new training, formal batch, PR66/67 adoption or PR74 result alteration.
The paired result is 1 win / 1 loss, insufficient for a strength claim.
