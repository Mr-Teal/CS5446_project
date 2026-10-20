import unittest
from types import SimpleNamespace as NS
from pair_b_prep.harness import DummyEvaluator, build_dummy, run_checks, children, answer, belief_specs

class HarnessTests(unittest.TestCase):
    def failures(self, evaluator):
        bundle=build_dummy({}); bundle.evaluator=evaluator
        return [c['name'] for c in run_checks(bundle) if c['status']=='fail']
    def test_demo_passes_with_manual_checks(self):
        checks=run_checks(build_dummy({}))
        self.assertFalse([c for c in checks if c['status']=='fail'])
        self.assertEqual(2,sum(c['status']=='manual' for c in checks))
    def test_wrong_perspective(self):
        class Wrong(DummyEvaluator):
            def evaluate_boards(self,fens,player): return super().evaluate_boards(fens,'white')
        self.assertIn('board_perspective_and_rules/king_captured',self.failures(Wrong()))
    def test_missing_castling(self):
        class Wrong(DummyEvaluator):
            def evaluate_children(self,fen):
                values=super().evaluate_children(fen); values.pop('e1g1',None); return values
        self.assertIn('children/castling_escape',self.failures(Wrong()))
    def test_wrong_parent_perspective(self):
        class Wrong(DummyEvaluator):
            def evaluate_children(self,fen): return {m:-v for m,v in super().evaluate_children(fen).items()}
        self.assertIn('children/king_capture_available',self.failures(Wrong()))
    def test_reversed_batch(self):
        class Wrong(DummyEvaluator):
            def evaluate_boards(self,fens,player): return super().evaluate_boards(fens,player)[::-1]
        self.assertIn('boards/batch_and_order',self.failures(Wrong()))
    def test_dropped_belief(self):
        class Wrong(DummyEvaluator):
            def evaluate_beliefs(self,turns): return super().evaluate_beliefs(turns)[:1]
        self.assertIn('beliefs/grouping_order_unknown_clock_and_policy',self.failures(Wrong()))
    def test_invalid_outputs(self):
        for result in [NS(hypothesis_values=(0,0),policy={'a1a2':1}),
                       NS(hypothesis_values=(float('nan'),0),policy=None),
                       NS(hypothesis_values=(0,0),policy={'a1a2':-0.2,'a1b1':0.6,'a1b2':0.6})]:
            with self.assertRaises(AssertionError): answer(result,belief_specs()[0])
    def test_extra_illegal_move(self):
        with self.assertRaises(AssertionError): children({'a1a2':0,'a1a3':0},{'moves':['a1a2']},1e-6)

class SharedContractTests(unittest.TestCase):
    def test_acting_player_for_both_colours_at_even_ply(self):
        from pair_b_prep.adapter_example import make_turn
        from fow_shared.contracts import Observation
        from dataclasses import fields
        for player, active, moves in [('white', 'w', ['a1a2']),
                                      ('black', 'b', ['h8h7'])]:
            with self.subTest(player=player):
                fen = f'7k/8/8/8/8/8/8/K7 {active} - - 0 80'
                turn = make_turn(dict(player=player, fens=[fen], weights=[1.0],
                                      legal_moves=moves))
                self.assertEqual(turn.observation.player, player)
                self.assertEqual(turn.observation.ply, 158)
                self.assertEqual(turn.observation.legal_moves, tuple(moves))
                self.assertEqual(turn.belief.hypotheses[0].fen, fen)
                if 'side_to_move' in {f.name for f in fields(Observation)}:
                    self.assertEqual(turn.observation.side_to_move, player)

    def test_real_shared_contracts_accept_probes(self):
        from pair_b_prep.adapter_example import make_turn
        from fow_shared.contracts import LeafValues
        for spec in belief_specs():
            turn = make_turn(spec)
            self.assertIsNone(turn.observation.halfmove_clock)
            self.assertEqual(tuple(spec['fens']),tuple(h.fen for h in turn.belief.hypotheses))
            LeafValues(tuple(0.0 for _ in spec['fens'])).validate_for(turn)

    def test_harness_runs_with_real_turn_objects(self):
        from pair_b_prep.adapter_example import make_turn
        bundle = build_dummy({})
        bundle.make_turn = make_turn
        self.assertFalse([c for c in run_checks(bundle) if c['status']=='fail'])

if __name__ == '__main__':
    unittest.main()
