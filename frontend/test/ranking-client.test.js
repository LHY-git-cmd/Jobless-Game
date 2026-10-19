/** 挑战客户端测试：失败重试冻结负载、旧响应隔离与顺序解锁。 */
import test from "node:test";
import assert from "node:assert/strict";
import { ChallengeClient, createRequestId, rankingRequest } from "../src/ranking-client.js";

/** 返回符合接口约定的三关测试状态。 */
function state() { return { run_id: "run", revision: 0, levels: [0, 1, 2].map((i) => ({ attempt_id: `a${i}`, seconds: null })), total_recorded: false }; }

test("安全上下文仍可使用原生 UUID 且保留 Crypto 方法接收者", () => {
  const cryptoApi = {
    randomUUID() {
      assert.equal(this, cryptoApi);
      return "823996ac-a872-492d-a938-6981cd31a060";
    },
  };
  assert.equal(createRequestId(cryptoApi), "823996ac-a872-492d-a938-6981cd31a060");
});

test("无安全随机数接口时给出可读错误而不退回普通随机数", () => {
  assert.throws(() => createRequestId({}), /更新浏览器/);
  assert.throws(() => createRequestId(null), /更新浏览器/);
});

test("HTTP 环境没有 randomUUID 时默认客户端可创建、重开并复用失败请求编号", async (t) => {
  // 模拟公网 HTTP 的 Web Crypto：保留安全随机数，移除仅安全上下文可用的 randomUUID。
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  const getRandomValues = globalThis.crypto.getRandomValues.bind(globalThis.crypto);
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: { getRandomValues } });
  t.after(() => Object.defineProperty(globalThis, "crypto", descriptor));
  const calls = [];
  const failures = new Set();
  const client = new ChallengeClient(async (path, options) => {
    calls.push({ path, id: options.body.request_id });
    if (!failures.has(path)) {
      failures.add(path);
      throw new Error("offline");
    }
    return state();
  });
  await assert.rejects(client.start(), /offline/);
  await client.start();
  await assert.rejects(client.restart(0), /offline/);
  await client.restart(0);
  const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  assert.match(calls[0].id, uuidV4);
  assert.match(calls[2].id, uuidV4);
  assert.equal(calls[0].id, calls[1].id);
  assert.equal(calls[2].id, calls[3].id);
  assert.notEqual(calls[0].id, calls[2].id);
});

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

test("刷新恢复只读取原轮次，待提交成绩保留原始幂等负载", async () => {
  const original = new ChallengeClient(async () => state(), () => "start-id");
  await original.start();
  original.request = async () => { throw new Error("offline"); };
  await assert.rejects(original.complete(0, 12, true));
  const snapshot = JSON.parse(JSON.stringify(original.snapshot()));
  const calls = [];
  const resumed = new ChallengeClient(async (path, options) => {
    calls.push({ path, options });
    const result = state();
    if (options) result.levels[0].seconds = options.body.duration_seconds;
    return result;
  });
  resumed.restore(snapshot);
  await resumed.resume();
  assert.deepEqual(calls[0], { path: "challenges/run", options: undefined });
  await resumed.complete(0, 999, false);
  assert.deepEqual(calls[1].options.body, snapshot.pending[0][1]);
  assert.equal(resumed.state.levels[0].seconds, 12);
});

test("网络错误与无效响应不能被视为保存成功", async (t) => {
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () => { throw new TypeError("network"); };
  await assert.rejects(rankingRequest("rankings/total"), /连接失败/);
  globalThis.fetch = async () => ({ ok: true, json: async () => null });
  await assert.rejects(rankingRequest("rankings/total"), /返回异常/);
});
