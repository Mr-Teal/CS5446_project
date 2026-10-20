// Fog Lab's boards: the pure helpers the page and its tests share, and drawing a board as a CSS grid of Unicode
// pieces, as in the approved mockups.
//
// Nothing here knows the rules of chess. A board is drawn from what the server sends (a FEN, or the squares and pieces
// of an observation), the moves come from the server's legal moves, and a click is reported as a square's name.
// Everything except drawBoard runs without a page, so Node's runner tests it: node --test tests/js/

const FILES = "abcdefgh";

// The Unicode chess symbols, white pieces in outline. Each is followed by U+FE0E, which asks for the text form:
// without it Windows draws the black pawn (U+265F) as a coloured emoji.
const SYMBOLS = {K: "\u2654", Q: "\u2655", R: "\u2656", B: "\u2657", N: "\u2658", P: "\u2659",
                 k: "\u265A", q: "\u265B", r: "\u265C", b: "\u265D", n: "\u265E", p: "\u265F"};
const TEXT_FORM = "\uFE0E";

const COORDS_FROM = 240;  // boards at least this wide (px) carry file letters and rank numbers in their edge squares

/** The pieces of a FEN (its first field is enough) as {square: piece letter}. Empty squares are left out. */
export function parseFen(fen) {
  const pieces = {};
  String(fen ?? "").trim().split(/\s+/)[0].split("/").slice(0, 8).forEach((row, index) => {
    let file = 0;
    for (const char of row) {
      if (/[1-8]/.test(char)) {
        file += Number(char);
      } else {
        if (file < 8) pieces[FILES[file] + (8 - index)] = char;
        file += 1;
      }
    }
  });
  return pieces;
}

/** The 64 square names in drawing order, row by row from the top left: a8, b8 .. h1, or h1, g1 .. a8 when `flip`
 * (Black at the bottom). */
export function displaySquares(flip) {
  const squares = [];
  for (let rank = 8; rank >= 1; rank -= 1) for (const file of FILES) squares.push(file + rank);
  return flip ? squares.reverse() : squares;
}

/** Whether `square` (such as "e4") is a dark square. a1 is dark. */
export function isDark(square) {
  return (FILES.indexOf(square[0]) + Number(square[1])) % 2 === 1;
}

/** A piece letter (KQRBNP for White, kqrbnp for Black) as its chess symbol in text form; "" for anything else. */
export function glyph(piece) {
  return typeof piece === "string" && Object.hasOwn(SYMBOLS, piece) ? SYMBOLS[piece] + TEXT_FORM : "";
}

/** The background for a value in [-1, 1], on the mockup's scale: the hue runs from red at -0.1 and below to green at
 * +0.5 and above, and the further the value is from 0, the darker. "transparent" when the value is not a number. */
export function heatColor(v) {
  if (typeof v !== "number" || !Number.isFinite(v)) return "transparent";
  const hue = 120 * Math.max(0, Math.min(1, (v + 0.1) / 0.6));
  return `hsl(${round1(hue)}, 65%, ${round1(88 - 40 * Math.abs(v))}%)`;
}

/** The `n` moves with the highest scores ({move: score}), followed by `chosen` when it is not among them: the table
 * always shows the move that was played (Ruling R13). Equal scores put `chosen` first and then go by name, so the
 * order never changes from one drawing to the next. [] when there are no scores. */
export function topMoves(scores, chosen, n = 6) {
  if (!scores) return [];
  const order = Object.keys(scores).sort(
    (a, b) => scores[b] - scores[a] || (b === chosen) - (a === chosen) || byName(a, b));
  const top = order.slice(0, n);
  if (typeof chosen === "string" && !top.includes(chosen)) top.push(chosen);
  return top;
}

/** The `n` moves with the lowest scores among those not in `exclude`, lowest first, equal scores by name. */
export function worstMoves(scores, exclude, n = 2) {
  if (!scores) return [];
  const skip = new Set(exclude ?? []);
  return Object.keys(scores).filter(move => !skip.has(move))
    .sort((a, b) => scores[a] - scores[b] || byName(a, b)).slice(0, n);
}

/** The moves in `legalMoves` (UCI) that start on `from`, grouped by the square they go to: {to: [uci, ...]}. A
 * promotion gives one move per piece on the same square, so the page must ask which; castling is the king's move of
 * two squares. */
export function moveTargets(legalMoves, from) {
  const targets = {};
  for (const move of legalMoves ?? []) {
    if (move.slice(0, 2) === from) (targets[move.slice(2, 4)] ??= []).push(move);
  }
  return targets;
}

/**
 * Draw a board into `el`, replacing what it held, as a grid of 64 squares.
 * - fen: the pieces, as a FEN or as {square: piece letter or null}, the form of an observation's visible_pieces.
 * - visible: the squares that are seen. Every other square is hatched as fog and shows no piece. null hides none.
 * - flip: Black at the bottom.
 * - marks: {class name: [squares]}; each listed square gets that class (the last move, a selected piece, its targets).
 * - size: the board's width and height in px.
 * - onSquare: called with a square's name when the square is clicked; null for a board that takes no clicks.
 * Each square is a div with data-square, and a piece is a span.pc inside it; a square holding a piece has has-piece.
 */
export function drawBoard(el, {fen = null, visible = null, flip = false, marks = {}, size = 320, onSquare = null} = {}) {
  const pieces = typeof fen === "string" ? parseFen(fen) : (fen ?? {});
  const seen = visible ? new Set(visible) : null;
  const marked = Object.entries(marks ?? {}).map(([name, squares]) => [name, new Set(squares ?? [])]);
  const coords = size >= COORDS_FROM;
  const cells = displaySquares(flip).map((square, index) => {
    const cell = document.createElement("div");
    cell.className = `sq ${isDark(square) ? "dk" : "lt"}`;
    cell.dataset.square = square;
    const symbol = glyph(pieces[square]);
    if (seen && !seen.has(square)) {
      cell.classList.add("fog");
    } else if (symbol) {
      cell.append(span("pc", symbol));
      cell.classList.add("has-piece");
    }
    for (const [name, squares] of marked) if (squares.has(square)) cell.classList.add(name);
    if (coords && index % 8 === 0) cell.append(span("coord rank", square[1]));
    if (coords && index >= 56) cell.append(span("coord file", square[0]));
    return cell;
  });
  el.classList.add("board");
  el.classList.toggle("clickable", typeof onSquare === "function");
  el.style.width = el.style.height = `${size}px`;
  el.style.fontSize = `${(size / 8) * 0.72}px`;
  el.replaceChildren(...cells);
  el.onclick = typeof onSquare === "function" ? event => {
    const cell = event.target.closest("[data-square]");
    if (cell && el.contains(cell)) onSquare(cell.dataset.square);
  } : null;
}

function span(className, text) {
  const node = document.createElement("span");
  node.className = className;
  node.textContent = text;
  return node;
}

function round1(x) {
  return Math.round(x * 10) / 10;
}

function byName(a, b) {
  return a < b ? -1 : a > b ? 1 : 0;
}
