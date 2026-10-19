/** 存档回归：三关数据、绝对计时、账号隔离与存储异常。 */
import test from "node:test";
import assert from "node:assert/strict";
import { loadProgress, saveProgress, clearProgress } from "../src/progress.js";
import { createAkari } from "../src/akari.js";
import { createGame } from "../src/game.js";
import { createSession, startLevel, levelSeconds } from "../src/session.js";

test("照明灯泡和原始计时起点往返保存，离线时间仍累计", () => {
  const values = new Map();
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
  const session = createSession(), akari = createAkari();
  startLevel(session, 1, 1000); akari.bulbs.add(0);
  assert.equal(saveProgress(storage, 1, { currentIndex: 1, session, akari, dialogs: [],
    challenge: { startId: "start", state: { run_id: "run", levels: [{}, {}, {}] }, pending: [] } }), true);
  const restored = loadProgress(storage, 1);
  assert.deepEqual(restored.akari.bulbs, new Set([0]));
  assert.equal(levelSeconds(restored.session, 1, 91000), 90);
  assert.equal(loadProgress(storage, 2), null);
  clearProgress(storage, 1);
  assert.equal(loadProgress(storage, 1), null);
});

test("存档损坏、版本不匹配、存储禁用或写满时不抛异常", () => {
  for (const raw of ["{", "null", '{"version":99}', '{"version":1,"userId":1}']) {
    assert.equal(loadProgress({ getItem: () => raw }, 1), null);
  }
  const denied = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("full"); }, removeItem() { throw new Error("denied"); } };
  assert.equal(loadProgress(denied, 1), null);
  assert.equal(saveProgress(denied, 1, {}), false);
  assert.doesNotThrow(() => clearProgress(denied, 1));
});

test("查看前关时存档仍保留后关灯泡；旧存档缺少前关棋盘时可查看已保存结果", () => {
  let raw;
  const storage = { getItem: () => raw, setItem: (_key, value) => { raw = value; } };
  const session = createSession(), akari = createAkari();
  session.levels[0].seconds = 12;
  akari.bulbs.add(0);
  const value = { currentIndex: 0, game: createGame(), akari, session, dialogs: [],
    challenge: { startId: "start", state: { run_id: "run", levels: [{ seconds: 12 }, { seconds: null }, { seconds: null }] }, pending: [] } };
  saveProgress(storage, 1, value);
  assert.deepEqual(loadProgress(storage, 1).akari.bulbs, new Set([0]));
  value.game = null;
  saveProgress(storage, 1, value);
  assert.equal(loadProgress(storage, 1).session.levels[0].seconds, 12);
  value.akari = { bulbs: [100], complete: false };
  saveProgress(storage, 1, value);
  assert.equal(loadProgress(storage, 1), null);
});
