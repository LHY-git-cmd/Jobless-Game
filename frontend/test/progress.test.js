/** 存档回归：三关数据、绝对计时、账号隔离与存储异常。 */
import test from "node:test";
import assert from "node:assert/strict";
import { loadProgress, saveProgress, clearProgress } from "../src/progress.js";
import { createAkari } from "../src/akari.js";
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
