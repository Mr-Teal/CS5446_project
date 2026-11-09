// Native data path of pairb.belief_evaluator.BeliefNetworkEvaluator.evaluate_children; the Python path stays the
// oracle. For one parent it lists the fog-legal moves in fow_shared.values.fog_legal_moves order (python-chess
// pseudo-legal order, fog-only castling appended), plays each (rk_play), decides it by the fog-of-war rules as
// pairb.values.rule_value does, and encodes it as fow_shared.features.encode_belief encodes the one-board belief
// evaluate_children builds (pairb.belief_evaluator._alone). Reuses rules_kernel.cpp (board layout, attack masks,
// play, castling-right cleaning, effective en passant, the visibility rule, FEN). See native_port_log.md, B2.
#include "rules_kernel.cpp"

namespace lk {

constexpr int PLANES = 32, CELLS = PLANES * 64, MAX_CHILDREN = 256;

static U pawn_attacks(int square, int color) {
    // python-chess BB_PAWN_ATTACKS[color][square]
    int r = square / 8 + (color ? 1 : -1), c = square % 8;
    U out = 0;
    if (r < 0 || r > 7) return 0;
    for (int dc : {-1, 1}) if (c + dc >= 0 && c + dc < 8) out |= bit(r * 8 + c + dc);
    return out;
}

static U slide(int square, U occ, int first, int last) {
    U targets = 0;
    for (int i = first; i < last; ++i) {
        U ray = attacks.ray[square][i], blockers = ray & occ;
        if (blockers) {
            int stop = i % 2 ? 63 - __builtin_clzll(blockers) : __builtin_ctzll(blockers);
            ray ^= attacks.ray[stop][i];
        }
        targets |= ray;
    }
    return targets;
}

static U colour(const Board& b, int color) { return color ? b.white : occupied(b) & ~b.white; }

static U attackers(const Board& b, int color, int square, U occ) {
    // python-chess Board.attackers_mask(color, square, occupied): piece sets of the board, sliders through `occ`.
    U a = (attacks.king[square] & b.pieces[5]) | (attacks.knight[square] & b.pieces[1])
        | (slide(square, occ, 0, 4) & (b.pieces[3] | b.pieces[4]))
        | (slide(square, occ, 4, 8) & (b.pieces[2] | b.pieces[4]))
        | (pawn_attacks(square, !color) & b.pieces[0]);
    return a & colour(b, color);
}

static U between(int a, int b) {
    // Squares strictly between two squares of one rank (all python-chess castling paths lie on the back rank).
    U out = 0;
    for (int s = std::min(a, b) + 1; s < std::max(a, b); ++s) out |= bit(s);
    return out;
}

static int msb(U v) { return 63 - __builtin_clzll(v); }

static void add_pawn(int* out, int& n, int from, int to) {
    if (to / 8 == 0 || to / 8 == 7) for (int p : {5, 4, 3, 2}) out[n++] = enc(from, to, p);  // Q, R, B, N
    else out[n++] = enc(from, to);
}

static int fog_moves(const Board& b, int* out) {
    // fow_shared.values.fog_legal_moves without the terminal check (_available_fog_moves), in its order:
    // python-chess generate_pseudo_legal_moves, then castling that python-chess refuses for attacked squares.
    // `b.rights` must be cleaned (rk::clean_rights), as python-chess's are after FEN parsing or any push.
    int n = 0, color = int(b.turn);
    U occ = occupied(b), own = colour(b, color), enemy = occ ^ own;
    for (U pieces = own & ~b.pieces[0]; pieces;) {  // piece moves, squares and targets scanned high to low
        int from = msb(pieces), kind = type(b, from);
        pieces ^= bit(from);
        U targets = kind == 1 ? attacks.knight[from] : kind == 5 ? attacks.king[from]
                  : slide(from, occ, kind == 2 ? 4 : 0, kind == 3 ? 4 : 8);
        for (targets &= ~own; targets;) { int to = msb(targets); targets ^= bit(to); out[n++] = enc(from, to); }
    }
    U backrank = color ? 0xFFULL : 0xFFULL << 56;
    U king = own & b.pieces[5] & backrank;
    king &= -king;
    int castles = n;
    if (king) {  // generate_castling_moves: rights scanned high to low, squares empty and not attacked
        int k = __builtin_ctzll(king), base = color ? 0 : 56;
        for (U rights = b.rights & backrank; rights;) {
            int rook_square = msb(rights);
            rights ^= bit(rook_square);
            U rook = bit(rook_square);
            bool a_side = rook_square < k;
            int king_to = base + (a_side ? 2 : 6), rook_to = base + (a_side ? 3 : 5);
            U path = between(k, king_to) | between(rook_square, rook_to) | bit(king_to) | bit(rook_to);
            if ((occ ^ king ^ rook) & path) continue;
            bool attacked = false;
            for (U s = between(k, king_to) | king; s && !attacked;) {
                int sq = msb(s); s ^= bit(sq);
                attacked = attackers(b, !color, sq, occ ^ king) != 0;
            }
            if (attacked || attackers(b, !color, king_to, occ ^ king ^ rook ^ bit(rook_to))) continue;
            int to = rook_square;  // _from_chess960: the king's standard destination
            if (k == base + 4 && rook_square == base + 7) to = base + 6;
            else if (k == base + 4 && rook_square == base) to = base + 2;
            out[n++] = enc(k, to);
        }
    }
    int castled = n;
    U pawns = b.pieces[0] & own;
    if (pawns) {
        for (U p = pawns; p;) {
            int from = msb(p); p ^= bit(from);
            for (U t = pawn_attacks(from, color) & enemy; t;) { int to = msb(t); t ^= bit(to); add_pawn(out, n, from, to); }
        }
        U single = color ? (pawns << 8) & ~occ : (pawns >> 8) & ~occ;
        U twice = color ? (single << 8) & ~occ & (0xFFULL << 16 | 0xFFULL << 24)
                        : (single >> 8) & ~occ & (0xFFULL << 40 | 0xFFULL << 32);
        for (U t = single; t;) { int to = msb(t); t ^= bit(to); add_pawn(out, n, to + (color ? -8 : 8), to); }
        for (U t = twice; t;) { int to = msb(t); t ^= bit(to); out[n++] = enc(to + (color ? -16 : 16), to); }
        if (b.ep < 64 && b.ep != 0 && !(occ & bit(int(b.ep)))) {  // generate_pseudo_legal_ep
            int ep = int(b.ep);
            U capturers = pawns & pawn_attacks(ep, !color) & (0xFFULL << 8 * (color ? 4 : 3));
            for (; capturers;) { int from = msb(capturers); capturers ^= bit(from); out[n++] = enc(from, ep); }
        }
    }
    // _available_fog_moves: castling with the right, the king on e1/e8, a piece on the rook's corner and empty
    // squares between, unless python-chess already generated it.
    int base = color ? 0 : 56;
    if (own & b.pieces[5] && msb(own & b.pieces[5]) == base + 4) {
        for (int side = 0; side < 2; ++side) {
            int rook = base + (side ? 0 : 7), to = base + (side ? 2 : 6);
            if (!(b.rights & bit(rook))) continue;  // has_*side_castling_rights on cleaned rights
            int move = enc(base + 4, to);
            bool listed = false;
            for (int i = castles; i < castled; ++i) listed |= out[i] == move;
            if (listed || !(occ & bit(rook)) || (occ & between(base + 4, rook))) continue;
            out[n++] = move;
        }
    }
    return n;
}

static Board push(const Board& parent, int action, int half, int& child_half, int& captured) {
    // rk_play: python-chess Board.push on cleaned rights, exact en passant square after a double step.
    int from = action & 63, to = (action >> 6) & 63;
    bool pawn = (parent.pieces[0] & bit(from)) != 0;
    Board child = play(parent, action, captured);
    child.ep = pawn && std::abs(from - to) == 16 ? U((from + to) / 2) : 64;
    child.rights = rk::clean_rights(child);
    child_half = pawn || captured >= 0 ? 0 : half + 1;
    return child;
}

static bool was_into_check(const Board& b) {
    U king = colour(b, !int(b.turn)) & b.pieces[5];
    return king && attackers(b, int(b.turn), msb(king), occupied(b));
}

// fow_shared.values.terminal_score for a board without history (no repetition is visible): 1 and the side to
// move's score when the game is over, else 0.
static int terminal(const Board& b, int half, double& score) {
    U kings = b.pieces[5];
    if (!(kings & b.white) || !(kings & ~b.white)) { score = kings & colour(b, int(b.turn)) ? 1.0 : -1.0; return 1; }
    if (half >= 100) { score = 0.0; return 1; }
    int moves[MAX_CHILDREN];
    if (fog_moves(b, moves) == 0) { score = 0.0; return 1; }
    return 0;
}

// pairb.values.rule_value: 1 and the White-view value when terminal_score or forced_score decides the board.
// A board whose parent was a FEN has a one-move history, so repetition never applies here or one move ahead.
static int rule_value(const Board& b, int half, double& white) {
    double score;
    if (!terminal(b, half, score)) {
        if (was_into_check(b)) score = 1.0;
        else {
            int moves[MAX_CHILDREN], n = fog_moves(b, moves), captured, next_half;
            bool any = false;
            double best = 0.0;
            for (int i = 0; i < n; ++i) {
                Board next = push(b, moves[i], half, next_half, captured);
                double ended, value;
                if (terminal(next, next_half, ended)) value = -ended + 0.0;
                else if (was_into_check(next)) value = -1.0;
                else return 0;
                best = any ? std::max(best, value) : value;
                any = true;
            }
            if (!any) return 0;
            score = best;
        }
    }
    white = (b.turn ? 1.0 : -1.0) * score + 0.0;
    return 1;
}

static int cell(int square, int white_player) {
    // fow_shared.features._index: the player's home rank is row 7 (Black mirrored top to bottom).
    int rank = square / 8, file = square % 8;
    return (white_player ? 7 - rank : rank) * 8 + file;
}

static void fill(float* plane, float value) { for (int i = 0; i < 64; ++i) plane[i] = value; }

// encode_belief(_alone(b), opponent_visible): one hypothesis of weight 1 at ply 0, population 1, search depth 0,
// no capture recency, from the side to move's view. `planes` holds 32 x 64 floats.
static void encode(const Board& b, int half, float* planes) {
    std::memset(planes, 0, sizeof(float) * CELLS);
    int player = int(b.turn);
    U own = colour(b, player);
    for (U occ = occupied(b); occ;) {
        int s = pop(occ), t = type(b, s), c = cell(s, player);
        bool mine = (own & bit(s)) != 0;
        planes[((mine ? 0 : 6) + t) * 64 + c] = 1.0f;
        if (!mine) planes[(14 + t) * 64 + c] += 1.0f;  // the hypothesis's weight
    }
    for (U seen = rk::visible_squares(b, player); seen;) {  // the observation: what the player sees
        int s = pop(seen), c = cell(s, player);
        planes[12 * 64 + c] = 1.0f;
        if (occupied(b) & ~own & bit(s)) planes[13 * 64 + c] = 1.0f;
    }
    for (U seen = rk::visible_squares(b, !player); seen;) {  // opponent_visible on the hypothesis board
        int s = pop(seen), c = cell(s, player);
        planes[21 * 64 + c] = 1.0f;
        if (own & bit(s)) planes[22 * 64 + c] = 1.0f;
    }
    U rights = b.rights;
    int home = player ? 0 : 56, away = player ? 56 : 0;
    fill(planes + 26 * 64, (rights & bit(home + 7)) ? 1.0f : 0.0f);
    fill(planes + 27 * 64, (rights & bit(home)) ? 1.0f : 0.0f);
    fill(planes + 28 * 64, (rights & bit(away + 7)) ? 1.0f : 0.0f);
    fill(planes + 29 * 64, (rights & bit(away)) ? 1.0f : 0.0f);
    U ep = rk::ep_effective(b);
    if (ep < 64) planes[30 * 64 + cell(int(ep), player)] = 1.0f;
    fill(planes + 31 * 64, float(std::min(double(half) / 100, 1.0)));
}

}  // namespace lk

extern "C" {

// evaluate_children's data for the parent `source` (packed with cleaned rights, its halfmove and fullmove
// counters). Returns the number of children n (0 when the parent's game is over), or -1 on a capacity error.
// Per child i, in fog_legal_moves order: actions[i] (native_tracker.encode), white[i] the White-view rule value
// and rule[i] = 1 when the rules decide the child (else white[i] = 0, rule[i] = 0). `planes` receives 32 x 8 x 8
// float32 planes for every child (all_planes) or for the undecided children only, in order; *encoded is the
// number written. `names` gets the UCI moves, space separated. `boards` (n packed children) and `fens`
// ('\n'-separated standard FENs) are optional (null to skip).
ZS_EXPORT int lk_children(const Board* source, int half, int full, int all_planes, int* actions, double* white,
                          unsigned char* rule, float* planes, int* encoded, char* names, int names_capacity,
                          Board* boards, char* fens, int fens_capacity) {
    try {
        Board parent = *source;
        parent.rights = rk::clean_rights(parent);
        double score;
        *encoded = 0;
        if (lk::terminal(parent, half, score)) return 0;
        int n = lk::fog_moves(parent, actions), written = 0, name_size = 0, fen_size = 0;
        int child_full = full + (parent.turn ? 0 : 1);
        for (int i = 0; i < n; ++i) {
            int child_half, captured;
            Board child = lk::push(parent, actions[i], half, child_half, captured);
            rule[i] = (unsigned char)lk::rule_value(child, child_half, white[i]);
            if (!rule[i]) white[i] = 0.0;
            if (all_planes || !rule[i]) lk::encode(child, child_half, planes + size_t(written++) * lk::CELLS);
            std::string name = rk::uci(actions[i]);
            if (name_size + int(name.size()) + 2 > names_capacity) return -1;
            if (i) names[name_size++] = ' ';
            std::memcpy(names + name_size, name.data(), name.size());
            name_size += int(name.size());
            if (boards) boards[i] = child;
            if (fens) {
                if (i) { if (fen_size + 1 >= fens_capacity) return -1; fens[fen_size++] = '\n'; }
                int size = zs_fen(&child, child_half, child_full, fens + fen_size, fens_capacity - fen_size);
                if (size < 0) return -1;
                fen_size += size;
            }
        }
        names[name_size] = 0;
        if (fens) fens[fen_size] = 0;
        *encoded = written;
        return n;
    } catch (...) { return -1; }
}

}
