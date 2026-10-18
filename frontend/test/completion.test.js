/** 真实页面流程回归：DOM 与接口用替身，计时、游戏规则、通关和保存逻辑使用真实模块。 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { SUDOKU_PUZZLE, SUDOKU_SOLUTION } from "../src/sudoku.js";
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
  /** 触发真实页面事件并返回异步结果。 */
  click(target = this) { if (!this.disabled) return this.listeners.click?.({ target }); }
}
/** 等待非阻塞保存及动态模块导入。 */
async function settle() { for (let i=0;i<5;i++) await new Promise(resolve => setImmediate(resolve)); }

test("逐关通关、冻结计时、保存重试与当前关开发验收", async (t) => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
  const nodes = new Map();
  for (const m of html.matchAll(/<[\w-]+\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const el = new Element(); const cls = m[1].match(/\bclass="([^"]+)"/)?.[1];
    if (cls) el.className = cls;
    if (/\bdisabled\b/.test(m[1])) el.disabled = true;
    nodes.set(m[2], el);
  }
  const $ = id => nodes.get(id), keys = {}, original = { document: globalThis.document, window: globalThis.window, fetch: globalThis.fetch, random: Math.random, now: Date.now };
  let now = 100000, current, fail = false, failRestart = false;
  const submissions = [];
  Date.now = () => now; Math.random = () => 0;
  globalThis.document = { getElementById: $, createElement: () => new Element(), createDocumentFragment: () => new Element(), addEventListener: (k,v) => { keys[k]=v; }, dispatchEvent: event => keys[event.type]?.(event) };
  globalThis.window = { scrollTo() {}, setInterval() {}, location: { assign() {} } };
  globalThis.fetch = async (path, options={}) => {
    const b = options.body ? JSON.parse(options.body) : null;
    if (path.endsWith("config")) return { ok: true, json: async () => ({ quick_complete_enabled: true }) };
    if (path.endsWith("start")) current = { run_id: crypto.randomUUID(), revision: 0, levels: [0,1,2].map(() => ({ attempt_id: crypto.randomUUID(), seconds: null })), total_recorded: false };
    if (path.endsWith("complete")) {
      submissions.push(b);
      if (fail) { fail=false; throw new TypeError("offline"); }
      current.levels[["mine","akari","sudoku"].indexOf(b.category)].seconds=b.duration_seconds;
      current.total_recorded=current.levels.every(x => x.seconds!==null);
    }
    if (path.endsWith("restart")) {
      if (failRestart) { failRestart=false; throw new TypeError("offline"); }
      const i=["mine","akari","sudoku"].indexOf(b.category);
      current.revision++; current.levels.splice(i,3-i,...Array.from({length:3-i},()=>({attempt_id:crypto.randomUUID(),seconds:null})));
    }
    return { ok: true, json: async () => structuredClone(current) };
  };
  t.after(() => { Date.now=original.now; Math.random=original.random; for (const k of ["document","window","fetch"]) { if(original[k]===undefined) delete globalThis[k]; else globalThis[k]=original[k]; } });
  await import("../src/main.js"); await settle();
  const visible=id=>!$(id).classList.contains("hidden"), enter=id=>$(id).listeners["authorized-start"]();
  await t.test("首页及手工事件都不能直接进入第二、第三关", async () => {
    assert.equal($("akari-entry").disabled,true); assert.equal($("sudoku-entry").disabled,true);
    enter("akari-entry"); enter("sudoku-entry"); assert.equal(visible("landing"),true);
    await enter("start-button"); enter("sudoku-entry"); assert.equal(visible("sudoku-screen"),false);
    $("rules-close").click();
  });
  await t.test("扫雷失败重试负载相同，保存成功才解锁且冻结65秒", async () => {
    $("board").click($("board").children[0]); $("flag-button").click(); now+=65000; fail=true;
    $("board").click($("board").children[99]); $("reveal-button").click(); await settle();
    assert.equal($("timer").textContent,"01:05"); assert.equal($("result-primary").disabled,true);
    $("result-primary").click(); assert.equal(visible("akari-screen"),false);
    $("save-retry").click(); await settle(); assert.deepEqual(submissions[0],submissions[1]);
    const board=$("board").children; $("result-secondary").click(); assert.equal($("board").children,board);
    now+=60000; $("mine-next").click(); assert.equal(visible("akari-rules-dialog"),true);
  });
  await t.test("照明用时130秒，停留时间不计时", async () => {
    $("akari-rules-close").click(); const bulbs=[0,2,11,19,28,30,36,41,45,48,54,61,66,73,80,89,92,97];
    $("akari-board").click($("akari-board").children[0]); now+=130000;
    for(const i of bulbs.slice(1)) $("akari-board").click($("akari-board").children[i]);
    await settle(); assert.equal($("akari-timer").textContent,"02:10"); now+=60000; $("result-primary").click();
    assert.equal(visible("sudoku-rules-dialog"),true);
  });
  await t.test("数独245秒，完整结算440秒并启用排行，重复打开不重复提交", async () => {
    $("sudoku-rules-close").click(); const blanks=[...SUDOKU_PUZZLE].flatMap((v,i)=>v==="0"?[i]:[]);
    for(const [n,i] of blanks.entries()) { if(n===1) now+=245000; $("sudoku-board").click($("sudoku-board").children[i]); const key=new Element(); key.dataset.digit=SUDOKU_SOLUTION[i]; $("sudoku-keypad").click(key); }
    await settle(); assert.match($("result-title").textContent,/恭喜/); now+=90000; $("result-primary").click();
    assert.equal($("settlement-total").textContent,"07:20"); assert.equal($("settlement-ranking").disabled,false);
    const count=submissions.length; keys.keydown({key:"Escape"}); $("settlement-open").click(); assert.equal(submissions.length,count);
    $("settlement-home").click(); enter("sudoku-entry"); assert.equal(visible("sudoku-screen"),false);
  });
  await t.test("开发按钮只完成当前关，重开失败可重试，换号清空本轮", async () => {
    await enter("start-button"); $("rules-close").click(); failRestart=true; await $("restart-button").click();
    assert.equal(visible("challenge-retry"),true);
    const beforeRestartRetry=submissions.length;
    $("board").click($("board").children[99]); $("reveal-button").click(); await settle();
    assert.equal(submissions.length,beforeRestartRetry);
    $("challenge-retry").click(); await settle();
    await $("mine-quick").click(); await settle(); assert.equal(current.levels[1].seconds,null); assert.equal(visible("akari-screen"),false);
    assert.equal(submissions.at(-1).development,true); const count=submissions.length; await $("mine-quick").click(); assert.equal(submissions.length,count);
    $("result-primary").click(); $("akari-rules-close").click(); await $("akari-quick").click(); await settle(); assert.equal(current.levels[2].seconds,null);
    $("result-primary").click(); $("sudoku-rules-close").click(); await $("sudoku-quick").click(); await settle(); assert.equal(current.total_recorded,true);
    keys["auth-changed"](); assert.equal(visible("landing"),true);
  });
});
