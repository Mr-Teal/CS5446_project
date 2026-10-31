"""Sparse sequence-form LP with explicit observation sequences and additive B."""

from dataclasses import dataclass
from math import isfinite
from time import perf_counter
import warnings

import numpy as np
from scipy.optimize import linprog, OptimizeWarning
from scipy.optimize._highspy._core import _Highs
from scipy.sparse import coo_matrix, csr_matrix, hstack


_HIGHS_NOT_SET = "(HiGHS Status 0: Not Set)"


class SolveError(RuntimeError):
    pass


class CertificateError(SolveError):
    pass


class LinearProgramError(SolveError):
    def __init__(self, message, *, side, scipy_status):
        super().__init__(message)
        self.side = side
        self.scipy_status = scipy_status
        self.highs_model_status = 0 if _HIGHS_NOT_SET in message else None
        self.retryable_not_set = scipy_status == 4 and self.highs_model_status == 0


@dataclass
class Solution:
    x: np.ndarray
    y: np.ndarray
    value: float
    lower: float
    upper: float
    flow_error: float
    inequality_error: float
    form: "SequenceForm"
    precision_attempts: tuple = ()

    def policy(self, player, infoset):
        parent, actions, indices = self.form.infosets[player][infoset]
        weights = (self.x, self.y)[player]
        if weights[parent] <= 0:
            return dict.fromkeys(actions, 1 / len(actions))
        values = np.maximum(weights[indices], 0.0)
        total = values.sum()
        if total <= 0:
            raise SolveError("positive parent realization has no action mass")
        return dict(zip(actions, (values / total).tolist()))

    def profile(self):
        return tuple({key: self.policy(p, key) for key in self.form.infosets[p]}
                     for p in (0, 1))


class SequenceForm:
    """An infoset action has one realization weight across all its hidden nodes.

    Optional node.observations supplies both players' private-memory keys, even
    off turn. A one-action flow row records each observation without adding a
    game move; this exposes the sequences used by Algorithm 12's B matrix.
    """

    def __init__(self, root, b_terms=(), auxiliary_infosets=(), deadline=None):
        self.sequences = [[None], [None]]
        self.index = [{None: 0}, {None: 0}]
        self.infosets = [{}, {}]
        self.nodes = {}
        self.observation_nodes = [{}, {}]
        rows = [[{0: 1.0}], [{0: 1.0}]]
        entries = {}

        def register(player, key, parent, actions):
            old = self.infosets[player].get(key)
            if old is not None:
                if old[0] != parent or old[1] != actions:
                    raise ValueError("inconsistent action set or imperfect recall: " + str(key))
                return old[2]
            indices = []
            row = {parent: -1.0}
            for action in actions:
                sequence = (key, action)
                idx = len(self.sequences[player])
                self.sequences[player].append(sequence)
                self.index[player][sequence] = idx
                row[idx] = 1.0
                indices.append(idx)
            self.infosets[player][key] = (parent, actions, indices)
            rows[player].append(row)
            return indices

        def visit(node, sequences, probability, ancestors):
            if len(self.nodes) % 1024 == 0 and deadline is not None and perf_counter() >= deadline:
                raise SolveError("deadline while constructing sequence form")
            if id(node) in ancestors:
                raise ValueError("cyclic game tree")
            sequences = list(sequences)
            observations = getattr(node, "observations", None)
            if observations is not None:
                for player, memory in enumerate(observations):
                    key = ("observe", memory)
                    sequences[player] = register(player, key, sequences[player], ("seen",))[0]
                    self.observation_nodes[player].setdefault(memory, []).append(id(node))
            self.nodes[id(node)] = (tuple(sequences), probability, node)
            if node.payoff is not None:
                if node.children or not isfinite(node.payoff):
                    raise ValueError("invalid leaf payoff")
                pair = tuple(sequences)
                entries[pair] = entries.get(pair, 0.0) + probability * node.payoff
                return
            if not node.children:
                raise ValueError("nonterminal has no actions")
            actions = tuple(node.children)
            path = ancestors | {id(node)}
            if node.player is None:
                if (set(actions) != set(node.probabilities)
                        or any(not isfinite(p) or p < 0 for p in node.probabilities.values())
                        or abs(sum(node.probabilities.values()) - 1) > 1e-10):
                    raise ValueError("invalid chance distribution")
                for action, child in node.children.items():
                    visit(child, sequences, probability * node.probabilities[action], path)
            else:
                if node.player not in (0, 1):
                    raise ValueError("invalid player")
                indices = register(node.player, node.infoset, sequences[node.player], actions)
                for (action, child), idx in zip(node.children.items(), indices):
                    next_sequences = list(sequences)
                    next_sequences[node.player] = idx
                    visit(child, next_sequences, probability, path)

        try:
            visit(root, (0, 0), 1.0, set())
        finally:
            # A self-referential closure would retain this entire form until GC.
            visit = None
        pending = list(auxiliary_infosets)
        while pending:
            remaining = []
            for player, key, parent, actions in pending:
                if parent not in self.index[player]:
                    remaining.append((player, key, parent, actions))
                    continue
                register(player, key, self.index[player][parent], tuple(actions))
            if len(remaining) == len(pending):
                raise ValueError("unanchored auxiliary sequence")
            pending = remaining
        self.A = self._matrix(entries)
        b_entries = {}
        for ours, theirs, value in b_terms:
            if not isfinite(value):
                raise ValueError("non-finite B coefficient")
            pair = (self.index[0][ours], self.index[1][theirs])
            b_entries[pair] = b_entries.get(pair, 0.0) + value
        self.B = self._matrix(b_entries)
        self.C = self.A + self.B
        self.parents = []
        for player in (0, 1):
            self.parents.append([None] + [self.infosets[player][key][0]
                                          for key, _ in self.sequences[player][1:]])
        self.flows = []
        self.rhs = []
        for player in (0, 1):
            triples = [(i, j, value) for i, row in enumerate(rows[player]) for j, value in row.items()]
            i, j, v = zip(*triples)
            self.flows.append(coo_matrix((v, (i, j)), shape=(len(rows[player]), len(self.sequences[player]))).tocsr())
            rhs = np.zeros(len(rows[player]))
            rhs[0] = 1
            self.rhs.append(rhs)

    def _matrix(self, entries):
        shape = tuple(len(s) for s in self.sequences)
        if not entries:
            return csr_matrix(shape)
        i, j = zip(*entries)
        matrix = coo_matrix((list(entries.values()), (i, j)), shape=shape).tocsr()
        matrix.eliminate_zeros()
        return matrix

    def _reduced(self):
        mappings, projections, flows, rhs = [], [], [], []
        for player in (0, 1):
            mapping = np.empty(len(self.sequences[player]), dtype=np.int64)
            mapping[0] = 0
            count, rows = 1, [0]
            for row, (parent, _, indices) in enumerate(self.infosets[player].values(), 1):
                if len(indices) == 1:
                    mapping[indices[0]] = mapping[parent]
                else:
                    mapping[indices] = np.arange(count, count + len(indices))
                    count += len(indices)
                    rows.append(row)
            projection = coo_matrix((np.ones(len(mapping)), (np.arange(len(mapping)), mapping)),
                                    shape=(len(mapping), count)).tocsr()
            mappings.append(mapping)
            projections.append(projection)
            flows.append(self.flows[player][rows] @ projection)
            rhs.append(self.rhs[player][rows])
        matrix = (projections[0].T @ self.C @ projections[1]).tocsr()
        matrix.eliminate_zeros()
        return matrix, flows, rhs, mappings

    def _full_potential(self, costs, player, maximize):
        values = np.asarray(costs).copy()
        potentials = np.empty(len(self.infosets[player]) + 1)
        for row, (parent, _, indices) in reversed(tuple(enumerate(self.infosets[player].values(), 1))):
            if len(indices) == 1:
                best = float(values[indices[0]])
            else:
                best = (max if maximize else min)(float(values[index]) for index in indices)
            potentials[row] = best
            values[parent] += best
        potentials[0] = values[0]
        return potentials

    def solve(self, deadline=None, *, eliminate_forced=True, refine=True):
        # HiGHS uses a process-global scheduler. The reused normal-form oracle
        # may have initialized it with another thread count. LPs are serialized.
        _Highs.resetGlobalScheduler(True)
        if eliminate_forced:
            C, (E, F), (e, f), mappings = self._reduced()
        else:
            C, (E, F), (e, f) = self.C, self.flows, self.rhs
            mappings = [np.arange(size) for size in C.shape]
        self.solved_shape = C.shape
        nx, ny = C.shape
        options = dict(primal_feasibility_tolerance=1e-8, dual_feasibility_tolerance=1e-8,
                       presolve=True, simplex_dual_edge_weight_strategy="steepest-devex", threads=1)
        primal_problem = dict(c=np.r_[np.zeros(nx), -f],
                              A_ub=hstack([-C.T, F.T], format="csr"), b_ub=np.zeros(ny),
                              A_eq=hstack([E, csr_matrix((E.shape[0], len(f)))], format="csr"), b_eq=e,
                              bounds=[(0, None)] * nx + [(None, None)] * len(f))
        dual_problem = dict(c=np.r_[np.zeros(ny), e],
                            A_ub=hstack([C, -E.T], format="csr"), b_ub=np.zeros(nx),
                            A_eq=hstack([F, csr_matrix((F.shape[0], len(e)))], format="csr"), b_eq=f,
                            bounds=[(0, None)] * ny + [(None, None)] * len(e))

        def run(problem, side, attempt):
            attempt["stage"] = side
            call_options = dict(options)
            started = perf_counter()
            if deadline is not None:
                remaining = deadline - started
                if remaining <= 0:
                    raise SolveError("deadline before LP")
                call_options["time_limit"] = remaining
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Unrecognized options detected", category=OptimizeWarning)
                answer = linprog(**problem, method="highs-ds", options=call_options)
            finished = perf_counter()
            finite = answer.x is not None and bool(np.all(np.isfinite(answer.x)))
            message, scipy_status = str(answer.message), int(answer.status)
            attempt["lp_results"].append(dict(side=side, scipy_status=scipy_status,
                highs_model_status=0 if _HIGHS_NOT_SET in message else None, message=message,
                success=bool(answer.success), finite_solution=finite,
                seconds=finished-started, options=call_options))
            if deadline is not None and finished >= deadline:
                raise SolveError("deadline after LP")
            if not answer.success:
                raise LinearProgramError(message, side=side, scipy_status=scipy_status)
            if not finite:
                raise SolveError("LP returned a missing or non-finite solution")
            return answer

        self.solve_attempts = []
        for tolerance in ((1e-8, 1e-9, 1e-10) if refine else (1e-8,)):
            options["primal_feasibility_tolerance"] = tolerance
            options["dual_feasibility_tolerance"] = tolerance
            attempt = dict(feasibility_tolerance=tolerance, lp_results=[])
            self.solve_attempts.append(attempt)
            try:
                primal = run(primal_problem, "primal", attempt)
                dual = run(dual_problem, "dual", attempt)
                x, y = primal.x[:nx][mappings[0]], dual.x[:ny][mappings[1]]
                attempt["stage"] = "certificate"
                solution = self._certify(x, y, attempt)
                if deadline is not None and perf_counter() >= deadline:
                    raise SolveError("deadline after LP certificate")
            except CertificateError as exc:
                attempt.update(accepted=False, error=str(exc), failure_kind="certificate")
                if tolerance == (1e-10 if refine else 1e-8):
                    raise
            except LinearProgramError as exc:
                attempt.update(accepted=False, error=str(exc),
                               failure_kind="highs_not_set" if exc.retryable_not_set else "lp_status")
                if not exc.retryable_not_set or tolerance == (1e-10 if refine else 1e-8):
                    raise
            except SolveError as exc:
                attempt.update(accepted=False, error=str(exc), failure_kind="solve")
                raise
            else:
                attempt["accepted"] = True
                solution.precision_attempts = tuple(self.solve_attempts)
                return solution

    def _certify(self, x, y, attempt):
        def restore_flow(weights, player):
            if np.min(weights) >= 0:
                return weights
            if np.min(weights) < -1e-8:
                raise CertificateError("negative realization exceeds feasibility tolerance")
            result = np.zeros_like(weights)
            result[0] = 1.
            for parent, actions, indices in self.infosets[player].values():
                positive = np.maximum(weights[indices], 0.)
                total = positive.sum()
                result[indices] = result[parent] * (positive / total if total > 0 else 1. / len(indices))
            return result
        x, y = restore_flow(x, 0), restore_flow(y, 1)
        E, F = self.flows
        e, f = self.rhs
        # Exact tree best responses lift the dual certificates to every original
        # flow row, including eliminated forced observation sequences and B.
        v = self._full_potential(self.C.T @ x, 1, False)
        u = self._full_potential(self.C @ y, 0, True)
        lower, upper = float(f @ v), float(e @ u)
        flow = max(np.max(np.abs(E @ x - e)), np.max(np.abs(F @ y - f)))
        inequalities = max(0., float(np.max(F.T @ v - self.C.T @ x)),
                           float(np.max(self.C @ y - E.T @ u)))
        value = float(x @ self.C @ y)
        attempt.update(flow_error=float(flow), inequality_error=inequalities,
                       lower=lower, upper=upper, gap=upper-lower, value=value)
        if (flow > 1e-8 or inequalities > 1e-8 or min(x.min(), y.min()) < -1e-8
                or abs(upper - lower) > 1e-8 or not lower - 1e-8 <= value <= upper + 1e-8):
            raise CertificateError(f"LP certificate failed: flow={flow}, inequalities={inequalities}, gap={upper-lower}")
        return Solution(x, y, value, lower, upper, float(flow), inequalities, self)

    def counterfactual(self, x):
        """Unnormalized opponent best responses, including applicable B terms."""
        values = np.asarray(self.C.T @ x).copy()
        infoset_values = {}
        for key, (parent, actions, indices) in reversed(tuple(self.infosets[1].items())):
            best = min(float(values[i]) for i in indices)
            infoset_values[key] = best
            values[parent] += best
        return values, infoset_values

    def reach(self, player, memory, strategy):
        return sum(self.nodes[i][1] * strategy[self.nodes[i][0][player]]
                   for i in self.observation_nodes[1 - player].get(memory, ()))

    def parent_sequence(self, player, index):
        return self.parents[player][index]

    def descends(self, player, index, ancestor):
        while index is not None:
            if index == ancestor:
                return True
            index = self.parent_sequence(player, index)
        return False
