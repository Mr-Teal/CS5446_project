// The Play page's pure helpers (static/board.js), run with Node's own runner: node --test tests/js/
import test from "node:test"; import assert from "node:assert/strict";
import {parseFen, displaySquares, isDark, glyph} from "../../src/pairb/lab/static/board.js";
import {heatColor, topMoves, worstMoves, moveTargets} from "../../src/pairb/lab/static/board.js";

test("start position", () => { const m = parseFen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
  assert.equal(m.e1, "K"); assert.equal(m.d8, "q"); assert.equal(Object.keys(m).length, 32); });
test("orientation", () => { assert.equal(displaySquares(false)[0], "a8"); assert.equal(displaySquares(false)[63], "h1");
  assert.equal(displaySquares(true)[0], "h1"); });
test("colours", () => { assert.ok(isDark("a1")); assert.ok(!isDark("h1")); assert.ok(isDark("h8")); });
test("text glyphs", () => { assert.ok(glyph("p").endsWith("\uFE0E")); });

// Catches: digits read as one empty square each, and a board part without the other FEN fields refused.
test("a board part alone, with gaps", () => {
  assert.deepEqual(parseFen("8/8/8/3p4/4P3/8/8/4K2k"), {d5: "p", e4: "P", e1: "K", h1: "k"});
});

// Catches: rows drawn in the wrong order (a board read down instead of across), and a turned board that is only
// mirrored: Black's view has h1 top left and a8 bottom right.
test("rows read across, and the turned board is the same squares backwards", () => {
  const white = displaySquares(false), black = displaySquares(true);
  assert.deepEqual(white.slice(0, 9), ["a8", "b8", "c8", "d8", "e8", "f8", "g8", "h8", "a7"]);
  assert.equal(black[63], "a8"); assert.deepEqual(black, [...white].reverse());
  assert.equal(new Set(white).size, 64);
});

// Catches: a white king drawn as a black one, and the emoji form of the black pawn on Windows.
test("each piece has its own symbol, as text", () => {
  assert.equal(glyph("K"), "\u2654\uFE0E"); assert.equal(glyph("P"), "\u2659\uFE0E");
  assert.equal(glyph("k"), "\u265A\uFE0E"); assert.equal(glyph("p"), "\u265F\uFE0E");
  assert.equal(glyph(null), ""); assert.equal(glyph("x"), "");
});

// The mockup's scale: hue from red (-0.1 and below) to green (+0.5 and above), lighter near 0.
test("heat colours follow the value", () => {
  assert.equal(heatColor(0.5), "hsl(120, 65%, 68%)");
  assert.equal(heatColor(0.2), "hsl(60, 65%, 80%)");
  assert.equal(heatColor(-0.1), "hsl(0, 65%, 84%)");
  assert.equal(heatColor(-1), "hsl(0, 65%, 48%)"); assert.equal(heatColor(1), "hsl(120, 65%, 48%)");
  assert.equal(heatColor(null), "transparent"); assert.equal(heatColor(undefined), "transparent");
});

// Ruling R13. Catches: the chosen move missing from the table when material values tie (it can be any of many equal
// moves), and a tie order that changes between draws.
test("the top moves always hold the chosen one", () => {
  const scores = {a2a3: 0, b2b3: 0, c2c3: 0, d2d3: 0, e2e3: 0, f2f3: 0, g2g3: 0, h2h3: 0, e2e4: 0.5};
  assert.deepEqual(topMoves(scores, "e2e4"), ["e2e4", "a2a3", "b2b3", "c2c3", "d2d3", "e2e3"]);
  assert.deepEqual(topMoves(scores, "h2h3"), ["e2e4", "h2h3", "a2a3", "b2b3", "c2c3", "d2d3"]);
  const low = {a: 0.9, b: 0.8, c: 0.7, d: 0.6, e: 0.5, f: 0.4, g: 0.3, h: -0.2};
  assert.deepEqual(topMoves(low, "h"), ["a", "b", "c", "d", "e", "f", "h"]);  // a policy can choose below the top 6
  assert.deepEqual(topMoves(low, "h", 2), ["a", "b", "h"]);
  assert.deepEqual(topMoves({a: 0.1}, "a"), ["a"]); assert.deepEqual(topMoves(null, "a"), []);
});

// Catches: the worst moves repeating rows already in the table, and ties read in a changing order.
test("the worst moves are the lowest of the rest", () => {
  const scores = {a: 0.3, b: -0.65, c: 0.1, d: -0.59, e: -0.65};
  assert.deepEqual(worstMoves(scores, []), ["b", "e"]);
  assert.deepEqual(worstMoves(scores, ["b"]), ["e", "d"]);
  assert.deepEqual(worstMoves(scores, Object.keys(scores)), []);
  assert.deepEqual(worstMoves(null, []), []);
});

// Catches: a promotion offered as one move (the piece must be asked for), and castling missing from the king's
// destinations: castling is the king moving two squares.
test("click-to-move targets come from the legal moves only", () => {
  const legal = ["a7a8q", "a7a8r", "a7a8b", "a7a8n", "e1g1", "e1f1", "h2h3"];
  assert.deepEqual(moveTargets(legal, "a7"), {a8: ["a7a8q", "a7a8r", "a7a8b", "a7a8n"]});
  assert.deepEqual(moveTargets(legal, "e1"), {g1: ["e1g1"], f1: ["e1f1"]});
  assert.deepEqual(moveTargets(legal, "c3"), {}); assert.deepEqual(moveTargets([], "e1"), {});
});
