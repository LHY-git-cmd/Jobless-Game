/** 真实页面流程回归：DOM 与接口用替身，计时、游戏规则、通关和保存逻辑使用真实模块。 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { SUDOKU_PUZZLE, SUDOKU_SOLUTION } from "../src/sudoku.js";
import { createGameController } from "../src/game/game-controller.js";
/** 页面所需的最小 DOM，disabled 控件不会触发点击。 */
class Element {
  /** 初始化类名、子节点与事件。 */
  constructor() {
    const c = new Set();
    this.classList = { add: (...v) => v.forEach(x => c.add(x)), remove: (...v) => v.forEach(x => c.delete(x)), contains: x => c.has(x) };
    this.children = []; this.dataset = {}; this.listeners = {}; this.attributes = {}; this.textContent = "";
  }
  /** 设置棋盘样式。 */
  set className(v) { this.classList.add(...v.split(/\s+/)); }
  /** 保存属性。 */
  setAttribute(k, v) { this.attributes[k] = v; }
  /** 添加棋盘节点。 */
  append(v) { this.children.push(v); }
  /** 重新绘制棋盘。 */
  replaceChildren(v) { this.children = [...v.children]; }
  /** 保存事件回调。 */
  addEventListener(k, v) { this.listeners[k] = v; }
  /** 实例卸载只移除自己的处理器，保留其他组件监听。 */
  removeEventListener(k, v) { if (this.listeners[k] === v) delete this.listeners[k]; }
  /** 返回键盘按钮。 */
  querySelectorAll() { return this.children; }
  /** 找到可聚焦按钮。 */
  querySelector() { return this.children.find(x => !x.disabled); }
  /** 当前目标是棋盘按钮。 */
  closest() { return this; }
  /** 记录聚焦。 */
  focus() { this.focused = true; }
  /** 不模拟布局滚动。 */
  scrollTo() {}
  /** 记录首页选择入口的滚动目标，不触发创建挑战。 */
  scrollIntoView() { this.scrolled = true; }
  /** 触发真实页面事件并返回异步结果。 */
  click(target = this) { if (!this.disabled) return this.listeners.click?.({ target }); }
}
/** 等待非阻塞保存及动态模块导入。 */
async function settle() { for (let i=0;i<5;i++) await new Promise(resolve => setImmediate(resolve)); }

test("独立关卡、冻结计时、保存重试与当前关开发验收", async (t) => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
  const nodes = new Map();
  /** 重建页面节点，模拟刷新时旧 DOM 与页面内存全部丢失。 */
  function resetNodes() {
    nodes.clear();
    for (const m of html.matchAll(/<[\w-]+\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const el = new Element(); const cls = m[1].match(/\bclass="([^"]+)"/)?.[1];
    if (cls) el.className = cls;
    if (/\bdisabled\b/.test(m[1])) el.disabled = true;
    nodes.set(m[2], el);
    }
  }
  resetNodes();
  const $ = id => nodes.get(id), keys = {}, original = { document: globalThis.document, window: globalThis.window, fetch: globalThis.fetch, random: Math.random, now: Date.now };
  let now = 100000, current, fail = false, failRestart = false, failResume = false, failStart = false;
  const startRequests = [];
  const submissions = [];
  Date.now = () => now; Math.random = () => 0;
  globalThis.document = { getElementById: $, createElement: () => new Element(), createDocumentFragment: () => new Element(), addEventListener: (k,v) => { keys[k]=v; },
    removeEventListener: (k,v) => { if(keys[k]===v) delete keys[k]; }, dispatchEvent: event => keys[event.type]?.(event) };
  const stored = new Map(), pageEvents = {}, intervals = new Set();
  let timerId = 0;
  globalThis.window = { scrollTo() {}, setInterval: callback => { pageEvents.tick = callback; intervals.add(++timerId); return timerId; },
    clearInterval: id => { intervals.delete(id); delete pageEvents.tick; }, location: { assign() {} },
    addEventListener: (key, callback) => { pageEvents[key] = callback; },
    removeEventListener: (key, callback) => { if(pageEvents[key]===callback) delete pageEvents[key]; },
    localStorage: { getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, value), removeItem: key => stored.delete(key) } };
  globalThis.fetch = async (path, options={}) => {
    const b = options.body ? JSON.parse(options.body) : null;
    if (path.endsWith("config")) return { ok: true, json: async () => ({ quick_complete_enabled: true }) };
    if ((!options.method || options.method === "GET") && path.startsWith("/api/challenges/")) {
      if (failResume) { failResume = false; throw new TypeError("offline"); }
      if (!path.endsWith(current?.run_id)) return { ok: false, status: 409, json: async () => ({ detail: "本轮已失效" }) };
    }
    if (path.endsWith("/start")) {
      startRequests.push(b.request_id);
      if (failStart) { failStart = false; throw new TypeError("offline"); }
      current = { run_id: crypto.randomUUID(), revision: 0, levels: [0,1,2].map(() => ({ attempt_id: crypto.randomUUID(), seconds: null })), total_recorded: false };
    }
    if (path.endsWith("complete")) {
      submissions.push(b);
      if (fail) { fail=false; throw new TypeError("offline"); }
      current.levels[["mine","akari","sudoku"].indexOf(b.category)].seconds=b.duration_seconds;
      current.total_recorded=false;
    }
    if (path.endsWith("restart")) {
      if (failRestart) { failRestart=false; throw new TypeError("offline"); }
      const i=["mine","akari","sudoku"].indexOf(b.category);
      current.revision++; current.levels[i]={attempt_id:crypto.randomUUID(),seconds:null};
    }
    return { ok: true, json: async () => structuredClone(current) };
  };
  t.after(() => { Date.now=original.now; Math.random=original.random; for (const k of ["document","window","fetch"]) { if(original[k]===undefined) delete globalThis[k]; else globalThis[k]=original[k]; } });
  let app = createGameController(); await settle();
  t.after(() => app.destroy());
  keys["auth-changed"]({ detail: { user: { id: 1 } } }); await settle();
  const visible=id=>!$(id).classList.contains("hidden"), enter=id=>$(id).listeners["authorized-start"]();
  /** 三关统一验证：点击开始后无操作也计时，重看规则和刷新都不重置起点。 */
  async function verifyRules(index) {
    const [opener, dialog, closer, timer] = [
      ["mine-rules", "rules-dialog", "rules-close", "timer"],
      ["akari-rules", "akari-rules-dialog", "akari-rules-close", "akari-timer"],
      ["sudoku-rules", "sudoku-rules-dialog", "sudoku-rules-close", "sudoku-timer"],
    ][index];
    assert.equal($(closer).textContent, "开始游戏");
    now += 7000; pageEvents.tick();
    assert.equal($(timer).textContent, "00:00");
    $(closer).click();
    now += 5000; pageEvents.tick();
    assert.equal($(timer).textContent, "00:05");
    $(opener).click();
    assert.equal(visible(dialog), true);
    assert.equal($(closer).textContent, "继续游戏");
    now += 5000; pageEvents.tick();
    assert.equal($(timer).textContent, "00:10");
    await reload(5000);
    assert.equal(visible(dialog), true);
    assert.equal($(timer).textContent, "00:15");
    keys.keydown({ key: "Escape" });
    assert.equal(visible(dialog), false);
    $(opener).click(); $(closer).click(); pageEvents.tick();
    assert.equal($(timer).textContent, "00:15");
  }
  /** 不触发退出事件直接丢弃页面，验证保存不依赖 beforeunload/pagehide。 */
  async function reload(away = 0, userId = 1) {
    // 清理旧页面动画定时器，但丢弃清理操作写入的数据，只保留刷新前已落盘的存档。
    const committed = [...stored];
    app.destroy();
    assert.equal(intervals.size, 0);
    assert.equal(Object.keys(keys).length, 0);
    assert.equal(Object.keys(pageEvents).length, 0);
    for (const node of nodes.values()) assert.equal(Object.keys(node.listeners).length, 0);
    stored.clear();
    for (const [key, value] of committed) stored.set(key, value);
    now += away;
    resetNodes();
    app = createGameController();
    assert.equal(intervals.size, 1);
    keys["auth-changed"]({ detail: { user: { id: userId } } });
    await settle();
  }
  await t.test("首页直接进入照明和数独，首次读规则不计时", async () => {
    assert.equal($("challenge-action-label").textContent, "选择你的挑战");
    $("challenge-action").click();
    assert.equal($("level-select").scrolled, true);
    assert.equal(startRequests.length, 0);
    assert.equal($("akari-entry").disabled,false); assert.equal($("sudoku-entry").disabled,false);
    await enter("sudoku-entry"); assert.equal(visible("sudoku-rules-dialog"), true);
    $("sudoku-back").click();
    await enter("akari-entry"); assert.equal(visible("akari-rules-dialog"), true);
    assert.equal(visible("sudoku-rules-dialog"), false);
    $("akari-back").click();
    await enter("start-button"); enter("sudoku-entry"); assert.equal(visible("sudoku-screen"),false);
    assert.equal(visible("akari-rules-dialog"), false);
    await reload(15000);
    assert.equal(visible("rules-dialog"), true);
    assert.equal($("timer").textContent, "00:00");
    $("board").click($("board").children[0]); $("flag-button").click();
    assert.equal($("mines-left").textContent, "10");
    keys.keydown({ key: "Escape", preventDefault() {} });
    assert.equal(visible("rules-dialog"), true);
    await verifyRules(0);
  });
  await t.test("扫雷保存失败重试负载相同，用时冻结65秒", async () => {
    $("board").click($("board").children[0]); $("flag-button").click();
    const before = $("board").children.map(cell => cell.attributes["aria-label"]);
    await reload(15000);
    assert.equal(visible("game-screen"), true, $("challenge-message").textContent);
    assert.deepEqual($("board").children.map(cell => cell.attributes["aria-label"]), before);
    assert.equal($("timer").textContent, "00:30");
    $("back-button").click(); now += 20000; await enter("start-button");
    assert.equal($("timer").textContent, "00:50");
    now+=15000; fail=true;
    $("board").click($("board").children[99]); $("reveal-button").click(); await settle();
    assert.equal($("timer").textContent,"01:05"); assert.equal($("result-primary").disabled,true);
    $("result-primary").click(); assert.equal(visible("akari-screen"),false);
    await reload(60000); assert.equal($("timer").textContent,"01:05");
    assert.deepEqual(submissions[0],submissions[1]);
    const board=$("board").children; $("result-secondary").click(); assert.equal($("board").children,board);
    $("mine-rules").click(); assert.equal(visible("rules-dialog"), true);
    assert.equal($("rules-close").textContent, "返回游戏");
    now+=60000; pageEvents.tick(); assert.equal($("timer").textContent, "01:05");
    $("rules-close").click(); $("back-button").click();
    assert.equal($("akari-entry").disabled, false);
    assert.equal($("akari-entry-status").textContent, "开始游戏");
    assert.equal($("sudoku-entry").disabled, false);
    assert.equal($("mine-entry-status").textContent, "已通关");
    await reload();
    assert.equal($("akari-entry").disabled, false);
    await enter("akari-entry"); assert.equal(visible("akari-rules-dialog"),true);
  });
  await t.test("照明用时130秒，停留时间不计时", async () => {
    await verifyRules(1); const bulbs=[0,2,11,19,28,30,36,41,45,48,54,61,66,73,80,89,92,97];
    $("akari-board").click($("akari-board").children[0]);
    $("akari-back").click();
    assert.equal($("challenge-action-label").textContent, "选择你的挑战");
    assert.equal($("akari-entry-status").textContent, "继续游戏");
    const count = submissions.length;
    await enter("start-button");
    assert.equal(visible("game-screen"), true);
    assert.equal($("timer").textContent, "01:05");
    assert.equal($("cleared-count").textContent, "90");
    assert.equal(submissions.length, count);
    $("result-secondary").click(); $("back-button").click();
    await reload(115000); await enter("akari-entry");
    assert.equal($("akari-timer").textContent, "02:10");
    assert.equal($("akari-board").children[0].classList.contains("bulb"), true);
    for(const i of bulbs.slice(1)) $("akari-board").click($("akari-board").children[i]);
    await settle(); assert.equal($("akari-timer").textContent,"02:10"); now+=60000;
    $("result-secondary").click(); $("akari-back").click();
    assert.equal($("sudoku-entry").disabled, false);
    assert.equal($("sudoku-entry-status").textContent, "开始游戏");
    await enter("sudoku-entry");
    assert.equal(visible("sudoku-rules-dialog"),true);
  });
  await t.test("数独仅结算245秒，返回首页后仍可查看结果", async () => {
    await verifyRules(2); const blanks=[...SUDOKU_PUZZLE].flatMap((v,i)=>v==="0"?[i]:[]);
    $("sudoku-notes-toggle").click();
    $("sudoku-board").click($("sudoku-board").children[blanks[0]]);
    keys.keydown({ key: "2" }); keys.keydown({ key: "5" }); keys.keydown({ key: "9" });
    assert.match($("sudoku-board").children[blanks[0]].attributes["aria-label"], /候选数 2、5、9/);
    await reload();
    assert.equal($("sudoku-notes-toggle").attributes["aria-pressed"], "true");
    assert.equal($("sudoku-board").children[blanks[0]].children[0].children.length, 9);
    $("sudoku-clear").click();
    assert.equal($("sudoku-board").children[blanks[0]].children.length, 0);
    $("sudoku-notes-toggle").click();
    for(const [n,i] of blanks.entries()) {
      if(n===1) {
        await reload(230000);
        assert.equal($("sudoku-timer").textContent, "04:05");
        assert.equal($("sudoku-board").children[blanks[0]].textContent, SUDOKU_SOLUTION[blanks[0]]);
      }
      $("sudoku-board").click($("sudoku-board").children[i]); const key=new Element(); key.dataset.digit=SUDOKU_SOLUTION[i]; $("sudoku-keypad").click(key);
    }
    await settle(); assert.match($("result-title").textContent,/恭喜/); now+=90000; $("result-primary").click();
    assert.equal($("settlement-time").textContent,"04:05");
    assert.equal($("settlement-title").textContent,"数独通关结算"); assert.equal($("settlement-ranking").disabled,false);
    const count=submissions.length; keys.keydown({key:"Escape"}); $("settlement-open").click(); assert.equal(submissions.length,count);
    $("settlement-home").click(); await enter("sudoku-entry"); assert.equal(visible("sudoku-screen"),true);
    assert.equal($("sudoku-timer").textContent,"04:05"); $("sudoku-back").click();
    assert.equal($("challenge-action-label").textContent, "选择你的挑战");
  });
  await t.test("开发按钮只完成当前关，重开失败可重试，换号清空本轮", async () => {
    await enter("start-button"); $("result-secondary").click(); failRestart=true; await $("restart-button").click();
    assert.equal(visible("challenge-retry"),true);
    const beforeRestartRetry=submissions.length;
    $("board").click($("board").children[99]); $("reveal-button").click(); await settle();
    assert.equal(submissions.length,beforeRestartRetry);
    await reload(30000);
    assert.equal(visible("game-screen"), true, $("challenge-message").textContent);
    assert.equal($("timer").textContent, "00:00");
    $("rules-close").click();
    await $("mine-quick").click(); await settle(); assert.equal(current.levels[1].seconds,130); assert.equal(visible("akari-screen"),false);
    assert.equal(submissions.at(-1).development,true); const count=submissions.length; await $("mine-quick").click(); assert.equal(submissions.length,count);
    $("back-button").click(); await enter("akari-entry"); $("akari-rules-close").click(); await $("akari-quick").click(); await settle(); assert.equal(current.levels[2].seconds,245);
    $("akari-back").click(); await enter("sudoku-entry"); $("sudoku-rules-close").click(); await $("sudoku-quick").click(); await settle(); assert.equal(current.total_recorded,false);
    keys["auth-changed"](); assert.equal(visible("landing"),true);
  });
  await t.test("换号不恢复其他账号棋局，原账号重新进入仍可续玩", async () => {
    keys["auth-changed"]({ detail: { user: { id: 1 } } }); await settle();
    await enter("start-button"); await $("restart-button").click(); $("rules-close").click();
    $("board").click($("board").children[0]); $("flag-button").click();
    await reload(10000, 2);
    assert.equal(visible("landing"), true);
    assert.equal($("akari-entry").disabled, false);
    assert.equal($("sudoku-entry").disabled, false);
    await reload(10000, 1);
    assert.equal(visible("game-screen"), true);
    assert.equal($("timer").textContent,"00:20");
  });
  await t.test("恢复网络失败保留存档，重试继续原局且累计离开时间", async () => {
    failResume = true;
    await reload(10000);
    assert.equal(visible("landing"), true);
    assert.equal(visible("challenge-retry"), true);
    $("challenge-retry").click(); await settle();
    assert.equal(visible("game-screen"), true);
    assert.equal($("timer").textContent,"00:30");
  });
  await t.test("爆炸过程中关闭页面恢复失败终盘，主动重开才清零", async () => {
    $("board").click($("board").children[1]); $("reveal-button").click();
    await reload(30000);
    assert.equal($("result-title").textContent,"游戏失败");
    assert.equal($("timer").textContent,"00:30");
    assert.equal($("board").children.filter(cell => cell.classList.contains("cell-mine")).length, 10);
    $("result-secondary").click(); $("mine-rules").click();
    now += 5000; pageEvents.tick();
    assert.equal($("timer").textContent, "00:30");
    $("rules-close").click();
    await $("restart-button").click(); await settle();
    assert.equal($("timer").textContent,"00:00");
  });
  await t.test("重开后尚未确认开始的棋局返回首页再刷新不会提前开始计时", async () => {
    $("back-button").click();
    await reload(10000);
    assert.equal(visible("landing"), true);
    await enter("start-button");
    assert.equal($("timer").textContent,"00:00");
  });
  await t.test("服务端轮次失效时不恢复旧棋盘或覆盖新轮次", async () => {
    current.run_id = crypto.randomUUID();
    await reload();
    assert.equal(visible("landing"), true);
    assert.match($("challenge-message").textContent, /失效/);
    assert.equal(stored.size, 0);
  });
  await t.test("重开扫雷保留照明棋盘和原始计时", async () => {
    await enter("start-button"); $("rules-close").click();
    await $("mine-quick").click(); await settle();
    $("back-button").click(); await enter("akari-entry"); $("akari-rules-close").click();
    $("akari-board").click($("akari-board").children[0]);
    $("akari-back").click(); await enter("start-button");
    $("result-secondary").click(); await $("restart-button").click();
    assert.equal($("timer").textContent, "00:00");
    $("back-button").click();
    assert.equal($("akari-entry").disabled, false);
    assert.equal($("sudoku-entry").disabled, false);
    await enter("start-button"); $("rules-close").click();
    await $("mine-quick").click(); await settle();
    $("back-button").click(); await enter("akari-entry");
    assert.equal($("akari-board").children[0].classList.contains("bulb"), true);
    assert.equal($("akari-timer").textContent, "00:00");
  });
  await t.test("首页选择入口只滚动，不清除任何关卡进度", async () => {
    $("akari-back").click(); await reload();
    const originalRun = current.run_id, originalSave = [...stored.values()][0];
    $("challenge-action").click();
    assert.equal($("level-select").scrolled, true);
    assert.equal(current.run_id, originalRun);
    assert.equal([...stored.values()][0], originalSave);
  });
  await t.test("销毁实例清理所有监听和定时器，晚到建轮响应不生成棋盘", async () => {
    app.destroy(); app.destroy(); resetNodes();
    let finishStart;
    app = createGameController({ request: async path => {
      if(path === 'challenges/config') return {quick_complete_enabled:true};
      if(path === 'challenges/start') return await new Promise(resolve => { finishStart=resolve; });
      throw new Error(`意外请求 ${path}`);
    } });
    keys['auth-changed']({detail:{user:{id:99}}});
    const pending = enter('start-button'), oldTick = pageEvents.tick;
    assert.equal(typeof finishStart, 'function');
    app.destroy(); app.destroy();
    assert.equal(intervals.size, 0);
    assert.equal(Object.keys(keys).length, 0);
    assert.equal(Object.keys(pageEvents).length, 0);
    for (const node of nodes.values()) assert.equal(Object.keys(node.listeners).length, 0);
    const before = $('timer').textContent;
    now += 10000; oldTick();
    finishStart({ run_id:'late', revision:0, levels:[0,1,2].map(() => ({attempt_id:'a',seconds:null})) });
    await pending; await settle();
    assert.equal($('board').children.length, 0);
    assert.equal($('timer').textContent, before);
  });
});
