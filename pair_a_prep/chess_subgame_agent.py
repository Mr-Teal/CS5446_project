"""Serial sampled-tree I^2/gadget agent with explicit approximation diagnostics."""

from dataclasses import asdict, replace
from hashlib import sha256
import json
from math import isfinite
from time import perf_counter
from types import SimpleNamespace

from fow_shared.contracts import Decision, TrainingRecord
from .anytime_agent import AnytimeConfig
from .chess_projection import project_chess, SavedChessBlueprint
from .chess_search import build_chess_tree, expand_chess_tree, SearchBudgetError, TreeCapacityError
from .gadgets import _key
from .one_sided import OneSidedExpansion
from .pcfr import PCFRPlus
from .search_agent import FixedDepthPCFRAgent, SearchResult
from .search_policies import heuristic_actions, StableSupport, purify_policy, seed_new
from .subgame_boundaries import BlendedGadgetControl
from .toy_games import behavioral_value, information_sets, nash_gap
from .warm_start import rebase_solver
from .gift_accounting import ledger_for_projection


def opponent_key_map(projection, to_raw=False):
    mapping = {}
    for group, root in zip(projection.groups, projection.tree.continuations):
        for key in information_sets(root)[1]:
            wrapped = _key("continuation", group, key)
            target, source = (key, wrapped) if to_raw else (wrapped, key)
            if (1, target) in mapping and mapping[1, target] != source:
                raise ValueError("opponent root memory cannot be flattened consistently")
            mapping[1, target] = source
    return mapping


class ChessSubgameAgent(FixedDepthPCFRAgent):
    name = "sampled-I2-gadget-pcfr-prototype-v2"

    def __init__(self, evaluator, config=None, initial_fen=None, purify=True,
                 submission_reserve_fraction=.1):
        super().__init__(evaluator, config or AnytimeConfig(growth="one_sided"), initial_fen)
        if self.config.growth != "one_sided":
            raise ValueError("the integrated subgame prototype requires growth=one_sided")
        self.purify = purify
        if not isfinite(submission_reserve_fraction) or not 0 <= submission_reserve_fraction < .5:
            raise ValueError("submission reserve fraction must be finite in [0,.5)")
        self.submission_reserve_fraction = submission_reserve_fraction
        self.last_evaluator_calls = 0
        self.last_stop_reason = None
        self.saved = None
        self.last_projection = self.last_solver = self.last_bridge = None

    def reset(self, player, seed):
        super().reset(player, seed)
        self.saved = None
        self.last_evaluator_calls = 0
        self.last_stop_reason = None
        self.last_projection = self.last_solver = self.last_bridge = None

    @property
    def config_id(self):
        data = dict(version=1, search=asdict(self.config), evaluator=self.evaluator.name,
            leaf={key: getattr(self.evaluator, key) for key in ("depth", "new_game_each_call", "call_timeout_s")
                  if hasattr(self.evaluator, key)}, initial_fen=self.initial_fen,
            purify=self.purify, knowledge="saved_sampled_tree_synchronized_I2",
            submission_reserve_fraction=self.submission_reserve_fraction,
            round_guard="previous_completed_round_including_mode_switch",
            preparation_window="solve_deadline_v3_single_replay_lazy_neighbours_attempt_local_eval_cache",
            fresh_boundary="min(minimax_proxy, previous_unshifted_value)", fresh_mass="unit",
            gift_scope="within_saved_raw_tree", no_move_rule="terminal_draw_v1",
            gift_accounting="retained_discarded_local_cf_audit_DAG_v1_no_ancestor_payments",
            half_budget="wall_clock" if self.config.stop_on_time else "round_count",
            fresh_roots="distinct_positions_v1",
            fallback="partial_solver_or_heuristic_depth1_v1",
            gadget="blended_resolve_maxmargin_pmax_v1",
            labels="per_hypothesis_raw_profile_belief_weighted_root_v1")
        return self.name+":"+sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]

    def solve(self, turn):
        if self._player != turn.observation.player or turn.observation.terminal or not turn.observation.legal_moves:
            raise ValueError("reset for the nonterminal acting player before solving")
        self.last_result = None
        self.last_evaluator_calls = 0
        self.last_stop_reason = None
        # Cleared here so a budget failure below cannot hand act() the previous
        # turn's projection as if it were this turn's partial result.
        self.last_projection = self.last_solver = self.last_bridge = None
        started = perf_counter()
        deadline = started+turn.time_budget_ms/1000 if self.config.stop_on_time else None
        growth_deadline = started+turn.time_budget_ms/1000*self.config.expansion_fraction if deadline else None
        solve_deadline = (deadline-turn.time_budget_ms/1000*self.submission_reserve_fraction
                          if deadline is not None else None)
        evaluation_deadline = solve_deadline
        calls = 0
        owner = self
        class CountedLeaf:
            name = owner.evaluator.name
            def evaluate_children(self, fen):
                nonlocal calls
                if calls >= owner.config.max_evaluator_calls:
                    raise SearchBudgetError("evaluator_limit")
                if evaluation_deadline is not None and perf_counter() >= evaluation_deadline:
                    raise SearchBudgetError("evaluation_deadline")
                calls += 1
                owner.last_evaluator_calls = calls
                return owner.evaluator.evaluate_children(fen)
        leaf = CountedLeaf()
        projection = project_chess(turn, leaf, initial_fen=self.initial_fen,
            depth=self.config.initial_depth, max_nodes=self.config.max_nodes,
            saved=self.saved, deadline=solve_deadline)
        evaluation_deadline = growth_deadline
        switches, expansions = 0, 0
        # One gadget for the whole turn: Resolve and Maxmargin share its tree and
        # the controller re-blends the root every round (Obscuro Fig. 10).
        bridge = projection.bridge("blended", leaf.name) if projection.boundaries else None
        control = BlendedGadgetControl(bridge.gadget, projection.boundaries.group_prior) if bridge else None
        mode = control.mode if control else "maxmargin"
        active_root = bridge.gadget.tree if bridge else projection.tree.root
        if self.saved is None:
            solver = PCFRPlus(active_root, schedule=self.config.schedule,
                              initial_actions=heuristic_actions(active_root))
        else:
            solver, retained = rebase_solver(self.saved.raw_solver, active_root,
                                            opponent_key_map(projection) if bridge else None)
            seed_new(solver, retained)
        initial_rounds = solver.rounds
        # Published before the round loop: if the budget runs out later, act()
        # plays this solver's current strategy instead of a random move.
        self.last_projection, self.last_solver, self.last_bridge = projection, solver, bridge
        sampler, stable = OneSidedExpansion(self._rng.getrandbits(64)), StableSupport()
        next_growth = self.config.rounds_per_stage
        growth_stopped = None
        previous_round_s = 0.
        for completed in range(self.config.rounds):
            round_started = perf_counter()
            if solve_deadline is not None:
                predicted = previous_round_s if self.submission_reserve_fraction > 0 else 0.
                if round_started+predicted >= solve_deadline:
                    self.last_stop_reason = "submission_reserve" if self.submission_reserve_fraction else "deadline"
                    break
            solver.step()
            if control:
                control.update(bridge.gadget, solver.policy())
                if control.mode != mode:
                    mode = control.mode
                    switches += 1
            previous_round_s = perf_counter()-round_started
            after_half = ((perf_counter()-started >= turn.time_budget_ms/2000) if deadline else
                          completed+1 > self.config.rounds/2)
            stable.observe(solver.policy()[0][projection.tree.root_infoset], after_half)
            if completed+1 < next_growth or growth_stopped:
                continue
            next_growth = completed+1+self.config.rounds_per_stage
            if completed+1 >= self.config.rounds-self.config.final_rounds:
                continue
            if growth_deadline is not None and perf_counter() >= growth_deadline:
                growth_stopped = "growth_deadline"
                continue
            try:
                if bridge:
                    mapping = {}
                    for path, context in projection.tree.frontiers.items():
                        i = int(path[0])
                        mapping[(projection.root_ids[i],)+path[1:]] = path
                    view = SimpleNamespace(root=solver.root, frontiers=mapping)
                    proposal = sampler.select(view, solver, self.config.max_depth, growth_deadline)
                    if proposal is None:
                        continue
                    bridge = bridge.expand(solver, leaf, selected_paths=(mapping[proposal[0]],),
                        max_nodes=self.config.max_nodes, deadline=growth_deadline, initialize_best=True)
                    projection.tree = bridge.roots.chess_tree
                    self.last_bridge = bridge
                else:
                    proposal = sampler.select(projection.tree, solver, self.config.max_depth, growth_deadline)
                    if proposal is None:
                        continue
                    projection.tree = expand_chess_tree(projection.tree, solver, leaf,
                        selected_paths=(proposal[0],), max_nodes=self.config.max_nodes,
                        deadline=growth_deadline, initialize_best=True)
                sampler.commit(proposal)
                expansions += 1
            except (SearchBudgetError, TreeCapacityError) as exc:
                growth_stopped = type(exc).__name__
        if solver.rounds == initial_rounds:
            raise SearchBudgetError("no complete solving round within budget")
        # Project gadget strategies back to raw continuations before computing
        # labels or saving a blueprint. Gadget exits/offsets never enter labels.
        raw_solver = solver if bridge is None else rebase_solver(
            solver, projection.tree.root, opponent_key_map(projection, to_raw=True))[0]
        profile = raw_solver.policy()
        by_id = {}
        for identity, root in zip(projection.root_ids, projection.tree.continuations):
            sets = information_sets(root)
            local = tuple({key: profile[p][key] for key in sets[p]} for p in (0, 1))
            by_id[identity] = behavioral_value(root, local)
        # A hypothesis whose position was already a root takes that root's value.
        values = tuple(by_id[projection.aliases.get(key, key)] for key in projection.current_ids)
        value = sum(h.weight*v for h, v in zip(turn.belief.hypotheses, values))
        raw = profile[0][projection.tree.root_infoset]
        played = purify_policy(raw, mode, stable.stable) if self.purify else dict(raw)
        move = self._rng.choices(list(played), weights=list(played.values()), k=1)[0]
        ledger = ledger_for_projection(None if self.saved is None else self.saved.gift_ledger, projection)
        elapsed = (perf_counter()-started)*1000
        diagnostics = dict(search_nodes=float(projection.tree.nodes), evaluator_calls=float(calls),
            solver_rounds=float(solver.rounds), solver_rounds_this_turn=float(solver.rounds-initial_rounds),
            expansions=float(expansions), mode_switches=float(switches), mode_resolve=float(mode == "resolve"),
            elapsed_ms=elapsed, over_budget=float(elapsed > turn.time_budget_ms), fallback=0.,
            solver_root_value=value, purification=float(self.purify),
            # Last-iterate Nash gap of the solved (gadget) game, Obscuro C.7's
            # "about half a pawn" check; it must fall as rounds grow.
            solver_nash_gap=nash_gap(solver.root, solver.policy()),
            p_max=control.p_max if control else 0.,
            minimum_margin=(min(control.margins.values()) if control and control.margins else 0.),
            projected_from_saved_tree=float(projection.boundaries is not None),
            zero_reach_uniform_prior=float(bool(projection.boundaries and projection.boundaries.audit.get("all_zero_opponent_reach"))))
        self.last_stop_reason = self.last_stop_reason or "round_limit"
        diagnostics["stop:"+self.last_stop_reason] = 1.
        diagnostics["submission_reserve_ms"] = (turn.time_budget_ms*self.submission_reserve_fraction
                                                 if self.config.stop_on_time else 0.)

        diagnostics.update({"projection:"+key: float(v) for key, v in projection.audit.items()})
        diagnostics.update(ledger.metrics())
        diagnostics.update({"raw_policy:"+a: p for a, p in raw.items()})
        diagnostics.update({"played_policy:"+a: p for a, p in played.items()})
        diagnostics["growth_stop:"+(growth_stopped or "round_limit")] = 1.
        decision = Decision(move, raw, diagnostics)
        decision.validate_for(turn.observation)
        self.last_result = SearchResult(decision, values, value)
        self.saved = SavedChessBlueprint(turn, projection.tree, projection.paths, raw_solver, value, ledger)
        self.last_projection, self.last_solver, self.last_bridge = projection, solver, bridge
        return self.last_result

    def act(self, turn):
        started = perf_counter()
        try:
            return self.solve(turn).decision
        except (SearchBudgetError, TreeCapacityError) as exc:
            return self.fallback_decision(turn, exc, started)

    def fallback_decision(self, turn, exc, started):
        """The anytime move after solve() ran out of budget (Obscuro Fig. 8).

        A move comes from the strategy computed so far, never from a uniform
        draw. Label runs call this too, after a failed label(): a fallback plays
        a move but is never written as a label. The saved blueprint is discarded,
        as the existing contract requires.
        """
        projection, solver = self.last_projection, self.last_solver
        self.saved = None
        self.last_result = None
        self.last_projection = self.last_solver = self.last_bridge = None
        if not turn.observation.legal_moves or turn.observation.terminal:
            raise exc
        moves = turn.observation.legal_moves
        # The solver built for THIS turn is used if it exists; its root policy is
        # the warm start or the heuristic initialization when no round completed.
        raw, source = None, None
        if projection is not None and solver is not None and projection.turn is turn:
            candidate = solver.policy()[0].get(projection.tree.root_infoset)
            if candidate is not None and set(candidate) == set(moves):
                raw, source = dict(candidate), "partial_solver"
        if raw is None:
            # Nothing solved this turn. The paper's first strategy at a new
            # node is the evaluator's best child; one depth-1 pass gives it.
            # heuristic_actions decides an infoset at its first DFS occurrence,
            # so one hypothesis yields the same action as all of them at a
            # fraction of the cost -- this runs after the budget is already gone.
            try:
                first = turn.belief.hypotheses[0]
                reduced = replace(turn, belief=replace(turn.belief, hypotheses=(replace(first, weight=1.),)))
                tree = build_chess_tree(reduced, self.evaluator, initial_fen=self.initial_fen,
                                        depth=1, max_nodes=self.config.max_nodes)
                best = heuristic_actions(tree.root).get((0, tree.root_infoset))
                if best in moves:
                    raw, source = {m: float(m == best) for m in moves}, "heuristic_depth1"
            except (SearchBudgetError, TreeCapacityError, ValueError):
                raw = None
        if raw is None:
            raw, source = dict.fromkeys(moves, 1/len(moves)), "uniform"
        # An unfinished solve is not a safe strategy: play its top action.
        played = purify_policy(raw, "resolve", None) if self.purify and source != "uniform" else dict(raw)
        move = self._rng.choices(list(played), weights=list(played.values()), k=1)[0]
        elapsed = (perf_counter()-started)*1000
        diagnostics = dict(fallback=1., elapsed_ms=elapsed,
                           over_budget=float(elapsed > turn.time_budget_ms),
                           evaluator_calls=float(self.last_evaluator_calls),
                           solver_rounds=float(solver.rounds) if solver is not None else 0.)
        diagnostics["fallback_policy:"+source] = 1.
        self.last_stop_reason = type(exc).__name__+": "+str(exc)
        diagnostics["stop:"+type(exc).__name__] = 1.
        diagnostics.update({"raw_policy:"+a: p for a, p in raw.items()})
        diagnostics.update({"played_policy:"+a: p for a, p in played.items()})
        decision = Decision(move, raw, diagnostics)
        decision.validate_for(turn.observation)
        return decision

    def label(self, turn, game_id):
        """One TrainingRecord per decision, as pair_b/docs/label_definitions.md defines it.

        hypothesis_values[i] is hypothesis i's value under the raw solved profile
        (a hypothesis aliased to another root takes that root's value), root_value
        is their belief-weighted mean, root_policy is the raw last iterate, and the
        move was sampled from the purified policy, recorded as played_policy. Roots
        retained from the saved tree (the I^2 closure) shape these values but are
        not hypotheses, so they are not listed. A budget failure raises and labels
        nothing: fallback policies are never labels.
        """
        if not game_id.strip():
            raise ValueError("label runs require a game_id")
        result = self.solve(turn)
        return TrainingRecord(turn, result.decision, result.root_value,
                              result.hypothesis_values, self._seed, self.name,
                              self.config_id, game_id)
