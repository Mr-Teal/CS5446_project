// Reuse the validated bitboard primitives, not the ZS21 history-merging policy.
#include "zs21/native/inference.cpp"

struct BeliefChild { Board board; int action, valid, zeroing; };

extern "C" __declspec(dllexport) int belief_children(
    const Board* parent, const View* view, int viewer, int own_move,
    BeliefChild* output, int capacity) {
    try {
        auto actions = own_move >= 0 ? std::vector<int>{own_move} : moves(*parent, int(parent->turn));
        if (int(actions.size()) > capacity) return -1;
        MatchView expected(*view);
        for (size_t i = 0; i < actions.size(); ++i) {
            int a = actions[i], from = a & 63, to = (a >> 6) & 63, captured;
            bool pawn = (parent->pieces[0] & bit(from)) != 0;
            Board child = play(*parent, a, captured);
            // The generic tracker exports exact FENs, including ineffective EP.
            child.ep = pawn && std::abs(from - to) == 16 ? U((from + to) / 2) : 64;
            auto& row = output[i];
            row.action = a;
            row.zeroing = pawn || captured >= 0;
            row.valid = matches(child, expected, viewer, parent->turn == U(viewer) ? -1 : captured);
            if (row.valid) row.board = child;
        }
        return int(actions.size());
    } catch (...) { return -1; }
}
