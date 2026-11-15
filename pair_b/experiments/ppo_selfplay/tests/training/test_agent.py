"""In a match the network must be shown exactly what it was shown in training."""
import random

import chess
import numpy as np

from fow_shared.contracts import AgentInput, HistoryEvent
from fowppo import env as E
from fowppo.agent import NoBelief, ObservationMemory, PpoAgent, action_table
from fowppo.model import PolicyValueNet
from team_observe_reference import observe  # Pair B's observe.py, copied unchanged from main

NAMES = {chess.WHITE: "white", chess.BLACK: "black"}


def fresh_memories(game):
    memories = {color: ObservationMemory(color) for color in NAMES}
    for color, memory in memories.items():
        memory.see(observe(game.board, NAMES[color], game.ply))
    return memories


def test_planes_from_team_observations_equal_training_planes():
    vec = E.VecFow(1)
    rng = random.Random(4)
    memories = fresh_memories(vec.games[0])
    games = captures = 0
    for _ in range(2500):
        game = vec.games[0]
        color = game.board.turn
        assert np.array_equal(memories[color].planes(), vec.obs[0]), (game.board.fen(), game.ply)
        table = action_table(observe(game.board, NAMES[color], game.ply))
        assert {a: chess.Move.from_uci(u) for a, u in table.items()} == vec.tables[0]
        captures += int(vec.obs[0][E.P_LOSS].sum())
        _, done = vec.step(np.array([rng.choice(sorted(vec.tables[0]))]))
        if done[0]:
            games += 1
            memories = fresh_memories(vec.games[0])
        else:
            for viewer, memory in memories.items():
                memory.see(observe(vec.games[0].board, NAMES[viewer], vec.games[0].ply))
    assert games >= 10 and captures > 100  # whole games, with captures, were compared


def test_agent_plays_a_legal_move_from_history_alone():
    torch_agent = PpoAgent(PolicyValueNet(blocks=1, channels=8), sample=True)
    torch_agent.reset("black", seed=3)
    board = chess.Board()
    history, tracker = [], NoBelief()
    tracker.reset("black", 0)
    for ply, uci in enumerate(("e2e4", "e7e5", "g1f3")):
        view = observe(board, "black", ply)
        history.append(HistoryEvent(view, uci if board.turn == chess.BLACK else None))
        board.push_uci(uci)
    view = observe(board, "black", 3)
    decision = torch_agent.act(AgentInput(view, tracker.update(view), 1000, tuple(history)))
    decision.validate_for(view)
    assert decision.move in view.legal_moves
