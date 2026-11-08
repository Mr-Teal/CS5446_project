import chess, chess.engine
FEN = "r2qr1k1/1p3p2/p1n4p/6pP/2p1P1n1/P1P3P1/3PPK2/1RBQ1BN1 w - g6 0 18"
b = chess.Board(FEN)
print("in check:", b.is_check(), "| ep_square:", chess.square_name(b.ep_square) if b.ep_square else None,
      "| has_legal_ep:", b.has_legal_en_passant(), "| legal:", sorted(m.uci() for m in b.legal_moves))
print("fen(legal):", b.fen(), "| fen(fen):", b.fen(en_passant="fen"))
eng = chess.engine.SimpleEngine.popen_uci("/usr/games/stockfish", timeout=5)
for label, board in (("as sent today", b.copy(stack=False)), ("ep normalised", b.copy(stack=False))):
    if label == "ep normalised" and not board.has_legal_en_passant():
        board.ep_square = None
    try:
        infos = eng.analyse(board, chess.engine.Limit(depth=1), multipv=board.legal_moves.count(), game=object())
        print(label, "-> ok, pv heads:", [i["pv"][0].uci() for i in infos if "pv" in i])
    except Exception as e:
        print(label, "->", type(e).__name__, str(e)[:90])
        eng = chess.engine.SimpleEngine.popen_uci("/usr/games/stockfish", timeout=5)
eng.quit()
