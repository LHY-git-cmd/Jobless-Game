/** 个人记录窗口：验证登录隔离、分类切换、失败重试和过期响应，避免泄露旧账号成绩。 */
import test from "node:test";
import assert from "node:assert/strict";
import { initPersonalRecords } from "../src/personal-records.js";

/** 提供本组件所用的最小 DOM，不替换记录加载和渲染逻辑。 */
class Element {
  /** 初始化可观察的文字、子节点、事件和样式。 */
  constructor() {
    this.textContent = ""; this.children = []; this.attributes = {}; this.listeners = {};
    const classes = new Set();
    this.classList = { add: (...v) => v.forEach(x => classes.add(x)), remove: (...v) => v.forEach(x => classes.delete(x)),
      contains: v => classes.has(v), toggle: (v, enabled) => enabled ? classes.add(v) : classes.delete(v) };
  }
  /** 保存可访问属性。 */
  setAttribute(name, value) { this.attributes[name] = value; }
  /** 按事件类型保存回调。 */
  addEventListener(name, listener) { this.listeners[name] = listener; }
  /** 替换私人成绩，清空时不能保留旧节点。 */
  replaceChildren(...children) { this.children = children; }
  /** 追加日期、标签和用时。 */
  append(...children) { this.children.push(...children); }
  /** 记录键盘焦点。 */
  focus() { this.focused = true; }
}

/** 每个测试创建独立窗口和注入的接口。 */
function setup(request) {
  const ids = ["personal-records", "records-panel", "records-status", "records-login", "records-refresh", "records-retry",
    "records-best", "records-best-label", "records-best-time", "records-best-date", "records-breakdown", "records-recent", "records-list",
    "records-total", "records-mine", "records-akari", "records-sudoku"];
  const nodes = Object.fromEntries(ids.map(id => [id, new Element()]));
  const events = {};
  const dom = { getElementById: id => nodes[id], createElement: () => new Element(), addEventListener: (name, callback) => { events[name] = callback; } };
  const panel = initPersonalRecords({ dom, request, onLogin: async callback => callback({ id: 7 }) });
  return { nodes, panel, events };
}

/** 生成包含最佳与最近一次重合的真实形状响应。 */
function result(category = "total", seconds = 75) {
  const record = { id: 10, duration_seconds: seconds, completed_at: "2026-10-18T10:20:00", times: category === "total" ? [15, 20, 40] : null };
  return { category, best: record, recent: [record] };
}

test("登录后加载个人记录，切换类别后展示对应最佳和最近三次", async () => {
  const calls = [];
  const { nodes, panel } = setup(async path => { calls.push(path); return result(path.split("=")[1]); });
  assert.equal(calls.length, 0);
  assert.match(nodes["records-status"].textContent, /登录/);
  await panel.setUser({ id: 7 });
  assert.deepEqual(calls, ["records/me?category=total"]);
  assert.equal(nodes["records-best-time"].textContent, "01:15");
  assert.match(nodes["records-breakdown"].textContent, /扫雷 00:15/);
  assert.equal(nodes["records-list"].children.length, 1);
  await nodes["records-mine"].listeners.click();
  assert.equal(calls.at(-1), "records/me?category=mine");
  assert.equal(nodes["records-mine"].attributes["aria-selected"], "true");
  assert.equal(nodes["records-breakdown"].classList.contains("hidden"), true);
});

test("空记录不显示虚构零秒，真实零秒成绩正常显示", async () => {
  let empty = true;
  const { nodes, panel } = setup(async () => empty ? { category: "total", best: null, recent: [] } : result("total", 0));
  await panel.setUser({ id: 7 });
  assert.equal(nodes["records-best"].classList.contains("hidden"), true);
  assert.match(nodes["records-status"].textContent, /还没有/);
  empty = false;
  await panel.refresh();
  assert.equal(nodes["records-best-time"].textContent, "00:00");
});

test("退出登录立即清空，旧账号晚到的响应不能恢复记录", async () => {
  let finish;
  const { nodes, panel } = setup(() => new Promise(resolve => { finish = resolve; }));
  const pending = panel.setUser({ id: 7 });
  await panel.setUser(null);
  finish(result()); await pending;
  assert.equal(nodes["records-best-time"].textContent, "");
  assert.equal(nodes["records-list"].children.length, 0);
  assert.match(nodes["records-status"].textContent, /登录/);
});

test("快速切换分类时丢弃上一分类响应", async () => {
  const waiting = [];
  const { nodes, panel } = setup(() => new Promise(resolve => waiting.push(resolve)));
  const total = panel.setUser({ id: 7 });
  const mine = nodes["records-mine"].listeners.click();
  waiting[1](result("mine", 20)); await mine;
  waiting[0](result("total", 99)); await total;
  assert.equal(nodes["records-best-time"].textContent, "00:20");
});

test("加载失败允许重试，过期会话清空旧成绩并提供重新登录", async () => {
  let fail = true, expired = false;
  const { nodes, panel } = setup(async () => {
    if (fail) throw new Error("连接失败");
    if (expired) { const error = new Error("请先登录"); error.status = 401; throw error; }
    return result();
  });
  await panel.setUser({ id: 7 });
  assert.equal(nodes["records-retry"].classList.contains("hidden"), false);
  fail = false; await nodes["records-retry"].listeners.click();
  assert.equal(nodes["records-best-time"].textContent, "01:15");
  expired = true; await panel.refresh();
  assert.equal(nodes["records-best-time"].textContent, "");
  assert.equal(nodes["records-login"].classList.contains("hidden"), false);
});

test("方向键可切换分类，保存通知触发刷新", async () => {
  const calls = [];
  const { nodes, panel, events } = setup(async path => { calls.push(path); return result(path.split("=")[1]); });
  await panel.setUser({ id: 7 });
  await nodes["records-total"].listeners.keydown({ key: "ArrowRight", preventDefault() {} });
  assert.equal(nodes["records-mine"].focused, true);
  assert.equal(nodes["records-panel"].attributes["aria-labelledby"], "records-mine");
  await events["records-updated"]();
  assert.equal(calls.length, 3);
});
