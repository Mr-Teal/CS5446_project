// Native fast path for RulesAdapter(backend="native"); the Python RulesAdapter stays the oracle.
// Reuses the ZS21 bitboard primitives (Board, attack masks, moves(), play(), zs_fen) and adds the parts whose
// semantics differ there: python-chess castling-right cleaning, the FoW repetition key, and the visibility of
// RulesAdapter.visible_squares, which is also defined when a king is missing. See native_port_log.md, B1.
#include "zs21/native/inference.cpp"

namespace rk {

static U clean_rights(const Board& b) {
    // python-chess Board.clean_castling_rights() for standard chess (rooks on a/h, king on e).
    U occ = occupied(b), white = b.white, black = occ & ~b.white, castling = b.rights & b.pieces[3];
    U w = castling & 0xFFULL & white & (bit(0) | bit(7));
    U k = castling & (0xFFULL << 56) & black & (bit(56) | bit(63));
    if (!(white & b.pieces[5] & bit(4))) w = 0;
    if (!(black & b.pieces[5] & bit(60))) k = 0;
    return w | k;
}

static U ep_effective(const Board& b) {
    // python-chess has_pseudo_legal_en_passant() for the side to move: the EP square, or 64.
    if (b.ep >= 64 || b.ep == 0) return 64;
    int ep = int(b.ep), color = int(b.turn);
    U occ = occupied(b), own = color ? b.white : occ & ~b.white;
    if (occ & bit(ep)) return 64;
    int rank = ep / 8 + (color ? -1 : 1), file = ep % 8;
    if (rank != (color ? 4 : 3)) return 64;
    for (int dc : {-1, 1}) {
        int f = file + dc;
        if (f >= 0 && f < 8 && (b.pieces[0] & own & bit(rank * 8 + f))) return U(ep);
    }
    return 64;
}

static U visible_squares(const Board& b, int color) {
    // RulesAdapter.visible_squares: own pieces plus every python-chess pseudo-legal destination for `color` as if
    // it were to move (en passant only for the real side to move, which also reveals the capturable pawn).
    // Castling destinations are not added separately: a castling right needs the own rook on its corner and
    // empty squares up to the king, so that rook's own move already reaches c1/g1 (c8/g8).
    U occ = occupied(b), own = color ? b.white : occ & ~b.white, enemy = occ ^ own, seen = own;
    for (int kind = 1; kind < 6; ++kind) {
        U pieces = b.pieces[kind] & own;
        while (pieces) {
            int f = pop(pieces);
            U targets = 0;
            if (kind == 1) targets = attacks.knight[f];
            else if (kind == 5) targets = attacks.king[f];
            else for (int i = (kind == 2 ? 4 : 0); i < (kind == 3 ? 4 : 8); ++i) {
                U ray = attacks.ray[f][i], blockers = ray & occ;
                if (blockers) {
                    int stop = i % 2 ? 63 - __builtin_clzll(blockers) : __builtin_ctzll(blockers);
                    ray ^= attacks.ray[stop][i];
                }
                targets |= ray;
            }
            seen |= targets & ~own;
        }
    }
    U pawns = b.pieces[0] & own, single, twice;
    for (U p = pawns; p;) {
        int f = pop(p), r = f / 8, c = f % 8, rr = r + (color ? 1 : -1);
        if (rr < 0 || rr > 7) continue;
        for (int dc : {-1, 1}) if (c + dc >= 0 && c + dc < 8) seen |= enemy & bit(rr * 8 + c + dc);
    }
    if (color) {
        single = (pawns << 8) & ~occ;
        twice = (single << 8) & ~occ & (0xFFULL << 16 | 0xFFULL << 24);
    } else {
        single = (pawns >> 8) & ~occ;
        twice = (single >> 8) & ~occ & (0xFFULL << 40 | 0xFFULL << 32);
    }
    seen |= single | twice;
    if (color == int(b.turn)) {
        U ep = ep_effective(b);
        if (ep < 64) seen |= bit(int(ep)) | bit(int(ep) + (color ? -8 : 8));
    }
    return seen;
}

static void square_name(std::string& s, int square) { s += char('a' + square % 8); s += char('1' + square / 8); }

static std::string uci(int action) {
    std::string s;
    square_name(s, action & 63);
    square_name(s, (action >> 6) & 63);
    if (action >> 12) s += "??nbrq"[action >> 12];
    return s;
}

static void player_lines(std::string& out, const Board& b, int color) {
    // squares (text), piece letters, visible_pieces JSON, visible_squares JSON; squares sorted by name.
    U mask = visible_squares(b, color);
    std::string text, letters, pieces = "{", squares = "[";
    bool first = true;
    for (int file = 0; file < 8; ++file) for (int rank = 0; rank < 8; ++rank) {
        int s = rank * 8 + file;
        if (!(mask & bit(s))) continue;
        int t = type(b, s);
        char letter = t < 0 ? '.' : (b.white & bit(s) ? "PNBRQK" : "pnbrqk")[t];
        if (!first) { text += ' '; pieces += ','; squares += ','; }
        first = false;
        square_name(text, s);
        letters += letter;
        pieces += '"'; square_name(pieces, s); pieces += "\":";
        if (letter == '.') pieces += "null"; else { pieces += '"'; pieces += letter; pieces += '"'; }
        squares += '"'; square_name(squares, s); squares += '"';
    }
    out += text; out += '\n'; out += letters; out += '\n';
    out += pieces; out += "}\n"; out += squares; out += ']';
}

}  // namespace rk

extern "C" {

// Everything RulesAdapter needs about one position, as '\n'-separated ASCII lines:
// 0 "<white king present> <black king present> <fog-legal move count>"
// 1 FoW position key (hex; fow_shared.values.fog_position_key fields)
// 2 fog-legal moves, sorted UCI, space separated (empty when a king is missing)   3 the same as a JSON list
// 4-7 White: visible squares (sorted), their piece letters ('.' empty), visible_pieces JSON, visible_squares JSON
// 8-11 Black: the same.
ZS_EXPORT int rk_analyze(const Board* source, char* out, int capacity) {
    try {
        Board b = *source;
        b.rights = rk::clean_rights(b);
        U occ = occupied(b);
        int kw = (b.pieces[5] & b.white) != 0, kb = (b.pieces[5] & occ & ~b.white) != 0;
        auto actions = moves(b, int(b.turn), false);
        std::vector<std::string> names;
        names.reserve(actions.size());
        for (int a : actions) names.push_back(rk::uci(a));
        std::sort(names.begin(), names.end());
        std::string text = std::to_string(kw) + ' ' + std::to_string(kb) + ' ' + std::to_string(names.size()) + '\n';
        U key[10] = {b.pieces[0], b.pieces[1], b.pieces[2], b.pieces[3], b.pieces[4], b.pieces[5], b.white,
                     b.rights, b.turn, rk::ep_effective(b)};
        char hex[17];
        for (U v : key) { std::snprintf(hex, sizeof hex, "%016llx", (unsigned long long)v); text += hex; }
        text += '\n';
        std::string list, json = "[";
        for (size_t i = 0; i < names.size(); ++i) {
            if (i) { list += ' '; json += ','; }
            list += names[i];
            json += '"'; json += names[i]; json += '"';
        }
        text += list; text += '\n'; text += json; text += "]\n";
        rk::player_lines(text, b, 1);
        text += '\n';
        rk::player_lines(text, b, 0);
        if (int(text.size()) + 1 > capacity) return -1;
        std::memcpy(out, text.c_str(), text.size() + 1);
        return int(text.size());
    } catch (...) { return -1; }
}

// python-chess Board.push for a fog-legal action (encoded as native_tracker.encode). Writes the successor (exact
// en passant square after a double step, cleaned castling rights) and returns
// captured_square | zeroing << 8, with captured_square 64 when nothing was captured.
ZS_EXPORT int rk_play(const Board* source, int action, Board* out) {
    Board parent = *source;
    parent.rights = rk::clean_rights(parent);
    int from = action & 63, to = (action >> 6) & 63, captured;
    bool pawn = (parent.pieces[0] & bit(from)) != 0;
    Board child = play(parent, action, captured);
    child.ep = pawn && std::abs(from - to) == 16 ? U((from + to) / 2) : 64;
    *out = child;
    return (captured < 0 ? 64 : captured) | int(pawn || captured >= 0) << 8;
}

}
