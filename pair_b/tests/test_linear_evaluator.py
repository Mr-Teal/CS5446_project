import shutil

import chess
import numpy as np
import pytest

from fow_shared.contracts import AgentInput, Belief, Hypothesis, Observation
from fow_shared.values import fog_legal_moves, rule_score
from pairb.encode import stm_sign
from pairb.linear import FEATURES, LinearCorrection
from pairb.linear_evaluator import LinearEvaluator
from pairb.stockfish import StockfishEvaluator

CAPTURE = "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1"
CASTLE = "8/8/8/8/8/4k3/4q3/4K2R w K - 0 1"
BLACK = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/2N2N2/PPPP1PPP/R1BQKB1R b KQkq - 3 3"


class FakeStockfish:
    name = "fake-d1"
    def __init__(self, **kwargs): pass
    def close(self): pass
    def board_value(self,b):
        rule=rule_score(b)
        return (rule[1] * stm_sign(b),True) if rule is not None else (0.2,False)
    def children_values(self,b):
        out={}
        for move in fog_legal_moves(b):
            child=b.copy();child.push(move)
            out[move.uci()]=self.board_value(child)
        return out


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr('pairb.linear_evaluator.StockfishEvaluator',FakeStockfish)


def model(): return LinearCorrection(np.zeros(FEATURES),0.1,0.1)


@pytest.mark.parametrize("fen",[chess.STARTING_FEN,BLACK,CAPTURE,CASTLE])
def test_children_perspective_coverage_and_exact_rules(fake,fen):
    board=chess.Board(fen)
    with LinearEvaluator(model()) as ev:
        got=ev.evaluate_children(fen)
    assert set(got)=={m.uci() for m in fog_legal_moves(board)}
    for move in fog_legal_moves(board):
        child=board.copy();child.push(move)
        value,rule=FakeStockfish().board_value(child)
        expected=value if rule else value+stm_sign(child)*0.1
        assert got[move.uci()]==pytest.approx(stm_sign(board)*expected)


def test_batches_and_beliefs_keep_order_and_named_perspective(fake):
    def turn(player,fens):
        return AgentInput(Observation(player=player,side_to_move=player,ply=0,
                                      visible_squares=(),visible_pieces={},legal_moves=()),
                          Belief(player,0,tuple(Hypothesis(f,1/len(fens)) for f in fens)),1000)
    turns=[turn('white',[CAPTURE,chess.STARTING_FEN]),turn('black',[BLACK])]
    with LinearEvaluator(model()) as ev:
        answers=ev.evaluate_beliefs(turns)
        assert answers[0].hypothesis_values==pytest.approx((1,0.3))
        assert answers[1].hypothesis_values==pytest.approx((-0.1,))
        assert ev.evaluate_boards([BLACK,chess.STARTING_FEN],'white')==pytest.approx([0.1,0.3])
        assert ev.evaluate_boards([],'white')==[]
        assert ev.evaluate_beliefs([])==[]
        with pytest.raises(ValueError): ev.evaluate_boards([],'other')


def test_terminal_and_checkpoint(fake,tmp_path):
    path=tmp_path/'best.npz';model().save(path)
    with LinearEvaluator.from_checkpoint(path) as ev:
        assert ev.evaluate_children('8/8/8/8/8/8/8/4K3 b - - 0 1')=={}
        assert ev.evaluate_boards([chess.STARTING_FEN],'white')==pytest.approx([0.3])


def test_rule_decided_boards_bypass_model(fake):
    class MustNotPredict:
        def predict(self,*args,**kwargs):
            raise AssertionError('rule-decided board reached linear model')
    with LinearEvaluator(MustNotPredict()) as ev:
        assert ev.evaluate_boards([CAPTURE,'8/8/8/8/8/8/8/4K3 b - - 0 1',
                                   '4k3/8/8/8/8/8/8/4K3 w - - 100 51'],
                                  'white')==[1.0,1.0,0.0]


@pytest.mark.skipif(shutil.which('stockfish') is None,reason='needs Stockfish')
@pytest.mark.parametrize('fen',[chess.STARTING_FEN,BLACK,CAPTURE,CASTLE])
def test_real_stockfish_children(fen):
    with StockfishEvaluator(1) as sf:
        baseline=sf.evaluate_children(fen)
    with LinearEvaluator(model()) as ev:
        actual=ev.evaluate_children(fen)
    assert actual.keys()==baseline.keys()
    board=chess.Board(fen)
    for uci,v in baseline.items():
        child=board.copy();child.push(chess.Move.from_uci(uci))
        expected=v if rule_score(child) is not None else -np.clip(-v+0.1,-1,1)
        assert actual[uci]==pytest.approx(expected,abs=1e-7)
