"""Draw Figure 1 of the D8 draft, value error by band, from this folder's JSON.

    python make_band_figure.py            # writes value-error-by-band.svg
    python make_band_figure.py --check    # checks that SVG's twelve bars against the JSON

Reads the JSON's `bands` block (mean |v - v_d11| per band and scorer, and each band's share of the
positions) and its `eval` block (positions and games) and writes plain SVG, with no third-party
package. value-error-by-band.png is the same figure rendered for the Word draft.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORT, FIGURE = HERE / "tanh-linear-d2-check-train.json", HERE / "value-error-by-band.svg"
BANDS = (("close |y|<0.3", "Close, |v| &lt; 0.3"), ("middle 0.3-0.9", "Leaning, 0.3 to 0.9"),
         ("decided |y|>0.9", "Decided, |v| &gt; 0.9"))
SCORERS = (("d1", "#9aa0a6", "Quick Stockfish (the paper's leaf)"), ("linear", "#a8c7f0", "Linear correction"),
           ("tanh_linear", "#4a86d8", "Linear, inside tanh"), ("network", "#1f3f8f", "Network 1"))
LEFT, RIGHT, BASE, TOP, TOP_VALUE = 70, 870, 380.0, 70.0, 0.12  # the plot area and its top value
BAR, GAP = 44, 10
INK, MUTED, GRID = "#1a2118", "#5f6b5a", "#e3e6e0"
SCALE = (BASE - TOP) / TOP_VALUE  # pixels per unit of value error


def svg(report) -> str:
    bands, rows, games = report["bands"], report["eval"]["rows"], report["eval"]["games"]
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="900" height="470" '
           'font-family="Calibri, Carlito, Arial, sans-serif">',
           '<rect width="900" height="470" fill="white"/>',
           f'<text x="70" y="30" font-size="20" font-weight="bold" fill="{INK}">Value error against careful '
           'Stockfish, by how decided the position is</text>',
           f'<text x="70" y="52" font-size="15" fill="{MUTED}">Mean |v - v_d11| on {rows:,} positions from '
           f'{games:,} fresh games; lower is better</text>']
    for i in range(7):
        tick = 0.02 * i
        y = BASE - tick * SCALE
        out.append(f'<line x1="{LEFT}" y1="{y:.1f}" x2="{RIGHT}" y2="{y:.1f}" stroke="{GRID}"/>')
        out.append(f'<text x="{LEFT - 8}" y="{y + 5:.1f}" font-size="13" text-anchor="end" fill="{MUTED}">'
                   f'{tick:.2f}</text>')
    width = (RIGHT - LEFT) / len(BANDS)
    for i, (key, label) in enumerate(BANDS):
        centre = LEFT + width * (i + 0.5)
        x = centre - (len(SCORERS) * BAR + (len(SCORERS) - 1) * GAP) / 2
        for name, colour, _ in SCORERS:
            value = bands[key][name]
            h = value * SCALE
            out.append(f'<rect x="{x:.1f}" y="{BASE - h:.1f}" width="{BAR}" height="{h:.1f}" fill="{colour}"/>')
            out.append(f'<text x="{x + BAR / 2:.1f}" y="{BASE - h - 6:.1f}" font-size="13" text-anchor="middle" '
                       f'fill="{INK}">{value:.3f}</text>')
            x += BAR + GAP
        out.append(f'<text x="{centre:.1f}" y="404" font-size="16" font-weight="bold" text-anchor="middle" '
                   f'fill="{INK}">{label}</text>')
        out.append(f'<text x="{centre:.1f}" y="424" font-size="14" text-anchor="middle" fill="{MUTED}">'
                   f'{bands[key]["share"]:.0%} of positions</text>')
    x = LEFT
    for _, colour, label in SCORERS:
        out.append(f'<rect x="{x}" y="448" width="14" height="14" fill="{colour}"/>')
        out.append(f'<text x="{x + 20}" y="460" font-size="14" fill="{INK}">{label}</text>')
        x += 46 + 7.4 * len(label)  # the swatch, then the label at about 7.4 px a character
    out.append("</svg>")
    return "\n".join(out)


def check(report, figure: str) -> int:
    """The bars of `figure`, in drawing order, against the JSON: the printed value to three
    decimals and the height to 0.05 px. Returns how many bars match."""
    bars = re.findall(r'<rect x="[\d.]+" y="[\d.]+" width="44" height="([\d.]+)" fill="#\w+"/>\n'
                      r'<text [^>]*>([\d.]+)</text>', figure)
    want = [report["bands"][key][name] for key, _ in BANDS for name, _, _ in SCORERS]
    if len(bars) != len(want):
        raise SystemExit(f"{len(bars)} bars in the figure, {len(want)} values in the JSON")
    for (height, printed), value in zip(bars, want):
        if printed != f"{value:.3f}" or abs(float(height) - value * SCALE) > 0.05:
            raise SystemExit(f"bar {printed} (height {height}) does not match {value}")
    return len(bars)


def main():
    report = json.loads(REPORT.read_text())
    if sys.argv[1:] == ["--check"]:
        print(f"{check(report, FIGURE.read_text())} bars match {REPORT.name}")
    else:
        FIGURE.write_text(svg(report))
        print(FIGURE)


if __name__ == "__main__":
    main()
