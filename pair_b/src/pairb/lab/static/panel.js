// The pure HTML builders and formatters both of Fog Lab's tabs use (Ruling R20): the Play tab (app.js) and the Tests
// tab (tests.js) import them from here instead of keeping copies.
//
// Nothing here touches the page, so Node's runner tests it: node --test tests/js/
// Text from the server goes into HTML only through esc(), and a number only once isNumber() has said it is one.

import {heatColor} from "./board.js";

export const MINUS = "\u2212", NONE = "\u2013", CHECK = "\u2713\uFE0E";

/** Whether `value` is a finite number (not NaN, not Infinity, not a string holding digits). */
export function isNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

/** A value with its sign (a true minus), to `digits` places; a dash when there is none. */
export function signed(value, digits = 3) {
  if (!isNumber(value)) return NONE;
  return `${value < 0 ? MINUS : value > 0 ? "+" : ""}${Math.abs(value).toFixed(digits)}`;
}

/** A value as it is, for a tooltip; "none" when it is not a number. */
export function exact(value) {
  return isNumber(value) ? String(value) : "none";
}

export function capitalise(text) {
  const words = String(text ?? "");
  return words && words[0].toUpperCase() + words.slice(1);
}

/** `text` made safe to put into HTML, as an element's text or an attribute's value. */
export function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
                                                          "'": "&#39;"})[char]);
}

/** `text` made safe to put into a URL as one path segment or query value. */
export function enc(text) {
  return encodeURIComponent(text);
}

/** A heatmap cell: the value on its colour, or a dash when there is no value. */
export function cell(value, extra = "") {
  const classes = ["v", isNumber(value) ? "" : "none", extra].filter(Boolean).join(" ");
  return `<td class="${classes}" style="background:${heatColor(value)}" title="${exact(value)}">`
    + `${isNumber(value) ? (value < 0 ? MINUS : "") + Math.abs(value).toFixed(2) : NONE}</td>`;
}

/** A centred bar for a value: right of the middle for a gain, left for a loss, `scale` filling half the track. */
export function bar(value, scale) {
  if (!isNumber(value)) return "";
  const width = Math.round(Math.min(1, Math.abs(value) / scale) * 50);
  const side = value < 0 ? `right:50%` : `left:50%`;
  return `<span class="track"><span class="zero"></span><span class="bar ${value < 0 ? "neg" : "pos"}" `
    + `style="${side};width:${width}%"></span></span>`;
}
