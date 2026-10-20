// Fog Lab's page: the tabs, and the Play tab.
//
// The page does no chess. It draws what the server sends (pairb.lab.server; a state is Session.state() or a replay's
// view_state()) and posts the human's clicks as UCI moves picked from the server's legal moves. Every request goes to
// the page's own server by a relative URL, since the server answers nothing else.
//
// What may be shown is the server's decision alone. A state that carries "bot" or "true_fen" has been revealed
// (Ruling R15), and only then do the bot panel, the Testing strip and the Testing switches appear. A fair game that is
// still going arrives without them; a replay always has them, even stepped back to before its end.

import {displaySquares, drawBoard, glyph, moveTargets, parseFen, topMoves, worstMoves} from "./board.js";
import {bar, capitalise, cell, CHECK, enc, esc, exact, isNumber, NONE, signed} from "./panel.js";
import {startTests} from "./tests.js";
import {showMoveReply} from "./playback.js";

const TOP_MOVES = 6;    // rows in the bot's table and the heatmap; the chosen move is added when it is not among them
const WORST_MOVES = 2;
const STRIP_SIZE = 200, MINI_SIZE = 88;  // px; the main board's size follows the window
const SESSION_KEY = "fogLab.play";       // the game on the screen, so that reloading the page keeps it
const STAR = "\u2605\uFE0E";
const COLOUR = {white: "White", black: "Black"};
const PIECE_NAMES = {q: "queen", r: "rook", b: "bishop", n: "knight"};
const REASONS = {
  king_capture: "a king was captured",
  fifty_move: "fifty moves went by without a capture or a pawn move",
  threefold_repetition: "the same position came up three times",
  no_legal_moves: "the side to move had no legal move",
};
const ALL_SQUARES = displaySquares(false);

// The tabs: a button[data-tab] in the header and a section[data-panel] for each. A tab's start function, when it has
// one, runs the first time the tab is shown: the Tests tab's page is tests.js. (The Play tab starts with the page.)
const TAB_START = {play: null, tests: startTests};
const startedTabs = new Set();

const ui = {
  config: null,       // GET /api/config
  mode: null,         // "game" (the live game) or "replay" (a loaded record); null until there is one
  gameId: null,       // the live game: the server keeps only the newest
  scorerLabel: null,  // the live game's scorer, as the New game panel named it
  replay: null,       // {id, plies, name} of the loaded replay
  full: null,         // the state at the end: the live game's latest, or the replay's last step
  state: null,        // the state on the screen, which the step controls move back and forth
  busy: null,         // what the page is waiting for, as text, or null
  pendingMove: null,  // the human's move while the server plays it and the bot replies
  selected: null,     // the square of the piece the human has picked up
  promotion: null,    // {to, moves} while the page asks what a pawn becomes
  notice: null,       // why a request failed
  info: null,         // a passing message, such as where a game was saved
  saved: [],          // GET /api/saved
  testing: false,     // Testing mode
  mainView: "you",    // what the main board shows in Testing mode: "you", "true" (the true board) or "bot"
  showReasoning: true,
  stepping: true,
};

const $ = id => document.getElementById(id);

// ---- requests ----

/** The JSON answer to a request to the page's own server; an Error with the server's message when it refuses. */
async function api(path, {method = "GET", body} = {}) {
  let response;
  try {
    response = await fetch(path, body === undefined ? {method}
      : {method, body, headers: {"Content-Type": "application/json"}});
  } catch {
    throw new Error("Fog Lab's server did not answer: is it still running?");
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    // not JSON: the status says enough
  }
  if (!response.ok) throw new Error(data?.error ?? `the server answered ${response.status}`);
  return data;
}

async function loadConfig() {
  try {
    ui.config = await api("/api/config");
  } catch (error) {
    ui.notice = `Could not read Fog Lab's settings: ${error.message}`;
    return;
  }
  const select = $("new-game").elements.scorer;
  const chosen = select.value;
  select.replaceChildren(...ui.config.scorers.map(info => {
    const option = new Option(info.available ? info.label : `${info.label} (unavailable)`, info.id);
    option.disabled = !info.available;
    if (!info.available) option.title = info.reason ?? "unavailable";
    return option;
  }));
  const usable = id => ui.config.scorers.some(info => info.id === id && info.available);
  select.value = usable(chosen) ? chosen : ui.config.default_scorer;
  const missing = ui.config.scorers.filter(info => !info.available);
  $("unavailable").hidden = missing.length === 0;
  $("unavailable").textContent = missing.length
    ? `Not available here: ${missing.map(info => `${info.label} (${info.reason})`).join("; ")}.` : "";
}

async function loadSaved() {
  try {
    ui.saved = await api("/api/saved");
  } catch (error) {
    ui.notice = `Could not list the saved games: ${error.message}`;
  }
}

// ---- actions ----

async function newGame(event) {
  event.preventDefault();
  if (ui.busy) return;
  const fields = $("new-game").elements;
  const options = {human: fields.human.value, scorer: fields.scorer.value, guesses: Number(fields.guesses.value),
                   seed: Number(fields.seed.value), fair: fields.fair.checked};
  const label = ui.config?.scorers.find(info => info.id === options.scorer)?.label ?? options.scorer;
  ui.notice = ui.info = null;
  await work(options.human === "white" ? "Starting the game\u2026" : "Starting the game; the bot may move first\u2026",
    async () => {
      const {state} = await api("/api/games", {method: "POST", body: JSON.stringify(options)});
      Object.assign(ui, {testing: fields.testing.checked && !options.fair, mainView: "you", scorerLabel: label,
                         replay: null});
      showLive(state);
    }, async error => {
      ui.notice = `The game did not start: ${error.message}`;
      await loadConfig();  // a scorer that failed to open is now listed as unavailable
    });
}

async function play(move) {
  if (!canMove(ui.state)) return;
  Object.assign(ui, {selected: null, promotion: null, pendingMove: move, notice: null, info: null});
  await work("Bot is thinking\u2026", async () => {
    const reply = await api(`/api/games/${enc(ui.gameId)}/move`,
      {method: "POST", body: JSON.stringify({move, include_after_human: true})});
    await showMoveReply(reply, state => {
      showLive(state);
      ui.busy = "Your move played; bot replies shortly\u2026";
      render();
    });
  }, error => {
    ui.notice = `${move} was not played: ${error.message}`;
  });
}

/** Show the state after `ply` moves of the game or replay on the screen. */
async function step(ply) {
  if (!ui.full || ui.busy || !Number.isInteger(ply) || ply < 0 || ply > ui.full.ply || ply === ui.state.ply) return;
  Object.assign(ui, {selected: null, promotion: null});
  if (ply === ui.full.ply) {
    ui.state = ui.full;
    render();
    return;
  }
  const path = ui.mode === "replay" ? `/api/replays/${enc(ui.replay.id)}?ply=${ply}`
    : `/api/games/${enc(ui.gameId)}?ply=${ply}`;
  await work("Loading\u2026", async () => {
    ui.state = await api(path);
  }, error => {
    ui.notice = `Could not step to ply ${ply}: ${error.message}`;
  });
}

function stepBy(where) {
  if (!ui.state) return;
  const ply = ui.state.ply;
  step({first: 0, back: ply - 1, forward: ply + 1, last: ui.full.ply}[where]);
}

async function save() {
  if (ui.busy || ui.mode !== "game") return;
  ui.notice = ui.info = null;
  await work("Saving\u2026", async () => {
    const {name} = await api(`/api/games/${enc(ui.gameId)}/save`, {method: "POST"});
    const record = await api(`/api/games/${enc(ui.gameId)}/record`);
    download(name, JSON.stringify(record, null, 1));
    ui.info = `Saved as ${name} in the games folder; a copy is downloading too.`;
    await loadSaved();
  }, error => {
    ui.notice = `The game was not saved: ${error.message}`;
  });
}

async function openSaved() {
  const name = $("saved-list").value;
  if (ui.busy || !name) return;
  ui.notice = ui.info = null;
  await work("Opening\u2026", async () => {
    const {id, plies} = await api("/api/replays", {method: "POST", body: JSON.stringify({name})});
    await showReplay({id, plies, name});
  }, error => {
    ui.notice = `${name} could not be opened: ${error.message}`;
  });
}

async function openFile() {
  const input = $("open-file");
  const file = input.files[0];
  input.value = "";  // so that choosing the same file again opens it again
  if (ui.busy || !file) return;
  ui.notice = ui.info = null;
  await work("Opening\u2026", async () => {
    const {id, plies} = await api("/api/replays", {method: "POST", body: await file.text()});
    await showReplay({id, plies, name: file.name});
  }, error => {
    ui.notice = `${file.name} could not be opened: ${error.message}`;
  });
}

async function backToGame() {
  if (ui.busy || !ui.gameId) return;
  await work("Loading\u2026", async () => {
    showLive(await api(`/api/games/${enc(ui.gameId)}`));
  }, error => {
    ui.notice = `The game is not there any more: ${error.message}`;
    ui.gameId = null;
  });
}

/** Run `job` with the page marked busy with `what`; `failed` gets the Error when it fails. Renders when done. A
 * pending move is over when its request is, whatever the answer. */
async function work(what, job, failed) {
  ui.busy = what;
  render();
  try {
    await job();
  } catch (error) {
    await failed(error);
  } finally {
    Object.assign(ui, {busy: null, pendingMove: null});
    writeSession();
    render();
  }
}

function showLive(state) {
  Object.assign(ui, {mode: "game", gameId: state.id, full: state, state, selected: null, promotion: null});
}

async function showReplay(replay) {
  const state = await api(`/api/replays/${enc(replay.id)}?ply=${replay.plies}`);
  Object.assign(ui, {mode: "replay", replay, full: state, state, selected: null, promotion: null, stepping: true,
                     mainView: "you"});
}

function toggle(name) {
  if (name === "reasoning") ui.showReasoning = !ui.showReasoning;
  else if (name === "stepping") ui.stepping = !ui.stepping;
  else if (name === "testing") ui.testing = !ui.testing;
  else if (name === "true") ui.mainView = ui.mainView === "true" ? "you" : "true";
  else if (name === "botview") ui.mainView = ui.mainView === "bot" ? "you" : "bot";
  if (!ui.testing) ui.mainView = "you";
  Object.assign(ui, {selected: null, promotion: null});
  writeSession();
  render();
}

function onSquare(square) {
  const legal = ui.state.you.legal_moves;
  const moves = ui.selected ? moveTargets(legal, ui.selected)[square] : undefined;
  if (moves?.length === 1) {
    play(moves[0]);
    return;
  }
  if (moves) {
    ui.promotion = {to: square, moves};  // one move per piece: ask which
  } else {
    ui.selected = square !== ui.selected && Object.keys(moveTargets(legal, square)).length ? square : null;
    ui.promotion = null;
  }
  render();
}

function putDown() {
  Object.assign(ui, {selected: null, promotion: null});
  render();
}

function onKey(event) {
  if (event.target.closest?.("input, select, textarea") || event.altKey || event.ctrlKey || event.metaKey) return;
  if (event.key === "Escape") {
    putDown();
    return;
  }
  const where = {ArrowLeft: "back", ArrowRight: "forward", Home: "first", End: "last"}[event.key];
  if (where && ui.state && !$("panel-play").hidden) {
    event.preventDefault();
    stepBy(where);
  }
}

// ---- what is shown ----

/** Whether the server has revealed the bot's side in `state` (Ruling R15): never decided from fair or over. */
function revealed(state) {
  return Boolean(state) && ("bot" in state || "true_fen" in state);
}

/** Whether the human can move now: the live game's latest position, the human to move, nothing pending. A game stopped
 * by an error has error set and over false, and takes no more moves. */
function canMove(state) {
  return ui.mode === "game" && !ui.busy && Boolean(state) && state.ply === ui.full?.ply && !state.over
    && !state.error && state.you.legal_moves.length > 0;
}

function boardView(state) {
  return revealed(state) && ui.testing ? ui.mainView : "you";
}

function render() {
  const state = ui.state;
  renderStatus(state);
  renderControls(state);
  renderBanners(state);
  renderMain(state);
  renderLog(state);
  renderStepbar(state);
  renderSwitches(state);
  renderMoveList(state);
  guarded($("bot-panel"), () => renderBotPanel(state));
  guarded($("t-heat"), () => renderTesting(state));
}

/** Run `draw`, which fills `box` from a bot turn. A record checks the turn's keys but not what an explanation holds, so
 * a record from elsewhere may hold what the page cannot draw: then `box` says so, and the rest of the page still works. */
function guarded(box, draw) {
  try {
    draw();
  } catch (error) {
    box.innerHTML = `<div class="note warn">This bot turn could not be drawn: ${esc(error.message)}</div>`;
  }
}

function renderStatus(state) {
  const config = ui.config;
  if (!config) {
    $("status-line").textContent = ui.notice ? "Fog Lab's settings could not be read" : "Connecting to Fog Lab\u2026";
    return;
  }
  const parts = [];
  if (ui.mode === "replay" && state) {
    const rules = state.rules === config.rules.name ? config.rules.label : state.rules;
    parts.push(`Replay of ${ui.replay.name}`, `Rules: ${rules}`, `Scorer: ${state.scorer}`);
  } else {
    parts.push(`Rules: ${config.rules.label}`);
    if (ui.mode === "game" && state) {
      const scorer = ui.scorerLabel ?? state.scorer ?? "?";
      parts.push(`Scorer: ${scorer}${state.device ? ` on ${state.device}` : ""}`);
    }
  }
  parts.push(config.torch ? config.machine : `${config.machine}, no torch`);
  $("status-line").textContent = parts.join(" \u00B7 ");
}

function renderControls(state) {
  const fields = $("new-game").elements;
  $("new-game-button").disabled = Boolean(ui.busy) || !ui.config;
  fields.testing.disabled = fields.fair.checked;  // a fair game has no Testing mode until it ends
  if (fields.fair.checked) fields.testing.checked = false;
  const save = $("save");
  save.hidden = ui.mode !== "game";
  save.disabled = Boolean(ui.busy) || !revealed(ui.full);
  save.title = revealed(ui.full) ? "Write the record to the games folder and download a copy"
    : "A fair game can be saved once it is over";
  const list = $("saved-list");
  const names = ui.saved.map(entry => entry.name);
  if (list.dataset.names !== names.join("\n")) {
    const keep = list.value;
    list.replaceChildren(...(names.length ? ui.saved.map(entry => new Option(entry.name, entry.name))
      : [new Option("No saved games yet", "")]));
    list.title = names.length ? "" : "Saved games appear here";
    if (names.includes(keep)) list.value = keep;
    list.dataset.names = names.join("\n");
  }
  list.disabled = names.length === 0;
  $("open-saved").disabled = Boolean(ui.busy) || names.length === 0;
  $("open-file-button").disabled = Boolean(ui.busy);
  $("back-to-game").hidden = ui.mode !== "replay" || !ui.gameId;
  $("back-to-game").disabled = Boolean(ui.busy);
}

function renderBanners(state) {
  const banners = [];
  if (state?.over && state.result) banners.push(["over", `Game over. ${resultText(state.result, state.human)}`]);
  if (state?.error) {
    banners.push(["error", ui.mode === "replay" ? `The game stopped here: ${state.error}`
      : `The game stopped: ${state.error}. No more moves can be played; Save keeps the record for a bug report.`]);
  }
  if (ui.notice) banners.push(["error", ui.notice, "notice"]);
  if (ui.info) banners.push(["info", ui.info, "info"]);
  if (state && !revealed(state)) {
    banners.push(["info", "Fair game: the bot's moves, its reasoning and the true board stay hidden until the game "
      + "ends. You see only your own view and your own moves."]);
  }
  $("banners").innerHTML = banners.map(([kind, text, dismiss]) => `<div class="banner ${kind}"><span>${esc(text)}`
    + `</span>${dismiss ? `<button type="button" class="close" data-dismiss="${dismiss}" aria-label="Dismiss">`
    + "\u00D7</button>" : ""}</div>`).join("");
}

function renderMain(state) {
  const board = $("main-board");
  if (!state) {
    drawBoard(board, {visible: [], size: mainSize()});
    board.closest(".board-col").style.width = `${mainSize() + 4}px`;
    $("main-caption").textContent = "Choose your colour and the bot's scorer, then press New game.";
    $("promotion").hidden = true;
    return;
  }
  const view = boardView(state), you = state.you, bot = state.bot_view;
  const marks = {last: squaresOf(state.your_moves.at(-1))};
  let fen, visible, caption;
  if (view === "true") {
    fen = state.true_fen;
    visible = null;
    marks.veil = ALL_SQUARES.filter(square => !you.visible_squares.includes(square));
    caption = "The true board (referee only). Veiled squares are hidden from you.";
  } else if (view === "bot") {
    fen = bot.visible_pieces;
    visible = bot.visible_squares;
    caption = `The bot's view (${COLOUR[other(state.human)]}): ${visible.length} squares seen. `
      + "Hatched squares are hidden from the bot.";
  } else {
    fen = you.visible_pieces;
    visible = you.visible_squares;
    caption = `Your view (${COLOUR[state.human]}): ${visible.length} squares seen. Hatched squares are hidden from you.`;
  }
  const size = mainSize(), moving = canMove(state) && view !== "bot";
  if (moving) {
    marks.movable = [...new Set(you.legal_moves.map(move => move.slice(0, 2)))];
    if (ui.selected) {
      marks.sel = [ui.selected];
      marks.dest = Object.keys(moveTargets(you.legal_moves, ui.selected));
    }
  }
  if (ui.pendingMove) marks.pending = squaresOf(ui.pendingMove);
  drawBoard(board, {fen, visible, flip: state.human === "black", marks, size, onSquare: moving ? onSquare : null});
  board.closest(".board-col").style.width = `${size + 4}px`;  // the board and its border
  $("main-caption").textContent = caption;
  renderPromotion(state);
}

function renderPromotion(state) {
  const box = $("promotion");
  box.hidden = !ui.promotion;
  if (!ui.promotion) return;
  const white = state.human === "white";
  box.innerHTML = '<div class="box" role="dialog" aria-label="Promote the pawn"><div class="cap">Promote the pawn to'
    + "</div><div>" + [...ui.promotion.moves].sort(byPiece).map(move => {
      const letter = move.slice(4);
      const symbol = glyph(white ? letter.toUpperCase() : letter);
      return `<button type="button" class="piece" data-move="${esc(move)}" title="${esc(PIECE_NAMES[letter] ?? move)}">`
        + `${symbol || esc(move)}</button>`;
    }).join("") + '</div><button type="button" class="cancel" data-move="">Cancel</button></div>';
}

/** Promotions in the usual order: queen, rook, bishop, knight. */
function byPiece(a, b) {
  return "qrbn".indexOf(a.slice(4)) - "qrbn".indexOf(b.slice(4));
}

function renderLog(state) {
  const parts = [];
  if (state) {
    parts.push(`Move ${moveNumber(state)}`);
    const last = state.your_moves.at(-1);
    if (last) parts.push(`your last move: ${last} (yellow)`);
    if (state.over) parts.push("game over");
    else if (state.error) parts.push("stopped");
    else if (state.to_move === state.human) parts.push(`${COLOUR[state.human]}, you, to move`);
    else parts.push(`${COLOUR[other(state.human)]}, the bot, to move`);
    if (ui.mode === "game" && state.ply < ui.full.ply) parts.push("go to the last move to play");
  }
  $("main-log").textContent = parts.join(" \u00B7 ");
  $("thinking").hidden = !ui.busy;
  $("thinking-text").textContent = ui.busy ?? "";
}

function renderStepbar(state) {
  const bar = $("stepbar");
  bar.hidden = !ui.stepping || !state;
  if (bar.hidden) return;
  const ply = state.ply, total = ui.full.ply;
  for (const button of bar.querySelectorAll("[data-step]")) {
    const back = button.dataset.step === "first" || button.dataset.step === "back";
    button.disabled = Boolean(ui.busy) || (back ? ply === 0 : ply === total);
  }
  $("step-where").textContent = `Ply ${ply} of ${total}`;
}

function renderSwitches(state) {
  const open = revealed(state), testing = open && ui.testing, view = boardView(state);
  const shown = {reasoning: open, true: testing, botview: testing, stepping: Boolean(state), testing: open};
  const on = {reasoning: ui.showReasoning, true: view === "true", botview: view === "bot", stepping: ui.stepping,
              testing: ui.testing};
  for (const chip of $("switches").querySelectorAll("[data-switch]")) {
    chip.hidden = !shown[chip.dataset.switch];
    chip.classList.toggle("on", on[chip.dataset.switch]);
    chip.setAttribute("aria-pressed", String(on[chip.dataset.switch]));
  }
}

function renderMoveList(state) {
  const box = $("move-list");
  if (!state) {
    box.replaceChildren();
    return;
  }
  const plies = plyList(ui.full);
  if (!plies.length) {
    box.innerHTML = '<span class="meta">No moves yet.</span>';
    return;
  }
  const offset = plies[0].player === "black" ? 1 : 0;
  box.innerHTML = plies.map(({ply, player, move}) => {
    const number = Math.floor((ply + offset) / 2) + 1;
    const label = player === "white" ? `<span class="num">${number}.</span>`
      : ply === 0 ? `<span class="num">${number}. \u2026</span>` : "";
    const classes = ["mv", player === state.human ? "mine" : "", ply === state.ply - 1 ? "current" : ""].join(" ");
    const title = move === null ? "The bot's moves stay hidden until the game ends" : `Show the board after ${move}`;
    return `${label}<button type="button" class="${classes.trim()}" data-ply="${ply + 1}" title="${esc(title)}">`
      + `${move === null ? "?" : esc(move)}</button>`;
  }).join(" ");
  const current = box.querySelector(".current");
  if (current) box.scrollTop = Math.max(0, current.offsetTop - box.offsetTop - box.clientHeight / 2);
}

function renderBotPanel(state) {
  const panel = $("bot-panel");
  panel.hidden = !revealed(state) || !ui.showReasoning;
  if (panel.hidden) return;
  const who = `Bot (${COLOUR[other(state.human)]})`, turn = state.bot;
  const thinking = ui.pendingMove ? ' <span class="spinner"></span>' : "";
  if (!turn) {
    panel.innerHTML = `<h4>${who} ${ui.pendingMove ? "is choosing a move" : "has not moved yet"}${thinking}</h4>`;
    return;
  }
  const ex = turn.explanation ?? {}, played = state.moves[turn.ply]?.move ?? ex.chosen;
  let html = `<h4>${ui.pendingMove ? `${who} is choosing a move${thinking}` : `${who} played ${esc(played)}`}</h4>`;
  if (ui.pendingMove) html += `<div class="cap">Its last turn, ${esc(played)}:</div>`;
  if (ex.chosen !== undefined && ex.chosen !== played) {
    html += `<div class="note warn">The explanation's chosen move is ${esc(ex.chosen)}, not ${esc(played)}.</div>`;
  }
  const pieces = ex.guesses?.length ? parseFen(ex.guesses[0]) : {};  // the bot's own pieces stand in every guess
  if (ex.app_inspection === true) {
    html += `<div class="cap">This agent gives no explanation of its own. Its policy, the probability it gave each
      move, with the app's average over the agent's own guesses (${esc(ex.scorer ?? "the scorer")}):</div>`;
    html += policyTable(ex, pieces);
    if (ex.error) html += `<div class="note warn">${esc(capitalise(ex.error))}</div>`;
    html += `<div class="note">${Object.keys(ex.policy ?? {}).length} legal moves. The values in the Testing strip are
      the app's inspection, not the agent's reasoning.</div>`;
  } else if (ex.averages) {
    const guesses = Array.isArray(ex.guesses) ? ex.guesses.length : 0;  // a number, whatever a record holds
    html += `<div class="cap">${uniform(ex.weights) ? "Average" : "Weighted average"} value over its ${guesses}
      guess${guesses === 1 ? "" : "es"} at your hidden pieces (${COLOUR[other(state.human)]}'s view, +1 =
      ${COLOUR[other(state.human)]} wins). Scorer ${esc(ex.scorer ?? "?")}, ${Math.round(ex.elapsed_ms ?? 0)} ms.</div>`;
    const rows = topMoves(ex.averages, ex.chosen, TOP_MOVES);
    html += valuesTable(ex, rows, pieces);
    const worst = worstMoves(ex.averages, rows, WORST_MOVES);
    html += `<div class="note">${Object.keys(ex.averages).length} legal moves.${worst.length ? ` Worst: ${worst.map(
      move => `${esc(move)} ${signed(ex.averages[move])}`).join(", ")}.` : ""}</div>`;
  } else {
    html += '<div class="note">No explanation was recorded for this turn.</div>';
  }
  if (ex.guesses?.length) {
    html += `<div class="cap gap">The ${ex.app_inspection ? "agent's" : "bot's"} guesses at the board</div>`
      + `<div class="minis">${ex.guesses.map((_, index) => `<div class="mini" title="weight ${esc(ex.weights?.[index])}">`
      + `<div data-guess="${index}"></div>guess ${index + 1}</div>`).join("")}</div>`;
  }
  panel.innerHTML = `<div class="${ui.pendingMove ? "stale" : ""}">${html}</div>`;
  for (const node of panel.querySelectorAll("[data-guess]")) {
    drawBoard(node, {fen: ex.guesses[Number(node.dataset.guess)], flip: state.human === "black", size: MINI_SIZE});
  }
}

function valuesTable(ex, rows, pieces) {
  const scale = Math.max(0.05, ...rows.map(move => Math.abs(ex.averages[move] ?? 0)));
  return '<div class="scroll"><table class="u"><tr><th>Move</th><th>Average</th><th></th><th>Range over guesses</th>'
    + "</tr>" + rows.map(move => {
      const average = ex.averages[move];
      return `<tr class="${move === ex.chosen ? "chosen" : ""}"><td>${moveLabel(move, pieces, ex)}</td>`
        + `<td class="num" title="${exact(average)}">${signed(average)}</td><td>${bar(average, scale)}</td>`
        + `<td class="num" title="${exact(ex.min?.[move])} to ${exact(ex.max?.[move])}">${signed(ex.min?.[move], 2)} to `
        + `${signed(ex.max?.[move], 2)}</td></tr>`;
    }).join("") + "</table></div>";
}

function policyTable(ex, pieces) {
  const rows = topMoves(ex.policy, ex.chosen, TOP_MOVES);
  return '<div class="scroll"><table class="u"><tr><th>Move</th><th>Policy</th><th></th><th>App\'s average</th></tr>'
    + rows.map(move => {
    const p = ex.policy?.[move];
    return `<tr class="${move === ex.chosen ? "chosen" : ""}"><td>${moveLabel(move, pieces, ex)}</td>`
      + `<td class="num" title="${exact(p)}">${isNumber(p) ? `${(p * 100).toFixed(1)}%` : NONE}</td>`
      + `<td>${isNumber(p) ? `<span class="track"><span class="bar pos" style="left:0;width:${Math.round(
        Math.min(1, Math.max(0, p)) * 100)}%"></span></span>` : ""}</td>`
      + `<td class="num" title="${exact(ex.averages?.[move])}">${signed(ex.averages?.[move])}</td></tr>`;
  }).join("") + "</table></div>";
}

function renderTesting(state) {
  const strip = $("testing");
  strip.hidden = !revealed(state) || !ui.testing;
  if (strip.hidden) return;
  const flip = state.human === "black", you = state.you, bot = state.bot_view;
  drawBoard($("t-you"), {fen: you.visible_pieces, visible: you.visible_squares, flip, size: STRIP_SIZE,
                         marks: {last: squaresOf(state.your_moves.at(-1))}});
  drawBoard($("t-true"), {fen: state.true_fen, flip, size: STRIP_SIZE});
  drawBoard($("t-bot"), {fen: bot.visible_pieces, visible: bot.visible_squares, flip, size: STRIP_SIZE});
  $("t-you-cap").textContent = `Your view (${COLOUR[state.human]}): ${you.visible_squares.length} squares seen`;
  $("t-bot-cap").textContent = `Bot's view (${COLOUR[other(state.human)]}): ${bot.visible_squares.length} squares seen`;
  $("t-heat").innerHTML = heatPanel(state);
}

function heatPanel(state) {
  const turn = state.bot;
  if (!turn) {
    return "<h4>Move values on each of the bot's guesses</h4><div class=\"note\">The bot has not moved yet.</div>"
      + trackerNote(state);
  }
  const ex = turn.explanation ?? {}, inspection = turn.inspection ?? {};
  const appInspection = ex.app_inspection === true;
  let html = appInspection
    ? `<h4>The app's inspection: move values on each of the agent's own guesses (${STAR} = the true board)</h4>
       <div class="cap">Computed by the app with ${esc(ex.scorer ?? "the scorer")}, not the agent's reasoning.</div>`
    : `<h4>Move values on each of the bot's guesses (${STAR} = the true board, scored by the app)</h4>`;
  const guesses = ex.guesses ?? [], pieces = guesses.length ? parseFen(guesses[0]) : {};
  const rows = ex.values ? topMoves(ex.averages, ex.chosen, TOP_MOVES) : [];
  const truth = inspection.true_values ?? null;
  if (rows.length) {
    html += '<div class="scroll"><table class="u heat"><tr><th>Move</th>'
      + guesses.map((_, index) => `<th class="c" title="weight ${esc(ex.weights?.[index])}">${index + 1}</th>`).join("")
      + `<th class="c">Average</th><th class="c truth">${STAR} True board</th></tr>`
      + rows.map(move => `<tr class="${move === ex.chosen ? "chosen" : ""}"><td>${moveLabel(move, pieces, ex)}</td>`
        + guesses.map((_, index) => cell(ex.values[move]?.[index])).join("")
        + `<td class="avg" title="${exact(ex.averages[move])}">${signed(ex.averages[move], 2)}</td>`
        + cell(truth?.[move], `truth${move === inspection.best_on_true_board ? " best" : ""}`) + "</tr>").join("")
      + "</table></div>";
  } else if (ex.error) {
    html += `<div class="note warn">${esc(capitalise(ex.error))}</div>`;
  }
  const notes = [];
  if (!appInspection && ex.chosen) notes.push(`The bot picks the best average: ${esc(ex.chosen)}.`);
  if (inspection.error) {
    notes.push(`<span class="warn">The app's check of the true board failed: ${esc(inspection.error)}</span>`);
  } else if (truth) {
    const best = inspection.best_on_true_board;
    notes.push(`On the true board the best move is ${esc(best)} (${signed(truth[best])}); the ${appInspection ? "agent"
      : "bot"}'s move ${esc(ex.chosen)} scores ${signed(truth[ex.chosen])} there.`);
    if (best && rows.length && !rows.includes(best)) notes.push(`(${esc(best)} is not among the rows above.)`);
  }
  if (!inspection.error) {
    notes.push(`<b>Lost by not knowing: ${signed(inspection.lost_by_not_knowing)}</b> (the best value on the true board
      minus the true-board value of the move played).`);
  }
  html += `<div class="note">${notes.join(" ")}</div>`;
  html += `<div class="note health">${healthLine(turn)}</div>`;
  return html + trackerNote(state);
}

/** The state's tracker_error (session.py: the bot's tracker failed on the view that ended the game, which the state
 * carries at the end only) as a warning, or "". The game is over all the same. */
function trackerNote(state) {
  if (typeof state.tracker_error !== "string" || !state.tracker_error) return "";
  return `<div class="note warn">${esc(capitalise(state.tracker_error))}. The game is over all the same: its result `
    + "stands.</div>";
}

function healthLine(turn) {
  const inspection = turn.inspection ?? {};
  const count = Array.isArray(inspection.particles) ? inspection.particles.length : turn.population_size;
  const parts = [isNumber(count)
    ? `${count} possible board${count === 1 ? "" : "s"}${inspection.capped ? " (capped: a sample of more)" : ""}`
    : "the number of possible boards is not known"];
  if (inspection.truth_in_particles === true) parts.push("the true board is among them");
  else if (inspection.truth_in_particles === false) parts.push('<b class="warn">the true board is not among them</b>');
  if (inspection.rebuilt === true) parts.push('<b class="warn">the tracker rebuilt its belief this turn</b>');
  else if (inspection.rebuilt === false) parts.push("no rebuild this turn");
  return `Belief health: ${parts.join(" \u00B7 ")}.`;
}

// ---- small helpers ----

function moveLabel(move, pieces, ex) {
  const symbol = glyph(pieces[move.slice(0, 2)]);
  return `${symbol ? `<span class="pc">${symbol}</span> ` : ""}${esc(move)}${move === ex.chosen ? ` ${CHECK}` : ""}`;
}

/** Every move up to the end of `full` as {ply, player, move}: all of them when revealed, else the human's own and a
 * null for each of the bot's. Turns alternate, so the side that moved first follows from whose turn it is. */
function plyList(full) {
  if (Array.isArray(full.moves)) return full.moves;
  const first = full.ply % 2 === 0 ? full.to_move : other(full.to_move);
  let mine = 0;
  return Array.from({length: full.ply}, (_, ply) => {
    const player = ply % 2 === 0 ? first : other(first);
    return {ply, player, move: player === full.human ? full.your_moves[mine++] ?? null : null};
  });
}

function moveNumber(state) {
  const first = state.ply % 2 === 0 ? state.to_move : other(state.to_move);
  return Math.floor((state.ply + (first === "black" ? 1 : 0)) / 2) + 1;
}

function resultText(result, human) {
  const why = REASONS[result.reason] ?? result.reason;
  if (result.winner === "draw") return `A draw: ${why}.`;
  if (result.reason === "king_capture") {
    return result.winner === human ? "You win: you captured the bot's king." : "The bot wins: it captured your king.";
  }
  return `${result.winner === human ? "You win" : "The bot wins"} (${COLOUR[result.winner] ?? result.winner}): ${why}.`;
}

function mainSize() {
  const fit = Math.min(window.innerWidth * 0.42, window.innerHeight - 250);
  return Math.floor(Math.max(296, Math.min(520, fit)) / 8) * 8;
}

function squaresOf(move) {
  return move ? [move.slice(0, 2), move.slice(2, 4)] : [];
}

function other(colour) {
  return colour === "white" ? "black" : "white";
}

function uniform(weights) {
  return !weights?.length || weights.every(weight => Math.abs(weight - weights[0]) < 1e-12);
}

function download(name, text) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], {type: "application/json"}));
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function writeSession() {
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({gameId: ui.gameId, scorerLabel: ui.scorerLabel,
      testing: ui.testing, mode: ui.mode, replay: ui.replay}));
  } catch {
    // storage can be switched off; the page works without it
  }
}

function readSession() {
  try {
    return JSON.parse(sessionStorage.getItem(SESSION_KEY) ?? "null");
  } catch {
    return null;
  }
}

/** After a reload: the live game and the replay that were on the screen, if the server still has them. It runs as
 * work, like any other request: the server answers a game's state only once a bot reply in progress is done, and until
 * then the page is busy, so New game cannot start a game that this answer would then replace on the screen. */
async function restore() {
  const saved = readSession();
  if (!saved) return;
  Object.assign(ui, {testing: Boolean(saved.testing), scorerLabel: saved.scorerLabel ?? null});
  const replay = saved.mode === "replay" && saved.replay ? saved.replay : null;
  if (!saved.gameId && !replay) return;
  await work(replay ? "Opening the replay\u2026" : "Opening the game\u2026", async () => {
    if (saved.gameId) {
      try {
        showLive(await api(`/api/games/${enc(saved.gameId)}`));
      } catch {
        ui.gameId = null;  // a newer game replaced it, or the server restarted
      }
    }
    if (replay) {
      try {
        await showReplay(replay);
      } catch {
        // the server keeps only the newest replays
      }
    }
  }, error => {
    ui.notice = `The game on the screen before could not be shown again: ${error.message}`;
  });
}

// ---- start ----

function showTab(name) {
  const tab = Object.hasOwn(TAB_START, name) ? name : "play";
  for (const button of document.querySelectorAll("[data-tab]")) {
    button.setAttribute("aria-selected", String(button.dataset.tab === tab));
  }
  for (const panel of document.querySelectorAll("[data-panel]")) panel.hidden = panel.dataset.panel !== tab;
  if (!startedTabs.has(tab)) {
    startedTabs.add(tab);
    TAB_START[tab]?.();
  }
}

async function startPlay() {
  $("new-game").addEventListener("submit", newGame);
  $("new-game").elements.fair.addEventListener("change", render);
  $("save").addEventListener("click", save);
  $("open-saved").addEventListener("click", openSaved);
  $("open-file-button").addEventListener("click", () => $("open-file").click());
  $("open-file").addEventListener("change", openFile);
  $("back-to-game").addEventListener("click", backToGame);
  const clicks = {stepbar: ["step", stepBy], switches: ["switch", toggle],
                  "move-list": ["ply", ply => step(Number(ply))], banners: ["dismiss", key => { ui[key] = null; render(); }],
                  promotion: ["move", move => (move ? play(move) : putDown())]};
  for (const [id, [key, act]] of Object.entries(clicks)) {
    $(id).addEventListener("click", event => {
      const target = event.target.closest(`[data-${key}]`);
      if (target && !target.disabled) act(target.dataset[key]);
    });
  }
  $("promotion").addEventListener("click", event => {
    if (event.target === $("promotion")) putDown();  // a click beside the box
  });
  document.addEventListener("keydown", onKey);
  let resizing = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizing);
    resizing = setTimeout(render, 100);
  });
  render();
  await Promise.all([loadConfig(), loadSaved()]);
  render();
  await restore();
  render();
}

for (const button of document.querySelectorAll("[data-tab]")) {
  button.addEventListener("click", () => {
    location.hash = button.dataset.tab;
  });
}
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
showTab(location.hash.slice(1));
startPlay();
