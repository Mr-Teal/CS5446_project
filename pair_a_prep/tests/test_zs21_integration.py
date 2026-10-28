from dataclasses import asdict, replace
import io
import json
from pathlib import Path
from time import perf_counter

import pytest

from fow_shared.contracts import AgentInput, Belief, Hypothesis, HistoryEvent
from pair_a_prep.zs21.agent import PaperAgent
from pair_a_prep.zs21.engine import Estimate
from pair_a_prep.zs21.integration import SharedAgent
from pair_a_prep.zs21.model import Referee
from pair_a_prep.zs21.protocol import ProcessAgent
from pair_a_prep.zs21.rule_profile import RULES_ID
from pair_a_prep.zs21.serve import serve


class FixedPool:
    def __init__(self, *args):
        self.closed = False

    def evaluate(self, boards, player, *, depth, deadline, scale):
        return tuple(Estimate(.1*scale, "integration_fixture", depth) for _ in boards)

    def close(self):
        self.closed = True


def turn_for(referee, player, agent, history):
    belief = Belief(player, referee.observe(player).ply,
                    (Hypothesis(agent.tracker.candidates[0].state.fen, 1.),),
                    population_size=len(agent.tracker.candidates))
    return AgentInput(referee.observe(player), belief, 16000, tuple(history))


@pytest.mark.parametrize("player", ["white", "black"])
@pytest.mark.parametrize("baseline", [False, True])
def test_shared_adapter_replays_every_private_observation_and_matches_direct_agent(player, baseline):
    ref, pool, history = Referee(), FixedPool(), []
    direct = PaperAgent(player, 77, pool, baseline=baseline, max_rounds=1)
    shared = SharedAgent(pool, baseline=baseline, max_rounds=1)
    shared.reset(player, 77)
    try:
        direct.observe(ref.observe(player))
        for _ in range(6):
            mover, old = ref.current_player(), ref.observe(player)
            if mover == player:
                turn = turn_for(ref, player, direct, history)
                reference = direct.act(perf_counter()+16)
                actual = shared.act(turn)
                assert actual.move == reference.move
                assert actual.root_policy == pytest.approx(reference.root_policy)
                assert len(shared.core.tracker.candidates) == len(direct.tracker.candidates)
                assert shared.core.tracker.memory == direct.tracker.memory
                with pytest.raises(ValueError, match="duplicate or stale"):
                    shared.act(turn)
                move = actual.move
            else:
                move = ref.observe(mover).legal_moves[0]
            history.append(HistoryEvent(old, move if mover == player else None))
            ref.apply(move)
            direct.observe(ref.observe(player), move if mover == player else None)
    finally:
        direct.close()
        shared.close()
    assert not pool.closed


def test_shared_adapter_requires_complete_history_and_reset_clears_state():
    ref, pool = Referee(), FixedPool()
    shared = SharedAgent(pool, max_rounds=1)
    shared.reset("black", 77)
    reference = PaperAgent("black", 77, pool, max_rounds=1)
    try:
        reference.observe(ref.observe("black"))
        ref.apply("e2e4")
        reference.observe(ref.observe("black"))
        incomplete = turn_for(ref, "black", reference, [])
        with pytest.raises(ValueError, match="complete private history"):
            shared.act(incomplete)
        assert shared.core.tracker.previous is None
        shared.reset("white", 78)
        assert shared.core.player == "white" and shared.core.tracker.previous is None
    finally:
        shared.close()
        reference.close()


@pytest.mark.parametrize("failure", ["wrong_rules", "wrong_schema", "act_before_start", "hidden_fen", "terminal_act", "nan_budget"])
def test_json_server_rejects_invalid_requests_and_cleans_up(failure):
    ref, pool = Referee(), FixedPool()
    start = dict(type="start", schema_version=1, player="white", seed=4, rules_id=RULES_ID)
    observation = dict(type="observe", observation=asdict(ref.observe("white")))
    messages = [start, observation, dict(type="act", remaining_seconds=16)]
    if failure == "wrong_rules":
        start["rules_id"] = "different"
    elif failure == "wrong_schema":
        start["schema_version"] = 2
    elif failure == "act_before_start":
        messages = [messages[-1]]
    elif failure == "hidden_fen":
        observation["observation"]["fen"] = ref._state.fen
    elif failure == "terminal_act":
        observation["observation"] = asdict(replace(ref.observe("white"), terminal=True, outcome=0., legal_moves=()))
    else:
        messages[-1]["remaining_seconds"] = float("nan")
    output = io.StringIO()
    serve(io.StringIO("\n".join(json.dumps(m) for m in messages)), output, engine="fixture",
          pool_factory=lambda _: pool, agent_kwargs=dict(max_rounds=1))
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert "error" in responses[-1]
    if failure not in ("wrong_rules", "wrong_schema", "act_before_start"):
        assert pool.closed


def test_json_server_runs_the_real_paper_agent_and_closes_pool_on_eof():
    ref, pool, output = Referee(), FixedPool(), io.StringIO()
    messages = [dict(type="start", schema_version=1, player="white", seed=4, rules_id=RULES_ID),
                dict(type="observe", observation=asdict(ref.observe("white"))),
                dict(type="act", remaining_seconds=16)]
    serve(io.StringIO("\n".join(json.dumps(m) for m in messages)), output, engine="fixture",
          pool_factory=lambda _: pool, agent_kwargs=dict(max_rounds=1))
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert responses[0]["agent"] == "zs21-paper" and responses[0]["rules_id"] == RULES_ID
    assert responses[-1]["decision"]["move"] in ref.observe("white").legal_moves
    assert pool.closed


def test_actual_paper_agent_process_can_play_and_exit_cleanly(tmp_path):
    repository = Path(__file__).resolve().parents[2]
    spec = tmp_path / "paper.json"
    spec.write_text(json.dumps(dict(cwd=str(repository), command=["pixi", "run", "--locked", "--manifest-path",
                   str(repository / "zs21_runtime/pixi.toml"), "-e", "darkchess", "python", "-X", "utf8",
                   "-m", "pair_a_prep.zs21.serve"])), encoding="utf-8")
    agent, ref = ProcessAgent(spec, "white", 4), Referee()
    try:
        deadline = perf_counter()+4
        agent.observe(ref.observe("white"), deadline=deadline)
        decision = agent.act(deadline)
        decision.validate_for(ref.observe("white"))
        assert decision.diagnostics["population"] == 1
        ref.apply(decision.move)
        agent.observe(ref.observe("white"), decision.move)
    finally:
        agent.close()
    assert agent.process.poll() == 0
