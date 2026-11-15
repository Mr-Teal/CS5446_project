"""All six report figures redrawn for the course format (15 Nov 2026): the canvas is 451 units wide, the text column
of an A4 page with 1-inch margins in points, so one unit prints as one point and every label is at least 12 pt.
Chess piece symbols stay small (pictures, not text). Writes fig_problem_12.svg, fig_tracking_12.svg,
state_figure_12.svg, fig_architecture_12.svg, fig_actions_12.svg and fig_pipeline_12.svg next to this script.
Data: qa4_figure_data.json, qa4_planes.json, tracking_ply1.json, qa4_legal.json (all computed on the VM)."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
W = 451
FS = 12
GLYPH = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
         "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}
VS = "︎"
LIGHT, DARK, FOG_L, FOG_D = "#f4f1ea", "#ddd6c8", "#bcc5ce", "#aab4be"
ACCENT, BLUE, SHADE, INK = "#b03a2e", "#2f4f6f", "#e3e8ee", "#1a1a1a"
FONT = "Times New Roman, Times, serif"
PFONT = "Apple Symbols, DejaVu Sans, Segoe UI Symbol, serif"
FILES = "abcdefgh"


def load(name):
    return json.load(open(os.path.join(HERE, name)))


def t(x, y, s, size=FS, anchor="start", bold=False, italic=False, fill=None, halo=False):
    assert size >= 12, s
    a = f' font-weight="bold"' if bold else ""
    a += ' font-style="italic"' if italic else ""
    a += f' fill="{fill}"' if fill else ""
    a += ' stroke="#ffffff" stroke-width="3" paint-order="stroke"' if halo else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}"{a}>{s}</text>'


def glyph(ch, cx, cy, size, opacity=1.0):
    op = f' opacity="{opacity:.2f}"' if opacity < 0.999 else ""
    return (f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="{size:.1f}" text-anchor="middle" dominant-baseline="central"'
            f' font-family="{PFONT}"{op}>{GLYPH[ch]}{VS}</text>')


def rect(x, y, w, h, fill="none", stroke=INK, sw=0.8, extra=""):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{extra}/>'


def arrow(x1, y1, x2, y2, mid="ar", color=INK, dash=False, width=1.0):
    d = ' stroke-dasharray="3 2"' if dash else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{width}"'
            f' marker-end="url(#{mid})"{d}/>')


def svg(name, height, body, label):
    defs = ('<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6"'
            ' orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#1a1a1a"/></marker>'
            '<marker id="ara" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="4" markerHeight="4"'
            f' orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{ACCENT}"/></marker></defs>')
    out = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" role="img" aria-label="{label}">'
           f'{defs}<g font-family="{FONT}" fill="{INK}">{"".join(body)}</g></svg>')
    open(os.path.join(HERE, name), "w").write(out)


def board_from_fen(fen):
    out = {}
    for r, row in enumerate(fen.split()[0].split("/")):
        f = 0
        for ch in row:
            if ch.isdigit():
                f += int(ch)
            else:
                out[FILES[f] + str(8 - r)] = ch
                f += 1
    return out


def board(pieces, x0, y0, s, gsize, ranks=range(8, 0, -1), visible=None, opacity=1.0, mark=None, coords=False,
          show_hidden=True):
    """Squares, rank 8 at the top; visible = set of squares Black sees (others greyed), None = all clear."""
    out = [f'<g opacity="{opacity:.2f}">'] if opacity < 0.999 else []
    ranks = list(ranks)
    for row, r in enumerate(ranks):
        for col, f in enumerate(FILES):
            sq = f + str(r)
            light = (col + r) % 2 == 1
            fog = visible is not None and sq not in visible
            fill = (FOG_L if light else FOG_D) if fog else (LIGHT if light else DARK)
            out.append(f'<rect x="{x0 + col * s:.1f}" y="{y0 + row * s:.1f}" width="{s:.2f}" height="{s:.2f}" fill="{fill}"/>')
            ch = pieces.get(sq)
            if ch and (show_hidden or not fog):
                out.append(glyph(ch, x0 + col * s + s / 2, y0 + row * s + s / 2 + s * 0.05, gsize))
    if mark:
        col, row = FILES.index(mark[0]), ranks.index(int(mark[1]))
        out.append(rect(x0 + col * s, y0 + row * s, s, s, stroke=ACCENT, sw=1.2))
    out.append(rect(x0, y0, 8 * s, len(ranks) * s, sw=0.7))
    if coords:
        for i, f in enumerate(FILES):
            out.append(t(x0 + i * s + s / 2, y0 + len(ranks) * s + 12, f, anchor="middle"))
        for i, r in enumerate(ranks):
            out.append(t(x0 - 4, y0 + i * s + s / 2 + 4, str(r), anchor="end"))
    if opacity < 0.999:
        out.append("</g>")
    return out


# ---------------------------------------------------------------- Figure 1: three problem types
def fig_problem():
    b = []
    for k, (title, agent, up) in enumerate([("(a) MDP", "Agent", "s, r"), ("(b) POMDP", "Agent, b(s)", "o, r"),
                                             ("(c) Our game", None, None)]):
        x0 = k * 152
        b.append(rect(x0 + 0.5, 0.5, 146, 168, stroke=ACCENT if k == 2 else "#bbbbbb", sw=1.3 if k == 2 else 0.8))
        b.append(t(x0 + 6, 16, title, bold=k == 2))
        if agent:
            aw = 64 if k == 0 else 84
            b.append(rect(x0 + 73 - aw / 2, 26, aw, 24))
            b.append(t(x0 + 73, 42, agent, anchor="middle"))
            b.append(rect(x0 + 10, 100, 126, 40))
            b.append(t(x0 + 73, 116, "Environment", anchor="middle"))
            b.append(t(x0 + 73, 132, "opponent fixed", anchor="middle", italic=True))
            b.append(arrow(x0 + 52, 100, x0 + 52, 52))
            b.append(arrow(x0 + 94, 50, x0 + 94, 98))
            b.append(t(x0 + 47, 80, up, anchor="end"))
            b.append(t(x0 + 99, 80, "a"))
        else:
            b.append(rect(x0 + 5, 26, 54, 24)); b.append(t(x0 + 32, 42, "White", anchor="middle"))
            b.append(rect(x0 + 87, 26, 54, 24)); b.append(t(x0 + 114, 42, "Black", anchor="middle"))
            b.append(rect(x0 + 18, 100, 110, 40))
            b.append(t(x0 + 73, 116, "Referee", anchor="middle"))
            b.append(t(x0 + 73, 132, "true board", anchor="middle", italic=True))
            b.append(arrow(x0 + 38, 100, x0 + 22, 52)); b.append(arrow(x0 + 40, 50, x0 + 58, 98))
            b.append(arrow(x0 + 108, 100, x0 + 124, 52)); b.append(arrow(x0 + 106, 50, x0 + 88, 98))
            b.append(t(x0 + 6, 82, "o<tspan baseline-shift=\"sub\">W</tspan>"))
            b.append(t(x0 + 141, 82, "o<tspan baseline-shift=\"sub\">B</tspan>", anchor="end"))
            b.append(t(x0 + 73, 72, "moves", anchor="middle"))
            b.append(t(x0 + 73, 158, "u<tspan baseline-shift=\"sub\">W</tspan> = −u<tspan baseline-shift=\"sub\">B</tspan>",
                       anchor="middle"))
    svg("fig_problem_12.svg", 170, b, "Three problem types: MDP, POMDP, and a two-player zero-sum game with hidden information.")


# ---------------------------------------------------------------- Figure 2: tracker, ply 0 -> 1
def fig_tracking():
    d = load("tracking_ply1.json")
    vis = set(d["visible"])
    sampled = {s["first"] for s in d["sampled"]}
    start = board_from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR")
    b = []
    b.append(t(0, 13, "(a) Ply 0: one stored board"))
    b += board(start, 2, 22, 12, 10.5)
    b.append(t(250, 13, "(c) Black's view after 1.Nh3"))
    b += board(dict(start, h3="N", **{}) if False else {**{k: v for k, v in start.items() if k != "g1"}, "h3": "N"},
               250, 22, 12, 10.5, visible=vis, show_hidden=False)
    b.append(t(104, 64, "expand: play"))
    b.append(t(104, 79, "every White"))
    b.append(t(104, 94, "first move ↓"))
    b.append(t(352, 64, "the same on"))
    b.append(t(352, 79, "all 20 boards:"))
    b.append(t(352, 94, "all 20 kept"))
    b.append(t(0, 140, "(b) 20 boards, one per White first move (ranks 1–4 drawn)"))
    pawn = sorted(m for m in d["legal"] if start[m[:2]] == "P")
    knight = sorted(m for m in d["legal"] if start[m[:2]] == "N")
    moves = pawn + knight
    for k, m in enumerate(moves):
        col, row = k % 10, k // 10
        x, y = 2.5 + col * 45, 148 + row * 46
        p = {sq: ch for sq, ch in start.items() if sq != m[:2]}
        p[m[2:4]] = start[m[:2]]
        b += board(p, x, y, 5, 4.6, ranks=range(4, 0, -1), opacity=1.0 if m in sampled else 0.33, mark=m[2:4])
        name = ("N" if start[m[:2]] == "N" else "") + m[2:4]
        b.append(t(x + 20, y + 20 + 14, name, anchor="middle", bold=m == "g1h3", fill="#8a8a8a" if m not in sampled else None))
    svg("fig_tracking_12.svg", 242, b, "Black's first tracker update: one stored start board expands into 20 boards, all 20 match what Black sees, 16 are sampled.")


# ---------------------------------------------------------------- Figure 3: the probability board
def fig_state():
    D = load("qa4_figure_data.json")
    P = load("qa4_planes.json")["planes"]
    vis = set(D["visible_squares"])
    b = []
    # (a) what Black sees
    b.append(t(0, 13, "(a) What Black sees"))
    b += board(D["visible_pieces"], 14, 22, 13, 11.5, visible=vis, coords=True)
    b.append(arrow(124, 74, 150, 74))
    b.append(t(137, 66, "tracker", anchor="middle", italic=True))
    # (b) four of the ten boards
    b.append(t(156, 13, "(b) 10 boards, 0.1 each"))
    hyps = {h["white_third_move"]: h for h in D["hypotheses"]}
    for k, (mv, name) in enumerate([("d1a4", "Qa4+ (true)"), ("d1c2", "Qc2"), ("b1c3", "Nc3"), ("e2e3", "e3")]):
        x, y = 160 + (k % 2) * 92, 22 + (k // 2) * 96
        b += board(board_from_fen(hyps[mv]["fen"]), x, y, 9.5, 8.6, visible=vis, mark=mv[2:4])
        b.append(t(x + 38, y + 76 + 14, name, anchor="middle", bold=mv == "d1a4"))
    b.append(t(350, 106, "+ 6 more", italic=True))
    b.append(arrow(345, 128, 372, 128))
    b.append(t(358, 146, "average", anchor="middle", italic=True))
    # (c) the probability board
    Y2 = 226
    b.append(t(0, Y2, "(c) Probability board"))
    s = 24
    x0, y0 = 0, Y2 + 8
    for row, r in enumerate(range(8, 0, -1)):
        for col, f in enumerate(FILES):
            sq = f + str(r)
            light = (col + r) % 2 == 1
            fog = sq not in vis
            fill = (FOG_L if light else FOG_D) if fog else (LIGHT if light else DARK)
            b.append(f'<rect x="{x0 + col * s}" y="{y0 + row * s}" width="{s}" height="{s}" fill="{fill}"/>')
    for sq, ch in D["visible_pieces"].items():
        col, row = FILES.index(sq[0]), 8 - int(sq[1])
        b.append(glyph(ch, x0 + col * s + s / 2, y0 + row * s + s / 2 + 1, 18))
    for sq, probs in D["white_piece_probability"].items():
        if sq in vis:
            continue
        col, row = FILES.index(sq[0]), 8 - int(sq[1])
        x, y = x0 + col * s, y0 + row * s
        items = sorted(probs.items(), key=lambda kv: "PNBRQK".index(kv[0]))
        if len(items) == 1 and items[0][1] > 0.999:
            b.append(glyph(items[0][0], x + s / 2, y + s / 2 + 1, 18))
        elif len(items) == 1:
            ch, p = items[0]
            b.append(glyph(ch, x + s / 2, y + 8, 12, max(p, 0.35)))
            b.append(t(x + s / 2, y + s - 2, f"{p:.1f}".lstrip("0"), anchor="middle", bold=True))
        else:
            for j, (ch, p) in enumerate(items):
                cx = x + s * (0.27 + 0.46 * j)
                b.append(glyph(ch, cx, y + 7, 9, max(p, 0.35)))
                b.append(t(cx, y + s - 2, f"{p:.1f}".lstrip("0"), anchor="middle", bold=True))
    b.append(rect(x0, y0, 8 * s, 8 * s, sw=0.7))
    # (d) four planes with their values
    b.append(t(208, Y2, "(d) Four of the 32 planes (blank = 0)"))
    hs = 13
    for k, (plane, name) in enumerate([("0", "own: pawns"), ("6", "enemy seen: pawns"), ("18", "queen probability"),
                                        ("21", "opponent's view")]):
        hx, hy = 210 + (k % 2) * 124, Y2 + 8 + (k // 2) * 126
        cells = P[plane]
        for row, r in enumerate(range(8, 0, -1)):
            for col, f in enumerate(FILES):
                v = cells.get(f + str(r), 0.0)
                c = round(255 - v * 185), round(255 - v * 160), round(255 - v * 130)
                b.append(f'<rect x="{hx + col * hs}" y="{hy + row * hs}" width="{hs}" height="{hs}" fill="#%02x%02x%02x"'
                         f' stroke="#d0d0d0" stroke-width="0.4"/>' % c)
                if v > 0:
                    txt = "1" if v > 0.995 else f"{v:.1f}".lstrip("0")
                    b.append(t(hx + col * hs + hs / 2, hy + row * hs + hs - 2.5, txt, anchor="middle",
                               fill="#ffffff" if v >= 0.55 else None))
        b.append(rect(hx, hy, 8 * hs, 8 * hs, sw=0.7))
        b.append(t(hx, hy + 8 * hs + 14, name))
    # (e) the 32 planes in groups
    Y3 = Y2 + 8 + 2 * 126 + 14
    b.append(t(0, Y3, "(e) The 32 planes in groups; shaded: from the sampled boards"))
    groups = [(["own", "pieces"], 6, False), (["enemy", "seen"], 6, False), (["squares", "seen"], 2, False),
              (["enemy", "probability"], 6, True), (["opponent's", "view"], 2, True), (["size, ply,", "2 zero"], 4, False),
              (["castling,", "clocks"], 6, False)]
    gw = (W - 6 * 3) / 7
    for k, (lines, n, shaded) in enumerate(groups):
        x = k * (gw + 3)
        b.append(rect(x, Y3 + 8, gw, 50, fill=SHADE if shaded else "none"))
        for j, line in enumerate(lines):
            b.append(t(x + gw / 2, Y3 + 23 + j * 14, line, anchor="middle"))
        b.append(t(x + gw / 2, Y3 + 52, f"×{n}", anchor="middle", italic=True))
    svg("state_figure_12.svg", Y3 + 62, b, "The probability board at 1.Nh3 d5 2.c4 Qd6 3.Qa4+, Black to move.")


# ---------------------------------------------------------------- Figure 4: architecture
def fig_architecture():
    b = []
    b.append(t(0, 13, "Encoder", italic=True))
    for k in range(3):
        b.append(rect(8 - 3 * k, 24 + 3 * k, 42, 42, fill=SHADE))
    b.append(t(27, 88, "32 × 8 × 8", anchor="middle"))
    b.append(arrow(52, 47, 70, 47))
    b.append(rect(72, 20, 106, 62))
    for j, (s, kw) in enumerate([("Stem", {"bold": True}), ("conv 3×3, 32→64", {}), ("BN, ReLU", {}),
                                  ("18,560 params", {"italic": True})]):
        b.append(t(125, 34 + j * 14, s, anchor="middle", **kw))
    b.append(arrow(178, 51, 194, 51))
    for k in range(3):
        b.append(rect(204 - 3 * k, 16 + 3 * k, 108, 62, fill="#ffffff"))
    for j, (s, kw) in enumerate([("Residual block", {"bold": True}), ("× 6, 64 channels", {}), ("(detail below)", {}),
                                  ("443,904 params", {"italic": True})]):
        b.append(t(252, 34 + j * 14, s, anchor="middle", **kw))
    b.append(arrow(306, 51, 324, 51))
    for k in range(3):
        b.append(rect(334 - 3 * k, 24 + 3 * k, 42, 42, fill="#ffffff"))
    b.append(t(353, 88, "64 × 8 × 8", anchor="middle"))
    b.append(f'<path d="M378,47 L440,47 L440,104 L57,104 L57,118" fill="none" stroke="{INK}" marker-end="url(#ar)"/>')
    b.append(t(0, 103, "Head", italic=True))
    rows2 = [(0, "Move head", ["conv 3×3, ReLU", "conv 1×1", "41,088 params"]),
             (150, "Scores", ["64 types × 64", "squares: 4,096", "(Figure 5a)"]),
             (300, "Fixed table", ["1,792 on-board", "→ from–to slot", "(Figure 5b)"])]
    for x, head, lines in rows2:
        b.append(rect(x + 2, 120, 140, 62, fill=SHADE if head == "Scores" else "none"))
        b.append(t(x + 72, 134, head, anchor="middle", bold=True))
        for j, line in enumerate(lines):
            b.append(t(x + 72, 148 + j * 14, line, anchor="middle", italic=line.startswith("(") or "params" in line))
    b.append(arrow(142, 151, 150, 151)); b.append(arrow(292, 151, 300, 151))
    b.append(f'<path d="M372,182 L372,194 L120,194 L120,204" fill="none" stroke="{INK}" marker-end="url(#ar)"/>')
    b.append(rect(40, 206, 160, 34))
    b.append(t(120, 220, "Legal mask", anchor="middle", bold=True))
    b.append(t(120, 234, "not legal → −∞ (Figure 5c)", anchor="middle"))
    b.append(arrow(200, 223, 222, 223))
    b.append(rect(224, 206, 220, 34, fill=SHADE, stroke=ACCENT, sw=1.3))
    b.append(t(334, 220, "Softmax: π(a | board)", anchor="middle", bold=True))
    b.append(t(334, 234, "play the most probable move", anchor="middle"))
    # residual block
    Y = 270
    b.append(t(0, Y - 8, "One residual block (73,984 params); BN = batch normalisation", italic=True))
    items = [("x", None), ("conv 3×3", 54), ("BN", 26), ("ReLU", 34), ("conv 3×3", 54), ("BN", 26), ("+", 0), ("ReLU", 34),
             ("out", None)]
    x = 2
    centres = []
    for k, (name, w) in enumerate(items):
        if w is None:
            b.append(t(x, Y + 15, name)); cx, x2 = x + 4, x + (8 if name == "x" else 18)
        elif w == 0:
            b.append(f'<circle cx="{x + 9}" cy="{Y + 11}" r="9" fill="none" stroke="{INK}"/>')
            b.append(t(x + 9, Y + 15.5, "+", anchor="middle")); cx, x2 = x + 9, x + 18
        else:
            b.append(rect(x, Y, w, 22)); b.append(t(x + w / 2, Y + 15, name, anchor="middle")); cx, x2 = x + w / 2, x + w
        centres.append(cx)
        if k < len(items) - 1:
            b.append(arrow(x2 + 1, Y + 11, x2 + 15, Y + 11))
            x = x2 + 17
    plus_x = centres[6]
    b.append(f'<path d="M6,{Y + 22} L6,{Y + 34} L{plus_x},{Y + 34} L{plus_x},{Y + 22}" fill="none" stroke="{INK}"'
             f' stroke-dasharray="3 2" marker-end="url(#ar)"/>')
    b.append(t(plus_x / 2, Y + 48, "skip connection: x is added back", anchor="middle", italic=True))
    svg("fig_architecture_12.svg", Y + 54, b, "Policy network architecture: stem, six residual blocks, move head, fixed table, legal mask, softmax.")


# ---------------------------------------------------------------- Figure 5: the 4,096 actions
def fig_actions():
    D = load("qa4_figure_data.json")
    legal = set(load("qa4_legal.json")["legal"])
    dirs = ((-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1))
    knight = ((-2, -1), (-2, 1), (-1, 2), (1, 2), (2, 1), (2, -1), (1, -2), (-1, -2))
    types = tuple((dr * k, dc * k) for dr, dc in dirs for k in range(1, 8)) + knight
    b = []
    s = 14
    # (a)
    b.append(t(0, 13, "(a) 64 move types"))
    b += board({}, 14, 22, s, 10, coords=True)
    fr, fc = 4, 3
    for k, (dr, dc) in enumerate(types):
        r, c = fr + dr, fc + dc
        if 0 <= r < 8 and 0 <= c < 8:
            cx, cy = 14 + c * s + s / 2, 22 + r * s + s / 2
            if k < 56:
                b.append(f'<circle cx="{cx}" cy="{cy}" r="3" fill="{BLUE}"/>')
            else:
                b.append(f'<rect x="{cx - 3}" y="{cy - 3}" width="6" height="6" fill="{ACCENT}" transform="rotate(45 {cx} {cy})"/>')
    b.append(rect(14 + fc * s + 1, 22 + fr * s + 1, s - 2, s - 2, sw=1.6))
    ly = 22 + 8 * s + 30
    b.append(f'<circle cx="5" cy="{ly - 4}" r="3" fill="{BLUE}"/>'); b.append(t(12, ly, "queen-like: 56"))
    b.append(f'<rect x="2" y="{ly + 7}" width="6" height="6" fill="{ACCENT}" transform="rotate(45 5 {ly + 10})"/>')
    b.append(t(12, ly + 15, "knight: 8"))
    b.append(t(0, ly + 30, "from d4: 35 on board"))
    # (b)
    gx, gy, c = 172, 22, 1.9
    b.append(t(152, 13, "(b) All 4,096 pairs"))
    reach = set()
    for r in range(8):
        for cc in range(8):
            for dr, dc in types:
                if 0 <= r + dr < 8 and 0 <= cc + dc < 8:
                    reach.add(((7 - r) * 8 + cc, (7 - r - dr) * 8 + cc + dc))
    assert len(reach) == 1792

    def sqi(n):
        return (int(n[1]) - 1) * 8 + FILES.index(n[0])
    cells = {(sqi(m[:2]), sqi(m[2:4])) for m in legal}
    b.append(f'<rect x="{gx}" y="{gy}" width="{64 * c}" height="{64 * c}" fill="#ececec"/>')
    for f, to in sorted(reach):
        b.append(f'<rect x="{gx + to * c:.2f}" y="{gy + f * c:.2f}" width="{c}" height="{c}" fill="#b9cadb"/>')
    for f, to in sorted(cells):
        col = ACCENT if (f, to) == (sqi("d5"), sqi("d4")) else BLUE
        b.append(f'<rect x="{gx + to * c - 0.5:.2f}" y="{gy + f * c - 0.5:.2f}" width="{c + 1}" height="{c + 1}" fill="{col}"/>')
    b.append(rect(gx, gy, 64 * c, 64 * c, sw=0.7))
    b.append(t(gx - 3, gy + 10, "a1", anchor="end")); b.append(t(gx - 3, gy + 64 * c, "h8", anchor="end"))
    b.append(t(gx, gy + 64 * c + 13, "a1")); b.append(t(gx + 64 * c, gy + 64 * c + 13, "h8", anchor="end"))
    for k, (fill, text) in enumerate([("#ececec", "never: 2,304"), ("#b9cadb", "possible: 1,792"), (BLUE, "legal here: 44"),
                                      (ACCENT, "played: d4")]):
        y = gy + 64 * c + 20 + k * 15
        b.append(rect(152, y - 1, 9, 9, fill=fill, stroke="#888888", sw=0.4)); b.append(t(165, y + 8, text))
    # (c)
    cx0 = 318
    b.append(t(300, 13, "(c) The 44 legal moves"))
    vis = set(D["visible_squares"])
    b += board(D["visible_pieces"], cx0, 22, s, 12, visible=vis, show_hidden=False)
    top = [("d5d4", ".25", "d4"), ("d5c4", ".21", "dxc4"), ("g8f6", ".20", "Nf6"), ("c7c6", ".08", "c6"), ("b8c6", ".07", "Nc6")]

    def ctr(sq):
        return cx0 + FILES.index(sq[0]) * s + s / 2, 22 + (8 - int(sq[1])) * s + s / 2
    for k, (mv, p, name) in enumerate(top):
        (x1, y1), (x2, y2) = ctr(mv[:2]), ctr(mv[2:4])
        b.append(arrow(x1, y1, x2 - (x2 - x1) * 0.15, y2 - (y2 - y1) * 0.15, mid="ara", color=ACCENT, width=1 + 5 * float(p)))
    for k, (mv, p, name) in enumerate(top):
        col = 300 + (k % 2) * 76
        b.append(t(col, ly + (k // 2) * 15, f"{name} {p}", bold=k == 0))
    b.append(t(376, ly + 30, "39 others", italic=True))
    svg("fig_actions_12.svg", max(ly + 36, gy + 64 * c + 20 + 4 * 15 + 2), b, "The 4,096 actions: 64 move types, the 64 by 64 grid of from-to pairs, and the 44 legal moves at the example position.")


# ---------------------------------------------------------------- Figure 6: data collection
def fig_pipeline():
    b = []
    b.append(t(0, 13, "Offline: collect, label, train", italic=True))
    boxes = [(0, 20, "1 Games", "961, both colours", False), (155, 20, "2 Positions", "58,693, mover's view", False),
             (310, 20, "3 Re-solve", "30 s, Stockfish d8", True), (0, 96, "4 Train", "cross-entropy", False),
             (310, 96, "5 Play", "probability board", False)]
    for x, y, head, body, shaded in boxes:
        b.append(rect(x + 1, y, 139, 40, fill=SHADE if shaded else "none"))
        b.append(t(x + 70, y + 16, head, anchor="middle", bold=True))
        b.append(t(x + 70, y + 32, body, anchor="middle"))
    b.append(arrow(141, 40, 154, 40)); b.append(arrow(296, 40, 309, 40))
    b.append(f'<path d="M380,60 L380,76 L70,76 L70,94" fill="none" stroke="{INK}" marker-end="url(#ar)"/>')
    b.append(arrow(141, 116, 309, 116))
    b.append(t(225, 110, "at play time", anchor="middle", italic=True))
    svg("fig_pipeline_12.svg", 138, b, "How the training data is made: games, positions, re-solve, training, play.")


# ---------------------------------------------------------------- the teacher's subgame (12-pt)
def fig_subgame():
    b = []
    b.append(t(110, 13, "our information set (2 of 16 boards): one move for all", italic=True))
    b.append(rect(104, 20, 340, 40, fill=SHADE, extra=' rx="8" stroke-dasharray="4 3"'))
    for x, name in ((150, "board 1"), (330, "board 2")):
        b.append(rect(x, 29, 62, 22, fill="#ffffff"))
        b.append(t(x + 31, 45, name, anchor="middle"))
    levels = [(44, "our boards"), (84, "our move"), (118, "opponent"), (152, "its reply"), (190, "leaf value")]
    for y, name in levels:
        b.append(t(0, y, name))
    nodes = []
    for bx in (181, 361):
        for dx, mv in ((-52, "a"), (52, "b")):
            nx = bx + dx
            b.append(f'<line x1="{bx + (dx / 6):.1f}" y1="51" x2="{nx}" y2="108" stroke="{INK}" stroke-width="1.6"/>')
            b.append(t((bx + nx) / 2 + (-17 if dx < 0 else 17), 84, mv, anchor="middle", bold=True))
            nodes.append(nx)
    for bx in (181, 361):
        b.append(rect(bx - 66, 103, 132, 22, extra=' rx="10" stroke-dasharray="3 3"'))
        b.append(t(bx, 140, "may not see a or b", anchor="middle", italic=True, halo=True))
    for nx in nodes:
        b.append(f'<circle cx="{nx}" cy="114" r="6" fill="#ffffff" stroke="{INK}"/>')
        for lx in (nx - 17, nx + 17):
            b.append(f'<line x1="{nx}" y1="120" x2="{lx}" y2="174" stroke="{INK}"/>')
            b.append(rect(lx - 8, 174, 16, 16, fill="#ffffff"))
            b.append(t(lx, 186.5, "v", anchor="middle", italic=True))
    # re-draw the halo labels on top of the reply lines
    for bx in (181, 361):
        b.append(t(bx, 140, "may not see a or b", anchor="middle", italic=True, halo=True))
    svg("fig_subgame_12.svg", 196, b, "The teacher's subgame: two of the sixteen sampled boards inside one information set of ours, our moves a and b, the opponent's replies, and leaf values.")


for f in (fig_problem, fig_tracking, fig_state, fig_architecture, fig_actions, fig_pipeline, fig_subgame):
    f()
print("ok")
