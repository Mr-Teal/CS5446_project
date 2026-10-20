import test from "node:test";
import assert from "node:assert/strict";
import {HUMAN_MOVE_PAUSE_MS, showMoveReply} from "../../src/pairb/lab/static/playback.js";

test("the human's actual observation is displayed before the reply and held for a second", async () => {
  const human = {ply: 1, you: {visible_squares: ["e4"]}};
  const bot = {ply: 2, you: {visible_squares: ["e4", "d5"]}};
  const frames = [];
  let release;
  const done = showMoveReply({after_human: human, state: bot}, state => frames.push(state), ms => {
    assert.equal(ms, 1000);
    assert.equal(ms, HUMAN_MOVE_PAUSE_MS);
    return new Promise(resolve => { release = resolve; });
  });
  assert.deepEqual(frames, [human]);
  release();
  await done;
  assert.deepEqual(frames, [human, bot]);
});

test("a human move that ends or stops the game has no extra delay", async () => {
  for (const state of [{ply: 1, over: true}, {ply: 1, error: "bot stopped"}]) {
    const frames = [];
    await showMoveReply({after_human: {ply: 1}, state}, s => frames.push(s), () => {
      assert.fail("there is no bot reply to delay");
    });
    assert.deepEqual(frames, [state]);
  }
});
