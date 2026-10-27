# Fixed-tree subgame gadgets

[gadgets.py](../gadgets.py) constructs small Resolve and Maxmargin games in
the existing `Node` format. They can be solved independently by the LP oracle
and by PCFR+. These builders do not construct a chess subgame or infer roots.

## Source and conventions

The structural reference is [Obscuro, Appendix B.2](https://arxiv.org/pdf/2506.01242v2).
Player 0 is the resolving agent; player 1 is its zero-sum opponent.

- Resolve samples a root, then lets the opponent enter or exit knowing its
  root information set J, not the individual hidden root. Exit pays the
  explicitly supplied `alternate_player0[J]` to player 0.
- Maxmargin lets the opponent choose J, samples a root conditional on J and
  subtracts `alternate_player0[J]` from player-0 continuation payoffs. There is
  no enter/exit choice in this gadget.

If upstream alternate values are expressed as opponent utility, negate them
before calling this API. No implicit perspective conversion is performed.

`reach_mass` is supplied externally and normalized within each J. Resolve's
default group probability is proportional to total group mass; `group_prior`
can supply another distribution. This option does not implement Obscuro's C.3
prior calculation. Maxmargin has an opponent selector, not a fixed group prior.
Alternate/gift updates in C.2 and gadget switching in C.1 remain separate work.

## Root identity and hidden information

Each `SubgameRoot` contains a stable `root_id`, `opponent_infoset`, continuation
tree and nonnegative reach mass. A group must have positive total mass.
Player-0 infoset IDs are preserved across roots: do not assign distinct keys
merely because the simulator knows the hidden root. Opponent continuation IDs
are refined by J because it remembers its root observation and gadget action.
They are NOT refined by individual root ID. A reserved namespace prevents
synthetic nodes colliding with user information sets.

Input continuations are copied. Trees with inconsistent actions or own-history
information sets are rejected by the fixed-tree solver's validation. The caller
is responsible for the semantic correctness of J and the original information
sets; the builder cannot reconstruct private histories from their string keys.

## API and label separation

```python
from pair_a_prep.gadgets import SubgameRoot, build_gadget
from pair_a_prep.pcfr import PCFRPlus
from pair_a_prep.toy_games import terminal

gadget = build_gadget(
    [SubgameRoot("candidate-1", "opponent-J", terminal(0.4), 1.0)],
    alternate_player0={"opponent-J": -0.2},
    mode="resolve",
)
solver = PCFRPlus(gadget.tree, schedule="alternating")
solver.run(100)
profile = solver.policy()
values = gadget.continuation_values(profile)  # {"candidate-1": 0.4}
label = gadget.belief_value(profile, {"candidate-1": 1.0})  # 0.4
```

The gadget game itself has value -0.2: the minimizing opponent exits. The raw
continuation label remains +0.4. `continuation_values` always evaluates entering
each root, excluding opt-out and Maxmargin offsets. `belief_value` requires a
separate normalized weight map; it never silently uses the gadget prior.
Payoffs may exceed [-1,1] after margin shifts; this module does not serialize
them as `TrainingRecord` labels or clip them.

## Verification

```powershell
python -m pytest -q pair_a_prep/tests/test_gadgets.py
python -m pair_a_prep.gadgets --rounds 2000 --output pair_a_prep/results/gadgets_new.json
```

The report compares PCFR+ with the independent normal-form LP oracle. The
two-root example shares a player-0 decision with payoffs (L,R)=(1,-1) at A
and (-1,1) at B, with alternate payoffs 0 and .4. Its analytic gadget values
are 0 for default Resolve, .2 for Resolve with group prior (.25,.75), and -.2
for Maxmargin. The maximizing probability of L is .4 for Maxmargin, showing
that subtracting the alternate value changes the objective as intended.

Tests also distinguish a hidden-root exit choice from an illegal per-root
choice, check payoff signs, conditional probabilities, independent label
weights, input-tree isolation and opponent recall. This is local gadget
verification, not a safety guarantee for the full game or evidence of chess
strength. KLUSS, blueprint reach construction, gifts, dynamic growth, persistence
and live Resolve/Maxmargin switching are not implemented here.
