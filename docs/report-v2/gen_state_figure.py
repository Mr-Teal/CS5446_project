"""Draw the report's Figure 2 (state representation) as inline SVG from qa4_figure_data.json (15 Nov 2026).
Usage: python3 gen_state_figure.py > state_figure.svg"""
import json
import os

D = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "qa4_figure_data.json")))
GLYPH = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
         "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}
TEXT = "︎"  # text presentation, never emoji
LIGHT, DARK, FOG_L, FOG_D, ACCENT = "#f4f1ea", "#ddd6c8", "#bcc5ce", "#aab4be", "#b03a2e"
FONT = "Times New Roman, Times, serif"
PIECE_FONT = "Apple Symbols, DejaVu Sans, Segoe UI Symbol, serif"
VISIBLE = set(D["visible_squares"])
SAN = {"a2a4": "a4", "b1c3": "Nc3", "b2b3": "b3", "d1a4": "Qa4+", "d1b3": "Qb3", "d1c2": "Qc2", "d2d3": "d3",
       "e2e3": "e3", "f2f3": "f3", "h1g1": "Rg1"}


def board_from_fen(fen):
    out = {}
    for r, row in enumerate(fen.split()[0].split("/")):
        f = 0
        for ch in row:
            if ch.isdigit():
                f += int(ch)
            else:
                out["abcdefgh"[f] + str(8 - r)] = ch
                f += 1
    return out


def xy(square, x0, y0, s):
    return x0 + "abcdefgh".index(square[0]) * s, y0 + (8 - int(square[1])) * s


def squares(x0, y0, s):
    out = []
    for f in "abcdefgh":
        for r in "12345678":
            sq = f + r
            x, y = xy(sq, x0, y0, s)
            light = ("abcdefgh".index(f) + int(r)) % 2 == 1
            fill = (LIGHT if light else DARK) if sq in VISIBLE else (FOG_L if light else FOG_D)
            out.append(f'<rect x="{x}" y="{y}" width="{s}" height="{s}" fill="{fill}"/>')
    out.append(f'<rect x="{x0}" y="{y0}" width="{8 * s}" height="{8 * s}" fill="none" stroke="#1a1a1a" stroke-width="0.8"/>')
    return out


def piece(ch, cx, cy, size, opacity=1.0):
    op = "" if opacity >= 0.999 else f' opacity="{opacity:.2f}"'
    return (f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="{size}" text-anchor="middle" dominant-baseline="central"'
            f' font-family="{PIECE_FONT}"{op}>{GLYPH[ch]}{TEXT}</text>')


def full_board(pieces, x0, y0, s, size):
    out = squares(x0, y0, s)
    for sq, ch in pieces.items():
        x, y = xy(sq, x0, y0, s)
        out.append(piece(ch, x + s / 2, y + s / 2 + s * 0.04, size))
    return out


def label(x, y, text, size=11, anchor="start", style=""):
    return f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}"{style}>{text}</text>'


svg = []
S, BIG = 24, 20  # main board square and glyph size
AX, AY = 14, 26  # panel (a)
CX = 482          # panel (c)

# (a) what Black sees
svg.append(label(AX, 13, "(a) What Black sees"))
svg += full_board(D["visible_pieces"], AX, AY, S, BIG)
for i, f in enumerate("abcdefgh"):
    for x0 in (AX, CX):
        svg.append(label(x0 + i * S + S / 2, AY + 8 * S + 10, f, 8.5, "middle"))
for i in range(8):
    svg.append(label(AX - 6, AY + i * S + S / 2 + 3, str(8 - i), 8.5, "middle"))

# (b) four of the ten sampled boards
svg.append(label(246, 13, "(b) Belief: 10 boards, 0.1 each"))
pick = ["d1a4", "d1c2", "b1c3", "e2e3"]
hyps = {h["white_third_move"]: h for h in D["hypotheses"]}
s, size = 11, 10
for k, mv in enumerate(pick):
    bx, by = 246 + (k % 2) * 96, 22 + (k // 2) * 112
    pieces = board_from_fen(hyps[mv]["fen"])
    svg += full_board(pieces, bx, by, s, size)
    x, y = xy(mv[2:], bx, by, s)
    svg.append(f'<rect x="{x}" y="{y}" width="{s}" height="{s}" fill="none" stroke="{ACCENT}" stroke-width="1.3"/>')
    if mv == "d1a4":  # the unseen check on the true board
        x1, y1 = xy("a4", bx, by, s)
        x2, y2 = xy("e8", bx, by, s)
        svg.append(f'<line x1="{x1 + s / 2}" y1="{y1 + s / 2}" x2="{x2 + s / 2}" y2="{y2 + s / 2}" stroke="{ACCENT}"'
                   f' stroke-width="1.2" stroke-dasharray="2.5 1.8"/>')
    name = "3." + SAN[mv] + (" (true)" if mv == "d1a4" else "")
    svg.append(label(bx + 4 * s, by + 8 * s + 11, name, 9.5, "middle"))
svg.append(label(246 + 92, 22 + 2 * 112 + 4, "+ 6 more boards", 9, "middle", ' font-style="italic"'))

# (c) the probability board: what Black sees, plus each enemy piece's share of the boards on every unseen square
svg.append(label(CX, 13, "(c) Probability board"))
svg += squares(CX, AY, S)
for sq, ch in D["visible_pieces"].items():
    x, y = xy(sq, CX, AY, S)
    svg.append(piece(ch, x + S / 2, y + S / 2 + 1, BIG))
for sq, probs in sorted(D["white_piece_probability"].items()):
    if sq in VISIBLE:
        continue
    x, y = xy(sq, CX, AY, S)
    items = sorted(probs.items(), key=lambda kv: "PNBRQK".index(kv[0]))
    if len(items) == 1:
        ch, p = items[0]
        if p > 0.999:
            svg.append(piece(ch, x + S / 2, y + S / 2 + 1, BIG))
        else:
            svg.append(piece(ch, x + S / 2 - 2, y + S / 2 - 1, 17, max(p, 0.35)))
            svg.append(label(x + S - 1.5, y + S - 2, f"{p:.1f}".lstrip("0"), 7.5, "end", ' font-weight="bold"'))
    else:
        for j, (ch, p) in enumerate(items):
            cx = x + S * (0.27 + 0.46 * j)
            svg.append(piece(ch, cx, y + S * 0.38, 11, max(p, 0.35)))
            svg.append(label(cx, y + S - 2, f"{p:.1f}".lstrip("0"), 6.5, "middle", ' font-weight="bold"'))

# arrows between the panels
mid = AY + 4 * S
for x1, x2, text in ((AX + 8 * S + 4, 242, "tracker"), (436, CX - 4, "average")):
    svg.append(f'<line x1="{x1}" y1="{mid}" x2="{x2}" y2="{mid}" stroke="#1a1a1a" stroke-width="1" marker-end="url(#ar2)"/>')
    svg.append(label((x1 + x2) / 2, mid - 5, text, 9.5, "middle", ' font-style="italic"'))

# (d) the 32 input planes, grouped, and the network
Y = 282
svg.append(label(AX, Y - 10, "(d) Network input: the probability board as 32 planes of 8×8"))
groups = [("own pieces", "", "6", False, 62), ("enemy pieces", "we see", "6", False, 70),
          ("squares", "we see", "2", False, 52), ("enemy piece", "probability", "6", True, 74),
          ("what the", "opponent sees", "2", True, 76), ("belief size,", "ply, 2 zero", "4", False, 64),
          ("castling, en", "passant, clock", "6", False, 78)]
x = AX
for top, bottom, count, shaded, w in groups:
    fill = "#e3e8ee" if shaded else "none"
    svg.append(f'<rect x="{x}" y="{Y}" width="{w}" height="46" fill="{fill}" stroke="#1a1a1a" stroke-width="0.8"/>')
    lines = [t for t in (top, bottom) if t]
    for j, t in enumerate(lines):
        svg.append(label(x + w / 2, Y + 14 + j * 11 + (5 if len(lines) == 1 else 0), t, 9.5, "middle"))
    svg.append(label(x + w / 2, Y + 41, "×" + count, 9, "middle", ' font-style="italic"'))
    x += w + 5
nx = x + 18
svg.append(f'<line x1="{x - 1}" y1="{Y + 23}" x2="{nx - 2}" y2="{Y + 23}" stroke="#1a1a1a" stroke-width="1" marker-end="url(#ar2)"/>')
svg.append(f'<rect x="{nx}" y="{Y}" width="{680 - 6 - nx}" height="46" fill="none" stroke="#1a1a1a" stroke-width="0.8"/>')
svg.append(label((nx + 674) / 2, Y + 19, "policy network", 10.5, "middle"))
svg.append(label((nx + 674) / 2, Y + 34, "one pass", 9, "middle", ' font-style="italic"'))
# (e) one plane from four of the groups, with the values the network reads (qa4_planes.json, from the exact input)
P = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "qa4_planes.json")))["planes"]
EY = Y + 62
svg.append(label(AX, EY, "(e) One plane from four of the groups, with the values the network reads (blank = 0)"))
examples = [("0", "own pieces: our pawns", ["The other five are alike:", "knights b8, g8; queen d6; …"]),
            ("6", "enemy pieces we see: pawns", ["Only on squares we see: c4, h2.", "Knights: h3; the rest empty."]),
            ("18", "enemy probability: queen", ["Pawns: e2 .9, e3 .1, g2 1;", "knights: b1 .9, c3 .1, h3 1."]),
            ("21", "what the opponent sees", ["Averaged over the 10 boards.", "Our pieces they see: d5 1, e8 .1."])]
HS = 13
for k, (plane, title, notes) in enumerate(examples):
    x0, y0 = AX + k * 172, EY + 8
    cells = P[plane]
    for row, r in enumerate(range(8, 0, -1)):
        for col, f in enumerate("abcdefgh"):
            v = cells.get(f + str(r), 0.0)
            shade = round(255 - v * (255 - 70)), round(255 - v * (255 - 95)), round(255 - v * (255 - 125))
            fill = "#%02x%02x%02x" % shade
            svg.append(f'<rect x="{x0 + col * HS}" y="{y0 + row * HS}" width="{HS}" height="{HS}" fill="{fill}"'
                       f' stroke="#d0d0d0" stroke-width="0.4"/>')
            if v > 0:
                txt = "1" if v > 0.995 else f"{v:.1f}".lstrip("0")
                color = ' fill="#ffffff"' if v >= 0.55 else ""
                svg.append(label(x0 + col * HS + HS / 2, y0 + row * HS + HS / 2 + 2.5, txt, 7, "middle", color))
    svg.append(f'<rect x="{x0}" y="{y0}" width="{8 * HS}" height="{8 * HS}" fill="none" stroke="#1a1a1a" stroke-width="0.7"/>')
    svg.append(label(x0, y0 + 8 * HS + 12, f"{title} (plane {plane})", 9.5, style=' font-weight="bold"'))
    for j, n in enumerate(notes):
        svg.append(label(x0, y0 + 8 * HS + 24 + j * 11, n, 9))
NY = EY + 8 + 8 * HS + 24 + 2 * 11 + 6
svg.append(label(AX, NY, "Constant planes: belief size .22 (log2 10 / 15), ply .025, our kingside castling 1, the enemy's .9 (lost on the"
                 " Rg1 board).", 9))
svg.append(label(AX, NY + 11, "Planes are drawn as the board; for Black the network gets each plane flipped top to bottom.", 9))
svg.append(label(AX, NY + 29, "Network output here: 3...d4 0.25 · dxc4 0.21 · Nf6 0.20 · c6 0.08 · Nc6 0.07. It plays d4;"
                 " of these, only c6 and Nc6 block the check on the true board.", 9.5))

H = NY + 37
head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 {H}" role="img" aria-label="State representation at 1.Nh3 d5 2.c4 Qd6 3.Qa4+, Black to'
        f' move: what Black sees, four of the ten boards Black cannot tell apart, the probability board that averages'
        f' them, and the 32 input planes it becomes.">')
defs = ('<defs><marker id="ar2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"'
        ' orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#1a1a1a"/></marker></defs>')
print(head + defs + f'<g font-family="{FONT}" fill="#1a1a1a">' + "".join(svg) + "</g></svg>")
