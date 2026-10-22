/** 独立关卡计时测试：确认开始、通关冻结、单关重开与直接进入数独。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createSession, restartLevel, startLevel, completeLevel, formatTime } from "../../src/legacy/game/session.js";

test("首次确认开始计时，重复确认不重置，通关后用时冻结", () => {
  const session = createSession();
  startLevel(session, 0, 1000);
  startLevel(session, 0, 9000);
  completeLevel(session, 0, 12500);
  completeLevel(session, 0, 50000);
  assert.equal(session.levels[0].seconds, 11);
});

test("重开当前关不会清除其他关卡成绩", () => {
  const session = createSession();
  for (let index = 0; index < 3; index += 1) {
    startLevel(session, index, 10000 * index);
    completeLevel(session, index, 10000 * index + (index + 1) * 1000);
  }
  assert.deepEqual(session.levels.map(level => level.seconds), [1, 2, 3]);
  restartLevel(session, 1);
  assert.deepEqual(session.levels.map(level => level.seconds), [1, null, 3]);
});

test("直接玩数独不会启动其他关卡计时或伪造通关成绩", () => {
  const session = createSession();
  startLevel(session, 2, 0);
  completeLevel(session, 2, 120000);
  assert.deepEqual(session.levels, [{ startedAt: null, seconds: null },
    { startedAt: null, seconds: null }, { startedAt: 0, seconds: 120 }]);
});

test("时长格式覆盖零秒、分钟与小时", () => {
  assert.equal(formatTime(0), "00:00");
  assert.equal(formatTime(125), "02:05");
  assert.equal(formatTime(3661), "1:01:01");
});
