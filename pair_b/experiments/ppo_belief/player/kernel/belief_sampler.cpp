// A capped sample of the positions that fit one player's observations, for PPO self-play.
//
// The rules are the team's and are used unchanged: Board, View, moves, play, matches, visible and
// canonical come from pair_a_prep/zs21/native/inference.cpp, which this file includes (build.py passes
// the repository root as an include folder). This file adds only the bookkeeping: which boards are
// kept, with what weight, and the 32-plane picture.
//
// A sampler belongs to one player. It is given that player's view after every ply and, after the
// player's own plies, the move the player made. It never receives the true board: bs_step takes the
// true board only to compute both players' views from it (zs_observe), and passes each sampler its
// own view. tests/training/test_kernel.py checks that this gives the same sample as feeding views directly.
//
//   exact      While the sample is under the cap it holds every position that fits the player's
//              observations, each weighted by the number of move histories that reach it (the
//              team's belief is uniform over histories).
//   capped     Above the cap, `cap` histories are drawn in proportion to those weights. The sample
//              can then miss the true position.
//   repaired   When no sampled position has a successor that fits a new view, every kept board is
//              rebuilt to fit the view: the squares in view are overwritten with what the player
//              sees, and the enemy pieces out of view keep their squares where the view allows it.
//              A rebuilt board is kept only if the team's `matches` accepts it.
//   blank      If no rebuilt board is accepted, the picture shows the view only until a later
//              repair succeeds.
#include "pair_a_prep/zs21/native/inference.cpp"

#include <cmath>

namespace {

struct Sampler {
    int viewer = 1, cap = 1024, ply = 0, capture = -1;
    bool blank = false;
    U own_rights = 0;             // the player's own castling rights (rook squares), known exactly
    double log2_population = 0;   // log2 of the estimated number of histories that fit
    std::mt19937_64 rng;
    View view{};                  // the player's newest view
    std::vector<Board> boards, next_boards;
    std::vector<double> weight, half, next_weight, next_half;  // half: mean halfmove clock
    std::unordered_map<Board, size_t, Hash, Equal> index;
    unsigned updates = 0, prunes = 0, repairs = 0, blanks = 0;
};

U own_of(const Board& b, int viewer) { U occ = occupied(b); return viewer ? b.white : occ & ~b.white; }

void clear_next(Sampler& s) {
    s.index.clear(); s.next_boards.clear(); s.next_weight.clear(); s.next_half.clear();
}

void add(Sampler& s, const Board& b, double w, double h) {
    auto found = s.index.find(b);
    if (found == s.index.end()) {
        s.index.emplace(b, s.next_boards.size());
        s.next_boards.push_back(b); s.next_weight.push_back(w); s.next_half.push_back(w * h);
    } else {
        s.next_weight[found->second] += w; s.next_half[found->second] += w * h;
    }
}

// Make the collected boards the sample. Returns the sum of their weights before normalising.
double commit(Sampler& s) {
    double total = 0;
    for (double w : s.next_weight) total += w;
    for (size_t i = 0; i < s.next_weight.size(); ++i) { s.next_half[i] /= s.next_weight[i]; s.next_weight[i] /= total; }
    s.boards.swap(s.next_boards); s.weight.swap(s.next_weight); s.half.swap(s.next_half);
    return total;
}

// Every successor of every kept board that fits the view. False, with the sample unchanged, if none does.
bool expand(Sampler& s, const View& v, int own_move) {
    MatchView expected(v);
    clear_next(s);
    const std::vector<int> single{own_move};
    for (size_t i = 0; i < s.boards.size(); ++i) {
        const Board& parent = s.boards[i];
        const bool ours = int(parent.turn) == s.viewer;
        if (ours != (own_move >= 0)) continue;
        const std::vector<int> actions = ours ? single : moves(parent, int(parent.turn), false);
        for (int a : actions) {
            const int from = a & 63;
            if (ours && !(own_of(parent, s.viewer) & bit(from))) continue;
            const bool pawn = (parent.pieces[0] & bit(from)) != 0;
            int captured;
            Board child = play(parent, a, captured);
            if (!matches(child, expected, s.viewer, ours ? -1 : captured)) continue;
            add(s, child, s.weight[i], pawn || captured >= 0 ? 0.0 : std::min(s.half[i] + 1.0, 100.0));
        }
    }
    if (s.next_boards.empty()) return false;
    s.log2_population += std::log2(commit(s));
    return true;
}

// Draw `cap` histories in proportion to the weights (systematic resampling); a board drawn k times
// keeps weight k / cap.
void resample(Sampler& s) {
    const double step = 1.0 / s.cap;
    double u = std::uniform_real_distribution<double>(0.0, step)(s.rng), cumulative = 0;
    size_t kept = 0;
    int drawn = 0;
    for (size_t i = 0; i < s.boards.size(); ++i) {
        cumulative += s.weight[i];
        int count = 0;
        while (u < cumulative && drawn < s.cap) { ++count; ++drawn; u += step; }
        if (count) { s.boards[kept] = s.boards[i]; s.half[kept] = s.half[i]; s.weight[kept] = count; ++kept; }
    }
    s.boards.resize(kept); s.half.resize(kept); s.weight.resize(kept);
    for (double& w : s.weight) w /= drawn;
}

int pick(std::mt19937_64& rng, U set) {  // a random member of a set of squares that is not empty
    int skip = int(rng() % U(__builtin_popcountll(set)));
    while (skip--) set &= set - 1;
    return __builtin_ctzll(set);
}

const U EDGE_RANKS = 0xff000000000000ffULL;  // no pawn stands on the first or the last rank

// Rebuild every kept board so that it fits the view. False, with the sample unchanged, if none fits.
bool repair(Sampler& s, const View& v, const View& before, int own_move) {
    const int viewer = s.viewer;
    MatchView expected(v);
    const U mask = v.mask, seen = occupied(v.contents), own = own_of(v.contents, viewer), enemy_seen = seen ^ own;
    // What the player's own pawns imply about squares out of view: an enemy piece on a square a pawn
    // attacks would be in view, and a pawn that cannot step forward is blocked by an unseen piece.
    U forbidden = 0, required = 0, pawns = v.contents.pieces[0] & own;
    while (pawns) {
        const int f = pop(pawns), r = f / 8, c = f % 8, d = viewer ? 1 : -1, t = f + d * 8;
        if (t < 0 || t > 63) continue;
        for (int dc : {-1, 1}) if (c + dc >= 0 && c + dc < 8) forbidden |= bit(t + dc);
        if (!(mask & bit(t))) required |= bit(t);
        else if (!(seen & bit(t)) && r == (viewer ? 1 : 6) && !(mask & bit(t + d * 8))) required |= bit(t + d * 8);
    }
    forbidden &= ~mask;
    if (own_move < 0 && v.captured >= 0 && !(mask & bit(v.captured))) required |= bit(v.captured);
    // The enemy piece the player's own move took, as the previous view showed it.
    int taken = -1, taken_square = -1;
    if (own_move >= 0) {
        const int from = own_move & 63, to = (own_move >> 6) & 63;
        const U before_seen = occupied(before.contents), before_own = own_of(before.contents, viewer);
        int target = to;
        if ((before.contents.pieces[0] & before_own & bit(from)) && from % 8 != to % 8 && !(before_seen & bit(to)))
            target = to + (viewer ? -8 : 8);  // en passant
        if ((before_seen ^ before_own) & bit(target)) { taken = type(before.contents, target); taken_square = target; }
    }
    // En passant: the capture the player may make now, or the right the player's double step gave.
    U ep = 64;
    if (int(v.contents.turn) == viewer) {
        for (int i = 0; i < v.count; ++i) {
            const int from = v.moves[i] & 63, to = (v.moves[i] >> 6) & 63;
            if ((v.contents.pieces[0] & own & bit(from)) && from % 8 != to % 8 && !(seen & bit(to))) ep = U(to);
        }
    } else if (own_move >= 0) {
        const int from = own_move & 63, to = (own_move >> 6) & 63;
        if ((v.contents.pieces[0] & own & bit(to)) && std::abs(to - from) == 16) ep = U((from + to) / 2);
    }
    const U enemy_corners = viewer ? (bit(56) | bit(63)) : (bit(0) | bit(7));

    clear_next(s);
    std::vector<int> pool;
    for (size_t i = 0; i < s.boards.size(); ++i) {
        const Board& p = s.boards[i];
        const U p_enemy = occupied(p) ^ own_of(p, viewer);
        U hidden[6];
        int target[6];
        for (int k = 0; k < 6; ++k) {
            target[k] = __builtin_popcountll(p.pieces[k] & p_enemy);
            hidden[k] = p.pieces[k] & p_enemy & ~mask;
            if (taken_square >= 0) hidden[k] &= ~bit(taken_square);
        }
        if (taken >= 0 && target[taken] > 0) --target[taken];
        // Keep this board's count of each enemy piece type: a piece that came into view replaces an
        // unseen one of its type (or an unseen pawn, if it may have promoted); a piece that left the
        // view is put back out of view.
        pool.clear();
        for (int k : {1, 2, 3, 4, 5, 0}) {
            int surplus = __builtin_popcountll(v.contents.pieces[k] & enemy_seen) + __builtin_popcountll(hidden[k]) - target[k];
            while (surplus > 0 && hidden[k]) { hidden[k] &= ~bit(pick(s.rng, hidden[k])); --surplus; }
            if (k >= 1 && k <= 4)
                while (surplus > 0 && hidden[0]) { hidden[0] &= ~bit(pick(s.rng, hidden[0])); --target[0]; --surplus; }
            for (; surplus < 0; ++surplus) pool.push_back(k);
        }
        for (int k = 0; k < 6; ++k) {
            U bad = hidden[k] & forbidden;
            hidden[k] &= ~forbidden;
            while (bad) { pop(bad); pool.push_back(k); }
        }
        U occ = seen;
        for (int k = 0; k < 6; ++k) occ |= hidden[k];
        bool possible = true;
        U missing = required & ~occ;
        while (missing && possible) {
            const int square = pop(missing);
            const bool edge = (EDGE_RANKS & bit(square)) != 0;
            int chosen = -1;
            for (size_t j = 0; j < pool.size() && chosen < 0; ++j)
                if (!(edge && pool[j] == 0)) { chosen = pool[j]; pool.erase(pool.begin() + long(j)); }
            if (chosen < 0) {  // move an unseen enemy piece from a square where nothing requires one
                U movable = 0;
                for (int k = edge ? 1 : 0; k < 6; ++k) movable |= hidden[k] & ~required;
                if (!movable) { possible = false; break; }
                const int source = pick(s.rng, movable);
                for (int k = 0; k < 6; ++k) if (hidden[k] & bit(source)) { chosen = k; hidden[k] &= ~bit(source); }
                occ &= ~bit(source);
            }
            hidden[chosen] |= bit(square); occ |= bit(square);
        }
        if (!possible) continue;
        for (int k : pool) {
            U allowed = ~mask & ~occ & ~forbidden;
            if (k == 0) allowed &= ~EDGE_RANKS;
            if (!allowed) continue;
            const int square = pick(s.rng, allowed);
            hidden[k] |= bit(square); occ |= bit(square);
        }
        Board b{};
        U hidden_all = 0;
        for (int k = 0; k < 6; ++k) { b.pieces[k] = v.contents.pieces[k] | hidden[k]; hidden_all |= hidden[k]; }
        b.white = viewer ? own : (enemy_seen | hidden_all);
        b.rights = s.own_rights | (p.rights & enemy_corners);
        b.turn = v.contents.turn;
        b.ep = ep;
        canonical(b);
        if (!matches(b, expected, viewer, v.captured)) continue;
        add(s, b, s.weight[i], std::min(s.half[i] + 1.0, 100.0));
    }
    if (s.next_boards.empty()) return false;
    commit(s);
    return true;
}

// 0: successors fit; 1: the sample was repaired; 2: blank.
int update(Sampler& s, const View& v, int own_move, int ply) {
    const View before = s.view;
    // The player's own castling rights last while its king and that rook stay at home.
    const U own = own_of(v.contents, s.viewer), king = v.contents.pieces[5] & own, rooks = v.contents.pieces[3] & own;
    const U corners = s.viewer ? (bit(0) | bit(7)) : (bit(56) | bit(63));
    s.own_rights &= rooks & corners;
    if (!(king & bit(s.viewer ? 4 : 60))) s.own_rights = 0;
    int status = 0;
    bool fits = false;
    try {
        fits = !s.blank && expand(s, v, own_move);
        if (!fits) {
            fits = repair(s, v, before, own_move);
            status = fits ? 1 : 2;
        }
        if (fits && int(s.boards.size()) > s.cap) { resample(s); ++s.prunes; }
    } catch (...) { fits = false; status = 2; }
    s.blank = !fits;
    s.repairs += status == 1; s.blanks += status == 2; ++s.updates;
    s.view = v; s.ply = ply; s.capture = own_move < 0 ? v.captured : -1;
    return status;
}

}  // namespace

extern "C" {

ZS_EXPORT void* bs_create() { try { return new Sampler(); } catch (...) { return nullptr; } }
ZS_EXPORT void bs_destroy(Sampler* s) { delete s; }

// A new game: the start position is known to both players.
ZS_EXPORT void bs_reset(Sampler* s, const Board* start, int viewer, U seed, int cap) {
    Board b = *start;
    canonical(b);
    s->viewer = viewer; s->cap = cap; s->ply = 0; s->capture = -1; s->blank = false;
    s->own_rights = b.rights & (viewer ? (bit(0) | bit(7)) : (bit(56) | bit(63)));
    s->log2_population = 0;
    s->rng.seed(seed);
    s->boards.assign(1, b); s->weight.assign(1, 1.0); s->half.assign(1, 0.0);
    s->updates = s->prunes = s->repairs = s->blanks = 0;
    zs_observe(&b, viewer, -1, &s->view);
}

// The player's view after a ply; own_move is the player's move that led to it, or -1.
ZS_EXPORT int bs_update(Sampler* s, const View* v, int own_move, int ply) { return update(*s, *v, own_move, ply); }

// Self-play: both players' views are computed from the true board after `mover` played `move`, and
// each sampler is given its own view. `captured` is the square of the piece the move took, or -1.
ZS_EXPORT void bs_step(Sampler* white, Sampler* black, const Board* after, int move, int captured, int mover, int ply) {
    for (Sampler* s : {white, black}) {
        const bool own = s->viewer == mover;
        View v;
        zs_observe(after, s->viewer, own ? -1 : captured, &v);
        update(*s, v, own ? move : -1, ply);
    }
}

// The picture for the player to move: fow_shared.features.PLANE_NAMES, collapsed to one board as
// pairb.belief_ablation's "marginals" mode does, 32 planes of 64 cells, each 0..255. Cell = square for
// White and square ^ 56 for Black, so the player's own side is always the first row.
ZS_EXPORT void bs_planes(Sampler* s, unsigned char* out) {
    static thread_local float p[32][64];
    std::memset(p, 0, sizeof(p));
    const View& v = s->view;
    const int viewer = s->viewer, flip = viewer ? 0 : 56;
    const U seen = occupied(v.contents), own = own_of(v.contents, viewer), enemy_seen = seen ^ own;
    for (int k = 0; k < 6; ++k) {
        for (U bits = v.contents.pieces[k] & own; bits;) p[k][pop(bits) ^ flip] = 1;
        for (U bits = v.contents.pieces[k] & enemy_seen; bits;) { const int c = pop(bits) ^ flip; p[6 + k][c] = 1; p[13][c] = 1; }
    }
    for (U bits = v.mask; bits;) p[12][pop(bits) ^ flip] = 1;
    if (!s->blank) {
        const U k_side = bit(viewer ? 63 : 7), q_side = bit(viewer ? 56 : 0);
        double k_right = 0, q_right = 0, clock = 0;
        for (size_t i = 0; i < s->boards.size(); ++i) {
            const Board& b = s->boards[i];
            const float w = float(s->weight[i]);
            const U b_own = own_of(b, viewer), b_enemy = occupied(b) ^ b_own;
            for (int k = 0; k < 6; ++k) for (U bits = b.pieces[k] & b_enemy; bits;) p[14 + k][pop(bits) ^ flip] += w;
            const U theirs = visible(b, !viewer);
            for (U bits = theirs; bits;) p[21][pop(bits) ^ flip] += w;
            for (U bits = theirs & b_own; bits;) p[22][pop(bits) ^ flip] += w;
            if (b.rights & k_side) k_right += s->weight[i];
            if (b.rights & q_side) q_right += s->weight[i];
            clock += s->weight[i] * s->half[i];
        }
        const float population = float(std::min(std::max(s->log2_population, 0.0) / 15, 1.0));
        for (int c = 0; c < 64; ++c) {
            p[20][c] = population; p[28][c] = float(k_right); p[29][c] = float(q_right);
            p[31][c] = float(std::min(clock / 100, 1.0));
        }
    } else {
        for (int k = 0; k < 6; ++k) for (U bits = v.contents.pieces[k] & enemy_seen; bits;) p[14 + k][pop(bits) ^ flip] = 1;
    }
    if (s->capture >= 0) p[23][s->capture ^ flip] = 1;
    const float ply = std::min(s->ply / 200.0f, 1.0f);
    const bool k_own = (s->own_rights & bit(viewer ? 7 : 63)) != 0, q_own = (s->own_rights & bit(viewer ? 0 : 56)) != 0;
    for (int c = 0; c < 64; ++c) { p[24][c] = ply; p[26][c] = k_own; p[27][c] = q_own; }
    if (int(v.contents.turn) == viewer)
        for (int i = 0; i < v.count; ++i) {
            const int from = v.moves[i] & 63, to = (v.moves[i] >> 6) & 63;
            if ((v.contents.pieces[0] & own & bit(from)) && from % 8 != to % 8 && !(seen & bit(to))) p[30][to ^ flip] = 1;
        }
    for (int k = 0; k < 32; ++k)
        for (int c = 0; c < 64; ++c)
            out[k * 64 + c] = (unsigned char)std::lround(255.0f * std::min(std::max(p[k][c], 0.0f), 1.0f));
}

// For tests and diagnostics only. The player never uses these.
ZS_EXPORT int bs_count(Sampler* s) { return s->blank ? 0 : int(s->boards.size()); }
ZS_EXPORT int bs_get(Sampler* s, int i, Board* board, double* weight, double* half) {
    if (i < 0 || i >= int(s->boards.size())) return 0;
    *board = s->boards[size_t(i)]; *weight = s->weight[size_t(i)]; *half = s->half[size_t(i)];
    return 1;
}
ZS_EXPORT double bs_log2_population(Sampler* s) { return s->log2_population; }
ZS_EXPORT void bs_counters(Sampler* s, unsigned* out) {
    out[0] = s->updates; out[1] = s->prunes; out[2] = s->repairs; out[3] = s->blanks; out[4] = s->blank;
    out[5] = unsigned(s->boards.size());
}
// How many kept boards do not fit the newest view (0 unless there is a fault).
ZS_EXPORT int bs_check(Sampler* s) {
    if (s->blank) return 0;
    MatchView expected(s->view);
    int wrong = 0;
    for (const Board& b : s->boards) wrong += !matches(b, expected, s->viewer, s->view.captured);
    return wrong;
}
// The weight the sample gives to a position (0 if it is not kept): for measuring, with the true board.
ZS_EXPORT double bs_weight_of(Sampler* s, const Board* board) {
    if (s->blank) return 0;
    Board b = *board;
    canonical(b);
    for (size_t i = 0; i < s->boards.size(); ++i) if (same(s->boards[i], b)) return s->weight[i];
    return 0;
}
ZS_EXPORT void bs_view(Sampler* s, View* out) { *out = s->view; }

}  // extern "C"
