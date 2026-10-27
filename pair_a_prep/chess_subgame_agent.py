"""Serial sampled-tree I^2/gadget agent with explicit approximation diagnostics."""

from dataclasses import asdict
from hashlib import sha256
import json
from math import isfinite
from time import perf_counter
from types import SimpleNamespace

from fow_shared.contracts import Decision, TrainingRecord
from .anytime_agent import AnytimeConfig
from .chess_projection import project_chess, SavedChessBlueprint
from .chess_search import expand_chess_tree, SearchBudgetError, TreeCapacityError
from .gadgets import _key
from .one_sided import OneSidedExpansion
from .pcfr import PCFRPlus
from .search_agent import FixedDepthPCFRAgent, SearchResult
from .search_policies import heuristic_actions, StableSupport, purify_policy, seed_new
from .subgame_boundaries import choose_mode, current_minimum_margin
from .toy_games import behavioral_value, information_sets
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
    name = "sampled-I2-gadget-pcfr-prototype-v1"

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
            half_budget="wall_clock" if self.config.stop_on_time else "round_count")
        return self.name+":"+sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]

    def solve(self, turn):
        if self._player != turn.observation.player or turn.observation.terminal or not turn.observation.legal_moves:
            raise ValueError("reset for the nonterminal acting player before solving")
        self.last_result = None
        self.last_evaluator_calls = 0
        self.last_stop_reason = None
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
        mode, switches, expansions = "maxmargin", 0, 0
        bridge = projection.bridge(mode, leaf.name) if projection.boundaries else None
        active_root = bridge.gadget.tree if bridge else projection.tree.root
        if self.saved is None:
            solver = PCFRPlus(active_root, schedule=self.config.schedule,
                              initial_actions=heuristic_actions(active_root))
        else:
            solver, retained = rebase_solver(self.saved.raw_solver, active_root,
                                            opponent_key_map(projection) if bridge else None)
            seed_new(solver, retained)
        initial_rounds = solver.rounds
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
            if bridge:
                target = choose_mode(current_minimum_margin(bridge.gadget, solver.policy()))
                if target != mode:
                    candidate = projection.bridge(target, leaf.name)
                    solver, retained = rebase_solver(solver, candidate.gadget.tree)
                    seed_new(solver, retained)
                    bridge, mode = candidate, target
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
                        prefix = ((projection.root_ids[i], "enter") if mode == "resolve" else
                                  (projection.groups[i], projection.root_ids[i]))
                        mapping[prefix+path[1:]] = path
                    view = SimpleNamespace(root=solver.root, frontiers=mapping)
                    proposal = sampler.select(view, solver, self.config.max_depth+1, growth_deadline)
                    if proposal is None:
                        continue
                    bridge = bridge.expand(solver, leaf, selected_paths=(mapping[proposal[0]],),
                        max_nodes=self.config.max_nodes, deadline=growth_deadline, initialize_best=True)
                    projection.tree = bridge.roots.chess_tree
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
        values = tuple(by_id[key] for key in projection.current_ids)
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
            label_root_contract_pending=float(projection.boundaries is not None))
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
            self.saved = None
            self.last_result = None
            self.last_projection = self.last_solver = self.last_bridge = None
            if not turn.observation.legal_moves or turn.observation.terminal:
                raise
            moves = turn.observation.legal_moves
            policy = dict.fromkeys(moves, 1/len(moves))
            elapsed = (perf_counter()-started)*1000
            diagnostics = dict(fallback=1., elapsed_ms=elapsed,
                               over_budget=float(elapsed > turn.time_budget_ms),
                               evaluator_calls=float(self.last_evaluator_calls))
            self.last_stop_reason = type(exc).__name__+": "+str(exc)
            diagnostics["stop:"+type(exc).__name__] = 1.
            diagnostics.update({"played_policy:"+a: p for a, p in policy.items()})
            decision = Decision(self._rng.choice(moves), policy, diagnostics)
            decision.validate_for(turn.observation)
            return decision

    def label(self, turn, game_id):
        if not game_id.strip():
            raise ValueError("label runs require a game_id")
        result = self.solve(turn)
        if result.decision.diagnostics["label_root_contract_pending"]:
            raise ValueError("projected subgame labels disabled pending solver-root/weight contract agreement")
        return TrainingRecord(turn, result.decision, result.root_value,
                              result.hypothesis_values, self._seed, self.name,
                              self.config_id, game_id)
