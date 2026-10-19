// The Tests page's pure helpers and HTML builders (static/tests.js), run with Node's own runner: node --test tests/js/
// The data below is shaped like a real run summary (pairb.lab.stage_runner, runs.py), cut down to what each test needs.
import test from "node:test"; import assert from "node:assert/strict";
import {cardStatus, fixtureMarks, forestX} from "../../src/pairb/lab/static/tests.js";
import {accuracyHtml, fixturesHtml, forestHtml, harnessHtml, logHref, rulesChoiceHtml, runHeadline, runNotes,
        runTime, stagesHtml} from "../../src/pairb/lab/static/tests.js";

const RUN = "20261020-024021-520886";
const HOSTILE = `<img src=x onerror="alert('x')">`;

/** The text a reader sees in `html`: tags dropped, entities decoded, spaces collapsed. */
function text(html) {
  return html.replace(/<[^>]*>/g, " ").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'").replace(/&amp;/g, "&").replace(/\s+/g, " ").trim();
}

/** Server text must reach the reader as text: never as markup, and whole. */
function shownAsText(html, payload) {
  assert.ok(!html.includes(payload), `raw markup in ${html}`);
  assert.ok(text(html).includes(payload), `${payload} not shown in ${text(html)}`);
}

const check = (key, label, status, summary, log = null, counts = {}) => ({key, label, status, summary, counts, log});
const stage = (label, merge, checks = [], extra = {}) => ({label, ref: `origin/${label}`, title: "",
                                                         sha: "55e0a56df8ff", merge, conflicts: [], checks, ...extra});

// ---- the brief's three exports ----

test("fixture marks: the blocked pawn's expectations", () => {
  const expect = {terminal: false, legal_excludes: ["e2e3", "e2e4"], visible_contains: ["e2"],
                  visible_excludes: ["e3"]};
  assert.deepEqual(fixtureMarks(expect), {see: ["e2"], nosee: ["e3"], mv: [], nomv: ["e3", "e4"]});
});

// Catches: a move marked on its starting square instead of where it goes, and one square marked once per promotion.
test("fixture marks: a move is marked where it goes, once per square", () => {
  assert.deepEqual(fixtureMarks({legal_contains: ["a7a8q", "a7a8r", "a7a8b", "a7a8n"]}),
                   {see: [], nosee: [], mv: ["a8"], nomv: []});
  assert.deepEqual(fixtureMarks({legal_contains: ["e2e4", "g1f3"], visible_contains: ["a1", "e4"]}).mv, ["e4", "f3"]);
  assert.deepEqual(fixtureMarks({}), {see: [], nosee: [], mv: [], nomv: []});
  assert.deepEqual(fixtureMarks({legal_contains: "e2e4", visible_contains: [7, "e2"], legal_excludes: [null]}),
                   {see: ["e2"], nosee: [], mv: [], nomv: []});
});

test("interval chart positions", () => {
  assert.equal(forestX(0), 50); assert.equal(forestX(-0.012), 0);
  assert.equal(forestX(0.012), 100); assert.equal(forestX(0.003), 62.5); assert.equal(forestX(0.5, 1), 75);
  assert.equal(forestX(-0.05), 0); assert.equal(forestX(0.05), 100);  // kept on the track
});

test("card status: red if any check failed", () => {
  const checks = [check("shared", "Shared + Pair A", "pass", "92 passed"),
                  check("pair_b", "Pair B", "fail", "1 failed"),
                  check("imports_a", "Imports", "unavailable", "Pair A's environment not set up here")];
  assert.equal(cardStatus(stage("+ PR #4", "clean", checks)), "red");
});

test("card status: grey when the merge failed", () => {
  for (const merge of ["conflict", "missing-ref", "skipped"]) assert.equal(cardStatus(stage("+ PR #5", merge)), "grey");
});

test("card status: green when every check passed or was unavailable or skipped", () => {
  const checks = [check("shared", "Shared + Pair A", "pass", "92 passed"),
                  check("pair_b", "Pair B", "unavailable", "Pair B's code is not in this stage yet"),
                  check("history", "History check", "skipped", "not run")];
  assert.equal(cardStatus(stage("main", "clean", checks)), "green");
});

// "+ this checkout" already held by the stages: nothing was built or checked there, which is no failure.
test("card status: a stage that adds nothing is grey", () => {
  assert.equal(cardStatus(stage("+ this checkout", "contained")), "grey");
});

// Ruling R30. Catches: a stopped run's cut-off check drawn as a red failure, and a real failure hidden by the stop.
test("card status: a check the stop cut off is no failure, but a real one still is", () => {
  const cut = [check("imports_b", "Imports, Pair B", "pass", "imports the stage's own code"),
               check("pair_b", "Pair B", "fail", "stopped"),
               check("shared", "Shared + Pair A", "skipped", "not run: the run was stopped")];
  assert.equal(cardStatus(stage("+ PR #4", "clean", cut), {stopped: true}), "grey");
  assert.equal(cardStatus(stage("+ PR #4", "clean", cut)), "red");  // not a stopped run: "stopped" is a summary
  const failedFirst = [check("pair_b", "Pair B", "fail", "1 failed, 98 passed"), ...cut.slice(1)];
  assert.equal(cardStatus(stage("+ PR #4", "clean", failedFirst), {stopped: true}), "red");
  const between = [check("pair_b", "Pair B", "pass", "99 passed"), cut[2]];  // stopped before its next check
  assert.equal(cardStatus(stage("+ PR #4", "clean", between), {stopped: true}), "grey");
});

// ---- logs ----

// Catches: a log link built from anything but a plain file name in the run's logs folder.
test("a check's log becomes a link to the run's log route", () => {
  assert.equal(logHref(RUN, "logs/4-harness-stockfish-d1.txt"),
               `/api/tests/runs/${RUN}/logs/4-harness-stockfish-d1.txt`);
  for (const log of [null, undefined, 3, "", "logs/", "4-pair_b.txt", "logs/../summary.json", "logs/a/b.txt",
                     "logs/.hidden", "/etc/passwd", "logs/x y.txt"]) {
    assert.equal(logHref(RUN, log), null, String(log));
  }
  for (const id of [null, "", "2026", `${RUN}/..`, "../x"]) assert.equal(logHref(id, "logs/0-shared.txt"), null);
});

// ---- the top bar ----

test("run times are the run's own local time", () => {
  assert.equal(runTime("2026-10-20T02:40:21+08:00"), "Tue 20 Oct, 02:40");
  assert.equal(runTime("2026-10-18T22:59:00-05:00"), "Sun 18 Oct, 22:59");
  assert.equal(runTime(null), "");
});

const MACHINE = {name: "C4QJ7945G2", system: "Darwin", release: "25.5.0", arch: "arm64", python: "3.14.6", torch: true};
const SUMMARY = {id: RUN, started: "2026-10-20T02:40:21+08:00", finished: "2026-10-20T02:47:37+08:00", machine: MACHINE,
                 fetch: {requested: false, ok: null, message: "not fetched: the run was asked not to"},
                 checkout_sha: "7c3e2a9a40879a9ba0c8d12ed95df6a64fa4081e", stopped: false, error: null, final: null,
                 stages: [stage("main", "clean", [check("shared", "Shared + Pair A", "pass", "92 passed")]),
                          stage("+ PR #4", "clean", [check("pair_b", "Pair B", "pass", "99 passed")])]};

test("the top bar names the run's time, length, machine, fetch and how many stages are green", () => {
  assert.equal(runHeadline(SUMMARY), "Last run Tue 20 Oct, 02:40 \u00B7 took 7 min 16 s \u00B7 C4QJ7945G2 "
               + "(macOS arm64) \u00B7 not fetched first \u00B7 2 of 2 stages green");
  const red = {...SUMMARY, machine: {...MACHINE, name: "BRYAN-MAC", arch: "x86_64", torch: false},
               fetch: {requested: true, ok: true, message: "fetched from origin"},
               stages: [...SUMMARY.stages, stage("+ PR #6", "clean", [check("pair_b", "Pair B", "fail", "1 failed")]),
                        stage("+ this checkout", "contained")]};
  assert.equal(runHeadline(red), "Last run Tue 20 Oct, 02:40 \u00B7 took 7 min 16 s \u00B7 BRYAN-MAC (macOS x86_64, "
               + "no torch) \u00B7 2 of 3 stages green, 1 red");
  const crashed = {...SUMMARY, machine: null, fetch: null, stages: [], error: "RuntimeError: could not run git"};
  assert.equal(runHeadline(crashed), "Last run Tue 20 Oct, 02:40 \u00B7 took 7 min 16 s \u00B7 no stage built");
});

// Rulings R30 and the run's own error. Catches: a stopped or failed run reported as if it were complete, and a fetch
// that failed passed over in silence.
test("the run's notes: stopped, failed, and a fetch that failed", () => {
  assert.deepEqual(runNotes(SUMMARY), []);
  const [stopped] = runNotes({...SUMMARY, stopped: true});
  assert.equal(stopped[0], "warn"); assert.match(stopped[1], /stopped/);
  const failed = runNotes({...SUMMARY, error: `RuntimeError: ${HOSTILE}`});
  assert.equal(failed[0][0], "error"); assert.ok(failed[0][1].includes(`RuntimeError: ${HOSTILE}`));
  const fetch = runNotes({...SUMMARY, fetch: {requested: true, ok: false,
                                              message: "Could not resolve host: github.com"}});
  assert.equal(fetch[0][0], "warn"); assert.ok(fetch[0][1].includes("Could not resolve host: github.com"));
});

// ---- 1. health ----

test("stage cards: one per stage, arrows between, the colour from the card status", () => {
  const html = stagesHtml([stage("main", "clean", [check("shared", "Shared + Pair A", "pass", "92 passed")]),
                           stage("+ PR #4", "clean", [check("pair_b", "Pair B", "fail", "1 failed, 98 passed",
                                                            "logs/1-pair_b.txt")]),
                           stage("+ PR #6", "skipped")], {runId: RUN});
  assert.equal(html.match(/class="stage /g).length, 3); assert.equal(html.match(/class="arrow"/g).length, 2);
  assert.match(html, /class="stage green"[^]*class="stage red"[^]*class="stage grey"/);
  assert.match(text(html), /Pair B 1 failed, 98 passed/);
});

// Catches: a failing check whose output is more than one click away.
test("stage cards: a failed check links its log", () => {
  const html = stagesHtml([stage("+ PR #4", "clean", [check("pair_b", "Pair B", "fail", "exit code 2",
                                                            "logs/1-pair_b.txt")])], {runId: RUN});
  assert.ok(html.includes(`href="/api/tests/runs/${RUN}/logs/1-pair_b.txt"`));
  assert.match(text(html), /Pair B exit code 2 open its log/);  // said on the failed line itself, not only the label
  const passed = stagesHtml([stage("main", "clean", [check("shared", "Shared + Pair A", "pass", "92 passed",
                                                           "logs/0-shared.txt")])], {runId: RUN});
  assert.ok(passed.includes(`href="/api/tests/runs/${RUN}/logs/0-shared.txt"`));  // every log that was written
  assert.equal(stagesHtml([stage("+ PR #4", "clean", [check("pair_b", "Pair B", "fail", "x", "../../etc/passwd")])],
                          {runId: RUN}).includes("href="), false);
});

test("stage cards: heading, title and commit, a conflict's files, a reason for each grey line", () => {
  const conflict = stage("+ PR #5", "conflict", [], {title: "Label definitions",
                                                     conflicts: ["pair_b/README.md", "fow_shared/contracts.py"]});
  const why = "Pair B's code is not in this stage yet (there is no pair_b folder)";
  const unavailable = stage("main", "clean", [check("imports_b", "Imports, Pair B", "unavailable", why)],
                            {title: "after PR #2", sha: "c522026051c94e5019268426eb414232e2709678"});
  const html = stagesHtml([unavailable, conflict, stage("+ PR #3", "skipped")]);
  const shown = text(html);
  assert.match(shown, /main after PR #2 \u00B7 c522026 /);
  assert.ok(shown.includes("Imports, Pair B Pair B's code is not in this stage yet (there is no pair_b folder)"));
  assert.ok(shown.includes("pair_b/README.md") && shown.includes("fow_shared/contracts.py"));
  assert.match(shown, /\+ PR #3 .*an earlier stage could not be built/);
  assert.match(text(stagesHtml([stage("+ PR #9", "missing-ref", [], {ref: "origin/pair-b/gone"})])),
               /origin\/pair-b\/gone names no commit here/);
  assert.match(text(stagesHtml([stage("+ this checkout", "contained")])), /already in the stages before it/i);
});

// Catches: Pair A's setup command, the reason on two lines of every card where its environment is missing, repeated in
// full on each, which makes every card several times taller; and the command lost.
test("stage cards: a long reason is said in short on its line, and in full once under the cards", () => {
  const why = "Pair A's environment not set up here: from the repository root, run python3 -m venv pair_a_prep/.venv, "
    + "then pair_a_prep/.venv/bin/python -m pip install -r pair_a_prep/requirements.txt";
  const lines = [check("imports_a", "Imports, shared + Pair A", "unavailable", why),
                 check("shared", "Shared + Pair A", "unavailable", why)];
  const html = stagesHtml([stage("main", "clean", lines), stage("+ PR #4", "clean", lines)]);
  const shown = text(html);
  assert.equal(shown.split(why).length - 1, 1);
  assert.equal(shown.split("Shared + Pair A Pair A's environment not set up here").length - 1, 2);
  const short = "Pair B's code is not in this stage yet (there is no pair_b folder)";  // short enough as it is
  assert.equal(text(stagesHtml([stage("main", "clean", [check("pair_b", "Pair B", "unavailable", short)])]))
    .split(short).length - 1, 1);
  const failed = "exit code 1: ModuleNotFoundError: No module named 'pairb.harness_adapter' while the harness started";
  const red = text(stagesHtml([stage("+ PR #3", "clean", [check("harness:belief", "Harness, Belief network", "fail",
                                                                failed, "logs/4-harness-belief.txt")])], {runId: RUN}));
  assert.equal(red.split(failed).length - 1, 1);  // a failure is said in full on its own line, and only there
});

// Ruling R30. Catches: a stopped run's cards drawn as failures, or as complete.
test("stage cards: a stopped run says stopped", () => {
  const html = stagesHtml([stage("main", "clean", [check("shared", "Shared + Pair A", "pass", "92 passed")]),
                           stage("+ PR #4", "clean", [check("pair_b", "Pair B", "fail", "stopped", "logs/1-pair_b.txt"),
                                                      check("shared", "Shared + Pair A", "skipped",
                                                            "not run: the run was stopped")]),
                           stage("+ PR #6", "skipped")], {runId: RUN, stopped: true});
  assert.equal(html.includes('class="stage red'), false);
  assert.equal(html.includes('class="ln fail"'), false); assert.match(html, /class="ln stopped"/);
  assert.match(html, /class="stage grey stopped"[^]*class="stage grey stopped"/);
  assert.match(text(html), /\+ PR #6 .*the run was stopped/);
  // A stop that came after a conflict: the stages after the conflict were skipped for it, not for the stop.
  const both = stagesHtml([stage("+ PR #5", "conflict", [], {conflicts: ["a.py"]}), stage("+ PR #3", "skipped")],
                          {stopped: true});
  assert.match(text(both), /\+ PR #3 .*an earlier stage could not be built/);
  assert.match(both, /<div class="stage grey"[^>]*><div class="hd"><span class="mark">[^<]*<\/span> \+ PR #3/);
});

// Catches: a pytest check whose tests all skipped (it ran to its end and checked nothing) drawn as anything but a grey
// line with pytest's words; in a stopped run, taken for a check the stop kept from starting, which only "not run: the
// run was stopped" is, so that a stage checked through before the stop came would say stopped.
test("stage cards: a check whose tests all skipped is grey with its summary, in a stopped run too", () => {
  const skipped = check("observe_vs_teal", "Our observe = Teal's", "skipped", "1 skipped", "logs/6-observe_vs_teal.txt",
                        {passed: 0, failed: 0, errors: 0, skipped: 1});
  const done = stage("+ PR #3", "clean", [check("pair_b", "Pair B", "pass", "99 passed"), skipped]);
  for (const stopped of [false, true]) {
    const html = stagesHtml([done], {runId: RUN, stopped});
    assert.match(html, /class="ln grey"/); assert.equal(html.includes('class="ln stopped"'), false);
    assert.match(text(html), /Our observe = Teal's 1 skipped/);
    assert.equal(cardStatus(done, {stopped}), "green");
  }
});

test("stage cards: a run in progress ends with what it is doing", () => {
  const html = stagesHtml([stage("main", "clean")], {running: `+ PR #4: ${HOSTILE}`});
  assert.match(html, /class="stage going"/); shownAsText(html, HOSTILE);
});

// Catches: server text put into the page as markup, and a server value (a merge or check status) used as a class name.
test("stage cards: everything the server sent is shown as text", () => {
  const html = stagesHtml([stage(HOSTILE, "conflict", [check("pair_b", HOSTILE, "fail", HOSTILE, "logs/1-x.txt")],
                                 {title: HOSTILE, conflicts: [HOSTILE], sha: HOSTILE, ref: HOSTILE})], {runId: RUN});
  shownAsText(html, HOSTILE);
  for (const status of ["pass", "fail", "unavailable", "skipped"]) {
    shownAsText(stagesHtml([stage("main", "clean", [check("x", HOSTILE, status, HOSTILE, "logs/0-x.txt")])],
                           {runId: RUN}), HOSTILE);
  }
  const odd = stagesHtml([stage("main", HOSTILE, [check("x", "x", HOSTILE, "x")])]);
  for (const [, names] of odd.matchAll(/class="([^"]*)"/g)) assert.match(names, /^[a-z0-9 _-]*$/);
});

// ---- 2. fog rules ----

const BLOCKED = {id: "blocked_pawn_hides_blocker", player: "white", fen: "7k/8/8/8/8/4n3/4P3/K7 w - - 0 1", history: 0,
                 visible: ["a1", "a2", "b1", "b2", "e2"], errors: [],
                 expect: {terminal: false, legal_excludes: ["e2e3", "e2e4"], visible_contains: ["e2"],
                          visible_excludes: ["e3"]}};
const THREEFOLD = {id: "threefold_needs_history", player: "black", fen: "8/8/8/8/8/8/8/K6k b - - 8 5", history: 8,
                   visible: ["g1", "h2"], errors: ["terminal: expected True, got False", HOSTILE],
                   expect: {terminal: true, winner: "draw", legal_count: 0, visible_pieces: {f5: "n", e5: null},
                            hidden_fields: ["halfmove_clock"]}};
const entry = (rules, cases, extra = {}) => ({rules, available: true, reason: null, status: "pass", cases,
                                              log: `logs/6-fixtures-${rules}.txt`, ...extra});

test("fog-rules cards: a board placeholder, a plain title, the expectations and the result", () => {
  const html = fixturesHtml(entry("standin", [BLOCKED, THREEFOLD]), {runId: RUN});
  assert.ok(html.includes('data-case="0"') && html.includes('data-case="1"'));
  const shown = text(html);
  assert.ok(shown.includes("1. A blocked pawn can't see its blocker blocked_pawn_hides_blocker"));
  assert.ok(shown.includes("White's view: 5 squares seen Sees e2 Can't see e3 May not play e2e3 e2e4 Game goes on "
                           + "pass"));
  assert.ok(shown.includes("Black's view, after replaying 8 moves: 2 squares seen"));
  assert.ok(shown.includes("knight shown on f5, e5 shown empty") && shown.includes("0 legal moves"));
  assert.ok(shown.includes("Game over: draw") && shown.includes("fail terminal: expected True, got False;"));
  shownAsText(html, HOSTILE);
});

test("fog-rules cards: an unknown position keeps its id as its title", () => {
  const html = fixturesHtml(entry("teal", [{...BLOCKED, id: `new_${HOSTILE}`}]));
  shownAsText(html, `1. new_${HOSTILE}`);
});

// Ruling R21. Catches: the section dropped (or shown empty) when the check itself failed or the rules are missing.
test("fog-rules cards: the check's own failure and missing rules are shown, with the reason", () => {
  const failed = fixturesHtml({rules: "standin", available: false, status: "fail", cases: [],
                               log: "logs/6-fixtures-standin.txt",
                               reason: `Traceback (most recent call last):\nValueError: ${HOSTILE}`}, {runId: RUN});
  assert.match(failed, /class="fx-error"/); shownAsText(failed, `ValueError: ${HOSTILE}`);
  assert.ok(failed.includes(`href="/api/tests/runs/${RUN}/logs/6-fixtures-standin.txt"`));
  const missing = fixturesHtml({rules: "teal", available: false, status: "unavailable", cases: [], log: null,
                                reason: "Teal's rules adapter (pair_a_prep.rules_adapter) is not in this checkout"});
  assert.ok(text(missing).includes("Teal's rules adapter (pair_a_prep.rules_adapter) is not in this checkout"));
  assert.equal(missing.includes("data-case"), false);
  assert.ok(text(fixturesHtml(undefined)).length > 0);
});

// Ruling R30. A stop that comes while the two fog-rules checks run (they are part of the final sections, which start
// only while the run is not stopping) leaves both entries {available: false, status: "fail", reason: "stopped"}, in a
// saved summary with stopped: true. Catches: those drawn as red failures ("the check itself failed"), against the
// page's own word that what a stop cut short is no failure; and a real failure of the check hidden by the stop.
const STOPPED_FX = rules => ({rules, available: false, status: "fail", reason: "stopped", cases: [],
                              log: `logs/6-fixtures-${rules}.txt`});

test("fog-rules cards: an entry the stop cut off says stopped, not failed; a real failure stays red", () => {
  for (const rules of ["standin", "teal"]) {
    const html = fixturesHtml(STOPPED_FX(rules), {runId: RUN, stopped: true});
    assert.equal(html.includes("fx-error"), false, rules); assert.match(html, /class="note fx-stopped"/);
    assert.match(text(html), /stopped .*run again/i); assert.equal(/failed/.test(text(html)), false);
    assert.ok(html.includes(`href="/api/tests/runs/${RUN}/logs/6-fixtures-${rules}.txt"`));  // what the log says
  }
  const chips = text(rulesChoiceHtml({standin: STOPPED_FX("standin"), teal: STOPPED_FX("teal")}, "standin",
                                     {stopped: true}));
  assert.ok(chips.includes("Our stand-in observe: stopped") && chips.includes("Teal's RulesAdapter: stopped"), chips);
  assert.match(fixturesHtml(STOPPED_FX("standin"), {runId: RUN}), /class="fx-error"/);  // the summary says no stop
  const crashed = {...STOPPED_FX("standin"), reason: "Traceback (most recent call last):\nValueError: bad fixtures"};
  assert.match(fixturesHtml(crashed, {runId: RUN, stopped: true}), /class="fx-error"/);  // a stopped run's real failure
  assert.ok(text(rulesChoiceHtml({standin: crashed}, "standin", {stopped: true})).includes("the check failed"));
});

test("the rules switch: each choice with how its positions went, the chosen one pressed", () => {
  const fixtures = {standin: entry("standin", [BLOCKED, BLOCKED, THREEFOLD], {status: "fail"}),
                    teal: {rules: "teal", available: false, status: "unavailable", reason: "not here", cases: []}};
  const html = rulesChoiceHtml(fixtures, "standin");
  assert.ok(text(html).includes("Our stand-in observe: 2 of 3 pass"));
  assert.ok(text(html).includes("Teal's RulesAdapter: unavailable"));
  assert.match(html, /data-rules="standin" aria-pressed="true"/);
  assert.match(html, /data-rules="teal" aria-pressed="false"/);
});

// ---- 3. scorer checks ----

const POSITIONS = ["kings_white", "kings_black", "king_captured", "fifty_move", "king_capture_available",
                   "castling_escape", "draw_before_capture"];
const ENCODER = "Inspect real encoder and data flow; passing black-box probes does not prove absence of leakage.";
function report(status = "pass", change = {}) {
  const checks = POSITIONS.flatMap(id => [{name: `children/${id}`, status: "pass"},
                                          {name: `board_perspective_and_rules/${id}`, status: "pass"}]);
  checks.push({name: "boards/batch_and_order", status: "pass"},
              {name: "beliefs/grouping_order_unknown_clock_and_policy", status: "pass"},
              {name: "encoder/per_hypothesis_clock_and_no_hidden_state", status: "manual", detail: ENCODER},
              {name: "history/repetition", status: "manual", detail: "FEN-only methods cannot represent repetition."});
  for (const [name, value] of Object.entries(change)) {
    const found = checks.find(item => item.name === name);
    if (found) Object.assign(found, value); else checks.push({name, ...value});
  }
  const counts = {pass: checks.filter(c => c.status === "pass").length, manual: 2,
                  fail: checks.filter(c => c.status === "fail").length};
  return {status, summary: `${counts.pass} pass, 2 manual, ${counts.fail} fail`, counts, checks,
          log: "logs/6-harness-x.txt",
          metadata: {warmups: 2, repeats: 10, tolerance: 1e-6, evaluator: "material-1-3-3-5-9",
                     config: {source_commit: "dedc29def1065242eab9bf5940caef878ffe2d8b"}}};
}
const UNAVAILABLE = {status: "unavailable", summary: "needs torch, which this machine does not have", counts: {},
                     checks: [], metadata: null, log: null};

test("scorer grid: the seven positions, two many-board rows and two by-hand rows, a column pair per scorer", () => {
  const {table} = harnessHtml({material: report(), "stockfish-d1": report()}, {commit: "7c3e2a9a4087", runId: RUN});
  const shown = text(table);
  assert.match(shown, /^Piece values Quick Stockfish Position moves board moves board /);
  for (const label of ["Kings only, White to move", "Every move reaches the fifty-move draw first",
                       "Many boards in one call, answers in order", "Beliefs: grouping, order, unknown clock",
                       "Encoder uses each guess's own clock, leaks nothing",
                       "Threefold repetition with the move history"]) {
    assert.ok(shown.includes(label), label);
  }
  assert.equal(table.match(/<td class="p">/g).length, 7 * 2 * 2);           // the positions: moves and board
  assert.equal(table.match(/<td class="p" colspan="2">/g).length, 2 * 2);    // the many-board calls
  assert.equal(table.match(/<td class="m" colspan="2">/g).length, 2 * 2);    // the by-hand items
  assert.ok(shown.includes(ENCODER));                                         // Bryan's note, in its row
});

// Catches: the scorers out of order or without their labels, and a check the grid does not know about dropped (a new
// failing check in Bryan's harness would then never be seen).
test("scorer grid: scorers in their order, and a check the grid does not know still shown", () => {
  const changed = {"children/fifty_move": {status: "fail", detail: `AssertionError: ${HOSTILE}`},
                   "children/new_position": {status: "fail", detail: "x"}, "speed/one_call": {status: "pass"}};
  const harness = {belief: report("fail", changed), material: report()};
  const {table, note} = harnessHtml(harness, {commit: "7c3e2a9", runId: RUN});
  assert.match(text(table), /^Piece values .*Belief network/);
  assert.ok(table.includes('<td class="f" title="AssertionError: &lt;img'));
  assert.ok(text(table).includes("new_position") && text(table).includes("speed/one_call"));
  shownAsText(note, `Belief network, children/fifty_move: AssertionError: ${HOSTILE}`);  // a failure's detail, in words
});

// Ruling R28 and the grey rule. Catches: the harness report's own source_commit (a throwaway merge commit) shown, and a
// scorer that could not run here drawn as passing or failing.
test("scorer grid: the stage's commit, the run settings, and an unavailable scorer grey with its reason", () => {
  const {table, note} = harnessHtml({material: report(), belief: UNAVAILABLE},
                                    {commit: "7c3e2a9a40879a9b", runId: RUN});
  const shown = text(note);
  assert.ok(shown.includes("commit 7c3e2a9") && !shown.includes("dedc29d"));
  assert.ok(shown.includes("2 warm-ups, 10 repeats, tolerance 1e-6"));
  assert.ok(shown.includes("Piece values 16 of 16"));
  assert.ok(shown.includes("Belief network: unavailable here: needs torch, which this machine does not have"));
  assert.match(table, /<th colspan="2" class="sc grey"[^>]*>Belief network/);
  assert.equal(table.match(/<td class="n"/g).length, 7 * 2 + 4);  // every cell of that scorer, none passing
  const why = /<td class="n"( colspan="2")? title="needs torch, which this machine does not have">/g;
  assert.equal(table.match(why).length, 7 * 2 + 4);  // and each says why
});

test("scorer grid: a harness that failed without a report links its log", () => {
  const crashed = {status: "fail", summary: "exit code 1: ModuleNotFoundError: No module named 'torch'", counts: {},
                   checks: [], metadata: null, log: "logs/6-harness-network1.txt"};
  const {note} = harnessHtml({material: report(), network1: crashed}, {commit: "7c3e2a9", runId: RUN});
  assert.ok(text(note).includes("Network 1: exit code 1: ModuleNotFoundError: No module named 'torch'"));
  assert.ok(note.includes(`href="/api/tests/runs/${RUN}/logs/6-harness-network1.txt"`));
});

test("scorer grid: no harness in the stage says so", () => {
  const {table, note} = harnessHtml({}, {commit: "c522026", label: "+ PR #4"});
  assert.equal(table, ""); assert.match(text(note), /Bryan's harness .*\+ PR #4/);
});

// ---- 4. accuracy ----

const NET1 = {title: "Network 1, on fresh games", source: "net1-v2/eval-d2-check-train.json", data: "d2-check",
              split: "train", created: "2026-10-18T22:40:18+08:00",
              sizes: {games: 959, positions: 94963, decisions: 3818},
              columns: [{key: "mae", label: "Value error", unit: null},
                        {key: "choice.top1", label: "Picks careful SF's move", unit: "%"},
                        {key: "choice.regret", label: "Value lost by its pick", unit: null}],
              rows: [{key: "material", label: "Piece values", highlight: false,
                      values: [0.33551, 27.7108, 0.210837]},
                     {key: "baseline", label: "Quick Stockfish", highlight: false,
                      values: [0.094885, 42.8759, 0.035481]},
                     {key: "network", label: "Network 1", highlight: true, values: [0.075671, 42.4306, 0.035205]}]};
const PER_MOVE = {title: "Per-move values, as a search uses them", source: "belief-v1-d1/eval-children-d16.json",
                  target_depth: 16, sizes: {games: 95, positions: 100, moves: 2849},
                  columns: [{key: "*_children", label: "All moves in one call", unit: null}],
                  rows: [{key: "belief", label: "Belief network", highlight: true, values: [0.07039510408617017]}]};

// Catches: values rounded until two rows look equal (the regret column needs four places), percentages shown as
// fractions, and the table's own row not marked.
test("accuracy cards: titles, provenance, and values to the places that tell the rows apart", () => {
  const html = accuracyHtml({tables: [NET1, PER_MOVE], differences: [], missing: [], why_missing: {}});
  const shown = text(html);
  assert.ok(shown.includes("Network 1, on fresh games"));
  assert.ok(shown.includes("959 games, 94,963 positions, 3,818 decisions"));
  assert.ok(shown.includes("d2-check") && shown.includes("net1-v2/eval-d2-check-train.json"));
  assert.ok(shown.includes("Piece values 0.336 28% 0.2108") && shown.includes("Quick Stockfish 0.095 43% 0.0355"));
  assert.ok(shown.includes("Network 1 0.076 42% 0.0352"));
  assert.match(html, /<tr class="kept"><td>Network 1</);
  assert.ok(shown.includes("against depth-16 Stockfish") && shown.includes("Belief network 0.070"));
});

// Ruling R24. Catches: every missing file called "not found" when the file is there but lacks a number.
test("accuracy cards: each file that gave no table, with why", () => {
  const why = "no 'mae.belief_children' in the file";
  const html = accuracyHtml({tables: [NET1], differences: [], missing: ["belief-v1-d1/eval-children-d16.json"],
                             why_missing: {"belief-v1-d1/eval-children-d16.json": why}});
  assert.ok(text(html).includes(`belief-v1-d1/eval-children-d16.json ${why}`));
  assert.equal(text(html).includes("not found"), false);
  shownAsText(accuracyHtml({tables: [{...NET1, title: HOSTILE}], differences: [], missing: [HOSTILE],
                            why_missing: {[HOSTILE]: HOSTILE}}), HOSTILE);
});

const DIFFERENCES = [
  {key: "regret_difference", label: "Network 1 vs quick Stockfish: value lost by its move pick",
   mean: -0.00027609850327431134, ci95: [-0.001664771359269205, 0.0010548869247829823], verdict: "tie"},
  {key: "root_mae_difference", label: "Belief network vs quick Stockfish: position error",
   mean: -0.008188591009107318, ci95: [-0.009357117053786671, -0.006999568198660082], verdict: "better"}];

test("interval chart: the mean and interval as numbers, and the verdict in words", () => {
  const shown = text(forestHtml(DIFFERENCES));
  assert.ok(shown.includes("Network 1 vs quick Stockfish: value lost by its move pick "
                           + "\u22120.0003 (\u22120.0017 to +0.0011) A tie"));
  assert.ok(shown.includes("\u22120.0082 (\u22120.0094 to \u22120.0070) Better"));
  assert.match(text(forestHtml([{label: "x", mean: 0.002, ci95: [0.001, 0.003]}])), /Worse/);  // no verdict: from ci95
});

// Catches: an interval wider than the default axis drawn off the track, or squashed against its edge.
test("interval chart: a wide interval still fits on the track", () => {
  const html = forestHtml([{label: "wide", mean: -0.04, ci95: [-0.05, -0.03], verdict: "better"}]);
  const [, left, width] = html.match(/class="ci" style="left:([\d.]+)%;width:([\d.]+)%"/).map(Number);
  const [, point] = html.match(/class="pt" style="left:([\d.]+)%"/).map(Number);
  assert.ok(left > 0 && left + width <= 100 && point > left && point < left + width, html);
  shownAsText(forestHtml([{label: HOSTILE, mean: 0, ci95: [-0.001, 0.001], verdict: HOSTILE}]), HOSTILE);
});
