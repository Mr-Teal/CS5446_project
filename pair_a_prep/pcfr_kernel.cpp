// PCFR+ round on a flattened tree: the native twin of pair_a_prep/pcfr.py (PCFRPlus with fast_prepare).
//
// Python owns the tree, the information-set numbering and every state array (see _pcfr_native.py); this file
// only walks them. The floating-point operations follow the Python reference in order:
//   * chance nodes sum like CPython 3.12's built-in sum() of floats (Neumaier compensation);
//   * `strategy @ values` is numpy's float64 dot, which calls OpenBLAS ddot; dot() below reproduces the
//     operation order of the kernel OpenBLAS 0.3.34 selects on the build host (AVX-512 "SkylakeX" ddot,
//     fused multiply-adds); other BLAS kernels differ from it by rounding only;
//   * `theta.sum()` is numpy's pairwise sum (pairwise_sum below);
//   * elementwise updates are single IEEE operations, so they match exactly (build with -ffp-contract=off).
// Return codes: 0 success, -1 next strategy requested while feedback is pending, -2 feedback without a
// pending strategy (the two ValueErrors of PredictiveRMPlus).

#include <cmath>
#include <cstdint>
#include <vector>

extern "C" {

struct PcfrSide {
    int32_t n_sets;
    int32_t n_levels;
    const int32_t* offset;       // n_sets + 1: actions of set s are [offset[s], offset[s + 1]) in the state arrays
    const int32_t* depth;        // n_sets: own-history depth (PCFRPlus._depth)
    const int32_t* level_begin;  // n_levels + 1, ranges into level_sets
    const int32_t* level_sets;   // n_sets: PCFRPlus._order, deepest level first
    const int32_t* level_depth;  // n_levels
    double* regrets;
    double* strategy;            // published strategy == PredictiveRMPlus.strategy
    double* previous_utility;
    double* sums;
    int8_t* pending;             // n_sets
    int32_t* initial_action;     // n_sets: action index to force at the next publish, or -1
    double* previous_opponent;   // the other side's action count: opponent strategy snapshot at the last observe
    int8_t* has_previous;        // one flag: previous_opponent is set
};

struct PcfrSolver {
    int32_t n_nodes;
    int32_t predictive;
    int32_t alternating;
    int32_t averaging_power;
    const int8_t* kind;          // 0 terminal, 1 chance, 2 decision; node 0 is the root, DFS order
    const int8_t* player;
    const int32_t* infoset;      // per-player set id of a decision node
    const double* payoff;        // player 0's payoff at a terminal
    const int32_t* child_begin;  // n_nodes + 1, ranges into child (children in dict order = infoset action order)
    const int32_t* child;
    const int32_t* chance_begin; // n_nodes + 1, ranges into chance_child / chance_prob (probabilities dict order)
    const int32_t* chance_child;
    const double* chance_prob;
    PcfrSide side[2];
};

}  // extern "C"

namespace {

enum { TERMINAL = 0, CHANCE = 1, DECISION = 2 };

double dot(const double* x, const double* y, int n) {
    // OpenBLAS ddot: 32-wide blocks into four 8-lane accumulators, folded to four 4-lane ones, then 16-wide
    // blocks, a fixed reduction, and a sequential fused tail.
    double result = 0.0;
    const int n1 = n & -16;
    if (n1) {
        const int n32 = n1 & ~31;
        double wide[4][8] = {};
        int i = 0;
        for (; i < n32; i += 32)
            for (int k = 0; k < 4; ++k)
                for (int l = 0; l < 8; ++l)
                    wide[k][l] = std::fma(x[i + 8 * k + l], y[i + 8 * k + l], wide[k][l]);
        double acc[4][4];
        for (int k = 0; k < 4; ++k)
            for (int l = 0; l < 4; ++l)
                acc[k][l] = wide[k][l] + wide[k][l + 4];
        for (; i < n1; i += 16)
            for (int k = 0; k < 4; ++k)
                for (int l = 0; l < 4; ++l)
                    acc[k][l] = std::fma(x[i + 4 * k + l], y[i + 4 * k + l], acc[k][l]);
        double v[4];
        for (int l = 0; l < 4; ++l)
            v[l] = ((acc[0][l] + acc[1][l]) + acc[2][l]) + acc[3][l];
        result = (v[0] + v[2]) + (v[1] + v[3]);
    }
    for (int i = n1; i < n; ++i)
        result = std::fma(y[i], x[i], result);
    return result;
}

double pairwise_sum(const double* a, long n) {
    // numpy's pairwise summation of a contiguous float64 array (np.add.reduce).
    if (n < 8) {
        double res = 0.0;
        for (long i = 0; i < n; ++i) res += a[i];
        return res;
    }
    if (n <= 128) {
        double r[8];
        for (int j = 0; j < 8; ++j) r[j] = a[j];
        long i = 8;
        for (; i < n - (n % 8); i += 8)
            for (int j = 0; j < 8; ++j) r[j] += a[i + j];
        double res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        for (; i < n; ++i) res += a[i];
        return res;
    }
    long n2 = n / 2;
    n2 -= n2 % 8;
    return pairwise_sum(a, n2) + pairwise_sum(a + n2, n - n2);
}

struct Compensated {
    // CPython 3.12 sum() over floats starting from the int 0.
    double total = 0.0, c = 0.0;
    bool first = true;
    void add(double x) {
        if (first) {
            total = x + 0.0;  // int 0 + float
            first = false;
            return;
        }
        double t = total + x;
        if (std::fabs(total) >= std::fabs(x)) c += (total - t) + x;
        else c += (x - t) + total;
        total = t;
    }
    double value() const { return (c != 0.0 && std::isfinite(c)) ? total + c : total; }
};

struct Scratch {
    std::vector<double> stack, values, theta, zeros, memo;
    std::vector<int8_t> memo_set, in_level, seen;
};

Scratch& scratch() {
    static thread_local Scratch s;
    return s;
}

double terminal_value(const PcfrSolver& s, int node, int player) {
    return player == 0 ? s.payoff[node] : -s.payoff[node];
}

// PCFRPlus._utilities: counterfactual action values of `player`; opponent nodes use `opponent` if given.
struct UtilityWalk {
    const PcfrSolver& s;
    int player;
    const double* opponent;
    double* values;
    double* stack;

    double visit(int node, double reach) {
        const int8_t kind = s.kind[node];
        if (kind == TERMINAL) return terminal_value(s, node, player);
        if (kind == CHANCE) {
            Compensated sum;
            for (int k = s.chance_begin[node]; k < s.chance_begin[node + 1]; ++k) {
                const double prob = s.chance_prob[k];
                sum.add(prob * visit(s.chance_child[k], reach * prob));
            }
            return sum.value();
        }
        const int p = s.player[node];
        const PcfrSide& side = s.side[p];
        const int offset = side.offset[s.infoset[node]];
        const double* strategy = (p != player && opponent) ? opponent + offset : side.strategy + offset;
        const int begin = s.child_begin[node], n = s.child_begin[node + 1] - begin;
        double* action_values = stack;
        stack += n;
        for (int i = 0; i < n; ++i)
            action_values[i] = visit(s.child[begin + i], p != player ? reach * strategy[i] : reach * 1.0);
        if (p == player) {
            double* target = values + offset;
            for (int i = 0; i < n; ++i) target[i] += reach * action_values[i];
        }
        const double value = dot(strategy, action_values, n);
        stack -= n;
        return value;
    }
};

// One level of PCFRPlus._prepare_fast: predictions for the sets flagged in_level, memo over final own nodes.
struct PredictionWalk {
    const PcfrSolver& s;
    int player;
    int depth;
    const int8_t* in_level;
    double* values;
    double* memo;
    int8_t* memo_set;
    double* stack;

    double visit(int node, double reach) {
        const int8_t kind = s.kind[node];
        if (kind == TERMINAL) return terminal_value(s, node, player);
        if (memo_set[node]) return memo[node];
        if (kind == CHANCE) {
            Compensated sum;
            for (int k = s.chance_begin[node]; k < s.chance_begin[node + 1]; ++k) {
                const double prob = s.chance_prob[k];
                sum.add(prob * visit(s.chance_child[k], reach * prob));
            }
            return sum.value();
        }
        const int p = s.player[node], set = s.infoset[node];
        const PcfrSide& side = s.side[p];
        const int offset = side.offset[set];
        const int begin = s.child_begin[node], n = s.child_begin[node + 1] - begin;
        double* action_values = stack;
        stack += n;
        double value;
        if (p == player) {
            const double* strategy = side.strategy + offset;
            for (int i = 0; i < n; ++i) action_values[i] = visit(s.child[begin + i], reach);
            if (in_level[set]) {
                double* target = values + offset;
                for (int i = 0; i < n; ++i) target[i] += reach * action_values[i];
            }
            value = dot(strategy, action_values, n);
            if (side.depth[set] > depth) {
                memo[node] = value;
                memo_set[node] = 1;
            }
        } else {
            const double* strategy = s.side[player].previous_opponent + offset;
            for (int i = 0; i < n; ++i) action_values[i] = visit(s.child[begin + i], reach * strategy[i]);
            value = dot(strategy, action_values, n);
        }
        stack -= n;
        return value;
    }
};

// PredictiveRMPlus.next_strategy followed by the initial-action override of PCFRPlus._publish.
void publish(const PcfrSolver& s, int player, int set, const double* prediction, double* theta) {
    const PcfrSide& side = s.side[player];
    const int offset = side.offset[set], n = side.offset[set + 1] - offset;
    double* regrets = side.regrets + offset;
    double* strategy = side.strategy + offset;
    const double baseline = dot(strategy, prediction, n);
    for (int i = 0; i < n; ++i) {
        const double x = regrets[i] + prediction[i] - baseline;
        theta[i] = x > 0.0 ? x : 0.0;
    }
    const double total = pairwise_sum(theta, n);
    if (total > 0.0)
        for (int i = 0; i < n; ++i) strategy[i] = theta[i] / total;
    else
        for (int i = 0; i < n; ++i) strategy[i] = 1.0 / n;
    side.pending[set] = 1;
    const int32_t action = side.initial_action[set];
    if (action >= 0) {
        for (int i = 0; i < n; ++i) strategy[i] = 0.0;
        strategy[action] = 1.0;
        side.initial_action[set] = -1;
    }
}

int total_actions(const PcfrSide& side) { return side.offset[side.n_sets]; }

int max_actions(const PcfrSide& side) {
    int best = 0;
    for (int set = 0; set < side.n_sets; ++set)
        if (side.offset[set + 1] - side.offset[set] > best) best = side.offset[set + 1] - side.offset[set];
    return best;
}

void reserve_stack(const PcfrSolver& s, Scratch& w) {
    const size_t need = static_cast<size_t>(s.child_begin[s.n_nodes]) + 1;
    if (w.stack.size() < need) w.stack.resize(need);
}

int prepare(const PcfrSolver& s, int player) {
    const PcfrSide& side = s.side[player];
    for (int set = 0; set < side.n_sets; ++set)
        if (side.pending[set]) return -1;
    Scratch& w = scratch();
    w.theta.resize(max_actions(side) + 1);
    if (!*side.has_previous || !s.predictive) {
        // No snapshot yet: zero predictions (the reference path). Not predictive: next_strategy zeroes them.
        w.zeros.assign(max_actions(side) + 1, 0.0);
        for (int k = 0; k < side.n_sets; ++k) publish(s, player, side.level_sets[k], w.zeros.data(), w.theta.data());
        return 0;
    }
    reserve_stack(s, w);
    w.values.assign(total_actions(side) + 1, 0.0);
    w.memo.assign(s.n_nodes, 0.0);
    w.memo_set.assign(s.n_nodes, 0);
    w.in_level.assign(side.n_sets + 1, 0);
    for (int level = 0; level < side.n_levels; ++level) {
        const int begin = side.level_begin[level], end = side.level_begin[level + 1];
        for (int k = begin; k < end; ++k) {
            const int set = side.level_sets[k];
            for (int a = side.offset[set]; a < side.offset[set + 1]; ++a) w.values[a] = 0.0;
            w.in_level[set] = 1;
        }
        PredictionWalk walk{s, player, side.level_depth[level], w.in_level.data(), w.values.data(),
                            w.memo.data(), w.memo_set.data(), w.stack.data()};
        walk.visit(0, 1.0);
        for (int k = begin; k < end; ++k) {
            const int set = side.level_sets[k];
            publish(s, player, set, w.values.data() + side.offset[set], w.theta.data());
            w.in_level[set] = 0;
        }
    }
    return 0;
}

int observe(const PcfrSolver& s, int player) {
    const PcfrSide& side = s.side[player];
    for (int set = 0; set < side.n_sets; ++set)
        if (!side.pending[set]) return -2;
    Scratch& w = scratch();
    reserve_stack(s, w);
    w.values.assign(total_actions(side) + 1, 0.0);
    UtilityWalk walk{s, player, nullptr, w.values.data(), w.stack.data()};
    walk.visit(0, 1.0);
    for (int set = 0; set < side.n_sets; ++set) {
        const int offset = side.offset[set], n = side.offset[set + 1] - offset;
        const double* utilities = w.values.data() + offset;
        double* regrets = side.regrets + offset;
        const double baseline = dot(side.strategy + offset, utilities, n);
        for (int i = 0; i < n; ++i) {
            const double x = regrets[i] + utilities[i] - baseline;
            regrets[i] = x > 0.0 ? x : 0.0;
            side.previous_utility[offset + i] = utilities[i];
        }
        side.pending[set] = 0;
    }
    const PcfrSide& other = s.side[1 - player];
    for (int a = 0; a < total_actions(other); ++a) side.previous_opponent[a] = other.strategy[a];
    *side.has_previous = 1;
    return 0;
}

void accumulate_visit(const PcfrSolver& s, int player, double weight, int8_t* seen, int node, double own_reach) {
    const int8_t kind = s.kind[node];
    if (kind == TERMINAL) return;
    const int begin = s.child_begin[node], end = s.child_begin[node + 1];
    if (kind == DECISION && s.player[node] == player) {
        const PcfrSide& side = s.side[player];
        const int set = s.infoset[node], offset = side.offset[set];
        const double* strategy = side.strategy + offset;
        if (!seen[set]) {
            const double scale = weight * own_reach;
            double* sums = side.sums + offset;
            for (int i = 0; i < end - begin; ++i) sums[i] += scale * strategy[i];
            seen[set] = 1;
        }
        for (int i = 0; i < end - begin; ++i)
            accumulate_visit(s, player, weight, seen, s.child[begin + i], own_reach * strategy[i]);
    } else {
        for (int k = begin; k < end; ++k) accumulate_visit(s, player, weight, seen, s.child[k], own_reach);
    }
}

}  // namespace

extern "C" {

int pcfr_utilities(const PcfrSolver* s, int player, const double* opponent, double* values) {
    Scratch& w = scratch();
    reserve_stack(*s, w);
    for (int a = 0; a < total_actions(s->side[player]); ++a) values[a] = 0.0;
    UtilityWalk walk{*s, player, opponent, values, w.stack.data()};
    walk.visit(0, 1.0);
    return 0;
}

int pcfr_prepare(const PcfrSolver* s, int player) { return prepare(*s, player); }

int pcfr_observe(const PcfrSolver* s, int player) { return observe(*s, player); }

int pcfr_accumulate_average(const PcfrSolver* s, int player, double weight) {
    Scratch& w = scratch();
    w.seen.assign(s->side[player].n_sets + 1, 0);
    accumulate_visit(*s, player, weight, w.seen.data(), 0, 1.0);
    return 0;
}

// PCFRPlus.step for a solver that has completed `rounds` rounds; the caller then increments its count.
int pcfr_step(const PcfrSolver* s, int64_t rounds) {
    int code;
    if (!s->alternating) {
        for (int p = 0; p < 2; ++p)
            if ((code = prepare(*s, p))) return code;
        for (int p = 0; p < 2; ++p)
            if ((code = observe(*s, p))) return code;
    } else {
        if (rounds == 0)
            for (int p = 0; p < 2; ++p)
                if ((code = prepare(*s, p))) return code;
        for (int p = 0; p < 2; ++p) {
            if ((code = observe(*s, p))) return code;
            if ((code = prepare(*s, p))) return code;
        }
    }
    int64_t weight = 1;
    for (int k = 0; k < s->averaging_power; ++k) weight *= rounds + 1;
    for (int p = 0; p < 2; ++p) pcfr_accumulate_average(s, p, static_cast<double>(weight));
    return 0;
}

}  // extern "C"
