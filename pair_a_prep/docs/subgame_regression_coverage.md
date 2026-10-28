# Stronger subgame regressions

This test-only follow-up is based on the #42 integration branch. It changes no agent, factory, label schema or default policy.

- A real depth-4 blueprint is prepared on the pawn fixture. A controlled budget exception forces a fallback on the next own turn. The test follows the actual fallback move and an opponent move, then requires a successful cold solve on the following turn. It checks genuine tree depth and recovery, not only cached-state assignment.
- A position-dependent evaluator gives different values to hidden hypotheses. Both cold and projected solves are checked against direct one-ply board arithmetic under the returned raw policy. Hypotheses carry unequal weights and are reversed in a second solve. The test checks input ordering, weighted root value and independence from the gadget's alternate/offset payments.
- Projected solves use solve() for internal verification; label() remains disabled for their unresolved root-set contract. This does not enable a training run or claim playing strength.

Run `python -m pytest pair_a_prep/tests/test_chess_subgame_agent.py -q`. The focused suite has 13 passing cases on the follow-up branch. These fixed-work fixtures are not timing benchmarks.
