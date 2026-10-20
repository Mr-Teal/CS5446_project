// The pure HTML builders and formatters both tabs share (static/panel.js, Ruling R20), run with Node's own runner:
// node --test tests/js/
import test from "node:test"; import assert from "node:assert/strict";
import {bar, capitalise, cell, esc, signed} from "../../src/pairb/lab/static/panel.js";

// Catches: a character left unescaped, so that server text (a record, a run summary) could open a tag or leave an
// attribute's quotes; and & escaped last, which would turn the other escapes into visible "&amp;lt;".
test("escaping covers the five characters HTML gives a meaning to", () => {
  assert.equal(esc(`<img src=x onerror="a('b')">&`), "&lt;img src=x onerror=&quot;a(&#39;b&#39;)&quot;&gt;&amp;");
  assert.equal(esc(null), ""); assert.equal(esc(undefined), ""); assert.equal(esc(0), "0");
});

// Catches: a hyphen where the true minus belongs, a plus missing on a gain, the digits ignored, and text or a value
// that is not finite printed as if it were a number.
test("a value with its sign", () => {
  assert.equal(signed(0.5), "+0.500"); assert.equal(signed(-0.25, 2), "\u22120.25"); assert.equal(signed(0), "0.000");
  assert.equal(signed(-0.00027609850327431134, 4), "\u22120.0003");
  for (const value of [null, undefined, NaN, Infinity, "0.5", true]) assert.equal(signed(value), "\u2013");
});

// Catches: a heatmap cell drawn without its colour or with a hyphen-minus, and a missing value shown as 0.
test("a heatmap cell shows the value on its colour, or a dash", () => {
  assert.equal(cell(0.5), '<td class="v" style="background:hsl(120, 65%, 68%)" title="0.5">0.50</td>');
  assert.equal(cell(-0.1), '<td class="v" style="background:hsl(0, 65%, 84%)" title="-0.1">\u22120.10</td>');
  assert.equal(cell(null, "truth best"),
    '<td class="v none truth best" style="background:transparent" title="none">\u2013</td>');
});

// Catches: a loss drawn on the gain side, and a bar longer than its half of the track.
test("a centred bar: right of the middle for a gain, left for a loss", () => {
  assert.equal(bar(0.25, 0.5), '<span class="track"><span class="zero"></span><span class="bar pos" '
    + 'style="left:50%;width:25%"></span></span>');
  assert.equal(bar(-1, 0.5), '<span class="track"><span class="zero"></span><span class="bar neg" '
    + 'style="right:50%;width:50%"></span></span>');
  assert.equal(bar(null, 1), "");
});

test("capitalising the first letter only", () => {
  assert.equal(capitalise("stopped: the engine quit"), "Stopped: the engine quit");
  assert.equal(capitalise(null), ""); assert.equal(capitalise(""), "");
});
