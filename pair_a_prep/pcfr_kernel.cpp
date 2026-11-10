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
//
// Threads (pcfr_set_threads, default 1). With more than one thread the walks over the whole tree (utilities,
// each prediction level, the average, the growth utilities) visit the root's children in parallel (OpenMP), one
// subtree per task. A subtree walk does not add into the shared per-action arrays: it records its contributions
// in a log of its own, in DFS order, and after the parallel part the logs are applied one after the other in root
// order, followed by the root's own operations. Every addition therefore happens in the order of the sequential
// walk, so the results are bit-equal for every thread count (test_pcfr_threads.py). The continuations' value
// walks of the gadget controller and pcfr_behavioral_values are independent per subtree and run in parallel too.
// With one thread (or a tree below g_parallel_nodes nodes) the sequential code runs.

#include <cmath>
#include <cstdint>
#include <vector>
#ifdef _OPENMP
#include <omp.h>
#endif

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

// subgame_boundaries.BlendedGadgetControl on a blended gadget whose tree is the solver's (see _pcfr_native.Control).
// Groups J in control order; roots in gadget.roots order, listed per group by group_begin / group_roots.
struct GadgetControl {
    int32_t n_groups;
    int32_t n_roots;
    int32_t predictive;
    int32_t history_width;       // doubles per round in `history` (0: none)
    double tolerance;
    const int32_t* root_node;    // n_roots: the continuation's flat node id (the root's child slot)
    const double* reach_mass;    // n_roots
    const int32_t* group_begin;  // n_groups + 1, ranges into group_roots
    const int32_t* group_roots;  // root indices of each group, in gadget.roots order
    const double* alternate;     // n_groups: alternate_player0[J]
    const double* alpha;         // n_groups
    const double* group_mass;    // n_groups: fsum of the group's reach masses (math.fsum, from Python)
    const int32_t* root_slot;    // n_roots: index of the root's entry in chance_prob (the root's probabilities dict)
    const int32_t* exit_slot;    // n_groups: index of "exit:J" there
    double* entry_regrets;       // 2 per group: R_J, the (enter, exit) PRM+
    double* entry_strategy;
    double* entry_previous;
    int8_t* entry_pending;       // n_groups
    double* selector_regrets;    // n_groups: the selector PRM+ over groups
    double* selector_strategy;
    double* selector_previous;
    int8_t* selector_pending;    // 1
    double* pi_resolve;          // n_groups
    double* pi_maxmargin;        // n_groups
    double* p_max;               // 1
    double* margins;             // n_groups
    double* values;              // n_roots: this round's continuation values
    double* entering;            // n_groups: scratch
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

// One root subtree's contributions to the shared per-action arrays, in the order the sequential walk makes them.
struct Log {
    std::vector<int32_t> head;  // per entry: the walk's own fields (see each walk)
    std::vector<double> data;   // per entry: its numbers
    void clear() {
        head.clear();
        data.clear();
    }
};

struct Scratch {
    std::vector<double> stack, values, theta, zeros, memo, mass, fallback, compensation, child_values;
    std::vector<int8_t> memo_set, in_level, seen, started, seen_local;
    std::vector<int32_t> count, touched, root_child;
    std::vector<double> root_reach;
    std::vector<Log> logs;
};

int g_threads = 1;
int g_parallel_nodes = 1024;  // smaller trees run sequentially (the results are the same; tests lower it)
int64_t g_parallel_walks = 0;  // root-parallel walks run so far (tests check that the parallel path ran)

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
    Log* log = nullptr;  // set: record (offset, n) and the n products instead of adding them into values

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
            if (log) {
                log->head.push_back(offset);
                log->head.push_back(n);
                for (int i = 0; i < n; ++i) log->data.push_back(reach * action_values[i]);
            } else {
                double* target = values + offset;
                for (int i = 0; i < n; ++i) target[i] += reach * action_values[i];
            }
        }
        const double value = dot(strategy, action_values, n);
        stack -= n;
        return value;
    }
};

// Adds a UtilityWalk / PredictionWalk log into values, entry by entry, as the walk would have.
void replay_values(const Log& log, double* values) {
    size_t d = 0;
    for (size_t h = 0; h < log.head.size(); h += 2) {
        double* target = values + log.head[h];
        for (int i = 0; i < log.head[h + 1]; ++i) target[i] += log.data[d++];
    }
}

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
    Log* log = nullptr;  // as in UtilityWalk

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
                if (log) {
                    log->head.push_back(offset);
                    log->head.push_back(n);
                    for (int i = 0; i < n; ++i) log->data.push_back(reach * action_values[i]);
                } else {
                    double* target = values + offset;
                    for (int i = 0; i < n; ++i) target[i] += reach * action_values[i];
                }
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

bool parallel_root(const PcfrSolver& s);
void utility_parallel(const PcfrSolver& s, int player, const double* opponent, double* values);
void prediction_parallel(const PcfrSolver& s, const PredictionWalk& base);

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
        if (parallel_root(s)) prediction_parallel(s, walk);
        else walk.visit(0, 1.0);
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
    if (parallel_root(s)) {
        utility_parallel(s, player, nullptr, w.values.data());
    } else {
        UtilityWalk walk{s, player, nullptr, w.values.data(), w.stack.data()};
        walk.visit(0, 1.0);
    }
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

// OneSidedExpansion.utilities under the published strategies (what PCFRPlus.policy() returns): every node is
// reached with reach * strategy[i] for both players; per set the reach-weighted sum of the player-signed action
// values (`totals`), the reach mass, and as fallback the CPython sum() of the signed values over the set's nodes and
// their count, all in the order of the Python walk. Payoffs stay player 0's; a decision node returns
// sum(policy[a] * v for a, v in values.items()) (a CPython sum, not a dot).
struct GrowthWalk {
    const PcfrSolver& s;
    double* totals[2];
    double* mass[2];
    double* fallback[2];      // compensated sums of the signed values, per action
    double* compensation[2];
    int8_t* started[2];       // per action: the compensated sum has its first term
    int32_t* count[2];        // per set: nodes visited
    double* stack;
    Log* log = nullptr;       // set: record (p, set, offset, n) and (reach, n signed values) instead (see replay)

    double visit(int node, double reach) {
        const int8_t kind = s.kind[node];
        if (kind == TERMINAL) return s.payoff[node];
        if (kind == CHANCE) {
            Compensated sum;
            for (int k = s.chance_begin[node]; k < s.chance_begin[node + 1]; ++k) {
                const double prob = s.chance_prob[k];
                sum.add(prob * visit(s.chance_child[k], reach * prob));
            }
            return sum.value();
        }
        const int p = s.player[node], set = s.infoset[node];
        const int offset = s.side[p].offset[set];
        const double* strategy = s.side[p].strategy + offset;
        const int begin = s.child_begin[node], n = s.child_begin[node + 1] - begin;
        double* values = stack;
        stack += n;
        for (int i = 0; i < n; ++i) values[i] = visit(s.child[begin + i], reach * strategy[i]);
        if (log) {
            log->head.insert(log->head.end(), {p, set, offset, n});
            log->data.push_back(reach);
            for (int i = 0; i < n; ++i) log->data.push_back(p == 0 ? values[i] * 1.0 : values[i] * -1.0);
            Compensated value;
            for (int i = 0; i < n; ++i) value.add(strategy[i] * values[i]);
            stack -= n;
            return value.value();
        }
        for (int i = 0; i < n; ++i) {
            const double signed_value = p == 0 ? values[i] * 1.0 : values[i] * -1.0;
            totals[p][offset + i] += reach * signed_value;
            Compensated term{fallback[p][offset + i], compensation[p][offset + i], !started[p][offset + i]};
            term.add(signed_value);
            fallback[p][offset + i] = term.total;
            compensation[p][offset + i] = term.c;
            started[p][offset + i] = 1;
        }
        mass[p][set] += reach;
        count[p][set] += 1;
        Compensated value;
        for (int i = 0; i < n; ++i) value.add(strategy[i] * values[i]);
        stack -= n;
        return value.value();
    }

    // A logged node's updates, in the order visit() makes them.
    void replay(const Log& log) {
        size_t d = 0;
        for (size_t h = 0; h < log.head.size(); h += 4) {
            const int p = log.head[h], set = log.head[h + 1], offset = log.head[h + 2], n = log.head[h + 3];
            const double reach = log.data[d++];
            for (int i = 0; i < n; ++i) {
                const double signed_value = log.data[d++];
                totals[p][offset + i] += reach * signed_value;
                Compensated term{fallback[p][offset + i], compensation[p][offset + i], !started[p][offset + i]};
                term.add(signed_value);
                fallback[p][offset + i] = term.total;
                compensation[p][offset + i] = term.c;
                started[p][offset + i] = 1;
            }
            mass[p][set] += reach;
            count[p][set] += 1;
        }
    }
};

// toy_games.value_walk (behavioral_value without its validation) under the published strategies: a terminal
// returns its payoff; any other node the CPython sum() over its children, in children order, of probability *
// child value, the probability being the strategy's for that action or, at a chance node, the probabilities dict
// entry of that child (looked up: chance_prob is in the dict's order, which may differ from the children's).
double behavioral_visit(const PcfrSolver& s, int node) {
    const int8_t kind = s.kind[node];
    if (kind == TERMINAL) return s.payoff[node];
    const int begin = s.child_begin[node], n = s.child_begin[node + 1] - begin;
    Compensated sum;
    if (kind == CHANCE) {
        for (int i = 0; i < n; ++i) {
            const int child = s.child[begin + i];
            double prob = 0.0;
            for (int k = s.chance_begin[node]; k < s.chance_begin[node + 1]; ++k)
                if (s.chance_child[k] == child) {
                    prob = s.chance_prob[k];
                    break;
                }
            sum.add(prob * behavioral_visit(s, child));
        }
        return sum.value();
    }
    const PcfrSide& side = s.side[s.player[node]];
    const double* strategy = side.strategy + side.offset[s.infoset[node]];
    for (int i = 0; i < n; ++i) sum.add(strategy[i] * behavioral_visit(s, s.child[begin + i]));
    return sum.value();
}

// Root-parallel walks (see the header). The root's children are walked as tasks, each into its own log; the logs
// are then applied in root order and the root's own operations follow, as in the sequential visit of node 0.

bool parallel_root(const PcfrSolver& s) {
    if (g_threads <= 1 || s.n_nodes < g_parallel_nodes) return false;
    const int8_t kind = s.kind[0];
    if (kind == TERMINAL) return false;
    const int count = kind == CHANCE ? s.chance_begin[1] - s.chance_begin[0] : s.child_begin[1] - s.child_begin[0];
    return count >= 2;
}

template <class Body>
void for_each_task(int m, const Body& body) {
    ++g_parallel_walks;
#pragma omp parallel for schedule(dynamic, 1) num_threads(g_threads)
    for (int k = 0; k < m; ++k) body(k);
}

// The root's children in visit order with their reach (`chance`: the probabilities order, else the children order).
void root_children(const PcfrSolver& s, Scratch& w, bool chance) {
    w.root_child.clear();
    w.root_reach.clear();
    if (chance) {
        for (int k = s.chance_begin[0]; k < s.chance_begin[1]; ++k) w.root_child.push_back(s.chance_child[k]);
    } else {
        for (int k = s.child_begin[0]; k < s.child_begin[1]; ++k) w.root_child.push_back(s.child[k]);
    }
    const size_t m = w.root_child.size();
    if (w.logs.size() < m) w.logs.resize(m);
    for (size_t k = 0; k < m; ++k) w.logs[k].clear();
    w.child_values.assign(m, 0.0);
}

// UtilityWalk::visit(0, 1.0).
void utility_parallel(const PcfrSolver& s, int player, const double* opponent, double* values) {
    Scratch& w = scratch();
    const double reach = 1.0;
    const bool chance = s.kind[0] == CHANCE;
    root_children(s, w, chance);
    const int m = static_cast<int>(w.root_child.size());
    const int p = chance ? -1 : s.player[0];
    const int offset = chance ? 0 : s.side[p].offset[s.infoset[0]];
    const double* strategy = chance ? nullptr : (p != player && opponent) ? opponent + offset : s.side[p].strategy + offset;
    for (int k = 0; k < m; ++k)
        w.root_reach.push_back(chance ? reach * s.chance_prob[s.chance_begin[0] + k]
                                      : (p != player ? reach * strategy[k] : reach * 1.0));
    Log* logs = w.logs.data();
    double* out = w.child_values.data();
    const int32_t* child = w.root_child.data();
    const double* child_reach = w.root_reach.data();
    for_each_task(m, [&](int k) {
        Scratch& t = scratch();
        reserve_stack(s, t);
        UtilityWalk walk{s, player, opponent, values, t.stack.data(), &logs[k]};
        out[k] = walk.visit(child[k], child_reach[k]);
    });
    for (int k = 0; k < m; ++k) replay_values(logs[k], values);
    if (!chance && p == player)
        for (int i = 0; i < m; ++i) values[offset + i] += reach * out[i];
    // The root's value (a compensated sum or a dot) is not used by any caller.
}

// PredictionWalk::visit(0, 1.0) for the walk `base` (its stack and log are per task).
void prediction_parallel(const PcfrSolver& s, const PredictionWalk& base) {
    if (base.memo_set[0]) return;
    Scratch& w = scratch();
    const double reach = 1.0;
    const bool chance = s.kind[0] == CHANCE;
    root_children(s, w, chance);
    const int m = static_cast<int>(w.root_child.size());
    const int player = base.player, p = chance ? -1 : s.player[0], set = chance ? -1 : s.infoset[0];
    const int offset = chance ? 0 : s.side[p].offset[set];
    for (int k = 0; k < m; ++k) {
        if (chance) w.root_reach.push_back(reach * s.chance_prob[s.chance_begin[0] + k]);
        else if (p == player) w.root_reach.push_back(reach);
        else w.root_reach.push_back(reach * s.side[player].previous_opponent[offset + k]);
    }
    Log* logs = w.logs.data();
    double* out = w.child_values.data();
    const int32_t* child = w.root_child.data();
    const double* child_reach = w.root_reach.data();
    for_each_task(m, [&](int k) {
        Scratch& t = scratch();
        reserve_stack(s, t);
        PredictionWalk walk = base;
        walk.stack = t.stack.data();
        walk.log = &logs[k];
        out[k] = walk.visit(child[k], child_reach[k]);
    });
    for (int k = 0; k < m; ++k) replay_values(logs[k], base.values);
    if (!chance && p == player) {
        const PcfrSide& side = s.side[p];
        if (base.in_level[set])
            for (int i = 0; i < m; ++i) base.values[offset + i] += reach * out[i];
        const double value = dot(side.strategy + offset, out, m);
        if (side.depth[set] > base.depth) {
            base.memo[0] = value;
            base.memo_set[0] = 1;
        }
    }
}

// GrowthWalk::visit(0, 1.0) for `walk` (the shared arrays).
void growth_parallel(const PcfrSolver& s, GrowthWalk& walk) {
    Scratch& w = scratch();
    const double reach = 1.0;
    const bool chance = s.kind[0] == CHANCE;
    root_children(s, w, chance);
    const int m = static_cast<int>(w.root_child.size());
    const int p = chance ? -1 : s.player[0], set = chance ? -1 : s.infoset[0];
    const int offset = chance ? 0 : s.side[p].offset[set];
    for (int k = 0; k < m; ++k)
        w.root_reach.push_back(chance ? reach * s.chance_prob[s.chance_begin[0] + k]
                                      : reach * s.side[p].strategy[offset + k]);
    Log* logs = w.logs.data();
    double* out = w.child_values.data();
    const int32_t* child = w.root_child.data();
    const double* child_reach = w.root_reach.data();
    for_each_task(m, [&](int k) {
        Scratch& t = scratch();
        reserve_stack(s, t);
        GrowthWalk task = walk;
        task.stack = t.stack.data();
        task.log = &logs[k];
        out[k] = task.visit(child[k], child_reach[k]);
    });
    for (int k = 0; k < m; ++k) walk.replay(logs[k]);
    if (!chance) {
        Log own;
        own.head.insert(own.head.end(), {p, set, offset, m});
        own.data.push_back(reach);
        for (int i = 0; i < m; ++i) own.data.push_back(p == 0 ? out[i] * 1.0 : out[i] * -1.0);
        walk.replay(own);
    }
}

// accumulate_visit for a subtree: the first visit of each set (in DFS order) and its own reach, into `log`.
void accumulate_log(const PcfrSolver& s, int player, int8_t* seen, std::vector<int32_t>& touched, Log& log, int node,
                    double own_reach) {
    const int8_t kind = s.kind[node];
    if (kind == TERMINAL) return;
    const int begin = s.child_begin[node], end = s.child_begin[node + 1];
    if (kind == DECISION && s.player[node] == player) {
        const PcfrSide& side = s.side[player];
        const int set = s.infoset[node];
        const double* strategy = side.strategy + side.offset[set];
        if (!seen[set]) {
            seen[set] = 1;
            touched.push_back(set);
            log.head.push_back(set);
            log.data.push_back(own_reach);
        }
        for (int i = 0; i < end - begin; ++i)
            accumulate_log(s, player, seen, touched, log, s.child[begin + i], own_reach * strategy[i]);
    } else {
        for (int k = begin; k < end; ++k) accumulate_log(s, player, seen, touched, log, s.child[k], own_reach);
    }
}

// accumulate_visit(0, 1.0) with the global first-visit flags `seen`.
void accumulate_parallel(const PcfrSolver& s, int player, double weight, int8_t* seen) {
    Scratch& w = scratch();
    const PcfrSide& side = s.side[player];
    const double own_reach = 1.0;
    root_children(s, w, false);
    const int m = static_cast<int>(w.root_child.size());
    const bool own = s.kind[0] == DECISION && s.player[0] == player;
    if (own) {
        const int set = s.infoset[0], offset = side.offset[set];
        if (!seen[set]) {
            const double scale = weight * own_reach;
            for (int i = 0; i < m; ++i) side.sums[offset + i] += scale * side.strategy[offset + i];
            seen[set] = 1;
        }
        for (int i = 0; i < m; ++i) w.root_reach.push_back(own_reach * side.strategy[offset + i]);
    } else {
        for (int i = 0; i < m; ++i) w.root_reach.push_back(own_reach);
    }
    Log* logs = w.logs.data();
    const int32_t* child = w.root_child.data();
    const double* child_reach = w.root_reach.data();
    const size_t sets = static_cast<size_t>(side.n_sets) + 1;
    for_each_task(m, [&](int k) {
        Scratch& t = scratch();
        if (t.seen_local.size() < sets) t.seen_local.resize(sets, 0);
        accumulate_log(s, player, t.seen_local.data(), t.touched, logs[k], child[k], child_reach[k]);
        for (int32_t set : t.touched) t.seen_local[set] = 0;
        t.touched.clear();
    });
    for (int k = 0; k < m; ++k) {
        const Log& log = logs[k];
        for (size_t e = 0; e < log.head.size(); ++e) {
            const int set = log.head[e];
            if (seen[set]) continue;
            const int offset = side.offset[set], n = side.offset[set + 1] - offset;
            const double scale = weight * log.data[e];
            for (int i = 0; i < n; ++i) side.sums[offset + i] += scale * side.strategy[offset + i];
            seen[set] = 1;
        }
    }
}

// values[k] = behavioral_visit(nodes[k]) for k < n, the subtrees in parallel when the tree is large.
void behavioral_many(const PcfrSolver& s, int n, const int32_t* nodes, double* values) {
    if (g_threads > 1 && s.n_nodes >= g_parallel_nodes && n >= 2) {
        for_each_task(n, [&](int k) { values[k] = behavioral_visit(s, nodes[k]); });
        return;
    }
    for (int k = 0; k < n; ++k) values[k] = behavioral_visit(s, nodes[k]);
}

}  // namespace

extern "C" {

int pcfr_utilities(const PcfrSolver* s, int player, const double* opponent, double* values) {
    Scratch& w = scratch();
    reserve_stack(*s, w);
    for (int a = 0; a < total_actions(s->side[player]); ++a) values[a] = 0.0;
    if (parallel_root(*s)) {
        utility_parallel(*s, player, opponent, values);
        return 0;
    }
    UtilityWalk walk{*s, player, opponent, values, w.stack.data()};
    walk.visit(0, 1.0);
    return 0;
}

int pcfr_prepare(const PcfrSolver* s, int player) { return prepare(*s, player); }

int pcfr_observe(const PcfrSolver* s, int player) { return observe(*s, player); }

int pcfr_accumulate_average(const PcfrSolver* s, int player, double weight) {
    Scratch& w = scratch();
    w.seen.assign(s->side[player].n_sets + 1, 0);
    if (parallel_root(*s)) accumulate_parallel(*s, player, weight, w.seen.data());
    else accumulate_visit(*s, player, weight, w.seen.data(), 0, 1.0);
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

// PCFRPlus.run(n): n consecutive pcfr_step calls from `rounds` completed rounds; *done = the rounds completed (n
// unless a step failed). With `trace`, row k (the actions of trace_set of trace_player) receives that set's
// published strategy after round k, i.e. what policy()[trace_player][key] returns after each step.
int pcfr_run(const PcfrSolver* s, int64_t rounds, int64_t n, int64_t* done, int trace_player, int trace_set,
             double* trace) {
    *done = 0;
    for (int64_t k = 0; k < n; ++k) {
        const int code = pcfr_step(s, rounds + k);
        if (code) return code;
        *done = k + 1;
        if (trace) {
            const PcfrSide& side = s->side[trace_player];
            const int offset = side.offset[trace_set], width = side.offset[trace_set + 1] - offset;
            for (int i = 0; i < width; ++i) trace[k * width + i] = side.strategy[offset + i];
        }
    }
    return 0;
}

// OneSidedExpansion.utilities on the flat tree: conditional[p] (player p's actions) receives, per set, the
// reach-weighted mean of the signed action values, or their plain mean over the set's nodes when it has no reach.
int pcfr_growth_utilities(const PcfrSolver* s, double* conditional0, double* conditional1) {
    Scratch& w = scratch();
    reserve_stack(*s, w);
    const int a0 = total_actions(s->side[0]), a1 = total_actions(s->side[1]);
    const int n0 = s->side[0].n_sets, n1 = s->side[1].n_sets;
    w.values.assign(a0 + a1 + 1, 0.0);
    w.fallback.assign(a0 + a1 + 1, 0.0);
    w.compensation.assign(a0 + a1 + 1, 0.0);
    w.started.assign(a0 + a1 + 1, 0);
    w.mass.assign(n0 + n1 + 1, 0.0);
    w.count.assign(n0 + n1 + 1, 0);
    GrowthWalk walk{*s, {w.values.data(), w.values.data() + a0}, {w.mass.data(), w.mass.data() + n0},
                    {w.fallback.data(), w.fallback.data() + a0}, {w.compensation.data(), w.compensation.data() + a0},
                    {w.started.data(), w.started.data() + a0}, {w.count.data(), w.count.data() + n0},
                    w.stack.data()};
    if (parallel_root(*s)) growth_parallel(*s, walk);
    else walk.visit(0, 1.0);
    double* conditional[2] = {conditional0, conditional1};
    for (int p = 0; p < 2; ++p) {
        const PcfrSide& side = s->side[p];
        for (int set = 0; set < side.n_sets; ++set) {
            const double mass = walk.mass[p][set];
            for (int a = side.offset[set]; a < side.offset[set + 1]; ++a) {
                if (mass > 0) {
                    conditional[p][a] = walk.totals[p][a] / mass;
                } else {
                    const Compensated term{walk.fallback[p][a], walk.compensation[p][a], !walk.started[p][a]};
                    conditional[p][a] = term.value() / static_cast<double>(walk.count[p][set]);
                }
            }
        }
    }
    return 0;
}

// value_walk of the subtrees at nodes[0..n): values[k] = the behavioral value of the subtree at nodes[k] under the
// published strategies (what toy_games.behavioral_value returns for it with PCFRPlus.policy()).
int pcfr_behavioral_values(const PcfrSolver* s, int32_t n, const int32_t* nodes, double* values) {
    behavioral_many(*s, n, nodes, values);
    return 0;
}

int64_t pcfr_parallel_walks() { return g_parallel_walks; }

// The number of threads of the root-parallel walks (at least 1) and the smallest tree (nodes) they run on
// (negative: unchanged); returns the previous number of threads.
int pcfr_set_threads(int n, int min_nodes) {
    const int previous = g_threads;
    g_threads = n < 1 ? 1 : n;
    if (min_nodes >= 0) g_parallel_nodes = min_nodes;
    return previous;
}

}  // extern "C"

namespace {

double fsum(const double* items, int n, std::vector<double>& partials) {
    // CPython 3.12 math.fsum (msum with exact partials, then half-even rounding across partials) for finite items.
    partials.clear();
    for (int k = 0; k < n; ++k) {
        double x = items[k];
        size_t i = 0;
        for (size_t j = 0; j < partials.size(); ++j) {
            double y = partials[j];
            if (std::fabs(x) < std::fabs(y)) {
                const double t = x;
                x = y;
                y = t;
            }
            const double hi = x + y;
            const double yr = hi - x;
            const double lo = y - yr;
            if (lo != 0.0) partials[i++] = lo;
            x = hi;
        }
        partials.resize(i);
        if (x != 0.0) partials.push_back(x);
    }
    double hi = 0.0, lo = 0.0;
    size_t m = partials.size();
    if (m > 0) {
        hi = partials[--m];
        while (m > 0) {
            const double x = hi, y = partials[--m];
            hi = x + y;
            const double yr = hi - x;
            lo = y - yr;
            if (lo != 0.0) break;
        }
        if (m > 0 && ((lo < 0.0 && partials[m - 1] < 0.0) || (lo > 0.0 && partials[m - 1] > 0.0))) {
            const double y = lo * 2.0;
            const double x = hi + y;
            const double yr = x - hi;
            if (y == yr) hi = x;
        }
    }
    return hi;
}

// PredictiveRMPlus.observe / next_strategy on one minimizer's arrays (np.maximum(x, 0) is x >= 0 ? x : 0 here:
// regrets and theta never meet -0.0 or NaN, see the D2 notes). Codes: -2 / -1 as in pcfr_step, -3 a non-finite
// utility, -4 a non-finite prediction.
int prm_observe(double* regrets, const double* strategy, double* previous, int8_t* pending, const double* u, int n) {
    if (!*pending) return -2;
    for (int i = 0; i < n; ++i)
        if (!std::isfinite(u[i])) return -3;
    const double baseline = dot(strategy, u, n);
    for (int i = 0; i < n; ++i) {
        const double x = regrets[i] + u[i] - baseline;
        regrets[i] = x >= 0.0 ? x : 0.0;
        previous[i] = u[i];
    }
    *pending = 0;
    return 0;
}

int prm_next(const double* regrets, double* strategy, const double* previous, int8_t* pending, int predictive, int n,
             double* theta, double* zeros) {
    if (*pending) return -1;
    for (int i = 0; i < n; ++i)
        if (!std::isfinite(previous[i])) return -4;
    const double* prediction = previous;
    if (!predictive) {
        for (int i = 0; i < n; ++i) zeros[i] = 0.0;
        prediction = zeros;
    }
    const double baseline = dot(strategy, prediction, n);
    for (int i = 0; i < n; ++i) {
        const double x = regrets[i] + prediction[i] - baseline;
        theta[i] = x >= 0.0 ? x : 0.0;
    }
    const double total = pairwise_sum(theta, n);
    for (int i = 0; i < n; ++i) strategy[i] = total > 0.0 ? theta[i] / total : 1.0 / n;
    *pending = 1;
    return 0;
}

// BlendedGadgetControl.update_from_solver after one round: values, R_J and selector feedback, the blend, and the
// root's chance probabilities rewritten (BlendedGadgetControl.apply) in the solver's chance_prob array.
int control_advance(const PcfrSolver& s, const GadgetControl& c, std::vector<double>& scratch,
                    std::vector<double>& partials) {
    const int g = c.n_groups;
    behavioral_many(s, c.n_roots, c.root_node, c.values);
    scratch.resize(static_cast<size_t>(3 * g) + 8);
    double* terms = scratch.data();
    for (int j = 0; j < g; ++j) {
        int k = 0;
        for (int q = c.group_begin[j]; q < c.group_begin[j + 1]; ++q, ++k) {
            const int r = c.group_roots[q];
            terms[k] = c.reach_mass[r] * c.values[r];
        }
        c.entering[j] = fsum(terms, k, partials) / c.group_mass[j];
        c.margins[j] = c.entering[j] - c.alternate[j];
    }
    double u[2], theta[2], zeros[2];
    int code;
    for (int j = 0; j < g; ++j) {
        u[0] = -c.entering[j];
        u[1] = -c.alternate[j];
        double* regrets = c.entry_regrets + 2 * j;
        double* strategy = c.entry_strategy + 2 * j;
        double* previous = c.entry_previous + 2 * j;
        if ((code = prm_observe(regrets, strategy, previous, c.entry_pending + j, u, 2))) return code;
        if ((code = prm_next(regrets, strategy, previous, c.entry_pending + j, c.predictive, 2, theta, zeros)))
            return code;
        c.pi_resolve[j] = strategy[0];
    }
    double* selector_u = terms;
    double* selector_theta = terms + g;
    double* selector_zeros = terms + 2 * g;
    for (int j = 0; j < g; ++j) selector_u[j] = -c.margins[j];
    if ((code = prm_observe(c.selector_regrets, c.selector_strategy, c.selector_previous, c.selector_pending,
                            selector_u, g)))
        return code;
    if ((code = prm_next(c.selector_regrets, c.selector_strategy, c.selector_previous, c.selector_pending,
                         c.predictive, g, selector_theta, selector_zeros)))
        return code;
    for (int j = 0; j < g; ++j) c.pi_maxmargin[j] = c.selector_strategy[j];
    double p_max = c.pi_resolve[0];  // Python max(): the first of the largest
    for (int j = 1; j < g; ++j)
        if (c.pi_resolve[j] > p_max) p_max = c.pi_resolve[j];
    *c.p_max = p_max;
    double* probabilities = const_cast<double*>(s.chance_prob);
    for (int j = 0; j < g; ++j) {
        const double entering = p_max * c.alpha[j] * c.pi_resolve[j] + (1 - p_max) * c.pi_maxmargin[j];
        for (int q = c.group_begin[j]; q < c.group_begin[j + 1]; ++q) {
            const int r = c.group_roots[q];
            probabilities[c.root_slot[r]] = entering * c.reach_mass[r] / c.group_mass[j];
        }
        probabilities[c.exit_slot[j]] = p_max * c.alpha[j] * (1 - c.pi_resolve[j]);
    }
    return 0;
}

}  // namespace

extern "C" {

// The subgame agent's gadget rounds: n times pcfr_step (from `rounds` completed) followed by control_advance, with
// pcfr_run's done / trace, and p_max after each round in p_max_trace[k]. With c->history_width > 0, history row k
// receives values (n_roots), margins, pi_resolve, pi_maxmargin (n_groups each), p_max and the root's whole
// chance_prob range after round k (tests).
int pcfr_run_gadget(const PcfrSolver* s, const GadgetControl* c, int64_t rounds, int64_t n, int64_t* done,
                    int trace_player, int trace_set, double* trace, double* p_max_trace, double* history) {
    std::vector<double> scratch, partials;
    *done = 0;
    for (int64_t k = 0; k < n; ++k) {
        int code = pcfr_step(s, rounds + k);
        if (code) return code;
        *done = k + 1;
        if (trace) {
            const PcfrSide& side = s->side[trace_player];
            const int offset = side.offset[trace_set], width = side.offset[trace_set + 1] - offset;
            for (int i = 0; i < width; ++i) trace[k * width + i] = side.strategy[offset + i];
        }
        if ((code = control_advance(*s, *c, scratch, partials))) return code;
        p_max_trace[k] = *c->p_max;
        if (history && c->history_width > 0) {
            double* row = history + k * c->history_width;
            const int g = c->n_groups;
            for (int r = 0; r < c->n_roots; ++r) *row++ = c->values[r];
            for (int j = 0; j < g; ++j) *row++ = c->margins[j];
            for (int j = 0; j < g; ++j) *row++ = c->pi_resolve[j];
            for (int j = 0; j < g; ++j) *row++ = c->pi_maxmargin[j];
            *row++ = *c->p_max;
            for (int q = s->chance_begin[0]; q < s->chance_begin[1]; ++q) *row++ = s->chance_prob[q];
        }
    }
    return 0;
}

}  // extern "C"
