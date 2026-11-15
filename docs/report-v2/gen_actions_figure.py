"""Draw the action-space figure (15 Nov 2026): the policy network's 64 move types from one square, how many of them
stay on the board from each square (1,792 of the 4,096 from-to slots), and the legal moves at the Qa4+ position of
the probability-board figure with the network's top five (probabilities from qa4_figure_policy.py, 44 legal moves
from the rules adapter). Move types as pairb.policy_net.MOVE_TYPES. Usage: python3 gen_actions_figure.py > fig_actions.svg"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, "qa4_figure_data.json")))
GLYPH = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
         "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}
TEXT = "︎"
LIGHT, DARK, FOG_L, FOG_D, ACCENT, BLUE = "#f4f1ea", "#ddd6c8", "#bcc5ce", "#aab4be", "#b03a2e", "#2f4f6f"
FONT = "Times New Roman, Times, serif"
PIECE_FONT = "Apple Symbols, DejaVu Sans, Segoe UI Symbol, serif"
FILES = "abcdefgh"
DIRECTIONS = ((-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1))
KNIGHT = ((-2, -1), (-2, 1), (-1, 2), (1, 2), (2, 1), (2, -1), (1, -2), (-1, -2))
TYPES = tuple((dr * d, dc * d) for dr, dc in DIRECTIONS for d in range(1, 8)) + KNIGHT
TOP = [("d5d4", 0.249), ("d5c4", 0.214), ("g8f6", 0.204), ("c7c6", 0.083), ("b8c6", 0.067)]
N_LEGAL = 44
S = 13


def label(x, y, text, size=10, anchor="start", extra=""):
    return f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}"{extra}>{text}</text>'


def xy(square, x0, y0):
    return x0 + FILES.index(square[0]) * S, y0 + (8 - int(square[1])) * S


def squares(x0, y0, fog=None):
    out = []
    for r in range(8):
        for c in range(8):
            light = (c + (8 - r)) % 2 == 1
            sq = FILES[c] + str(8 - r)
            hidden = fog is not None and sq not in fog
            fill = (FOG_L if light else FOG_D) if hidden else (LIGHT if light else DARK)
            out.append(f'<rect x="{x0 + c * S}" y="{y0 + r * S}" width="{S}" height="{S}" fill="{fill}"/>')
    out.append(f'<rect x="{x0}" y="{y0}" width="{8 * S}" height="{8 * S}" fill="none" stroke="#1a1a1a" stroke-width="0.8"/>')
    for i, f in enumerate(FILES):
        out.append(label(x0 + i * S + S / 2, y0 + 8 * S + 9, f, 7.5, "middle"))
    for i in range(8):
        out.append(label(x0 - 5, y0 + i * S + S / 2 + 2.5, str(8 - i), 7.5, "middle"))
    return out


svg = []
Y0 = 34
# (a) the 64 move types from d4
AX = 16
svg.append(label(AX - 8, 13, "(a) 64 move types from one square", 11))
svg.append(label(AX - 8, 25, "here d4; types that leave the board are dropped", 9, extra=' font-style="italic"'))
svg += squares(AX, Y0)
fr, fc = 4, 3  # d4 as (row from top, col)
for t, (dr, dc) in enumerate(TYPES):
    r, c = fr + dr, fc + dc
    if 0 <= r < 8 and 0 <= c < 8:
        cx, cy = AX + c * S + S / 2, Y0 + r * S + S / 2
        if t < 56:
            svg.append(f'<circle cx="{cx}" cy="{cy}" r="3" fill="{BLUE}"/>')
        else:
            svg.append(f'<rect x="{cx - 3}" y="{cy - 3}" width="6" height="6" fill="{ACCENT}" transform="rotate(45 {cx} {cy})"/>')
svg.append(f'<rect x="{AX + fc * S + 1}" y="{Y0 + fr * S + 1}" width="{S - 2}" height="{S - 2}" fill="none" stroke="#1a1a1a" stroke-width="1.6"/>')
ty = Y0 + 8 * S + 22
svg.append(f'<circle cx="{AX + 3}" cy="{ty - 3}" r="3" fill="{BLUE}"/>')
svg.append(label(AX + 10, ty, "56 queen-like (8 directions × 1–7)", 9))
svg.append(f'<rect x="{AX}" y="{ty + 6}" width="6" height="6" fill="{ACCENT}" transform="rotate(45 {AX + 3} {ty + 9})"/>')
svg.append(label(AX + 10, ty + 12, "8 knight jumps", 9))
svg.append(label(AX - 8, ty + 26, "From d4, 35 of the 64 stay on the board.", 9))

# (b) the 4,096 from-to slots as a 64 x 64 grid: rows = from-square, columns = to-square (a1, b1, ..., h8)
BX, C = 214, 2.4
LEGAL = set(json.load(open(os.path.join(HERE, "qa4_legal.json")))["legal"])
svg.append(label(BX - 10, 13, "(b) The 4,096 actions: every from–to pair", 11))
svg.append(label(BX - 10, 25, "rows: from-square, columns: to-square (a1, b1, …, h8)", 9, extra=' font-style="italic"'))
reach = set()
for r in range(8):
    for c in range(8):
        for dr, dc in TYPES:
            if 0 <= r + dr < 8 and 0 <= c + dc < 8:
                reach.add(((7 - r) * 8 + c, (7 - r - dr) * 8 + c + dc))  # (from, to) as rank * 8 + file
assert len(reach) == 1792
def sqi(name):
    return (int(name[1]) - 1) * 8 + FILES.index(name[0])
legal_cells = {(sqi(m[:2]), sqi(m[2:4])) for m in LEGAL}
played = (sqi("d5"), sqi("d4"))
svg.append(f'<rect x="{BX}" y="{Y0}" width="{64 * C}" height="{64 * C}" fill="#ececec"/>')
for (f, t) in sorted(reach):
    fill = "#b9cadb"
    svg.append(f'<rect x="{BX + t * C}" y="{Y0 + f * C}" width="{C}" height="{C}" fill="{fill}"/>')
for (f, t) in sorted(legal_cells):
    fill = ACCENT if (f, t) == played else BLUE
    svg.append(f'<rect x="{BX + t * C - 0.4}" y="{Y0 + f * C - 0.4}" width="{C + 0.8}" height="{C + 0.8}" fill="{fill}"/>')
svg.append(f'<rect x="{BX}" y="{Y0}" width="{64 * C}" height="{64 * C}" fill="none" stroke="#1a1a1a" stroke-width="0.8"/>')
svg.append(label(BX - 3, Y0 + 4, "a1", 7, "end")); svg.append(label(BX - 3, Y0 + 64 * C, "h8", 7, "end"))
svg.append(label(BX, Y0 + 64 * C + 9, "a1", 7)); svg.append(label(BX + 64 * C, Y0 + 64 * C + 9, "h8", 7, "end"))
LX = BX + 64 * C + 10
for k, (fill, text) in enumerate([("#ececec", "never a move: 2,304"), ("#b9cadb", "queen line or knight"), (BLUE, "legal here: 44"),
                                  (ACCENT, "played: d4")]):
    svg.append(f'<rect x="{LX}" y="{Y0 + 4 + k * 26}" width="9" height="9" fill="{fill}" stroke="#888" stroke-width="0.4"/>')
    svg.append(label(LX + 13, Y0 + 12 + k * 26, text, 8.5))
svg.append(label(LX + 13, Y0 + 12 + 1 * 26 + 10, "jump: 1,792", 8.5))
GY = Y0 + 64 * C + 22
svg.append(label(BX - 10, GY, "The network scores 64 move types on each of the 64", 9))
svg.append(label(BX - 10, GY + 12, "squares (a); a fixed table puts each on-board one", 9))
svg.append(label(BX - 10, GY + 24, "into its from–to cell. Grey cells never get a score.", 9))

# (c) the legal moves at the Qa4+ position and the top five
CX = 488
svg.append(label(CX - 8, 13, f"(c) Legal mask at Figure 3's position", 11))
svg.append(label(CX - 8, 25, f"{N_LEGAL} legal moves of 4,096; softmax over them", 9, extra=' font-style="italic"'))
visible = set(D["visible_squares"])
svg += squares(CX, Y0, fog=visible)
for sq, ch in D["visible_pieces"].items():
    x, y = xy(sq, CX, Y0)
    svg.append(f'<text x="{x + S / 2:.1f}" y="{y + S / 2 + 1:.1f}" font-size="11" text-anchor="middle" dominant-baseline="central"'
               f' font-family="{PIECE_FONT}">{GLYPH[ch]}{TEXT}</text>')
for k, (mv, p) in enumerate(TOP):
    x1, y1 = xy(mv[:2], CX, Y0)
    x2, y2 = xy(mv[2:], CX, Y0)
    x1, y1, x2, y2 = x1 + S / 2, y1 + S / 2, x2 + S / 2, y2 + S / 2
    w = 1 + 4 * p
    svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2 - (x2 - x1) * 0.18}" y2="{y2 - (y2 - y1) * 0.18}" stroke="{ACCENT}"'
               f' stroke-width="{w:.1f}" stroke-opacity="0.85" marker-end="url(#a8)"/>')
    mx, my = (x1 + x2) / 2 + (4 if k in (3,) else 0), (y1 + y2) / 2 + (0 if k != 0 else -1)
    svg.append(label(round(mx + 5, 1), round(my - 2, 1), str(k + 1), 8.5, "middle",
                     f' font-weight="bold" fill="{ACCENT}" stroke="#ffffff" stroke-width="2.5" paint-order="stroke"'))
for k, (mv, p) in enumerate(TOP):
    san = {"d5d4": "d4", "d5c4": "dxc4", "g8f6": "Nf6", "c7c6": "c6", "b8c6": "Nc6"}[mv]
    svg.append(label(CX + 8 * S + 8, Y0 + 12 + k * 13, f"{k + 1} {san} {p:.2f}", 9.5, extra=' font-weight="bold"' if k == 0 else ""))
svg.append(label(CX + 8 * S + 8, Y0 + 12 + 5 * 13, "39 others", 9, extra=' font-style="italic"'))
svg.append(label(CX - 8, ty, "Arrows: the network's five most probable moves.", 9))
svg.append(label(CX - 8, ty + 12, "A promotion shares its pawn move's slot", 9))
svg.append(label(CX - 8, ty + 24, "and is played as a queen.", 9))

H = max(ty + 32, GY + 30)
head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 {H}" role="img" aria-label="The 4,096 actions: the policy'
        f' head scores 64 move types on each of 64 squares; 1,792 of these from-to pairs are possible moves; at the example'
        f' position the legal mask leaves {N_LEGAL} and the network puts 0.25 on d4.">')
defs = ('<defs><marker id="a8" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="4" markerHeight="4"'
        f' orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{ACCENT}"/></marker></defs>')
print(head + defs + f'<g font-family="{FONT}" fill="#1a1a1a">' + "".join(svg) + "</g></svg>")
