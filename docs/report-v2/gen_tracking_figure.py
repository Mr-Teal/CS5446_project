"""Draw the tracking figure (Black's first tracker update, ply 0 -> 1) from tracking_ply1.json (15 Nov 2026).
Usage: python3 gen_tracking_figure.py > fig_tracking.svg"""
import json
import os

D = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracking_ply1.json")))
GLYPH = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
         "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}
TEXT = "︎"
LIGHT, DARK, FOG_L, FOG_D, ACCENT, SHADE = "#f4f1ea", "#ddd6c8", "#bcc5ce", "#aab4be", "#b03a2e", "#e3e8ee"
FONT = "Times New Roman, Times, serif"
PIECE_FONT = "Apple Symbols, DejaVu Sans, Segoe UI Symbol, serif"
START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
FILES = "abcdefgh"
VISIBLE = set(D["visible"])
SAMPLED = {s["first"] for s in D["sampled"]}
PIECE_NAME = {"N": "N", "B": "B", "R": "R", "Q": "Q", "K": "K", "P": ""}


def board(fen):
    out = {}
    for r, row in enumerate(fen.split("/")):
        f = 0
        for ch in row:
            if ch.isdigit():
                f += int(ch)
            else:
                out[FILES[f] + str(8 - r)] = ch
                f += 1
    return out


def play(pieces, uci):
    p = dict(pieces)
    p[uci[2:4]] = p.pop(uci[:2])
    return p


def san(pieces, uci):
    return PIECE_NAME[pieces[uci[:2]].upper()] + uci[2:4]


def piece(ch, cx, cy, size, opacity=1.0):
    op = "" if opacity >= 0.999 else f' opacity="{opacity:.2f}"'
    return (f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="{size}" text-anchor="middle" dominant-baseline="central"'
            f' font-family="{PIECE_FONT}"{op}>{GLYPH[ch]}{TEXT}</text>')


def label(x, y, text, size=10, anchor="start", extra=""):
    return f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}"{extra}>{text}</text>'


def draw(pieces, x0, y0, s, glyph, ranks=range(8, 0, -1), fog=False, opacity=1.0, mark=None):
    """Squares (ranks from top to bottom as given) with pieces; fog greys squares Black does not see."""
    out = [f'<g opacity="{opacity:.2f}">'] if opacity < 0.999 else []
    ranks = list(ranks)
    for row, r in enumerate(ranks):
        for col, f in enumerate(FILES):
            sq = f + str(r)
            light = (col + r) % 2 == 1
            if fog and sq not in VISIBLE:
                fill = FOG_L if light else FOG_D
            else:
                fill = LIGHT if light else DARK
            out.append(f'<rect x="{x0 + col * s}" y="{y0 + row * s}" width="{s}" height="{s}" fill="{fill}"/>')
            ch = pieces.get(sq)
            if ch and not (fog and sq not in VISIBLE):
                out.append(piece(ch, x0 + col * s + s / 2, y0 + row * s + s / 2 + s * 0.05, glyph))
    if mark:
        col, row = FILES.index(mark[0]), ranks.index(int(mark[1]))
        out.append(f'<rect x="{x0 + col * s}" y="{y0 + row * s}" width="{s}" height="{s}" fill="none" stroke="{ACCENT}" stroke-width="1.2"/>')
    out.append(f'<rect x="{x0}" y="{y0}" width="{8 * s}" height="{len(ranks) * s}" fill="none" stroke="#1a1a1a" stroke-width="0.7"/>')
    if opacity < 0.999:
        out.append("</g>")
    return out


start = board(START)
svg = []
# (a) ply 0
S = 13
AX, AY = 10, 34
svg.append(label(AX, 13, "(a) Ply 0: stored", 11))
svg.append(label(AX, 25, "1 board, count 1", 9.5, extra=' font-style="italic"'))
svg += draw(start, AX, AY, S, 11)
# (b) expand: 20 boards, ranks 1-4 only
GX, GY, s = 158, 34, 9
svg.append(label(GX, 13, "(b) Expand: one board per White first move (20)", 11))
svg.append(label(GX, 25, "ranks 1–4 drawn; ranks 5–8 are the same on all 20", 9.5, extra=' font-style="italic"'))
moves = sorted(D["legal"], key=lambda m: (start[m[:2]].upper() != "P", m[2], m[3] if start[m[:2]].upper() == "P" else m[2:]))
moves = [m for m in moves if start[m[:2]].upper() == "P"] + [m for m in moves if start[m[:2]].upper() != "P"]
for k, m in enumerate(moves):
    col, row = k % 5, k // 5
    x, y = GX + col * 76, GY + row * 50
    faded = m not in SAMPLED
    svg += draw(play(start, m), x, y, s, 8, ranks=range(4, 0, -1), opacity=0.35 if faded else 1.0, mark=m[2:4])
    name = san(start, m) + (" (true)" if m == "g1h3" else "")
    style = ' font-weight="bold"' if m == "g1h3" else (' fill="#8a8a8a"' if faded else "")
    svg.append(label(x + 4 * s, y + 4 * s + 10, name, 9, "middle", style))
# (c) Black's view after ply 1
CX, CY = 566, 34
svg.append(label(CX, 13, "(c) Black's view at ply 1", 11))
svg.append(label(CX, 25, "the same on all 20 boards", 9.5, extra=' font-style="italic"'))
svg += draw(play(start, "g1h3"), CX, CY, S, 11, fog=True)
# arrows
mid = AY + 4 * S
svg.append(f'<line x1="{AX + 8 * S + 3}" y1="{mid}" x2="{GX - 4}" y2="{mid}" stroke="#1a1a1a" marker-end="url(#a7)"/>')
svg.append(label((AX + 8 * S + GX) / 2, mid - 5, "expand", 9.5, "middle", ' font-style="italic"'))
svg.append(f'<line x1="{CX - 4}" y1="{mid}" x2="{GX + 5 * 76 - 6}" y2="{mid}" stroke="#1a1a1a" marker-end="url(#a7)"/>')
svg.append(label((CX + GX + 5 * 76 - 10) / 2, mid - 5, "filter", 9.5, "middle", ' font-style="italic"'))
svg.append(label(CX + 4 * S, CY + 8 * S + 13, "all 20 match:", 9.5, "middle"))
svg.append(label(CX + 4 * S, CY + 8 * S + 25, "all 20 kept", 9.5, "middle"))
# legend under the grid
LY = GY + 4 * 50 + 4
svg.append(label(GX, LY, "Sampled into the belief: the 16 boards shown in full, weight 1/16 each; faded: stored but not sampled this turn.", 9.5))
# step strip
steps = [("Stored", "1 board"), ("Expand", "20 boards"), ("Filter", "20 kept"), ("Merge", "none equal"),
         ("Guard", "under 96,000"), ("Sample", "16 × 1/16")]
SY = LY + 14
w, gap = 100, 16
for k, (head, body) in enumerate(steps):
    x = 2 + k * (w + gap)
    fill = SHADE if k == 5 else "none"
    svg.append(f'<rect x="{x}" y="{SY}" width="{w}" height="30" fill="{fill}" stroke="#1a1a1a" stroke-width="0.8"/>')
    svg.append(label(x + w / 2, SY + 13, head, 10.5, "middle", ' font-weight="bold"'))
    svg.append(label(x + w / 2, SY + 25, body, 9.5, "middle", ' font-style="italic"'))
    if k < 5:
        svg.append(f'<line x1="{x + w}" y1="{SY + 15}" x2="{x + w + gap - 2}" y2="{SY + 15}" stroke="#1a1a1a" marker-end="url(#a7)"/>')
H = SY + 34
head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 {H}" role="img" aria-label="Black\'s first tracker update:'
        ' one stored start board expands into 20 boards, one per White first move; Black sees only ranks 5 to 8 and no'
        ' White piece, so all 20 are kept; 16 of them are sampled into the belief with weight 1/16 each.">')
defs = ('<defs><marker id="a7" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6"'
        ' orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#1a1a1a"/></marker></defs>')
print(head + defs + f'<g font-family="{FONT}" fill="#1a1a1a">' + "".join(svg) + "</g></svg>")
