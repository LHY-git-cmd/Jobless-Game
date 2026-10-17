/** 挑战计时测试：首次操作计时、通关冻结、重开、跳关和合计一致性。 */
import test from "node:test";
import assert from "node:assert/strict";
import { createSession, restartLevel, startLevel, completeLevel, sessionSummary, formatTime } from "../src/session.js";

test("首次操作开始计时，通关后查看结果和结算不再增加用时", () => {
  const session = createSession();
  startLevel(session, 0, 1000);
  startLevel(session, 0, 9000);
  completeLevel(session, 0, 12500);
  completeLevel(session, 0, 50000);
  assert.equal(session.levels[0].seconds, 11);
});

test("三关用时按序汇总，重开当前关不会清除前序关卡成绩", () => {
  const session = createSession();
  for (let index = 0; index < 3; index += 1) {
    startLevel(session, index, 10000 * index);
    completeLevel(session, index, 10000 * index + (index + 1) * 1000);
  }
  assert.deepEqual(sessionSummary(session), { times: [1, 2, 3], total: 6, complete: true });
  restartLevel(session, 1);
  assert.deepEqual(sessionSummary(session), { times: [1, null, null], total: 1, complete: false });
});

test("跳关不会伪造前序关卡零秒成绩，完整通关才能算全程成绩", () => {
  const session = createSession();
  startLevel(session, 2, 0);
  completeLevel(session, 2, 120000);
  assert.deepEqual(sessionSummary(session), { times: [null, null, 120], total: 120, complete: false });
});

test("时长格式覆盖零秒、分钟与小时", () => {
  assert.equal(formatTime(0), "00:00");
  assert.equal(formatTime(125), "02:05");
  assert.equal(formatTime(3661), "1:01:01");
});
