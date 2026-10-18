/** 挑战客户端测试：失败重试冻结负载、旧响应隔离与顺序解锁。 */
import test from "node:test";
import assert from "node:assert/strict";
import { ChallengeClient, rankingRequest } from "../src/ranking-client.js";

/** 返回符合接口约定的三关测试状态。 */
function state() { return { run_id: "run", revision: 0, levels: [0, 1, 2].map((i) => ({ attempt_id: `a${i}`, seconds: null })), total_recorded: false }; }

test("通关失败后的重试复用冻结负载并只解锁下一关", async () => {
  const calls = [];
  let fail = true;
  const current = state();
  const client = new ChallengeClient(async (path, options) => {
    calls.push(structuredClone(options.body));
    if (path.endsWith("start")) return structuredClone(current);
    if (fail) { fail = false; throw new Error("offline"); }
    current.levels[0].seconds = options.body.duration_seconds;
    return structuredClone(current);
  }, () => "id");
  await client.start();
  assert.equal(client.canEnter(1), false);
  await assert.rejects(client.complete(0, 9, true));
  await client.complete(0, 99, false);
  assert.deepEqual(calls[1], calls[2]);
  assert.equal(client.state.levels[0].seconds, 9);
  assert.equal(client.canEnter(1), true);
  assert.equal(client.canEnter(2), false);
});

test("离开后的旧请求不能覆盖新轮次", async () => {
  let finish;
  const client = new ChallengeClient(() => new Promise((resolve) => { finish = resolve; }), () => "id");
  const old = client.start();
  client.reset();
  finish(state());
  await assert.rejects(old, /已离开/);
  assert.equal(client.state, null);
});

test("网络错误与无效响应不能被视为保存成功", async (t) => {
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () => { throw new TypeError("network"); };
  await assert.rejects(rankingRequest("rankings/total"), /连接失败/);
  globalThis.fetch = async () => ({ ok: true, json: async () => null });
  await assert.rejects(rankingRequest("rankings/total"), /返回异常/);
});
