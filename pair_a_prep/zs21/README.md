# ZS21 Dark Chess reproduction

This package contains the reproduced 2021 nested 1-KLSS agent and its matched
one-FoW-ply baseline. It reuses the repository's rules, contracts and board
assets; its sequence-form LP and information-set implementation are separate
from the PCFR+ / Obscuro preparation modules.

Start with the [installation and FoW integration manual](../../zs21_runtime/README.md).
It includes the locked Pixi runtime, human play, the native Python interface,
the shared AgentInput adapter, the actual paper-agent JSON service, examples,
validation commands and Stockfish corresponding-source/license information.

From the repository root:

```powershell
pixi install --manifest-path zs21_runtime/pixi.toml --locked -e darkchess
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess doctor
pixi run --manifest-path zs21_runtime/pixi.toml --locked -e darkchess play --white human --black paper
```

The default rule profile is `paper2021_fow_no_moves_draw_v1` (PR #28).
The default budget is 16 seconds from turn transfer. The formal runner shares
four single-thread Stockfish 13 workers. Algorithm decisions and remaining
uncertainties are documented in [implementation notes](../../zs21_runtime/docs/IMPLEMENTATION.md).
No machine-specific parent workspace or local research archive is required.

The [HiGHS recovery record](../docs/zs21_highs_recovery.md) documents bounded
retries for the two historical Not Set failures, unchanged full-game acceptance,
portable failure fixtures and the diagnostic replay command.
