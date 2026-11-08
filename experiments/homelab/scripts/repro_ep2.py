# Raw UCI, no python-chess engine wrapper, so nothing can hang: what does Stockfish answer
# for a fog-of-war hypothesis that has an en-passant square while the mover is in check from a knight?
import subprocess, select, sys, chess
CASES = [("c4 'h5g6'", "r2qr1k1/1p3p2/p1n4p/6pP/2p1P1n1/P1P3P1/3PPK2/1RBQ1BN1 w - g6 0 18"),
         ("c30 'b5a6'", "r4b1r/1p3k2/5np1/pP5p/2n2P1P/Pb4P1/3KP3/qN3B1R w - a6 0 18"),
         ("c44 'e4f3'", "8/p1k5/P2pN3/3P2B1/2P1pP1P/8/2P3P1/R3K2R b KQ f3 0 29")]
def ask(fen, multipv):
    import threading
    p = subprocess.Popen(["/usr/games/stockfish"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    timer = threading.Timer(5.0, p.kill); timer.start()
    p.stdin.write("uci\n"); p.stdin.flush()
    while "uciok" not in p.stdout.readline(): pass
    p.stdin.write(f"setoption name MultiPV value {multipv}\nposition fen {fen}\ngo depth 1\n"); p.stdin.flush()
    pvs, best = [], None
    for line in p.stdout:
        if " pv " in line: pvs.append(line.split(" pv ")[1].split()[0])
        if line.startswith("bestmove"): best = line.split()[1]; break
    timer.cancel()
    try:
        p.stdin.write("quit\n"); p.stdin.flush(); p.wait(timeout=5)
    except Exception:
        p.kill()
    return best, pvs
for label, fen in CASES:
    b = chess.Board(fen)
    legal = sorted(m.uci() for m in b.legal_moves)
    print(f"{label}: in_check={b.is_check()} ep={chess.square_name(b.ep_square)} has_legal_ep={b.has_legal_en_passant()} legal={legal}")
    print(f"   fen(legal)={b.fen()}")
    best, pvs = ask(b.fen(en_passant="fen"), len(legal))
    print(f"   sent ep as python-chess does -> bestmove {best} pvs {pvs}  all legal? {all(m in legal for m in pvs + [best])}")
    best2, pvs2 = ask(b.fen(), len(legal))
    print(f"   sent with ep cleared        -> bestmove {best2} pvs {pvs2}  all legal? {all(m in legal for m in pvs2 + [best2])}")
