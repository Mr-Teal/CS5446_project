# The four practice datasets' manifests

The data folders are not in git (they are hundreds of MB), but their manifests say how each was
made: command, seed, Stockfish settings, counts and run time. Each file here wraps one manifest as
written, with the home folder written as `~`, and gives the SHA-256 of the original file, which is
the `manifest.json` hash in the provenance records (`checkpoints/*/provenance.json`, the eval
reports' `source`).

| Dataset | What it is | Seed | Games or beliefs | Seconds |
|---|---|---|---|---|
| d2-v2 | Network 1's training data | 2026 | 8,000 games, 795,945 records | 1,781 |
| d2-check | the fresh check games | 7 | 1,200 games, 119,303 records | 367 |
| d6-v1 | the belief network's training beliefs | 2026 | 11,999 beliefs | 206 |
| d6-check | the fresh check beliefs | 7 | 4,766 beliefs | 93 |
