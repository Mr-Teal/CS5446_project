// Fog Lab's Tests tab: the latest test run, drawn as in the approved mockup (docs/superpowers/specs/fog-lab-mockups/
// tests.html, spec section 5), and "Run again".
//
// The page does no testing and no chess. The server runs the stages (pairb.lab.stage_runner, in the background through
// runs.py) and the page draws what it answers, by relative URLs only:
//
//     POST /api/tests/run {fetch}     202 {id}; 409 while a run is going
//     GET  /api/tests/status          {running, id, started, progress, stages, error}: polled while a run goes (R7)
//     GET  /api/tests/latest          the newest saved summary; 404 when there is none
//     GET  /api/tests/runs/<id>/logs/<name>   a check's output, as text
//
// Health (section 1) shows the run that is going, its cards filling in as each stage ends, or else the latest saved
// run. The fog rules, the scorer checks and the accuracy (sections 2 to 4) come from the latest saved run's "final":
// the last stage that was built. Grey is never a failure: a check that cannot run here (no torch, no Pair A
// environment), one a stage cannot run (no pair_b yet), a pytest check whose tests all skipped, a stage that was not
// built. A stopped run's cards say "stopped" (R30).
//
// Everything above "the page" is pure, so Node's runner tests it: node --test tests/js/. Text from the server reaches
// the page only through esc() or textContent, and a server value never becomes a class name.

import {drawBoard, glyph} from "./board.js";
import {capitalise, CHECK, enc, esc, exact, isNumber, NONE, signed} from "./panel.js";

const RUN_ID = /^[0-9]{8}-[0-9]{6}-[0-9]{6}$/;           // runs.RUN_ID
const LOG_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;   // runs.LOG_NAME
const STOPPED = "stopped";                               // stage_runner.STOPPED: the summary of a check a stop cut off
const NOT_RUN = "not run: the run was stopped";          // stage_runner.NOT_RUN: a check a stop kept from starting
const DOT = " \u00B7 ", ARROW = "\u2192", CROSS = "\u2717\uFE0E", HALT = "\u25A0\uFE0E";
const POLL_MS = 1500;
const FX_SIZE = 132;  // px: the fog-rules boards
const DEFAULT_SPAN = 0.012;  // the interval chart's half-width, as in the mockup, unless an interval needs more
const LONG_REASON = 80;  // characters: a grey line's reason longer than this is said in short (shortReason)

// The scorers in scorers.SCORER_IDS order, with scorers.LABELS.
const SCORERS = [["material", "Piece values"], ["stockfish-d1", "Quick Stockfish"],
                 ["stockfish-d11", "Careful Stockfish"], ["network1", "Network 1"], ["belief", "Belief network"]];
// The two rules implementations: id, label, and the label inside a sentence.
const RULES = [["standin", "Our stand-in observe", "our stand-in observe"],
               ["teal", "Teal's RulesAdapter", "Teal's RulesAdapter"]];

// Plain titles for Pair A's positions (pair_a_prep/fixtures), as in the mockup. A position not listed keeps its id.
const TITLES = {
  initial_white: "Starting position",
  blocked_pawn_hides_blocker: "A blocked pawn can't see its blocker",
  pawn_capture_reveals_target: "A pawn sees what it can capture",
  slider_stops_at_capture: "A rook's view stops at the first piece",
  expose_own_king_is_legal: "Leaving your king in check is allowed",
  king_capture_available_is_not_terminal_yet: "The king still has to be taken",
  captured_king_ends_game: "Taking the king ends the game",
  castle_through_attacked_square: "Castling through an attacked square",
  castle_escapes_orthodox_checkmate: "Castling out of normal-chess mate",
  castling_requires_rights: "No castling without castling rights",
  en_passant_reveals_pawn_and_target: "En passant shows the pawn and its square",
  expired_en_passant_loses_visibility: "A move later, both are hidden again",
  all_underpromotions: "All four promotions are allowed",
  bare_kings_are_not_automatic_draw: "Two bare kings play on",
  orthodox_stalemate_has_fog_moves: "No stalemate: the king may step into check",
  fifty_move_draw: "Fifty-move rule draws",
  threefold_needs_history: "Threefold repetition needs the move history",
};
const PIECE_NAMES = {p: "pawn", n: "knight", b: "bishop", r: "rook", q: "queen", k: "king"};
const HIDDEN_FIELDS = {halfmove_clock: "the clock", repetitions: "the repetition count"};

// Bryan's harness (pair_b_prep/harness.py): its positions, each checked as "moves" and as "board", then the checks of
// many boards at once and the two items it leaves to a person. A check it adds later is still shown (harnessRows).
const MOVES = "children/", BOARD = "board_perspective_and_rules/";
const POSITIONS = [
  ["kings_white", "Kings only, White to move"], ["kings_black", "Kings only, Black to move"],
  ["king_captured", "Black's king already taken"], ["fifty_move", "Fifty-move draw reached"],
  ["king_capture_available", "White can take the king"], ["castling_escape", "Castling out of normal-chess mate"],
  ["draw_before_capture", "Every move reaches the fifty-move draw first"],
];
const MANY_BOARDS = [["boards/batch_and_order", "Many boards in one call, answers in order"],
                     ["beliefs/grouping_order_unknown_clock_and_policy", "Beliefs: grouping, order, unknown clock"]];
const BY_HAND = [
  ["encoder/per_hypothesis_clock_and_no_hidden_state", "Encoder uses each guess's own clock, leaks nothing"],
  ["history/repetition", "Threefold repetition with the move history"],
];

const VERDICTS = {better: "Better", tie: "A tie", worse: "Worse"};
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// ---- the brief's three helpers ----

/** The marks of one of Pair A's positions, for drawBoard: squares that must be seen (see) or stay hidden (nosee), and
 * the squares moves go to that must be allowed (mv) or must not (nomv), each square once. */
export function fixtureMarks(expect) {
  const e = expect && typeof expect === "object" ? expect : {};
  const squares = list => (Array.isArray(list) ? list : []).filter(item => typeof item === "string");
  const ends = list => [...new Set(squares(list).filter(move => move.length >= 4).map(move => move.slice(2, 4)))];
  return {see: squares(e.visible_contains), nosee: squares(e.visible_excludes), mv: ends(e.legal_contains),
          nomv: ends(e.legal_excludes)};
}

/** Where `v` sits on the interval chart, in percent of the track: 0 at -span, 50 at zero, 100 at +span, and kept on the
 * track beyond. */
export function forestX(v, span = DEFAULT_SPAN) {
  return Math.min(100, Math.max(0, 50 + (v / span) * 50));
}

/** A stage card's colour. Red when a check failed; otherwise grey when the stage was not built (its merge failed, it
 * was skipped, or the stages before it already held it) and green when every check passed or was unavailable or
 * skipped. In a run that was `stopped` (R30), a check the stop cut off ("stopped", or skipped) fails nothing, but
 * leaves the card grey: it was not checked through. */
export function cardStatus(stage, {stopped = false} = {}) {
  const checks = Array.isArray(stage?.checks) ? stage.checks : [];
  if (checks.some(item => item?.status === "fail" && !cutOff(item, stopped))) return "red";
  if (stage?.merge !== "clean") return "grey";
  return checks.every(item => ["pass", "unavailable", "skipped"].includes(item?.status) && !cutOff(item, stopped))
    ? "green" : "grey";
}

/** Whether a stop cut `item` off: in a stopped run, the check it stopped ("fail" with the summary "stopped") and those
 * it kept from starting ("skipped" with the summary NOT_RUN). A pytest check whose tests all skipped is "skipped" too,
 * with pytest's words: it ran to its end, and nothing cut it off. */
function cutOff(item, stopped) {
  return stopped && ((item?.status === "skipped" && item?.summary === NOT_RUN)
    || (item?.status === "fail" && item?.summary === STOPPED));
}

// ---- links and words ----

/** The route that serves a check's log (`log` as the summary gives it, "logs/<name>"), or null for anything else. */
export function logHref(runId, log) {
  if (typeof runId !== "string" || !RUN_ID.test(runId)) return null;
  if (typeof log !== "string" || !log.startsWith("logs/")) return null;
  const name = log.slice("logs/".length);
  return LOG_NAME.test(name) ? `/api/tests/runs/${enc(runId)}/logs/${enc(name)}` : null;
}

/** An ISO time as the run's machine wrote it ("2026-10-20T02:40:21+08:00") in words, "Tue 20 Oct, 02:40": its own
 * local time, whatever time zone the browser is in. Text that is not such a time comes back as it is. */
export function runTime(iso) {
  const found = typeof iso === "string" ? /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso) : null;
  if (!found) return typeof iso === "string" ? iso : "";
  const [, year, month, day, hour, minute] = found;
  if (Number(month) < 1 || Number(month) > 12) return iso;
  const weekday = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day))).getUTCDay();
  return `${DAYS[weekday]} ${Number(day)} ${MONTHS[Number(month) - 1]}, ${hour}:${minute}`;
}

/** The time of day in an ISO time, "02:40:21", or "". */
function clockTime(iso) {
  return (typeof iso === "string" ? /T(\d{2}:\d{2}:\d{2})/.exec(iso)?.[1] : null) ?? "";
}

/** How long from `started` to `finished` (ISO times), "7 min 16 s"; "" when either is not a time. */
function took(started, finished) {
  const ms = Date.parse(finished) - Date.parse(started);
  if (!Number.isFinite(ms) || ms < 0) return "";
  const seconds = Math.round(ms / 1000), minutes = Math.floor(seconds / 60);
  if (minutes < 1) return `${seconds} s`;
  if (minutes < 60) return `${minutes} min ${seconds % 60} s`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

/** The summary's machine in words: "C4QJ7945G2 (macOS arm64)", with ", no torch" where torch is missing. */
function machineText(machine) {
  if (!machine || typeof machine !== "object") return "";
  const about = [machine.system === "Darwin" ? "macOS" : words(machine.system), words(machine.arch)].filter(Boolean);
  const parts = [about.join(" "), machine.torch === false ? "no torch" : ""].filter(Boolean).join(", ");
  return parts ? `${words(machine.name)} (${parts})`.trim() : words(machine.name);
}

/** "5 of 6 stages green, 1 red": every stage but one that added nothing ("contained"). */
function stageCount(stages, stopped) {
  const counted = (Array.isArray(stages) ? stages : []).filter(stage => stage?.merge !== "contained");
  if (!counted.length) return "no stage built";
  const looks = counted.map(stage => cardStatus(stage, {stopped}));
  const green = looks.filter(look => look === "green").length, red = looks.filter(look => look === "red").length;
  return `${green} of ${counted.length} stage${counted.length === 1 ? "" : "s"} green${red ? `, ${red} red` : ""}`;
}

/** The top bar's line for a saved run, as plain text: when it ran and for how long, on which machine, whether it
 * fetched first, and how many stages are green. */
export function runHeadline(summary) {
  const parts = [`Last run ${runTime(summary?.started)}`];
  const length = took(summary?.started, summary?.finished);
  if (length) parts.push(`took ${length}`);
  const machine = machineText(summary?.machine);
  if (machine) parts.push(machine);
  if (summary?.fetch?.requested === false) parts.push("not fetched first");
  parts.push(stageCount(summary?.stages, summary?.stopped === true));
  return parts.join(DOT);
}

/** What a saved run needs said beside its cards, as [kind, plain text]: kind "error" or "warn". */
export function runNotes(summary) {
  const notes = [];
  if (!summary || typeof summary !== "object") return notes;
  if (summary.error) {
    notes.push(["error", `The run failed: ${summary.error}. The window that started Fog Lab has the details.`]);
  }
  if (summary.stopped === true) {
    notes.push(["warn", "This run was stopped before it was done: Fog Lab was closed while it ran. The cards it cut "
      + "short say stopped, and they are not failures; run again for a full result."]);
  }
  if (summary.fetch?.requested === true && summary.fetch.ok === false) {
    notes.push(["warn", "The run could not fetch from GitHub, so it used the refs this checkout already had: "
      + `${summary.fetch.message}`]);
  }
  return notes;
}

/** Text the server sent where text is expected, or "". */
function words(value) {
  return typeof value === "string" ? value : "";
}

/** A title attribute holding `text` (escaped), or nothing when there is none. */
function tip(text) {
  return text ? ` title="${esc(text)}"` : "";
}

/** A link that opens the log at `href` in the page's log viewer (or a new tab, with the usual modifier keys). */
function logLink(href, title, text, className = "") {
  return `<a${className ? ` class="${className}"` : ""} href="${esc(href)}" data-log data-title="${esc(title)}">`
    + `${text}</a>`;
}

// ---- 1. health: the stage cards ----

const MARKS = {green: CHECK, red: CROSS, grey: NONE};
const MERGE_WORDS = {conflict: "merge conflict", "missing-ref": "ref not found", skipped: "skipped",
                     contained: "contained"};

/** The stage cards in merge order with an arrow between each, the summary's `stages` (or a run's so far). `runId`
 * makes the checks' logs links; `stopped` is the summary's (R30); `running`, the line the run is at, adds a card for
 * the work in progress. A grey line's reason that is long is said in short on its line and in full once, under the
 * cards: Pair A's setup command would otherwise fill two lines of every card. */
export function stagesHtml(stages, {runId = null, stopped = false, running = null} = {}) {
  let blocked = false;  // by a conflict or a missing ref: the stages after it were skipped for it
  const long = new Set();
  const cards = (Array.isArray(stages) ? stages : []).map(stage => {
    const card = stageCard(stage && typeof stage === "object" ? stage : {}, {runId, stopped, blocked, long});
    if (stage?.merge === "conflict" || stage?.merge === "missing-ref") blocked = true;
    return card;
  });
  if (running !== null && running !== undefined) {
    cards.push(`<div class="stage going"><div class="hd"><span class="spinner"></span> Running<small>the next `
      + `step</small></div><div class="ln"><span class="why">${esc(running)}</span></div></div>`);
  }
  const notes = [...long].map(reason => `<div>${esc(reason)}</div>`).join("");
  return cards.join(`<span class="arrow" aria-hidden="true">${ARROW}</span>`)
    + (notes ? `<div class="note stage-notes">${notes}</div>` : "");
}

function stageCard(stage, {runId, stopped, blocked, long}) {
  const look = cardStatus(stage, {stopped});
  const merge = stage.merge, checks = Array.isArray(stage.checks) ? stage.checks : [];
  const halted = stopped && (merge === "skipped" ? !blocked : checks.some(item => cutOff(item, stopped)));
  const sha = words(stage.sha).slice(0, 7);
  const said = halted ? STOPPED : Object.hasOwn(MERGE_WORDS, merge) ? MERGE_WORDS[merge] : "";
  const head = `<div class="hd"><span class="mark">${halted && look !== "red" ? HALT : MARKS[look]}</span> `
    + `${esc(stage.label)}<small>${esc([words(stage.title), sha, said].filter(Boolean).join(DOT))}</small></div>`;
  const where = [words(stage.ref), words(stage.sha)].filter(Boolean).join(" at ");
  const context = {runId, stopped, long, stage: words(stage.label)};
  let body;
  if (merge === "clean") {
    body = checks.map(item => checkLine(item, context)).join("");
  } else if (merge === "conflict") {
    const files = (Array.isArray(stage.conflicts) ? stage.conflicts : []).map(file => `<li>${esc(file)}</li>`).join("");
    body = files ? `${reason("Merge conflict in")}<ul class="files">${files}</ul>`
      + reason("The stages after it were not run.")
      : reason("Git could not merge it, so the stages after it were not run.");
  } else if (merge === "missing-ref") {
    body = reason(`${words(stage.ref) || "Its ref"} names no commit here, so the stages after it were not run.`);
  } else if (merge === "skipped") {
    const why = blocked ? "an earlier stage could not be built" : stopped ? "the run was stopped" : "not run";
    body = reason(`Skipped: ${why}.`);
  } else if (merge === "contained") {
    body = reason("Already in the stages before it, so there was nothing new to check here.");
  } else {
    body = reason(`Merge: ${words(merge) || "unknown"}`) + checks.map(item => checkLine(item, context)).join("");
  }
  const classes = ["stage", look, halted ? "stopped" : ""].filter(Boolean).join(" ");
  return `<div class="${classes}"${tip(where)}>${head}${body}</div>`;
}

/** A grey line's reason as its line says it: one longer than LONG_REASON characters up to its first ": ", when that
 * comes early enough ("Pair A's environment not set up here"); any other as it is. */
function shortReason(text) {
  const cut = text.length > LONG_REASON ? text.indexOf(": ") : -1;
  return cut > 0 && cut <= LONG_REASON ? text.slice(0, cut) : text;
}

function reason(text) {
  return `<div class="ln"><span class="why">${esc(text)}</span></div>`;
}

/** One check of a card: its label and summary. A check that ran links its log, and a failed one says so again at the
 * end of its line; grey lines (unavailable, skipped) give their reason, and a check the stop cut off says stopped. */
function checkLine(item, {runId, stopped, long, stage}) {
  const check = item && typeof item === "object" ? item : {};
  const kind = cutOff(check, stopped) ? "stopped" : check.status === "pass" ? "pass" : check.status === "fail" ? "fail"
    : "grey";
  const href = logHref(runId, check.log), label = esc(words(check.label) || words(check.key) || "?");
  const title = `${stage}${DOT}${words(check.label) || words(check.key)}`;
  const name = href ? logLink(href, title, label, "lab") : `<span class="lab">${label}</span>`;
  const summary = String(check.summary ?? ""), ran = kind === "pass" || kind === "fail";
  const head = ran ? summary : shortReason(summary);  // a result is said in full; only a reason is shortened
  if (head !== summary) long.add(summary);
  const said = ran ? `<b>${esc(summary)}</b>`
    : `<span class="why"${head === summary ? "" : tip(summary)}>${esc(head)}</span>`;
  const open = kind === "fail" && href ? logLink(href, title, "open its log \u203A", "open") : "";
  return `<div class="ln ${kind}">${name}${said}${open}</div>`;
}

// ---- 2. fog rules: Pair A's positions ----

/** The cards for one fixtures entry (stage_runner's final.fixtures[rules]): one per position, each with an empty
 * div[data-case] for its board, which the page draws once the cards are in. An entry for rules the stage lacks gives
 * its reason, and one whose check itself failed gives the end of its error output (R21): the section never empties.
 * In a run that was `stopped`, an entry the stop cut off says so, in the stopped colour, and is no failure (R30). */
export function fixturesHtml(entry, {runId = null, stopped = false} = {}) {
  if (!entry || typeof entry !== "object") return '<div class="note">This run has no result for these rules.</div>';
  const named = RULES.find(([rules]) => rules === entry.rules);
  const label = named?.[1] ?? words(entry.rules), inSentence = named?.[2] ?? words(entry.rules);
  const href = logHref(runId, entry.log);
  const log = href ? ` ${logLink(href, `Fog rules${DOT}${label}`, "Open its log")}` : "";
  if (entryCutOff(entry, stopped)) {
    return `<div class="note fx-stopped">The run was stopped while it checked Pair A's positions against `
      + `${esc(inSentence)}, so there is no result yet: run again for one.${log}</div>`;
  }
  if (entry.available !== true) {
    if (entry.status === "fail") {
      return `<div class="fx-error"><h4>The fog-rules check itself failed against ${esc(inSentence)}</h4>`
        + `<pre>${esc(entry.reason)}</pre>${log}</div>`;
    }
    return `<div class="note fx-none">${esc(label)} cannot be checked in this stage: `
      + `${esc(words(entry.reason) || "it is unavailable")}.${log}</div>`;
  }
  const cases = Array.isArray(entry.cases) ? entry.cases : [];
  if (!cases.length) return `<div class="note">No positions were checked.${log}</div>`;
  return cases.map((item, index) => fixtureCard(item && typeof item === "object" ? item : {}, index)).join("");
}

function fixtureCard(item, index) {
  const ok = Array.isArray(item.errors) && item.errors.length === 0;
  const errors = Array.isArray(item.errors) ? item.errors : ["the check gave no list of errors for it"];
  const view = item.player === "black" ? "Black's view" : item.player === "white" ? "White's view"
    : `${esc(item.player)}'s view`;
  const replayed = isNumber(item.history) && item.history > 0
    ? `, after replaying ${item.history} move${item.history === 1 ? "" : "s"}` : "";
  const seen = Array.isArray(item.visible) ? item.visible.length : 0;
  const title = typeof item.id === "string" && Object.hasOwn(TITLES, item.id) ? TITLES[item.id] : item.id;
  return `<div class="fc${ok ? "" : " failing"}"><div class="fx-board" data-case="${index}"></div>`
    + `<h5>${index + 1}. ${esc(title)}</h5><div class="id">${esc(item.id)}</div>`
    + `<div class="ex">${view}${replayed}: ${seen} square${seen === 1 ? "" : "s"} seen<br>`
    + `${expectLines(item.expect).join("<br>")}</div>`
    + `<div class="res">${ok ? '<span class="ok">pass</span>' : `<span class="bad">fail</span> `
    + errors.map(esc).join("; ")}</div></div>`;
}

/** A position's expectations as lines of HTML, in the mockup's order. */
function expectLines(expect) {
  const e = expect && typeof expect === "object" ? expect : {};
  const some = list => Array.isArray(list) && list.length > 0;
  const listed = list => list.map(esc).join(" ");
  const key = kind => `<span class="key ${kind}"></span>`;
  const lines = [];
  if (some(e.visible_contains)) lines.push(`${key("see")}Sees ${listed(e.visible_contains)}`);
  if (some(e.visible_excludes)) lines.push(`${key("nosee")}Can't see ${listed(e.visible_excludes)}`);
  if (e.visible_pieces && typeof e.visible_pieces === "object") {
    const shown = Object.entries(e.visible_pieces).map(([square, piece]) => {
      if (!piece) return `${esc(square)} shown empty`;
      const name = typeof piece === "string" && Object.hasOwn(PIECE_NAMES, piece.toLowerCase())
        ? PIECE_NAMES[piece.toLowerCase()] : esc(piece);
      const symbol = glyph(piece);
      return `${symbol ? `<span class="pc">${symbol}</span> ` : ""}${name} shown on ${esc(square)}`;
    });
    if (shown.length) lines.push(shown.join(", "));
  }
  if (some(e.legal_contains)) lines.push(`${key("mv")}May play ${listed(e.legal_contains)}`);
  if (some(e.legal_excludes)) lines.push(`${key("nomv")}May not play ${listed(e.legal_excludes)}`);
  if (isNumber(e.legal_count)) lines.push(`${e.legal_count} legal move${e.legal_count === 1 ? "" : "s"}`);
  if (some(e.hidden_fields)) {
    const names = e.hidden_fields.map(field => (typeof field === "string" && Object.hasOwn(HIDDEN_FIELDS, field)
      ? HIDDEN_FIELDS[field] : esc(field)));
    const joined = names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : names[0];
    lines.push(`${capitalise(joined)} stay${names.length > 1 ? "" : "s"} hidden`);
  }
  lines.push(e.terminal === true ? `Game over: ${e.winner === "draw" ? "draw" : `${esc(e.winner)} wins`}`
    : "Game goes on");
  return lines;
}

/** The switch between the two rules implementations, each with how its positions went; `chosen` is pressed.
 * `stopped` is the summary's, as for fixturesHtml. */
export function rulesChoiceHtml(fixtures, chosen, {stopped = false} = {}) {
  return RULES.map(([rules, label]) => {
    const entry = fixtures && typeof fixtures === "object" ? fixtures[rules] : null, on = rules === chosen;
    return `<button type="button" class="chip${on ? " on" : ""}" data-rules="${rules}" aria-pressed="${on}">`
      + `${esc(label)}: ${esc(entryWords(entry, stopped))}</button>`;
  }).join("");
}

/** Whether a stop cut a fog-rules entry off: in a stopped run, the check it ended, which stage_runner reports as
 * failed with the reason "stopped" (R30). */
function entryCutOff(entry, stopped) {
  return stopped && entry?.available !== true && entry?.status === "fail" && entry?.reason === STOPPED;
}

function entryWords(entry, stopped) {
  if (!entry || typeof entry !== "object") return "no result";
  if (entryCutOff(entry, stopped)) return STOPPED;
  if (entry.available !== true) return entry.status === "fail" ? "the check failed" : "unavailable";
  const cases = Array.isArray(entry.cases) ? entry.cases : [];
  const passing = cases.filter(item => Array.isArray(item?.errors) && item.errors.length === 0).length;
  return `${passing} of ${cases.length} pass`;
}

// ---- 3. scorer checks: Bryan's harness on each scorer ----

/** The checks of a harness entry that the grid can place: those with a name. */
function checksOf(entry) {
  return (Array.isArray(entry?.checks) ? entry.checks : []).filter(item => typeof item?.name === "string");
}

/** The grid's rows: the known positions, then any other position a report names; and the checks that are neither a
 * position's nor among the known ones, so that a check Bryan adds is shown, not dropped. */
function harnessRows(columns) {
  const names = new Set(columns.flatMap(({entry}) => checksOf(entry).map(item => item.name)));
  const positions = POSITIONS.map(([id, label]) => ({id, label}));
  for (const name of names) {
    const id = name.startsWith(MOVES) ? name.slice(MOVES.length) : name.startsWith(BOARD) ? name.slice(BOARD.length)
      : null;
    if (id !== null && !positions.some(position => position.id === id)) positions.push({id, label: id});
  }
  const known = new Set([...MANY_BOARDS, ...BY_HAND].map(([name]) => name));
  const others = [...names].filter(name => !name.startsWith(MOVES) && !name.startsWith(BOARD) && !known.has(name));
  return {positions, others: others.map(name => [name, name])};
}

/** A scorer's overall look in the grid's heading: grey when its check did not run here. */
function scorerLook(entry) {
  return entry?.status === "pass" ? "pass" : entry?.status === "fail" ? "fail" : "grey";
}

function gridCell(column, name, span = false) {
  const {entry, found} = column, wide = span ? ' colspan="2"' : "";
  if (scorerLook(entry) === "grey") return `<td class="n"${wide}${tip(words(entry?.summary))}>${NONE}</td>`;
  const item = found.get(name);
  if (!item) return `<td class="n"${wide}${tip(found.size ? "not in this scorer's report" : "no report")}>${NONE}</td>`;
  if (item.status === "pass") return `<td class="p"${wide}>${CHECK}</td>`;
  if (item.status === "manual") return `<td class="m"${wide}>by hand</td>`;
  if (item.status === "fail") return `<td class="f"${wide}${tip(words(item.detail))}>${CROSS}</td>`;
  return `<td class="n"${wide}${tip(words(item.status))}>?</td>`;
}

/** A number for the run settings line: 1e-6 rather than 0.000001. */
function shortNumber(value) {
  if (!isNumber(value)) return NONE;
  return value !== 0 && Math.abs(value) < 1e-3 ? value.toExponential().replace("e+", "e") : String(value);
}

/** The scorer grid as {table, note}: `table` the rows for a <table>, "" when the stage has no harness, and `note` the
 * HTML under it. `commit` is the stage's own (R28), never the reports' source_commit, which is the run's throwaway
 * merge commit; `label` names the stage. */
export function harnessHtml(harness, {commit = null, runId = null, label = ""} = {}) {
  const all = harness && typeof harness === "object" ? harness : {};
  const ids = [...SCORERS.filter(([id]) => Object.hasOwn(all, id)),
               ...Object.keys(all).filter(id => !SCORERS.some(([known]) => known === id)).map(id => [id, id])];
  if (!ids.length) {
    return {table: "", note: `<p>Bryan's harness is not in ${esc(label || "the last stage built")}, so there are no `
      + "scorer checks: its pull request (#3) is not among the stages that were built.</p>"};
  }
  const columns = ids.map(([id, name]) => {
    const entry = all[id] && typeof all[id] === "object" ? all[id] : {};
    return {id, name, entry, found: new Map(checksOf(entry).map(item => [item.name, item]))};
  });
  const {positions, others} = harnessRows(columns);
  const across = 1 + 2 * columns.length;
  const heading = columns.map(({name, entry}) => {
    const look = scorerLook(entry);
    const small = look === "grey" ? (entry.status === "skipped" ? "not run" : "unavailable")
      : look === "fail" ? "failed" : "";
    return `<th colspan="2" class="sc ${look}"${tip(words(entry.summary))}>${esc(name)}`
      + `${small ? `<small>${small}</small>` : ""}</th>`;
  }).join("");
  let table = `<tr><th></th>${heading}</tr><tr><th class="l">Position</th>`
    + `${columns.map(() => "<th>moves</th><th>board</th>").join("")}</tr>`;
  table += positions.map(({id, label: name}) => `<tr><td class="lab">${esc(name)}<br><code>${esc(id)}</code></td>`
    + columns.map(column => gridCell(column, MOVES + id) + gridCell(column, BOARD + id)).join("") + "</tr>").join("");
  const group = (title, rows, notes = false) => (rows.length ? `<tr class="grp"><td colspan="${across}">${title}</td>`
    + "</tr>" + rows.map(([name, plain]) => `<tr><td class="lab">${esc(plain)}<br><code>${esc(name)}</code>`
    + `${notes ? bryansNote(columns, name) : ""}</td>${columns.map(column => gridCell(column, name, true)).join("")}`
    + "</tr>").join("") : "");
  table += group("Calls with many boards", MANY_BOARDS);
  table += group("Checked by hand (the harness cannot test these from outside)", BY_HAND, true);
  table += group("Other checks in the reports", others);
  return {table, note: harnessNote(columns, {commit, runId, label})};
}

/** Bryan's notes on a by-hand item: the reports' "detail", each different one once. */
function bryansNote(columns, name) {
  const details = [...new Set(columns.map(({found}) => words(found.get(name)?.detail)).filter(Boolean))];
  return details.length ? `<div class="bryan">Bryan: ${details.map(detail => `\u201C${esc(detail)}\u201D`).join(" ")}`
    + "</div>" : "";
}

function harnessNote(columns, {commit, runId, label}) {
  const lines = [];
  const counted = columns.filter(({entry}) => isNumber(entry.counts?.pass) && isNumber(entry.counts?.fail));
  if (counted.length) {
    lines.push(`Automatic checks passing: ${counted.map(({name, entry}) => `${esc(name)} ${entry.counts.pass} of `
      + `${entry.counts.pass + entry.counts.fail}`).join(DOT)}.`);
  }
  const settings = [...new Set(columns.map(({entry}) => entry.metadata).filter(meta => meta && typeof meta === "object")
    .map(meta => `${shortNumber(meta.warmups)} warm-ups, ${shortNumber(meta.repeats)} repeats, tolerance `
      + `${shortNumber(meta.tolerance)}`))];
  const sha = words(commit).slice(0, 7);
  const where = [settings.length ? `Each check: ${settings.join("; ")}` : "",
                 sha ? `commit ${sha}${label ? ` (${label})` : ""}` : ""].filter(Boolean).join("; ");
  if (where) lines.push(`${esc(where)}.`);
  for (const {name, entry} of columns) {
    const href = logHref(runId, entry.log), log = href ? ` ${logLink(href, `Harness${DOT}${name}`, "Its log")}` : "";
    if (scorerLook(entry) === "grey") {
      lines.push(`${esc(name)}: ${entry.status === "skipped" ? "not run" : "unavailable here"}: `
        + `${esc(entry.summary)}.`);
    } else if (entry.status === "fail") {
      const failing = checksOf(entry).filter(item => item.status === "fail");
      lines.push(failing.length ? failing.map(item => `${esc(name)}, ${esc(item.name)}: ${esc(item.detail)}`).join("; ")
        + `.${log}` : `${esc(name)}: ${esc(entry.summary)}.${log}`);
    }
  }
  return lines.map(line => `<p>${line}</p>`).join("");
}

// ---- 4. accuracy ----

/** The fewest places, from `start`, that give every different value in `values` a different text: four for a column
 * whose rows agree to three places. */
function columnDigits(values, start, most = 6) {
  const numbers = [...new Set(values.filter(isNumber))];
  for (let digits = start; digits < most; digits += 1) {
    if (new Set(numbers.map(value => value.toFixed(digits))).size === numbers.length) return digits;
  }
  return most;
}

/** A whole number with a comma between each group of three digits: 94,963. */
function thousands(count) {
  return String(Math.trunc(count)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** The accuracy cards: one per table read from the saved evaluation files, then one per file that gave no table, with
 * the reader's own reason for it (R24). */
export function accuracyHtml(accuracy) {
  const tables = Array.isArray(accuracy?.tables) ? accuracy.tables : [];
  const missing = Array.isArray(accuracy?.missing) ? accuracy.missing : [];
  const why = accuracy?.why_missing && typeof accuracy.why_missing === "object" ? accuracy.why_missing : {};
  return tables.map(table => accuracyCard(table && typeof table === "object" ? table : {})).join("")
    + missing.map(path => `<div class="card missing"><h4>No table from <code>${esc(path)}</code></h4><div class="why">`
      + `${esc(typeof path === "string" && Object.hasOwn(why, path) ? why[path] : "the reader gave no reason")}`
      + "</div></div>").join("");
}

function accuracyCard(table) {
  const columns = Array.isArray(table.columns) ? table.columns : [];
  const rows = (Array.isArray(table.rows) ? table.rows : []).filter(row => row && typeof row === "object");
  const value = (row, index) => (Array.isArray(row.values) ? row.values[index] : undefined);
  const percent = columns.map(column => column?.unit === "%");
  const digits = columns.map((_, index) => columnDigits(rows.map(row => value(row, index)), percent[index] ? 0 : 3));
  const top = Math.max(0, ...rows.map(row => value(row, 0)).filter(isNumber));  // the bars: the first column
  const cells = row => columns.map((_, index) => {
    const number = value(row, index);
    if (!isNumber(number)) return `<td>${NONE}</td>`;
    const bar = index === 0 && top > 0
      ? `<span class="ebar" style="width:${Math.round((Math.max(0, number) / top) * 90)}px"></span>` : "";
    return `<td class="num" title="${exact(number)}">${number.toFixed(digits[index])}${percent[index] ? "%" : ""}`
      + `${bar}</td>`;
  }).join("");
  return `<div class="card"><h4>${esc(table.title)}</h4><div class="why">${provenance(table)}</div>`
    + `<div class="scroll"><table class="u acc-t"><tr><th></th>${columns.map(column => `<th>${esc(column?.label)}</th>`)
      .join("")}</tr>${rows.map(row => `<tr${row.highlight === true ? ' class="kept"' : ""}><td>${esc(row.label)}</td>`
      + `${cells(row)}</tr>`).join("")}</table></div></div>`;
}

/** Where a table's numbers come from: what it was measured on, the data and split, the depth it was measured against,
 * when the file was made, and the file. */
function provenance(table) {
  const sizes = table.sizes && typeof table.sizes === "object" ? Object.entries(table.sizes) : [];
  const counts = sizes.filter(([, count]) => isNumber(count)).map(([name, count]) => `${thousands(count)} ${name}`);
  const data = [words(table.data) && `${words(table.data)} data`, words(table.split) && `${words(table.split)} split`];
  const parts = [counts.join(", "), data.filter(Boolean).join(", "),
                 isNumber(table.target_depth) ? `against depth-${table.target_depth} Stockfish` : "",
                 words(table.created) ? `made ${runTime(table.created)}` : ""].filter(Boolean);
  return `${esc(parts.join(DOT))}<br><code>${esc(table.source)}</code>`;
}

/** The interval chart: each paired difference as its mean and 95% interval against zero, with the verdict in words,
 * then the axis. The axis reaches past the widest interval, and is at least the mockup's +-0.012. "" when there is no
 * difference to draw. */
export function forestHtml(differences) {
  const rows = (Array.isArray(differences) ? differences : []).filter(difference => isNumber(difference?.mean)
    && Array.isArray(difference.ci95) && difference.ci95.length === 2 && difference.ci95.every(isNumber));
  if (!rows.length) return "";
  const span = Math.max(DEFAULT_SPAN, ...rows.flatMap(({mean, ci95}) => [mean, ...ci95].map(v => Math.abs(v) * 1.2)));
  const tick = niceTick(span), places = Math.max(0, -Math.floor(Math.log10(tick)));
  const ticks = [-tick, 0, tick].map(at => `<span style="left:${forestX(at, span).toFixed(2)}%">`
    + `${at === 0 ? "0" : signed(at, places)}</span>`).join("");
  return rows.map(row => forestRow(row, span)).join("")
    + `<div class="axis"><span></span><span class="ticks">${ticks}</span><span></span></div>`
    + '<div class="note">Left of 0: the first scorer named errs less than the second.</div>';
}

function forestRow({label, mean, ci95: [low, high], verdict}, span) {
  const said = typeof verdict === "string" && Object.hasOwn(VERDICTS, verdict) ? verdict
    : high < 0 ? "better" : low > 0 ? "worse" : "tie";
  const left = forestX(low, span), right = forestX(high, span);
  return `<div class="fr"><span>${esc(label)}<br><span class="meta">${signed(mean, 4)} (${signed(low, 4)} to `
    + `${signed(high, 4)})</span></span><span class="ftrack"><span class="zero"></span><span class="ci" `
    + `style="left:${left.toFixed(2)}%;width:${Math.max(0, right - left).toFixed(2)}%"></span><span class="pt" `
    + `style="left:${forestX(mean, span).toFixed(2)}%"></span></span>`
    + `<span class="verdict ${said}">${VERDICTS[said]}</span></div>`;
}

/** The largest of 1, 2 or 5 times a power of ten that fits in nine tenths of `span`: the axis's tick. */
function niceTick(span) {
  const most = span * 0.9, power = 10 ** Math.floor(Math.log10(most));
  return [5, 2, 1].map(step => step * power).find(step => step <= most) ?? power;
}

// ---- the page ----

const page = {
  latest: undefined,   // the newest saved summary; null when there is none yet; undefined until it has been asked for
  status: null,        // GET /api/tests/status
  rules: "standin",    // which rules implementation's positions are drawn
  starting: false,     // the request that starts a run is out
  notice: null,        // [kind, text]: why a request failed, or what a refused start said
  timer: null,         // the next poll
  poll: 0,             // the newest poll: an older one that answers late is dropped
  log: 0,              // the newest log asked for, likewise
  drawn: null,         // {latest, rules} that sections 2 to 4 were last drawn from
};

const $ = id => document.getElementById(id);

/** Start the Tests tab, the first time it is shown: its buttons, then the latest run and how a run is going. */
export function startTests() {
  $("t-run").addEventListener("click", runAgain);
  $("t-rules").addEventListener("click", event => {
    const button = event.target.closest("[data-rules]");
    if (!button) return;
    page.rules = button.dataset.rules;
    render();
  });
  $("panel-tests").addEventListener("click", openLog);
  $("t-log-close").addEventListener("click", () => $("t-log").close());
  render();
  refresh();
}

/** The answer to a request to the page's own server, as {status, ok, data}. An Error when the server does not
 * answer. */
async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("Fog Lab's server did not answer: is it still running?");
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    // not JSON: the status says enough
  }
  return {status: response.status, ok: response.ok, data};
}

function refusal(answer) {
  return typeof answer.data?.error === "string" ? answer.data.error : `the server answered ${answer.status}`;
}

async function refresh() {
  await Promise.all([loadLatest(), poll()]);
}

/** Read the newest saved run: page.latest, or null when none has been saved. */
async function loadLatest() {
  try {
    const answer = await request("/api/tests/latest");
    if (answer.ok) page.latest = answer.data;
    else if (answer.status === 404) page.latest = null;
    else page.notice = ["error", `Could not read the last test run: ${refusal(answer)}`];
  } catch (error) {
    page.notice = ["error", `Could not read the last test run: ${error.message}`];
  }
  render();
}

/** Ask how the run is going, and again every POLL_MS while it goes; once it has ended, read its saved summary. */
async function poll() {
  clearTimeout(page.timer);
  const mine = (page.poll += 1), wasRunning = Boolean(page.status?.running);
  let answer;
  try {
    answer = await request("/api/tests/status");
  } catch (error) {
    if (mine !== page.poll) return;
    page.notice = ["error", `Could not ask how the test run is going: ${error.message}`];
    if (wasRunning) page.timer = setTimeout(poll, POLL_MS * 4);  // the server may be restarting
    render();
    return;
  }
  if (mine !== page.poll) return;
  if (!answer.ok) {
    page.notice = ["error", refusal(answer)];
    render();
    return;
  }
  if (page.notice?.[1]?.startsWith("Could not ask")) page.notice = null;
  page.status = answer.data;
  if (page.status?.running) {
    page.timer = setTimeout(poll, POLL_MS);
    render();
  } else if (wasRunning) {
    if (page.notice?.[0] === "info") page.notice = null;  // "a run is already going": the run it meant is over
    await loadLatest();  // the run is over, and its summary was saved before status said so (runs.py)
  } else {
    render();
  }
}

async function runAgain() {
  if (page.starting || page.status?.running) return;
  Object.assign(page, {starting: true, notice: null});
  render();
  let follow = false;  // poll: the run started, or one is going already (409), which this page then follows
  try {
    const answer = await request("/api/tests/run", {method: "POST", headers: {"Content-Type": "application/json"},
                                                    body: JSON.stringify({fetch: $("t-fetch").checked})});
    if (answer.status === 202) {
      page.status = {running: true, id: answer.data?.id ?? null, started: null, progress: [], stages: [], error: null};
    } else {
      page.notice = [answer.status === 409 ? "info" : "error", `The run did not start: ${refusal(answer)}`];
    }
    follow = answer.status === 202 || answer.status === 409;
  } catch (error) {
    page.notice = ["error", `The run did not start: ${error.message}`];
  } finally {
    page.starting = false;
  }
  if (follow) await poll();
  else render();
}

/** Show the log a link names in the log viewer. A click with a modifier key opens it the browser's way instead. */
async function openLog(event) {
  const link = event.target.closest("a[data-log]");
  if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  const href = link.getAttribute("href"), mine = (page.log += 1), text = $("t-log-text");
  $("t-log-title").textContent = link.dataset.title || "Log";
  $("t-log-open").setAttribute("href", href);
  text.textContent = "Loading\u2026";
  if (!$("t-log").open) $("t-log").showModal();
  let shown;
  try {
    const response = await fetch(href);
    const body = await response.text();
    shown = response.ok ? body : `The log could not be read: the server answered ${response.status}.`;
  } catch {
    shown = "Fog Lab's server did not answer: is it still running?";
  }
  if (mine === page.log) text.textContent = shown;
}

// ---- drawing the page ----

/** Draw the page. Sections 2 to 4 are drawn again only when what they show has changed (another saved run, the other
 * rules), not on every poll of a run that is going, which would rebuild 17 boards each time and lose the reader's
 * place and selection. */
function render() {
  const running = Boolean(page.status?.running);
  draw("t-banners", () => bannersHtml(running));
  draw("t-stages", () => healthHtml(running));
  if (page.drawn?.latest !== page.latest || page.drawn?.rules !== page.rules) {
    page.drawn = {latest: page.latest, rules: page.rules};
    draw("t-fixtures", drawFixtures);
    draw("t-grid-note", drawHarness);
    draw("t-acc", drawAccuracy);
  }
  renderBar(running);
}

/** Fill the element `id` with the HTML `build` returns (nothing when it returns undefined, having drawn it itself). A
 * summary from an older or newer Fog Lab may hold what a part cannot draw: then that part says so, and the rest of the
 * page still works. */
function draw(id, build) {
  try {
    const html = build();
    if (html !== undefined) $(id).innerHTML = html;
  } catch (error) {
    $(id).innerHTML = `<div class="note warn">This part could not be drawn: ${esc(error.message)}</div>`;
  }
}

function renderBar(running) {
  const status = page.status, busy = running || page.starting;
  $("t-run").disabled = busy;
  $("t-fetch").disabled = busy;
  $("t-spinner").hidden = !busy;
  let line;
  if (running) {
    const since = Date.parse(status.started), minutes = Math.floor((Date.now() - since) / 60000);
    line = status.started ? `Running since ${clockTime(status.started)}${minutes >= 1 ? ` (${minutes} min)` : ""}`
      + `${DOT}${status.stages?.length ?? 0} stage${status.stages?.length === 1 ? "" : "s"} done` : "Starting the run";
  } else if (page.starting) {
    line = "Starting the run";
  } else if (page.latest) {
    line = runHeadline(page.latest);
  } else {
    line = page.latest === null ? "No test run has been saved yet" : "Reading the last test run\u2026";
  }
  $("t-last").textContent = line;
  const box = $("t-progress"), lines = running && Array.isArray(status.progress) ? status.progress : [];
  box.hidden = !running;
  box.replaceChildren(...lines.map(text => Object.assign(document.createElement("div"), {textContent: String(text)})));
  box.scrollTop = box.scrollHeight;
}

function bannersHtml(running) {
  const notes = [], latest = page.latest, status = page.status;
  if (page.notice) notes.push(page.notice);
  if (!running && status?.error && status.id !== latest?.id) {
    notes.push(["error", `The last run failed: ${status.error}`]);
  }
  if (!running) notes.push(...runNotes(latest));
  if (running && latest) {
    notes.push(["info", `The fog rules, scorer checks and accuracy below are from the last saved run `
      + `(${runTime(latest.started)}); this run's replace them when it ends.`]);
  }
  if (!running && latest === null) {
    notes.push(["info", "No test run has been saved yet. Press Run again: a run takes several minutes, and the cards "
      + "fill in as it goes."]);
  }
  const kinds = {error: "error", warn: "caution", info: "info"};
  return notes.map(([kind, text]) => `<div class="banner ${kinds[kind] ?? "info"}"><span>${esc(text)}</span></div>`)
    .join("");
}

function healthHtml(running) {
  if (running) {
    const status = page.status, progress = Array.isArray(status.progress) ? status.progress : [];
    return stagesHtml(status.stages, {runId: status.id, running: progress.at(-1) ?? "Starting\u2026"});
  }
  const latest = page.latest;
  if (!latest) return latest === null ? '<div class="note">No stages yet.</div>' : "";
  if (!Array.isArray(latest.stages) || !latest.stages.length) return '<div class="note">This run built no stage.</div>';
  return stagesHtml(latest.stages, {runId: latest.id, stopped: latest.stopped === true});
}

/** Why the latest run has no results for sections 2 to 4, as HTML; "" while it is being read. */
function noResults() {
  const latest = page.latest;
  if (latest === undefined) return "";
  if (latest === null) return '<div class="note">No test run has been saved yet.</div>';
  const why = latest.stopped === true ? "was stopped before it read these results"
    : latest.error ? "failed before it read these results" : "built no stage, so there are no results";
  return `<div class="note">The last run ${why}.</div>`;
}

function drawFixtures() {
  const final = page.latest?.final, box = $("t-fixtures");
  const entry = final?.fixtures && typeof final.fixtures === "object" ? final.fixtures[page.rules] : undefined;
  const cases = entry?.available === true && Array.isArray(entry.cases) ? entry.cases : [];
  $("t-fx-count").textContent = cases.length ? `${cases.length} ` : "";
  $("t-legend").hidden = !cases.length;
  const stopped = page.latest?.stopped === true;  // R30: what the stop cut off is no failure
  $("t-rules").innerHTML = final ? `<span class="meta">Checked against:</span> ${rulesChoiceHtml(final.fixtures,
    page.rules, {stopped})}<span class="meta">in ${esc(final.label)}</span>` : "";
  if (!final) return noResults();
  box.innerHTML = fixturesHtml(entry, {runId: page.latest.id, stopped});
  for (const node of box.querySelectorAll("[data-case]")) {
    const item = cases[Number(node.dataset.case)] ?? {};
    drawBoard(node, {fen: typeof item.fen === "string" ? item.fen : "", flip: item.player === "black",
                     visible: Array.isArray(item.visible) ? item.visible : [], marks: fixtureMarks(item.expect),
                     size: FX_SIZE});
  }
  return undefined;
}

/** The scorer grid. The commit is the stage card's own (R28): the last stage built cleanly with final's label. */
function drawHarness() {
  const latest = page.latest, final = latest?.final, grid = $("t-grid");
  if (!final) {
    grid.innerHTML = "";
    grid.hidden = true;
    return noResults();
  }
  const stage = (Array.isArray(latest.stages) ? latest.stages : [])
    .findLast(item => item?.label === final.label && item?.merge === "clean");
  const {table, note} = harnessHtml(final.harness, {commit: stage?.sha ?? null, runId: latest.id,
                                                    label: words(final.label)});
  grid.innerHTML = table;
  grid.hidden = !table;
  return note;
}

function drawAccuracy() {
  const final = page.latest?.final;
  const forest = final ? forestHtml(final.accuracy?.differences) : "";
  $("t-forest").innerHTML = forest;
  $("t-forest-card").hidden = !forest;
  $("t-acc-from").textContent = final
    ? `These are the files in pair_b/checkpoints of \u201C${words(final.label)}\u201D, the last stage built.` : "";
  return final ? accuracyHtml(final.accuracy) : noResults();
}
