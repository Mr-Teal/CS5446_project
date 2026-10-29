import json
from pathlib import Path
from time import perf_counter

import pytest

from pair_a_prep.zs21.protocol import ProcessAgent
from pair_a_prep.zs21.model import Referee


from pair_a_prep.zs21.platform_support import locked_runtime_available

_LOCKED_OK, _LOCKED_WHY = locked_runtime_available()
pytestmark = pytest.mark.skipif(not _LOCKED_OK, reason=f"ZS21 process service: {_LOCKED_WHY}")


@pytest.mark.parametrize("player", ["white", "black"])
def test_external_process_uses_only_the_selected_private_seat(tmp_path, player):
    repository = Path(__file__).resolve().parents[2]
    manifest = repository / "zs21_runtime/pixi.toml"
    invocation = ["pixi", "run"] + (["--manifest-path", str(manifest)] if manifest.exists() else [])
    spec = tmp_path / "agent.json"
    spec.write_text(json.dumps(dict(cwd=str(repository), command=invocation+["--locked", "-e", "darkchess",
                    "python", "-X", "utf8", "-m", "pair_a_prep.zs21.protocol", "--random-example"])), encoding="utf-8")
    agent = ProcessAgent(spec, player, 4)
    try:
        referee = Referee()
        agent.observe(referee.observe(player))
        if player == "black":
            referee.apply("e2e4")
            agent.observe(referee.observe(player))
        decision = agent.act(perf_counter()+8)
        decision.validate_for(referee.observe(player))
        referee.apply(decision.move)
        agent.observe(referee.observe(player), decision.move)
    finally:
        agent.close()
